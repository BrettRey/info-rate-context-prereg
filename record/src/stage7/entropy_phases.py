"""The entropy phases of the production command, after the stamp.

Each phase refuses real jobs without the anchored freeze (the runner and the NS
lens check it too). From a counts-phase run record (src/stage7/counts_phase.py):

1. Read texts: syllable counts on the read texts in every configuration of the
   main-run panel (`ns_lens.run_files`), giving each configuration's canonical,
   matched and paper-subset speech rates and the NS-closest selection.
2. KenLM in every preparation of every run, each job carrying its
   configuration's rates (the rates are analysis metadata, not inputs).
3. Neural in the first-listed universe (the jobs the counts phase prepared for
   it) and in NS-closest (each first-listed main-run preparation prepared again
   with named inputs that carry the lens report). In a simulated run every
   declaration already has neural jobs.
4. Assembly of all scores with the named universes, the report files, the
   plateau report (B/2 against B), and the lens again with the main run's
   first-listed universes for the calibration report. Twice (Brett's OOV rule,
   2026-10-15): escape-coded scores (`src/stage4/escape.py`) and pooled-symbol
   scores, the rule choosing which is the main analysis (`report/`) and which the
   labelled secondary (`report-secondary/`). The one-at-a-time checks the counts
   phase prepared are scored with KenLM in the first-listed line treatment, apart
   from the universes, and reported in `report/sensitivity-checks.json`.

Outputs go under `work/`; `entropy-record.json` lists them.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


CP = _load('production_counts_phase', ROOT / 'src/stage7/counts_phase.py')
L, P, SS = CP.L, CP.P, CP.SS
R = _load('production_runner', ROOT / 'src/stage5/runner.py')
S = _load('production_assemble', ROOT / 'src/stage6/assemble.py')
LENS = _load('production_ns_lens', ROOT / 'src/stage6/ns_lens.py')
B = LENS.B
NAMED = _load('production_named_universes', ROOT / 'src/stage6/named_universes.py')
PL = _load('production_plateau', ROOT / 'src/stage6/plateau.py')
E = _load('production_entropy_gate', ROOT / 'src/stage3/segment_entropy.py')
ESC = _load('production_escape', ROOT / 'src/stage4/escape.py')
SC = _load('production_sensitivity_checks', ROOT / 'src/stage7/sensitivity_checks.py')
SCHEMA = 'production-entropy-v1'
# The runner's default limit on a run's own folder (3 GB) is the working copy's; a real
# run's KenLM folder holds every job's scores and a job's scratch, and the main report's
# complete curve over 1.6 million universes is about 10 GB. The free-space floor and the
# data/ ceiling still apply (DECISIONS.md, 2026-10-16).
RUN_LIMIT_BYTES = 200 * 1024 ** 3
SCORING_WORKERS = 'INFO_RATE_SCORING_WORKERS'
FREEZE_OPTIONS = ('freeze_archive', 'freeze_proof', 'block_headers')


def scoring_workers():
    """KenLM jobs scored at once: INFO_RATE_SCORING_WORKERS, default 1 (in this process).
    Set it by memory, not cores: each job's materialisation decodes its declaration's
    whole syllable record."""
    value = os.environ.get(SCORING_WORKERS, '1')
    if not value.isdigit() or int(value) < 1:
        raise ValueError(f'{SCORING_WORKERS} must be a positive integer')
    return int(value)
OOV_LINE = 0.001  # Brett, 2026-10-15: 0.1% of held-out tokens


def configuration_id(declaration):
    return B.configuration_id(declaration)


def preparations(record, root):
    """Every preparation's manifest in the run record, in record order."""
    return [Path(root) / prepared['inputs'] for run in record['runs'].values()
            for info in run['languages'].values() for prepared in info['preparations']]


def preparation_jobs(record, root, estimator):
    """Every preparation's jobs of one estimator, all at once (the neural jobs, which are few)."""
    jobs = []
    for inputs in preparations(record, root):
        jobs += L.preparation_jobs(inputs, estimator=estimator)
    return jobs


def with_rates(jobs, rates):
    """Attach each job's configuration rates; a job without them can't be assembled."""
    out = []
    for job in jobs:
        cid = configuration_id(job['tokenisation']['declaration'])
        if cid not in rates:
            raise ValueError(f"no read-text rates for configuration {cid} ({job['language']})")
        out.append(dict(job, rates=rates[cid]))
    return out


