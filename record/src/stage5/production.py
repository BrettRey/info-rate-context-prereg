"""Production neural configuration, pinned to the approved fake-data preset."""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage5_production_iterables", _BoundaryPath(__file__).with_name("iterables.py"))
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import importlib.util
from pathlib import Path

NAMED_UNIVERSES = ('first-listed', 'dictionary', 'NS-closest')
PRESET = 'zero_unigram_cosine5'


@_boundary
def neural_settings():
    # Derive the complete declaration from the approval's source of truth.
    path = Path(__file__).resolve().parents[1] / 'fakedata/f1_neural_final.py'
    spec = importlib.util.spec_from_file_location('production_final_preset', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.settings_for(module.FULL)


@_boundary
def validate_neural(job, effective):
    if job.get('simulated') is True:
        return
    if job.get('named_universe') not in NAMED_UNIVERSES:
        raise ValueError('production neural job must name first-listed, dictionary or NS-closest')
    declaration = resolve_named(job)
    if effective['settings'] != neural_settings():
        raise ValueError('production neural settings must equal approved zero_unigram_cosine5 preset')
    return declaration


@_boundary
def resolve_named(job):
    """Rebuild the prospective selection; never trust an arbitrary ready label.

    Required named_universe_inputs declares the full registry language panel
    and ordered shared_settings. Optional ns_lens names a run_files report file.
    The production command must supply these from authoritative frozen files.
    """
    path = Path(__file__).resolve().parents[1] / 'stage6/named_universes.py'
    spec = importlib.util.spec_from_file_location('production_named_builder', path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    if 'named_universe_inputs' not in job:
        raise ValueError('production neural job requires named_universe_inputs')
    inputs = job['named_universe_inputs']
    if not isinstance(inputs, dict) or set(inputs) - {'languages', 'shared_settings', 'ns_lens'}:
        raise ValueError('invalid named universe builder inputs')
    if not {'languages', 'shared_settings'}.issubset(inputs):
        raise ValueError('named universe inputs require languages and shared_settings')
    languages = inputs['languages']
    registry = builder.registry_module()
    if set(languages) != set(registry.REGISTRY):
        raise ValueError('production named universe inputs must declare the full language panel')
    built = builder.build(languages, inputs['shared_settings'], registry=registry,
        ns_lens=inputs.get('ns_lens'))
    declaration = next(d for d in builder.consume(built)['neural']
                       if d['name'] == job['named_universe'])
    if declaration['status'] != 'ready':
        raise ValueError('named universe is pending: ' + declaration['name'])
    shared = importlib.util.spec_from_file_location('production_shared_settings', Path(__file__).resolve().parents[1] / 'stage3/shared_settings.py')
    SHARED = importlib.util.module_from_spec(shared); shared.loader.exec_module(SHARED)
    if (SHARED.restrict(declaration['shared'], job['shared'], job['language']) != job['shared'] or
            declaration['options'].get(job['language']) != job['options']):
        raise ValueError('production neural options/shared setting differ from named universe declaration')
    return declaration
