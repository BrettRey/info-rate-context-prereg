"""The counts phase of the production command: everything the freeze stamps, no entropy.

Per run (main, Wikipedia), from a corpus manifest (src/stage7/corpora.py):

1. Each language under its first-listed text settings (gap drop, stub 0.5, Thai
   prose lines of 80 characters where they apply): documents, then a counts
   pass. The counts pass builds the common line mask with empty onset
   inventories and counts each line's syllables under the first-listed
   option. Syllable counts come from the counters, not from where syllables are
   cut, so they don't depend on the inventory; `prepare` later checks that the
   mask built with learned inventories drops exactly the same lines. This breaks
   the circle split → onsets → mask → counts → split.
2. The document split from those counts (src/stage4/splits.py), chosen once.
3. Every text variant of every language (the cross product of the text forks
   that apply to it) reuses the split, restricted to the documents it has, and
   is counted under its own settings.
4. B₀ for the run is the smallest training total over every language and every
   text variant (Brett, 2026-10-13), so every universe of the run trains on the
   same amount. Each variant is cut to B₀ from its own counts; each budget label
   (B, B/2, and 3B where that text reaches it) is prepared with
   `linguistic_inputs.prepare`, onset inventories from the variant's B₀ prefix.

Outputs go under `work/`; `run-record.json` lists every file the freeze needs.
Each counts pass and preparation is reused only when its inputs match.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import hashlib
import importlib.util
import itertools
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


L = _load('production_linguistic_inputs', ROOT / 'src/stage4/linguistic_inputs.py')
P = L.P
SP = _load('production_splits', ROOT / 'src/stage4/splits.py')
BU = _load('production_budgets', ROOT / 'src/stage4/budgets.py')
SS = _load('production_shared_settings', ROOT / 'src/stage3/shared_settings.py')
C = _load('production_corpora', ROOT / 'src/stage7/corpora.py')
SCHEMA = 'production-counts-v1'


def digest(value):
    return hashlib.sha256(P.canonical(value).encode()).hexdigest()


def variants(language, run, prose_values=()):
    """The text settings for one language in one run, first-listed first."""
    forks = [f for f in ('stub', 'gap') if SS.applicable(f, language, run)]
    values = [SS.FORKS[f] for f in forks]
    if SS.applicable('thai_prose_lines', language, run):
        forks.append('thai_prose_lines')
        values.append(tuple(v for v in SS.FORKS['thai_prose_lines'] if v in prose_values))
    return [dict(run=run, **dict(zip(forks, combo))) for combo in itertools.product(*values)]


def counts(texts, language, gap, work, backend, cache=None, saved_only=False):
    """First-listed syllables per line under the common mask built with empty inventories.

    cache: the language's G2P cache folder (`g2p_cache`); by default the mask and
    the scan each keep their own inside `work`. saved_only: return the saved counts
    or refuse; a variant's worker reads the first-listed counts another worker made.
    """
    work = Path(work)
    key = digest(dict(texts=texts, language=language, gap=gap, versions=P.version(),
                      backend=backend.descriptor() if backend else None))
    marker = work / 'counts.json'
    if marker.exists():
        saved = json.loads(marker.read_text())
        if saved.get('key') == key:
            return saved['counts'], saved['mask_sha256']
    if saved_only:
        raise ValueError(f'{language}: the first-listed counts must be measured before another variant')
    declarations = P.registry().universes(language)
    def bootstrap(declaration):
        return dict(P.registry_configuration(declaration, inventory=frozenset(), g2p=backend), gap_treatment=gap)
    # Without a supplied G2P the mask's declarations can be scanned in parallel (P.mask_adapter rebuilds bootstrap).
    mask = (P.build_language_mask(texts, language, work / 'counts-mask.json', cache_dir=cache,
                                  adapter_spec=dict(gap_treatment=gap, inventories={})) if backend is None else
            P.build_language_mask(texts, language, work / 'counts-mask.json', prepare=bootstrap, cache_dir=cache))
    validated = P.validated_mask(mask)  # once, not per document
    first = declarations[0]
    result = {}
    for document, lines in texts.items():
        report = P.process_document(document, lines, language, first['option'], work / 'scan',
                                    cache_dir=cache or work / 'g2p-cache', removal_mask=validated, declaration=first,
                                    _scan_only=True, **bootstrap(first))
        result[document] = [len(line['syllables']) for line in report['lines']]
    P.atomic(marker, (P.canonical(dict(key=key, counts=result, mask_sha256=mask['sha256'])) + '\n').encode())
    return result, mask['sha256']


MAIN_FORKS = ('line', 'run', 'budget', 'stub', 'gap')


def named_inputs():
    """Named-universe inputs for the main run: the full panel and its shared forks in registry order.

    The language-set fork (with or without YUE) is a panel choice, not a job
    label, and the Thai prose lines exist only in the Wikipedia run, where no
    named universe (and so no neural estimate) is defined.
    """
    return dict(languages=sorted(P.registry().REGISTRY),
                shared_settings={fork: list(SS.FORKS[fork]) for fork in MAIN_FORKS})


def workers():
    """Languages counted or prepared at once: INFO_RATE_WORKERS, default 1 (in this process)."""
    value = os.environ.get('INFO_RATE_WORKERS', '1')
    if not value.isdigit() or int(value) < 1:
        raise ValueError('INFO_RATE_WORKERS must be a positive integer')
    return int(value)


def g2p_cache(work, language):
    """One G2P cache folder per language for the whole counts phase (P9, item 8a).

    Every stage, variant, declaration and run of a language reads and writes it:
    entries are keyed by G2P signature and word, and the post-fix Catalan run spent
    most of its CPU starting espeak-ng again for the same word types in nine
    separate folders (`results/p9/README.md` §1).
    """
    return Path(work) / 'g2p-cache' / language


def _language(run_name, language, rows, root, work, sizes, seed, backend, only=None):
    """One language of one run: the split from its first-listed counts, then every text variant's counts.

    Holds one corpus at a time: each variant keeps its training units and the
    manifest entry it is read from again when it is prepared. only: one variant's
    settings digest (P9, item 8a); the split still comes from the first-listed
    counts, which for any other variant must already be saved.
    """
    prose = [e.get('thai_prose_lines') for e in rows if e.get('thai_prose_lines')]
    listed = variants(language, run_name, prose)
    first = listed[0]
    directory = work / run_name / language
    measured = {}
    if only is not None and only not in {digest(v) for v in listed}:
        raise ValueError(f'{language}: no text variant {only}')
    for settings in listed:
        if only is not None and settings != first and digest(settings) != only:
            continue
        entry = next(e for e in rows if e.get('thai_prose_lines') == settings.get('thai_prose_lines'))
        corpus = C.read_entry(entry, root, settings.get('stub', '0.5'))
        if settings == first:
            # The first-listed variant is counted for the split: same text, same counts.
            per_line, _ = counts(corpus['texts'], language, first.get('gap', 'drop'), directory / 'counts-first', backend,
                                 g2p_cache(work, language), saved_only=only not in (None, digest(first)))
            split, split_record = SP.make_split(
                [dict(document=d, group=corpus['groups'][d], syllables=sum(per_line[d])) for d in corpus['texts']],
                language, seed=seed, **sizes)
            P.atomic(directory / 'split.json', (P.canonical(split) + '\n').encode())
            base = dict(split=split, split_record=split_record, units=[[d, per_line[d]] for d in split['train']],
                        duplicates=corpus['duplicates'], dropped_stubs=corpus['dropped_stubs'])
            mask = directory / 'counts-first' / 'counts-mask.json'
        else:
            # Every other variant, restricted to its documents in the one split, counted under its own settings.
            per_line, _ = counts(corpus['texts'], language, settings.get('gap', 'drop'),
                                 directory / digest(settings)[:12] / 'counts', backend, g2p_cache(work, language))
            mask = directory / digest(settings)[:12] / 'counts' / 'counts-mask.json'
        if only is not None and digest(settings) != only:
            del corpus
            continue  # the first-listed variant, read only for the split
        part = {s: tuple(d for d in ids if d in corpus['texts']) for s, ids in base['split'].items()}
        alternative = corpus.get('stub_rule_alternative')
        measured[digest(settings)] = dict(
            settings=settings, entry=entry, directory=directory / digest(settings)[:12], split=part, mask=mask,
            units=[[d, per_line[d]] for d in part['train']],
            stub_rule_alternative=None if alternative is None else dict(
                documents=len(alternative['documents']), characters=alternative['characters']))
        del corpus
    return base, measured


def measure_language(run_name, language, rows, *, root, work, sizes, seed, backends=None, variant=None):
    """What B₀ needs from one language: each variant's training total, in variant order (or one variant's)."""
    base, measured = _language(run_name, language, rows, root, work, sizes, seed, dict(backends or {}).get(language),
                               only=variant)
    return dict(first_total=BU.total(base['units']),
                variants=[dict(settings=m['settings'], total=BU.total(m['units']),
                               stub_rule_alternative=m['stub_rule_alternative']) for m in measured.values()])


def save_arguments(path, arguments):
    """Publish a label's prepare arguments once; refuse different ones later.

    A retry with other settings would otherwise overwrite the arguments the
    NS-closest phase trusts before prepare's own resume check refused it.
    """
    path = Path(path)
    data = (P.canonical(arguments) + '\n').encode()
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f'Refusing to replace {path.name} with changed preparation arguments')
        return
    P.atomic(path, data)


def prepare_language(run_name, language, rows, *, root, work, sizes, seed, b0, floor, simulated, neural_settings,
                     onset_source='lexicon',
                     backends=None, variant=None):
    """Every text variant (or one) and budget label of one language, cut to the run's B₀; its run-record entry."""
    backends = dict(backends or {})
    base, measured = _language(run_name, language, rows, root, work, sizes, seed, backends.get(language),
                               only=variant)
    prose = [e.get('thai_prose_lines') for e in rows if e.get('thai_prose_lines')]
    prepared = []
    for key in sorted(measured):
        m = measured[key]
        settings, split, units, directory = m['settings'], m['split'], m['units'], m['directory']
        texts = C.read_entry(m['entry'], root, settings.get('stub', '0.5'))['texts']
        paths = C.write_documents({d: texts[d] for s in split.values() for d in s}, directory / 'documents')
        del texts
        labels = ['B', 'B/2'] + (['3B'] if BU.total(units) >= 3 * b0 else [])
        # Every budget label of a variant is prepared from one scan (P8, result-neutral),
        # with the variant's counts mask as the provisional mask.
        outputs, cuts, shared_by_label = {}, {}, {}
        for label in labels:
            budget = BU.argument_for(units, b0, label)
            output = directory / label.replace('/', '-')
            arguments = dict(documents={d: paths[d] for s in split.values() for d in s},
                             splits={s: list(ids) for s, ids in split.items()}, language=language,
                             floor=floor, onset_source=onset_source,
                             gap_treatment=settings.get('gap', 'drop'), simulated=simulated,
                             shared=dict(settings, budget=label), budget=budget,
                             neural_settings=neural_settings,
                             provisional_mask=str(Path(m['mask']).relative_to(root)))
            # Saved so the NS-closest phase can prepare again with the lens report. A
            # retry with other settings is refused here, before prepare's own resume
            # check, so the saved arguments always describe the preparation on disk.
            save_arguments(output.parent / f"{output.name}.prepare-arguments.json", arguments)
            outputs[label], cuts[label], shared_by_label[label] = output, budget, arguments['shared']
        values = L.prepare(arguments['documents'], arguments['splits'], language,
                           backends={language: backends[language]} if language in backends else None,
                           floor=floor, onset_source=onset_source,
                           gap_treatment=arguments['gap_treatment'], simulated=simulated,
                           labels=[dict(output=outputs[l], shared=shared_by_label[l], budget=cuts[l]) for l in labels],
                           provisional_mask=m['mask'],
                           named_inputs=None if simulated else named_inputs(),
                           neural_settings=neural_settings, g2p_cache=g2p_cache(work, language))
        for label, value in zip(labels, values):
            budget, output = cuts[label], outputs[label]
            prepared.append(dict(settings=settings, budget=label, target=budget['target'],
                                 arguments=str((output.parent / f"{output.name}.prepare-arguments.json").relative_to(root)),
                                 realised_first_listed=BU.cut(units, budget['target'])[1],
                                 inputs=str((output / 'inputs.json').relative_to(root)),
                                 inputs_sha256=value['sha256'], removal_mask_sha256=value['removal_mask_sha256'],
                                 realised_by_option={k: sum(v['train'].values()) for k, v in value['counts'].items()}))
    prepared.sort(key=lambda p: (variants(language, run_name, prose).index(p['settings']),
                                 SS.FORKS['budget'].index(p['budget'])))
    return dict(split=base['split_record'], duplicates=base['duplicates'], dropped_stubs=base['dropped_stubs'],
                training_total=BU.total(base['units']), preparations=prepared)


