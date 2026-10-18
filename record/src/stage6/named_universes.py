"""Prospective named selections from the local registry and supplied settings.

Shared declaration: {fork: [first_label, ...]}. Only its first-listed complete
setting is selected. NS-closest is recomputed from a run_files report file;
the file hash binds that calibration evidence to the resulting declaration.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage6_named_universes_iterables", _BoundaryPath(__file__).resolve().parents[1] / "stage5/iterables.py")
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import copy
import importlib.util
import hashlib
import json
import math
from pathlib import Path

SCHEMA = 'named-universes-v1'


@_boundary
def registry_module():
    path = Path(__file__).resolve().parents[1] / 'stage3/multiverse.py'
    spec = importlib.util.spec_from_file_location('named_registry', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@_boundary
def options_for(config, registry):
    language, option = config['language'], config['option']
    entry = registry[language][option]
    if entry['calibration_only']:
        raise ValueError('named universe cannot use calibration-only configuration')
    result = dict(convention=option)
    for fork in entry['forks']:
        value = config[fork['target']][fork['setting']]
        if value not in fork['values']:
            raise ValueError('named configuration has unregistered fork value')
        if fork['setting'] in result:
            raise ValueError('ambiguous named option label')
        result[fork['setting']] = value
    return result


@_boundary
def read_lens_report(path):
    """Require run_files provenance and recompute from its declared inputs.

    This catches mistaken/manual selections, not deliberate report forgery.
    Neither the saved winner nor caller-supplied derived scores are trusted.
    """
    if not isinstance(path, (str, Path)):
        raise ValueError('NS lens must be a run_files report file')
    raw = Path(path).read_bytes()
    report = json.loads(raw)
    inputs = report.get('selection_inputs', {})
    hashes = report.get('input_sha256', {})
    if (report.get('schema') != 'ns-lens-v1' or inputs.get('writer') != 'ns_lens.run_files'
            or not {'configs', 'selected_texts', 'universes'}.issubset(inputs)
            or not {'readings', 'texts'}.issubset(hashes)
            or any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
                   for v in hashes.values())):
        raise ValueError('NS lens must be a complete ns_lens.run_files report')
    spec = importlib.util.spec_from_file_location('named_ns_lens', Path(__file__).with_name('ns_lens.py'))
    lens = importlib.util.module_from_spec(spec); spec.loader.exec_module(lens)
    readings = {}
    for row in report['per_text']:
        key = (row['Language'], row['Text'])
        ns = row['NS']
        if not isinstance(ns, (int, float)) or not math.isfinite(ns) or ns <= 0:
            raise ValueError('NS lens report needs positive finite NS')
        if key in readings and readings[key]['NS'] != ns:
            raise ValueError('Conflicting NS in lens report')
        readings[key] = dict(Language=key[0], Text=key[1], NS=ns)
    rebuilt = lens.evaluate(list(readings.values()), report['per_text'], inputs['universes'],
        selected_texts={tuple(key) for key in inputs['selected_texts']}, configs=inputs['configs'],
        leaveout_mode=report['leaveout_mode'])
    return rebuilt, hashlib.sha256(raw).hexdigest()


@_boundary
def build(languages, shared_settings, *, ns_lens=None, registry=None):
    module = registry or registry_module()
    if not languages or len(set(languages)) != len(languages):
        raise ValueError('declare unique languages for named universes')
    if not isinstance(shared_settings, dict) or not shared_settings:
        raise ValueError('supply an ordered shared-settings declaration')
    shared = {}
    for key, values in shared_settings.items():
        if (not isinstance(key, str) or not key or not isinstance(values, (list, tuple)) or not values
                or any(not isinstance(v, str) or not v for v in values) or len(set(values)) != len(values)):
            raise ValueError('shared forks need unique ordered string labels')
        shared[key] = values[0]
    configurations = {language: copy.deepcopy(module.universes(language)[0]) for language in languages}
    first = dict(name='first-listed', status='ready', shared=shared,
                 options={l: options_for(c, module.REGISTRY) for l, c in configurations.items()},
                 configurations=configurations)
    # Currently every pronunciation source is the selected main source. A
    # future dictionary fork needs an explicit registry adapter before use.
    if any('dictionary' in f['values'] for l in languages for e in module.REGISTRY[l].values() for f in e['forks']):
        raise ValueError('dictionary fork added: define its named selection before building')
    dictionary = dict(copy.deepcopy(first), name='dictionary', alias_of='first-listed',
                      alias_reason='registry has no dictionary alternative')
    closest = dict(name='NS-closest', status='pending', shared=shared,
                   reason='NS lens output with a complete production selection is required')
    if ns_lens is not None:
        ns_lens, report_sha256 = read_lens_report(ns_lens)
        target = ns_lens.get('ns_closest')
        if target is not None:
            if set(target['languages']) != set(languages):
                raise ValueError('NS-closest selection must cover exactly the declared languages')
            score = target.get('calibration_score')
            if not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
                raise ValueError('NS-closest needs a finite nonnegative calibration score')
            configs = {}
            for row in ns_lens['per_text']:
                cid, config = row['configuration_id'], row['configuration']
                if cid in configs and configs[cid] != config:
                    raise ValueError('conflicting NS-lens configuration IDs')
                configs[cid] = config
            selected = {}
            for language, cid in target['languages'].items():
                if cid not in configs or configs[cid]['language'] != language:
                    raise ValueError('NS-closest configuration is missing from lens output')
                config = copy.deepcopy(configs[cid])
                # configuration_id is metadata, not part of the registry value.
                config.pop('configuration_id', None)
                if config not in module.universes(language):
                    raise ValueError('NS-closest configuration is outside production registry')
                selected[language] = config
            closest = dict(name='NS-closest', status='ready', shared=shared,
                           options={l: options_for(c, module.REGISTRY) for l, c in selected.items()},
                           configurations=selected, calibration_score=score,
                           provenance=dict(schema=ns_lens['schema'], scope=target.get('scope'),
                                           tie_rule=ns_lens.get('tie_rule'), report_sha256=report_sha256))
    declarations = [first, dictionary, closest]
    return dict(schema=SCHEMA, shared_settings=copy.deepcopy(shared_settings),
                declarations={e: copy.deepcopy(declarations) for e in ('kenlm', 'neural')})


@_boundary
def consume(value):
    """Accept builder output or the existing estimator-to-list declarations."""
    if value.get('schema') != SCHEMA:
        return value
    result = {estimator: declarations for estimator, declarations in value['declarations'].items()}
    for declarations in result.values():
        for d in declarations:
            if d.get('status') not in ('ready', 'pending'):
                raise ValueError('invalid named universe availability')
            if d.get('alias_of'):
                matches = [other for other in declarations if other['name'] == d['alias_of']
                           and other.get('shared') == d.get('shared')]
                if len(matches) != 1 or matches[0].get('options') != d.get('options'):
                    raise ValueError('named alias must select the same estimates as its target')
    return result