def one_estimate_each(jobs):
    """One job per (language, settings, options, estimator), the first kept.

    Assembly selects named universes by options, so NS-closest reuses a
    first-listed estimate when it picks the same option, and the runner
    refuses duplicate jobs.
    """
    unique, seen = [], set()
    for job in jobs:
        key = P.canonical([job['language'], job['shared'], job['options'], job['estimator']])
        if key not in seen:
            seen.add(key); unique.append(job)
    return unique


def first_listed(group):
    return all(SS.FIRST_LISTED.get(k) == v for k, v in group['shared'].items())


def calibration_universes(groups):
    """The main run's first-listed KenLM universes and their densities, for the calibration report.

    Every main-run fork has a first-listed value, so exactly one KenLM group
    can be first-listed; more than one means a label went wrong.
    """
    chosen = [g for g in groups if g['estimator'].get('name', 'kenlm') == 'kenlm' and first_listed(g)
              and g['names'] is None]
    if len(chosen) > 1:
        raise ValueError(f'{len(chosen)} first-listed KenLM groups; expected one (check the shared labels)')
    universes, densities = [], {}
    for group in chosen:
        for u, choice in enumerate(group['choices']):
            universes.append(dict(name=f'first-listed-{u}', languages={
                language: configuration_id(group['records'][l][int(choice[l])]['identity']['tokenisation']['declaration'])
                for l, language in enumerate(group['languages'])},
                R={rung: float(group['R'][u][k]) for k, rung in enumerate(group['rungs'])}))
        densities.update({configuration_id(r['identity']['tokenisation']['declaration']):
                          {k: v['id_bits'] for k, v in r['scores'].items()}
                          for rr in group['records'] for r in rr})
    return universes, densities


def oov_rule(record, root):
    """Brett's OOV rule (2026-10-15) over every preparation's counts.

    The pooled unknown symbol is the main analysis only if, in every language,
    text variant, declaration and budget, held-out targets unseen in training are
    under 0.1% of held-out syllable tokens; otherwise escape coding is. A row's
    share counts unseen syllables and, as the flagged rungs see them, unseen
    (flag, syllable) pairs (`linguistic_inputs.oov_counts`). Every declaration of
    every preparation in the run record must have exactly one row, and only those
    rows count (Codex review).
    """
    rows, read, wanted = {}, set(), set()
    for run in record['runs'].values():
        for language, info in run['languages'].items():
            for prepared in info['preparations']:
                folder = (Path(root) / prepared['inputs']).parent
                shared = P.canonical(dict(prepared['settings'], budget=prepared['budget']))
                manifest = json.loads((folder / 'inputs.json').read_text())
                wanted |= {(language, shared, configuration_id(d)) for d in manifest['declarations']}
                # A variant's summary sits in its first label's folder and covers every label.
                for path in (folder / 'oov-summary.json', folder.with_name('B') / 'oov-summary.json'):
                    if path.exists() and path not in read:
                        read.add(path)
                        summary = json.loads(path.read_text())
                        for row in summary['rows']:
                            key = (summary['language'], P.canonical(row['shared']), row['declaration'])
                            if key in rows and rows[key] != row:
                                raise ValueError(f'Two different OOV counts for one preparation: {key}')
                            rows[key] = row
    if wanted - set(rows):
        raise ValueError('A preparation has no OOV counts, so the OOV rule cannot be applied')
    def share(key):
        row = rows[key]
        return (row['unseen_syllable_tokens'] + row['unseen_pair_tokens']) / row['heldout_syllable_tokens']
    largest = max(sorted(wanted), key=share)
    return dict(main='escape-coded' if share(largest) >= OOV_LINE else 'pooled', line=OOV_LINE, rows=len(wanted),
                largest=dict(share=share(largest), language=largest[0], shared=json.loads(largest[1]),
                             declaration=largest[2]))


def escape_tables(entries, work):
    """Each scored job's spelling bits per rung and test document, one preparation at a time."""
    work = R.local(work); work.mkdir(parents=True, exist_ok=True)
    tables = {}
    key = lambda e: (str(e[1]['preparation']), configuration_id(e[1]['tokenisation']['declaration']), e[0])
    for jid, job in sorted(dict(entries).items(), key=lambda e: key(e)):
        tables[jid] = ESC.job_escape(job)
        P.atomic(work / f'{jid}.json', (P.canonical(tables[jid]) + '\n').encode())
    return tables