def check_language(run_name, language, rows, *, root, work, simulated, backends=None, variant=None):
    """The one-at-a-time checks of one language (or one check view, `variant`), as preparations.

    Each check view (`multiverse.check_views`; design in DECISIONS.md, 2026-10-16)
    is prepared from the main run's first-listed text variant at B, from the same
    documents, splits and budget that preparation was given, with its own masks over
    the view's declarations and the view's onset source and floor. No neural inputs.
    """
    backends = dict(backends or {})
    first = digest(_listed('main', language, rows)[0])[:12]
    source = work / 'main' / language / first / 'B.prepare-arguments.json'
    arguments = json.loads(source.read_text())
    main = json.loads((source.parent / 'B' / 'inputs.json').read_text())
    # The main preparation verified this budget against its first-listed units; a check uses it as given.
    if (main['budget'] != arguments['budget'] or {s: list(v) for s, v in main['splits'].items()} != arguments['splits']
            or main.get('check') is not None):
        raise ValueError(f'{language}: the check budget must be the main first-listed preparation\'s, as it verified it')
    views = P.registry().check_views(language)
    if variant is not None:
        views = [v for v in views if v['id'] == variant]
        if len(views) != 1:
            raise ValueError(f'{language}: no check view {variant}')
    prepared = []
    for view in views:
        output = work / run_name / language / view['id'] / 'B'
        value = L.prepare(arguments['documents'], arguments['splits'], language,
                          backends={language: backends[language]} if language in backends else None,
                          floor=view['preparation']['floor'], onset_source=view['preparation']['onset_source'],
                          gap_treatment=arguments['gap_treatment'], simulated=simulated,
                          labels=[dict(output=output, shared=arguments['shared'], budget=arguments['budget'])],
                          named_inputs=None, neural_settings=None, g2p_cache=g2p_cache(work, language),
                          check=view['id'])[0]
        prepared.append(dict(view={k: view[k] for k in view if k != 'declarations'},
                             inputs=str((output / 'inputs.json').relative_to(root)), inputs_sha256=value['sha256'],
                             removal_mask_sha256=value['removal_mask_sha256'],
                             main_inputs=str((source.parent / 'B' / 'inputs.json').relative_to(root))))
    return dict(checks=prepared)


