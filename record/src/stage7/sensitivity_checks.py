"""The one-at-a-time sensitivity checks: each alternative against its default, on identical text.

Brett's checks (boundary rows, 2026-10-10; onset source and floors 1 and 10,
2026-10-15); how they run is in DECISIONS.md, 2026-10-16. The counts phase prepares
each check view (`multiverse.check_views`) from the main run's first-listed variant
at B; the entropy phase scores its KenLM jobs in the first-listed line treatment.
Here each check is reported as its two arms' estimates at every rung (pooled and
escape-coded) and their difference, the share of held-out syllable labels that
differ position by position (the count difference where a row changes counts),
and the masked lines of the check's mask beside the main preparation's. Nothing
here decides anything.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'sensitivity-checks-v1'


def _load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


L = _load('checks_linguistic_inputs', ROOT / 'src/stage4/linguistic_inputs.py')
P = L.P


def check_jobs(record, root, line):
    """Every check preparation's KenLM jobs in one line treatment."""
    jobs = []
    for info in record.get('checks', {}).values():
        for entry in info['checks']:
            jobs += [j for j in L.preparation_jobs(Path(root) / entry['inputs'], estimator='kenlm')
                     if j['shared']['line'] == line]
    return jobs


def _manifest(path):
    return L.read_preparation(path)


def _labels(manifest, key):
    record = manifest['syllable_records'][key]
    return L.read_record(record, manifest['artifacts'][record])


def label_change(a, b, documents):
    """Held-out syllable labels that differ between two scans of the same lines, position by position."""
    compared = changed = count_lines = count_difference = 0
    for d in documents:
        for x, y in zip(a[d]['lines'], b[d]['lines']):
            if x['status'] != 'complete' or y['status'] != 'complete':
                continue
            if len(x['syllables']) != len(y['syllables']):
                count_lines += 1; count_difference += len(y['syllables']) - len(x['syllables'])
                continue
            compared += len(x['syllables'])
            changed += sum(s['label'] != t['label'] for s, t in zip(x['syllables'], y['syllables']))
    return dict(syllable_tokens_compared=compared, labels_changed=changed,
                changed_share=changed / compared if compared else None,
                lines_with_count_change=count_lines, syllable_count_difference=count_difference)


def _masked(path, documents):
    mask = P.read_mask(path)
    return sum(len(mask['documents'][d]['masked_lines']) for d in documents if d in mask['documents'])


def report(record, root, records, entries, escape=None):
    """Each check's two arms, their difference at every rung, label changes and masked lines."""
    root = Path(root)
    by_job = {jid: job for jid, job in entries}
    arms = {}
    for r in records:
        job = by_job[r['job_id']]
        key = (str(Path(job['preparation']).resolve()), L.configuration_id(job['tokenisation']['declaration']))
        if key in arms:
            raise ValueError(f'Two scored jobs for one check arm: {key}')
        scores = {rung: s['id_bits'] for rung, s in r['scores'].items()}
        escaped = None
        if escape is not None:
            escaped = {rung: s['id_bits'] for rung, s in escape(r)['scores'].items()}
        arms[key] = dict(pooled=scores, escape_coded=escaped)
    rows = []
    for language, info in sorted(record.get('checks', {}).items()):
        by_view = {e['view']['id']: e for e in info['checks']}
        for entry in info['checks']:
            view = entry['view']
            path = (root / entry['inputs']).resolve()
            manifest = _manifest(path)
            keys = [L.configuration_id(d) for d in manifest['declarations']]
            if view['kind'] == 'preparation-default':
                continue
            if view['kind'] == 'boundary':
                if len(keys) != 2:
                    raise ValueError(f'{language}: a boundary check needs its default and changed declarations')
                default, changed = (str(path), keys[0]), (str(path), keys[1])
                declaration = manifest['declarations'][0]
                labels = label_change(_labels(manifest, keys[0]), _labels(manifest, keys[1]), manifest['splits']['test'])
            else:
                base = by_view[view['default']]
                base_path = (root / base['inputs']).resolve()
                base_manifest = _manifest(base_path)
                if [L.configuration_id(d) for d in base_manifest['declarations']] != keys or len(keys) != 1:
                    raise ValueError(f'{language}: a preparation check and its default must share one declaration')
                default, changed = (str(base_path), keys[0]), (str(path), keys[0])
                declaration = base_manifest['declarations'][0]
                labels = label_change(_labels(base_manifest, keys[0]), _labels(manifest, keys[0]),
                                      manifest['splits']['test'])
            if default not in arms or changed not in arms:
                raise ValueError(f'{language}: a check arm was not scored ({view["id"]})')
            estimates = {}
            for analysis in ('pooled', 'escape_coded'):
                a, b = arms[default][analysis], arms[changed][analysis]
                if a is None:
                    continue
                estimates[analysis] = {rung: dict(default=a[rung], alternative=b[rung], difference=b[rung] - a[rung])
                                       for rung in sorted(a)}
            documents = list(manifest['splits']['test'])
            rows.append(dict(language=language, view=view, declaration=declaration, estimates=estimates, labels=labels,
                             masked_test_lines=dict(check=_masked(path.parent / 'removal-mask.json', documents),
                                                    main=_masked((root / entry['main_inputs']).resolve().parent
                                                                 / 'removal-mask.json', documents))))
    unmeasured = [dict(row, language=language) for language in sorted(record.get('checks', {}))
                  for row in P.registry().unmeasured_checks(language)]
    return dict(schema=SCHEMA, checks=len(rows), rows=rows, unmeasured=unmeasured)


def declaration_label(declaration):
    """The default declaration a check row departs from: its option, then its settings and counter options."""
    choices = {**declaration.get('settings', {}), **declaration.get('counter_options', {})}
    return ' '.join([declaration['option'], *(f'{k}={v}' for k, v in sorted(choices.items()))])


def markdown(value):
    lines = ['# One-at-a-time sensitivity checks', '',
             'Each alternative against its default on identical text (main run, first-listed variant, B, running text).', '',
             '| language | default declaration | check | alternative | labels changed | rung 1 difference (bits) | rung 4 difference (bits) |',
             '|---|---|---|---|---:|---:|---:|']
    for row in value['rows']:
        view = row['view']
        name = f"row {view['row']} {view['setting']}" if view['kind'] == 'boundary' else view['setting']
        estimates = row['estimates'].get('escape_coded') or row['estimates']['pooled']
        share = row['labels']['changed_share']
        lines.append(f"| {row['language']} | {declaration_label(row['declaration'])} | {name} | {view['alternative']} | "
                     f"{'' if share is None else f'{share:.2%}'} | {estimates['1']['difference']:+.4f} | "
                     f"{estimates['4']['difference']:+.4f} |")
    for row in value['unmeasured']:
        lines.append(f"| {row['language']} | {declaration_label(row['declaration'])} | row {row['row']} {row['setting']} | "
                     f"{row['alternative']} | not run: {row['reason']} | | |")
    return '\n'.join(lines) + '\n'