def span_tables(entries, work):
    """Each scored job's context spans per rung (`escape.job_spans`), one preparation at a time."""
    work = R.local(work); work.mkdir(parents=True, exist_ok=True)
    spans = {}
    key = lambda e: (str(e[1]['preparation']), configuration_id(e[1]['tokenisation']['declaration']), e[0])
    for jid, job in sorted(dict(entries).items(), key=lambda e: key(e)):
        spans[jid] = ESC.job_spans(job)
        P.atomic(work / f'{jid}.json', (P.canonical(spans[jid]) + '\n').encode())
    return spans


def span_inputs(groups, spans):
    """`assemble.diagnostic_tables` inputs: each analysis selection's context spans, from its job's table.

    Keyed as `diagnostic_tables` keys them, from the assembled records (assembly rewrites a record's
    options, so the scored records' own metadata wouldn't match)."""
    jobs = {}
    for g in groups:
        for own in g['records']:
            for r in own:
                meta = S.job_metadata(r)
                jobs[S.RUNNER.digest([r['job_id'], meta['language'], meta['shared'], meta['options']])] = dict(
                    context_spans=spans[r['job_id']]['rungs'])
    return dict(jobs=jobs)


def _guard(work, options):
    """The guard for the driver's own writes in a run folder, under the run's limit (Codex review)."""
    return R.DiskGuard(margin=options.get('margin_bytes', R.GB), limit=options.get('limit_bytes', 3 * R.GB), work=work)


def _job_digest(job):
    return P.digest(P.canonical(job).encode())


def _score(spec):
    """One job in its own folder, in this fresh interpreter (`--score`): rebuilt from its
    manifest, run as `run_materialised` runs it, its escape table written."""
    [job] = [j for sha, j in L.preparation_entries(spec['inputs'], estimator='kenlm') if sha == spec['job_sha256']]
    if spec['rates'] is not None:
        job = dict(job, rates=spec['rates'])
    options = dict(spec['options'], **{k: Path(v) for k, v in spec['freeze'].items()})
    # The job's own files, written before the runner's checks, keep the others' room too (Codex review).
    try:
        R.DiskGuard(margin=options.get('margin_bytes', R.GB), limit=options.get('limit_bytes', 3 * R.GB),
                    work=Path(spec['folder'])).check(_materialised_bytes(job))
    except R.DiskStop as error:
        return dict(completed=[], skipped=[], stopped=str(error), tables={}, spans={}, entropy_authorization=None)
    one = run_materialised([job], Path(spec['folder']), **options)
    tables, spans = {}, {}
    for jid in one['completed'] + one['skipped']:
        path = Path(spec['escape']) / f'{jid}.json'
        P.atomic(path, (P.canonical(ESC.job_escape(job)) + '\n').encode())
        tables[jid] = str(path)
        if spec.get('spans'):
            path = Path(spec['spans']) / f'{jid}.json'
            P.atomic(path, (P.canonical(ESC.job_spans(job)) + '\n').encode())
            spans[jid] = str(path)
    return dict({k: one[k] for k in ('completed', 'skipped', 'stopped')}, tables=tables, spans=spans,
                entropy_authorization=one.get('entropy_authorization'))


def _score_in_workers(items, n, options, escape_work, spans_work=None):
    """Each item (inputs, job digest, rates, folder) scored by `_score` in a fresh interpreter,
    n at a time, started in order; after a stop or a failure no further item starts and the
    running ones finish. Returns each item's result (None where it never started or failed)
    and the first failure, so a caller keeps its peers' scores before raising it."""
    import concurrent.futures, subprocess
    freeze = {k: str(options[k]) for k in FREEZE_OPTIONS if options.get(k) is not None}
    plain = {k: v for k, v in options.items() if k not in FREEZE_OPTIONS}
    def one(item):
        inputs, sha, rates, folder = item
        folder.mkdir(parents=True, exist_ok=True)
        spec, result, log = folder / 'score.json', folder / 'score-result.json', folder / 'score.log'
        result.unlink(missing_ok=True)
        P.atomic(spec, (P.canonical(dict(inputs=str(inputs), job_sha256=sha, rates=rates, folder=str(folder),
                                          escape=str(escape_work), spans=str(spans_work) if spans_work else None,
                                          options=plain, freeze=freeze)) + '\n').encode())
        with open(log, 'wb') as out:
            code = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--score', str(spec)],
                                  stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT).returncode
        if code != 0 or not result.exists():
            tail = log.read_bytes()[-2000:].decode('utf-8', 'replace')
            raise RuntimeError(f'scoring worker failed (exit {code}) for {inputs} job {sha[:16]}; log {log}:\n{tail}')
        return json.loads(result.read_text())
    results, pending, queue = [None] * len(items), {}, iter(enumerate(items))
    error = stopped = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        while True:
            while error is None and stopped is None and len(pending) < n:
                nxt = next(queue, None)
                if nxt is None:
                    break
                pending[pool.submit(one, nxt[1])] = nxt[0]
            if not pending:
                break
            done, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                i = pending.pop(future)
                if future.exception() is not None:
                    error = error or future.exception()
                else:
                    results[i] = future.result()
                    stopped = stopped or results[i]['stopped']
    return results, error