STAGES = dict(measure=measure_language, prepare=prepare_language, check=check_language)


def _listed(run_name, language, rows):
    """A language's text variants, first-listed first, as `_language` lists them."""
    return variants(language, run_name, [e.get('thai_prose_lines') for e in rows if e.get('thai_prose_lines')])


def _combine(stage, run_name, language, rows, values):
    """One language's entry from its variants' worker results, as one process would give it."""
    if stage == 'check':
        return dict(checks=[c for v in values for c in v['checks']])
    if stage == 'measure':
        if len({v['first_total'] for v in values}) != 1:
            raise ValueError(f'{language}: variant workers disagree on the first-listed total')
        return dict(first_total=values[0]['first_total'], variants=[x for v in values for x in v['variants']])
    shared = {k: values[0][k] for k in values[0] if k != 'preparations'}
    if any({k: v[k] for k in v if k != 'preparations'} != shared for v in values):
        raise ValueError(f'{language}: variant workers disagree on the split')
    order = _listed(run_name, language, rows)
    preparations = sorted((p for v in values for p in v['preparations']),
                          key=lambda p: (order.index(p['settings']), SS.FORKS['budget'].index(p['budget'])))
    return dict(shared, preparations=preparations)


def _by_language(stage, run_name, by_language, n, *, root, work, backends, **options):
    """`stage` for every language of a run, in this process or in n fresh interpreters at once.

    Each worker is a new `python -I -B` running this file on one text variant of
    one language (P9, item 8a: Brett, one worker per text variant), not a fork, so
    nothing but its JSON arguments and its JSON result crosses the process
    boundary. The first-listed variants are measured first, since every other
    variant takes its split from them; a language's entry is put together from
    its variants' results in variant order. Every result goes through JSON on
    both routes, so the run record is the same however many workers there are.
    Largest corpora start first.
    """
    if n <= 1:
        return {language: json.loads(P.canonical(STAGES[stage](run_name, language, rows, root=root, work=work,
                                                               backends=backends, **options)))
                for language, rows in sorted(by_language.items())}
    if backends:
        raise ValueError('Supplied G2P backends cannot reach a worker process')
    import concurrent.futures, subprocess, time
    def size(language):
        return sum((root / e['path']).stat().st_size for e in by_language[language])
    def one(language, variant):
        folder = work / run_name / language / 'workers'
        name = f'{stage}-{variant[:12]}'
        spec, result, log = folder / f'{name}.json', folder / f'{name}-result.json', folder / f'{name}.log'
        for stale in (result, folder / f'{name}-usage.json'):
            stale.unlink(missing_ok=True)
        P.atomic(spec, (P.canonical(dict(stage=stage, run_name=run_name, language=language, rows=by_language[language],
                                          root=str(root), work=str(work), options=dict(options, variant=variant)))
                        + '\n').encode())
        started = time.time()
        with open(log, 'wb') as out:
            code = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker', str(spec)],
                                  stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT).returncode
        if code != 0 or not result.exists():
            tail = log.read_bytes()[-2000:].decode('utf-8', 'replace')
            raise RuntimeError(f'{stage} worker for {run_name} {language} failed (variant {variant[:12]}, exit {code}); '
                               f'log {log}:\n{tail}')
        value = json.loads(result.read_text(encoding='utf-8'))
        usage = dict(json.loads((folder / f'{name}-usage.json').read_text()), wall_seconds=round(time.time() - started, 1))
        P.atomic(folder / f'{name}-usage.json', (P.canonical(usage) + '\n').encode())
        return value
    order = sorted(by_language, key=lambda language: (-size(language), language))
    if stage == 'check':  # one worker per check view
        listed = {language: [v['id'] for v in P.registry().check_views(language)] for language in order}
    else:
        listed = {language: [digest(v) for v in _listed(run_name, language, by_language[language])] for language in order}
    # Measuring: every first-listed variant, then the rest. Preparing: every variant at once.
    waves = ([[(l, listed[l][0]) for l in order], [(l, v) for l in order for v in listed[l][1:]]]
             if stage == 'measure' else [[(l, v) for l in order for v in listed[l]]])
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        for jobs in waves:
            futures = {job: pool.submit(one, *job) for job in jobs}
            done, _ = concurrent.futures.wait(futures.values(), return_when=concurrent.futures.FIRST_EXCEPTION)
            failed = [f.exception() for f in done if f.exception() is not None]
            if failed:  # jobs not yet started don't start; running ones finish
                for f in futures.values():
                    f.cancel()
                raise failed[0]
            results.update({job: f.result() for job, f in futures.items()})
    return {language: _combine(stage, run_name, language, by_language[language],
                               [results[(language, v)] for v in listed[language]])
                    if listed[language] else dict(checks=[])
            for language in sorted(by_language)}