def _merged(results, items, jobs, work):
    """Workers' results in job order, each scored job's cache record linked into `work`'s cache;
    every worker must report the same authorisation."""
    cache = work / 'cache'; cache.mkdir(parents=True, exist_ok=True)
    report = dict(completed=[], skipped=[], stopped=None)
    entries, tables, spans, authorizations = [], {}, {}, {}
    for result, (_, _, _, folder), job in zip(results, items, jobs):
        if result is None:
            continue
        if result['entropy_authorization'] is not None:
            authorizations[P.canonical(result['entropy_authorization'])] = result['entropy_authorization']
        report['completed'] += result['completed']; report['skipped'] += result['skipped']
        for jid in result['completed'] + result['skipped']:
            link = cache / f'.{jid}.json.link'
            link.unlink(missing_ok=True)
            os.link(folder / 'cache' / f'{jid}.json', link); os.replace(link, cache / f'{jid}.json')
            entries.append((jid, job))
            tables[jid] = json.loads(Path(result['tables'][jid]).read_text())
            if jid in result.get('spans', {}):
                spans[jid] = json.loads(Path(result['spans'][jid]).read_text())
        if result['stopped'] is not None and report['stopped'] is None:
            report['stopped'] = result['stopped']
    if len(authorizations) > 1:
        raise ValueError('Scoring workers reported different entropy authorisations')
    authorization = next(iter(authorizations.values()), None)
    if authorization is not None:
        report['entropy_authorization'] = authorization
    return report, entries, tables, spans, authorization


def _materialised_bytes(job):
    """What a job's materialisation writes: its files' recorded sizes."""
    return sum((L.recorded(job['preparation'], path) or (None, 0))[1] or 0 for path in L.job_paths(job))


def _margin(jobs, n):
    """Each of n concurrent jobs keeps room for the others' files and declared peaks above the floor."""
    return R.GB + (n - 1) * (R.GB + max((j['peak_bytes'] for j in jobs), default=0)
                             + max((j.get('materialised_bytes', 0) for j in jobs), default=0))


def run_checks(jobs, work, escape_work=None, **options):
    """Each check arm scored alone, in its own folder.

    Every check preparation has its own mask, and a boundary check's two arms
    share option labels, so the cross-job checks that hold across the universes
    (one mask per language, one job per language, setting and options) would
    refuse them as one batch; alone, each arm gets every per-job check. With
    `INFO_RATE_SCORING_WORKERS` above 1 (and the built-in estimator), several arms
    run at once, each in a fresh interpreter, and their escape tables are made there.
    """
    work = R.local(work)
    report = dict(completed=[], skipped=[], stopped=None, entries=[], records=[])
    key = lambda job: (str(job['preparation']), configuration_id(job['tokenisation']['declaration']))
    ordered = sorted(jobs, key=key)
    folders = [work / hashlib.sha256(P.canonical(list(key(job))).encode()).hexdigest()[:16] for job in ordered]
    n = scoring_workers()
    if n > 1 and options.get('estimator') is None and ordered:
        items = [(Path(job['preparation']), _job_digest(job), None, folder) for job, folder in zip(ordered, folders)]
        escape_work = R.local(escape_work or work / 'escape-tables'); escape_work.mkdir(parents=True, exist_ok=True)
        sizes = [dict(peak_bytes=job['peak_bytes'], materialised_bytes=_materialised_bytes(job)) for job in ordered]
        results, error = _score_in_workers(items, n, dict(options, margin_bytes=_margin(sizes, n)), escape_work)
        report['tables'] = {}
        for result, job, folder in zip(results, ordered, folders):
            if result is None:
                continue
            for name in ('completed', 'skipped'):
                report[name] += result[name]
            report['entries'] += [(jid, job) for jid in result['completed'] + result['skipped']]
            report['tables'].update({jid: json.loads(Path(p).read_text()) for jid, p in result['tables'].items()})
            if result['stopped'] is not None and report['stopped'] is None:
                report['stopped'] = result['stopped']
            if result['completed'] or result['skipped']:  # an arm scored beside a stopped one keeps its record
                report['records'] += list(S.cached_records(folder / 'cache'))
        if error is not None:
            raise error
        return report
    for job, folder in zip(ordered, folders):
        one = run_materialised([job], folder, **options)
        for name in ('completed', 'skipped', 'entries'):
            report[name] += one[name]
        if one['stopped'] is not None:
            report['stopped'] = one['stopped']
            break
        report['records'] += list(S.cached_records(folder / 'cache'))
    return report


def _compared(job):
    """What the runner's cross-job checks read of a job, its per-document lists by digest."""
    return dict({k: job[k] for k in ('simulated', 'language', 'shared', 'options', 'estimator') if k in job},
                tokenisation=dict(mask_sha256=job['tokenisation'].get('mask_sha256')),
                documents=R.digest(job['documents']), source_hashes=R.digest(job.get('source_hashes')))


def run_by_preparation(manifests, rates, work, escape_work, spans_work=None, **options):
    """`run_materialised` over every preparation's KenLM jobs, one preparation at a time (P9 at
    real size: a run's jobs don't fit in memory together; DECISIONS.md, 2026-10-16).

    A first pass makes the runner's cross-job checks over every preparation's jobs,
    their per-document lists compared by digest, so nothing runs before every check
    has passed, as when one call had all the jobs. The second pass reads each
    preparation's jobs again and runs them, and makes each scored job's escape table
    while its preparation is read. Entries keep each job's metadata, not the job.
    With `INFO_RATE_SCORING_WORKERS` above 1 (and the built-in estimator), that many
    jobs run at once, each in a fresh interpreter in its own folder under `work/jobs`;
    each scored job's cache record is linked into `work/cache`, and the active manifest
    lists every job in job order, as the one-at-a-time run writes it. With `spans_work`,
    each scored job's context spans (`escape.job_spans`) are made beside its escape table.
    """
    work, escape_work = R.local(work), R.local(escape_work)
    escape_work.mkdir(parents=True, exist_ok=True)
    if spans_work is not None:
        spans_work = R.local(spans_work); spans_work.mkdir(parents=True, exist_ok=True)
    compared, peaks = [], []
    for inputs in manifests:
        for job in L.preparation_jobs(inputs, estimator='kenlm'):
            with_rates([job], rates)
            compared.append(_compared(job))
            peaks.append(dict(peak_bytes=job['peak_bytes'], materialised_bytes=_materialised_bytes(job)))
    R.cross_job_checks(compared, builtin=options.get('estimator') is None)
    n = scoring_workers()
    if n > 1 and options.get('estimator') is None:
        items, kept = [], []
        for inputs in manifests:
            for sha, job in L.preparation_entries(inputs, estimator='kenlm'):
                job = with_rates([job], rates)[0]
                items.append((Path(inputs), sha, job['rates'], work / 'jobs' / sha[:16]))
                kept.append({k: job[k] for k in R.METADATA_KEYS if k in job})
        results, error = _score_in_workers(items, n, dict(options, margin_bytes=_margin(peaks, n)), escape_work,
                                           spans_work)
        report, entries, tables, spans, authorization = _merged(results, items, kept, work)
        R.write_json(work / 'manifest.json', R.manifest_value(entries, authorization), _guard(work, options))
        if error is not None:  # the peers' scores are in the phase's cache and manifest first (Codex review)
            raise error
        report['entries'], report['tables'], report['spans'] = entries, tables, spans
        return report
    report = dict(completed=[], skipped=[], stopped=None)
    entries, tables, spans, authorization = [], {}, {}, None
    for inputs in manifests:
        for job in with_rates(L.preparation_jobs(inputs, estimator='kenlm'), rates):
            written = L.materialise(job)
            try:
                one = R.run([job], work, **options)
            finally:
                L.dematerialise(written)
            authorization = one.get('entropy_authorization', authorization)
            report['completed'] += one['completed']; report['skipped'] += one['skipped']
            for jid in one['completed'] + one['skipped']:
                entries.append((jid, {k: job[k] for k in R.METADATA_KEYS if k in job}))
                tables[jid] = ESC.job_escape(job)
                P.atomic(escape_work / f'{jid}.json', (P.canonical(tables[jid]) + '\n').encode())
                if spans_work is not None:
                    spans[jid] = ESC.job_spans(job)
                    P.atomic(spans_work / f'{jid}.json', (P.canonical(spans[jid]) + '\n').encode())
            if one['stopped'] is not None:
                report['stopped'] = one['stopped']
                break
        if report['stopped'] is not None:
            break
    if authorization is not None:
        report['entropy_authorization'] = authorization
    work.mkdir(parents=True, exist_ok=True)
    R.write_json(work / 'manifest.json', R.manifest_value(entries, authorization), _guard(work, options))
    report['entries'], report['tables'], report['spans'] = entries, tables, spans
    return report