def _worker(spec_path):
    import resource, time
    started = time.process_time()
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    root, work = Path(spec['root']), Path(spec['work'])
    value = STAGES[spec['stage']](spec['run_name'], spec['language'], spec['rows'], root=root, work=work, **spec['options'])
    folder, name = Path(spec_path).parent, Path(spec_path).stem  # <stage>-<variant>
    P.atomic(folder / f"{name}-result.json", (P.canonical(value) + '\n').encode())
    # Peak memory (bytes on macOS, kilobytes on Linux) and CPU time, kept out of the run record.
    # Child CPU is the G2P tools the worker starts (espeak-ng once per new word type).
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    P.atomic(folder / f"{name}-usage.json", (P.canonical(dict(
        max_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, platform=sys.platform,
        cpu_seconds=round(time.process_time() - started, 1),
        child_cpu_seconds=round(children.ru_utime + children.ru_stime, 1))) + '\n').encode())


def run(manifest_path, work, *, root=ROOT, sizes=None, seed=SP.SEED, backends=None, floor=3, simulated=False,
        neural_settings=None, onset_source='lexicon'):
    """The counts phase for every run in the manifest; returns and writes the run record.

    With INFO_RATE_WORKERS above 1, text variants are counted, then prepared,
    that many at a time in separate processes (one per variant); supplied G2P backends (simulated runs
    only) can't cross a process boundary, so with them every language runs here.
    """
    root = Path(root).resolve()
    work = Path(work).resolve()
    if not work.is_relative_to(root):
        raise ValueError('The production work directory must be inside the project')
    if not simulated and backends:
        raise ValueError("A real run uses the registry's production G2P routes; supplied backends are for simulated runs")
    manifest = C.read_manifest(manifest_path, root)
    # Named universes span the whole registry panel, so a real main run must
    # hold every registry language; stop here rather than after the counts.
    main_languages = {e['language'] for e in manifest['entries'] if e['run'] == 'main'}
    if not simulated and main_languages != set(named_inputs()['languages']):
        raise ValueError('A real run needs every registry language in the main run; missing '
                         f"{sorted(set(named_inputs()['languages']) - main_languages)}, extra "
                         f"{sorted(main_languages - set(named_inputs()['languages']))}")
    sizes = dict(SP.DEFAULT_SIZES if sizes is None else sizes)
    backends = dict(backends or {})
    n = 1 if backends else workers()
    record = dict(schema=SCHEMA, corpus_manifest_sha256=C.sha256_file(manifest_path), sizes=sizes, seed=seed,
                  floor=floor, onset_source=onset_source, simulated=simulated, versions=P.version(), runs={})
    for run_name in ('main', 'wikipedia'):
        entries = [e for e in manifest['entries'] if e['run'] == run_name]
        if not entries:
            continue
        by_language = {}
        for entry in entries:
            by_language.setdefault(entry['language'], []).append(entry)
        common = dict(root=root, work=work, backends=backends, sizes=sizes, seed=seed)
        summaries = _by_language('measure', run_name, by_language, n, **common)
        # Every text variant of every language, counted under its own settings, before any budget is set.
        totals = {(language, digest(v['settings'])): v for language, s in sorted(summaries.items()) for v in s['variants']}
        # B₀: the smallest training total over every language and text variant (Brett, 2026-10-13).
        smallest = min(totals, key=lambda k: (totals[k]['total'], k))
        b0 = totals[smallest]['total']
        if b0 < 2:
            raise ValueError('The smallest training total is too small for B/2')
        # Reported beside B₀: what first-listed settings alone would give, so the
        # cost of taking the minimum over variants is visible.
        first_listed = min(s['first_total'] for s in summaries.values())
        plan = dict(B0=b0, B0_first_listed=first_listed,
                    set_by=dict(language=smallest[0], settings=totals[smallest]['settings']),
                    totals={k[0] + ' ' + P.canonical(v['settings']): v['total'] for k, v in totals.items()},
                    # The duplicate-article stub rule's measured alternative, per Wikipedia variant.
                    stub_rule_alternative={k[0] + ' ' + P.canonical(v['settings']): v['stub_rule_alternative']
                                           for k, v in totals.items() if v['stub_rule_alternative'] is not None})
        P.atomic(work / run_name / 'budget-plan.json', (P.canonical(plan) + '\n').encode())
        options = dict(common, b0=b0, floor=floor, onset_source=onset_source, simulated=simulated,
                       neural_settings=neural_settings)
        languages = _by_language('prepare', run_name, by_language, n, **options)
        record['runs'][run_name] = dict(B0=plan['B0'], B0_first_listed=plan['B0_first_listed'],
                                        set_by=plan['set_by'], totals=plan['totals'],
                                        stub_rule_alternative=plan['stub_rule_alternative'], languages=languages)
    # The one-at-a-time checks (Brett; design in DECISIONS.md, 2026-10-16), from the main run's preparations.
    main_entries = [e for e in manifest['entries'] if e['run'] == 'main']
    if main_entries:
        by_language = {}
        for entry in main_entries:
            by_language.setdefault(entry['language'], []).append(entry)
        record['checks'] = _by_language('check', 'checks', by_language, n, root=root, work=work, backends=backends,
                                        simulated=simulated)
    record['sha256'] = digest(record)
    P.atomic(work / 'run-record.json', (P.canonical(record) + '\n').encode())
    return record


if __name__ == '__main__':
    if sys.argv[1:2] != ['--worker'] or len(sys.argv) != 3:
        raise SystemExit('usage: counts_phase.py --worker SPEC.json (started by run())')
    _worker(sys.argv[2])