def run_materialised(jobs, work, **options):
    """`R.run` one job at a time, each job's token files or word corpora written just
    before it and removed after (P9: a run's token files are TB-scale if all are kept).

    The runner checks every file against the preparation's recorded digests as it
    always did; the cross-job checks run once here, and the active manifest lists
    every job, as one `R.run` over all of them would have written it.
    """
    work = R.local(work)
    R.cross_job_checks(jobs, builtin=options.get('estimator') is None)
    report = dict(completed=[], skipped=[], stopped=None)
    entries, authorization = [], None
    for job in jobs:
        written = L.materialise(job)
        try:
            one = R.run([job], work, **options)
        finally:
            L.dematerialise(written)
        authorization = one.get('entropy_authorization', authorization)
        report['completed'] += one['completed']; report['skipped'] += one['skipped']
        entries += [(jid, job) for jid in one['completed'] + one['skipped']]
        if one['stopped'] is not None:
            report['stopped'] = one['stopped']
            break
    if authorization is not None:
        report['entropy_authorization'] = authorization
    work.mkdir(parents=True, exist_ok=True)
    R.write_json(work / 'manifest.json', R.manifest_value(entries, authorization), _guard(work, options))
    report['entries'] = entries  # job ids beside their jobs, for escape coding
    return report


def run(record_path, work, *, root=ROOT, readings, texts, freeze_archive=None, freeze_proof=None,
        block_headers=None, simulated=False, estimator=None, estimator_version=None, lens_backends=None,
        prepare_backends=None):
    """All entropy phases from a counts-phase run record; returns and writes the entropy record."""
    root = Path(root).resolve(); work = Path(work).resolve()
    if not work.is_relative_to(root):
        raise ValueError('The production work directory must be inside the project')
    if not simulated and (lens_backends or prepare_backends):
        raise ValueError("A real run uses the registry's production G2P routes; supplied backends are for simulated runs")
    freeze = dict(freeze_archive=freeze_archive, freeze_proof=freeze_proof, block_headers=block_headers)
    authorization = None
    if not simulated:
        authorization = E.entropy_authorization(**freeze)
    record = json.loads(Path(record_path).read_text())
    if record.get('schema') != CP.SCHEMA or bool(record.get('simulated')) != bool(simulated):
        raise ValueError('The run record is not a counts-phase record of this kind (simulated or real)')
    if estimator is not None and not simulated:
        raise ValueError('Custom estimators are for simulated runs only')
    main = record['runs']['main']
    panel = sorted(main['languages'])
    configs = B.configurations(panel)
    # 1. Read texts: rates per configuration and the NS-closest selection.
    lens, matched = LENS.run_files(readings, texts, work / 'lens', configs=configs, backends=lens_backends, **freeze)
    rates = {row['configuration_id']: row['rates'] for row in matched}
    # 2. KenLM everywhere.
    runner_options = dict(estimator=estimator, estimator_version=estimator_version, limit_bytes=RUN_LIMIT_BYTES, **freeze)
    kenlm = run_by_preparation(preparations(record, root), rates, work / 'kenlm', work / 'escape',
                               spans_work=work / 'spans', **runner_options)
    # 2b. The one-at-a-time checks (design in DECISIONS.md, 2026-10-16): KenLM, running text, outside the assembly.
    check_jobs = SC.check_jobs(record, root, SS.FIRST_LISTED['line'])
    checks = run_checks(check_jobs, work / 'checks', work / 'checks-escape', **runner_options) if check_jobs else None
    # 3. Neural: first-listed from the counts phase; NS-closest from a fresh preparation.
    # The neural model runs only in the named universes; KenLM spans every universe,
    # so only the neural declarations go to assembly.
    built = NAMED.consume(NAMED.build(panel, CP.named_inputs()['shared_settings'], ns_lens=work / 'lens' / 'lens.json'))
    named = {'neural': built['neural']}
    neural_jobs = preparation_jobs(record, root, 'neural')
    if not simulated:
        for info in main['languages'].values():
            # The first-listed variant is prepared again with the lens report, for every
            # budget label the counts phase prepared from it: one scan covers the same
            # documents, so the removal mask is the same frozen mask the variant's other
            # jobs use (the runner requires one); only the B label's NS-closest jobs run.
            group = [p for p in info['preparations'] if all(SS.FIRST_LISTED[k] == v for k, v in p['settings'].items())]
            budgets = [p['budget'] for p in group]
            if 'B' not in budgets:
                continue
            argument_sets = [json.loads((root / p['arguments']).read_text()) for p in group]
            first = argument_sets[budgets.index('B')]
            if any((a['documents'], a['splits'], a.get('provisional_mask')) !=
                   (first['documents'], first['splits'], first.get('provisional_mask')) for a in argument_sets):
                raise ValueError('The budget labels of one text variant must share documents, splits and mask')
            labels = [dict(output=(root / p['inputs']).parent.with_name(Path(p['inputs']).parent.name + '-ns-closest'),
                           shared=a['shared'], budget=a['budget']) for p, a in zip(group, argument_sets)]
            L.prepare(first['documents'], first['splits'], first['language'],
                      backends=prepare_backends, floor=first['floor'], onset_source=first['onset_source'],
                      gap_treatment=first['gap_treatment'], simulated=False, labels=labels,
                      named_inputs=dict(CP.named_inputs(), ns_lens=str(work / 'lens' / 'lens.json')),
                      neural_settings=first['neural_settings'],
                      provisional_mask=root / first['provisional_mask'] if first.get('provisional_mask') else None)
            neural_jobs += [j for j in L.preparation_jobs(labels[budgets.index('B')]['output'] / 'inputs.json',
                                                          estimator='neural')
                            if j.get('named_universe') == 'NS-closest']
    neural_jobs = one_estimate_each(neural_jobs)
    neural = run_materialised(with_rates(neural_jobs, rates), work / 'neural', **runner_options) if neural_jobs else None
    # 4. Assembly, reports, plateau, and the lens on the first-listed universes.
    records = list(S.cached_records(work / 'kenlm' / 'cache'))
    tables, spans = dict(kenlm['tables']), dict(kenlm['spans'])  # made as each KenLM job ran
    if neural is not None:
        records += list(S.cached_records(work / 'neural' / 'cache'))
        tables.update(escape_tables(neural['entries'], work / 'escape'))
        spans.update(span_tables(neural['entries'], work / 'spans'))
    rule = oov_rule(record, root)
    if {r['job_id'] for r in records} - set(tables):
        raise ValueError('A scored job has no escape table')
    if {r['job_id'] for r in records} - set(spans):
        raise ValueError('A scored job has no span table')
    escaped = [ESC.apply(r, tables[r['job_id']], R.digest, stand_in=estimator is not None) for r in records]
    pooled = [ESC.pooled_counts(r, tables[r['job_id']], R.digest) for r in records]
    del records
    analyses = dict(main=escaped, secondary=pooled) if rule['main'] == 'escape-coded' else \
        dict(main=pooled, secondary=escaped)
    del pooled, escaped
    # The last preparation's state, syllable record and manifest stay in module caches for a next job of the
    # same preparation; the report needs none of them (Codex review).
    ESC._STATE.clear()
    for module in {id(m): m for m in (L, ESC.L)}.values():
        module._RECORD.clear(); module._PREPARATION.clear()
    # One assembly in memory at a time: holding the main analysis's groups while the
    # secondary was assembled doubled the report step's memory (rehearsal, 2026-10-17).
    outputs = {}
    for name, folder in (('main', 'report'), ('secondary', 'report-secondary')):
        chosen = analyses.pop(name)
        groups_n = S.assemble(chosen, named_universes=named, allow_incomplete=True)
        # The span beside every rung (Brett, 2026-10-17), as the diagnostics' context spans.
        report_n = S.write_outputs(groups_n, work / folder, guard=R.DiskGuard(work=work / folder, limit=RUN_LIMIT_BYTES),
                                   diagnostics=span_inputs(groups_n, spans))
        plateau_n = PL.deltas([r for r in chosen if r['identity'].get('estimator', {}).get('name', 'kenlm') == 'kenlm'])
        P.atomic(work / folder / 'plateau.json', (P.canonical(plateau_n) + '\n').encode())
        (work / folder / 'plateau.md').write_text(PL.markdown(plateau_n), encoding='utf-8')
        if name == 'main':
            # Kept on disk, not in memory, while the secondary is assembled (Codex review).
            P.atomic(work / 'calibration-universes.json', (P.canonical(dict(zip(
                ('universes', 'densities'), calibration_universes(groups_n)))) + '\n').encode())
        outputs[name] = (dict(groups=len(groups_n), issues=list(getattr(groups_n, 'issues', []))), report_n, plateau_n)
        del chosen, groups_n
    main_groups, report, plateau = outputs['main']
    calibration_input = json.loads((work / 'calibration-universes.json').read_text())
    universes, densities = calibration_input['universes'], calibration_input['densities']
    del calibration_input
    check_report = None
    if checks is not None:
        check_tables = checks['tables'] if 'tables' in checks else escape_tables(checks['entries'], work / 'checks-escape')
        check_report = SC.report(record, root, checks['records'], checks['entries'], escape=lambda r: ESC.apply(
            r, check_tables[r['job_id']], R.digest, stand_in=estimator is not None))
        P.atomic(work / 'report' / 'sensitivity-checks.json', (P.canonical(check_report) + '\n').encode())
        (work / 'report' / 'sensitivity-checks.md').write_text(SC.markdown(check_report), encoding='utf-8')
    calibration = None
    if universes:
        calibration, _ = LENS.run_files(readings, texts, work / 'lens-universes', configs=configs,
                                        universes=universes, densities=densities, backends=lens_backends, **freeze)
    # Modules loaded fresh mid-run (production.resolve_named, the neural preset)
    # come from disk, so the files must still match what was authorized.
    if authorization is not None:
        E.F.unchanged_since(authorization)
    result = dict(schema=SCHEMA, run_record_sha256=record['sha256'], simulated=simulated,
                  authorization=authorization, lens=str((work / 'lens' / 'lens.json').relative_to(root)),
                  ns_closest=lens.get('ns_closest'), kenlm=dict(completed=len(kenlm['completed']), stopped=kenlm['stopped']),
                  neural=None if neural is None else dict(completed=len(neural['completed']), stopped=neural['stopped']),
                  groups=main_groups['groups'], issues=main_groups['issues'], report=report,
                  plateau_rows=len(plateau['rows']), calibration_universes=len(universes),
                  oov_rule=rule, main_analysis=rule['main'],
                  secondary=dict(analysis='pooled' if rule['main'] == 'escape-coded' else 'escape-coded',
                                 groups=outputs['secondary'][0]['groups'], report=outputs['secondary'][1],
                                 issues=outputs['secondary'][0]['issues'],
                                 plateau_rows=len(outputs['secondary'][2]['rows'])),
                  escape=dict(jobs=len(tables), sha256=R.digest(tables)),
                  spans=dict(jobs=len(spans), sha256=R.digest(spans)),
                  checks=None if checks is None else dict(completed=len(checks['completed']), stopped=checks['stopped'],
                                                          reported=check_report['checks'],
                                                          report=str((work / 'report' / 'sensitivity-checks.json').relative_to(root))),
                  calibration_closest=None if calibration is None else calibration.get('closest_universe'))
    result['sha256'] = hashlib.sha256(P.canonical(result).encode()).hexdigest()
    P.atomic(work / 'entropy-record.json', (P.canonical(result) + '\n').encode())
    return result


if __name__ == '__main__':
    if sys.argv[1:2] != ['--score'] or len(sys.argv) != 3:
        raise SystemExit('usage: entropy_phases.py --score SPEC.json (started by run_by_preparation and run_checks)')
    _spec = json.loads(Path(sys.argv[2]).read_text())
    _value = _score(_spec)
    P.atomic(Path(_spec['folder']) / 'score-result.json', (P.canonical(_value) + '\n').encode())
