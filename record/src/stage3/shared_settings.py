"""Shared settings: the forks every language in a universe takes together.

From `notes/multiverse-spec.md` section 2.1, values in the spec's order, so the
first value of each fork is the first-listed universe's. Labels are the ones jobs
carry in `shared` (line labels as `linguistic_inputs.prepare` writes them).

Applicability:
- `line`, `budget`: every language and run.
- `run`: main (16 subtitle languages, YUE from Wikipedia) or Wikipedia (all 17).
- `yue`: the language panel with or without YUE; a panel-level fork (same B).
- `stub`, `gap`: wherever Wikipedia text is used (every language in the Wikipedia
  run; only YUE in the main run).
- `thai_prose_lines`: THA in the Wikipedia run only.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
FORKS = {
    'line': ('running', 'bounded'),            # cross-line; line-bounded
    'budget': ('B', 'B/2', '3B'),              # 3B only for languages that reach it
    'run': ('main', 'wikipedia'),
    'yue': ('with', 'without'),
    'stub': ('0.5', '0.3'),
    'gap': ('drop', 'split'),
    'thai_prose_lines': ('80', '150', 'paragraph'),
}
FIRST_LISTED = {fork: values[0] for fork, values in FORKS.items()}
PANEL_FORKS = ('yue',)
# Forks that change the text a language's line mask is built on. One frozen mask
# is required per language and setting of these (and per inclusion set); line
# treatment, budget and the YUE language set leave the mask unchanged.
TEXT_FORKS = ('run', 'stub', 'gap', 'thai_prose_lines')


def mask_key(language, shared):
    """The language plus the text-changing shared settings that apply to it: one mask per key."""
    shared = shared if isinstance(shared, dict) else {}
    run = shared.get('run', FIRST_LISTED['run'])
    applies = [f for f in TEXT_FORKS if f == 'run' or (run in FORKS['run'] and applicable(f, language, run))]
    return (language, tuple((fork, shared.get(fork)) for fork in applies))


def wikipedia_text(language, run):
    """Whether this language's corpus in this run is Wikipedia text."""
    if run not in FORKS['run']:
        raise ValueError(f'Unknown run: {run}')
    return run == 'wikipedia' or language == 'YUE'


def applicable(fork, language, run):
    """Whether a shared fork applies to one language's jobs in a run."""
    if fork not in FORKS:
        raise ValueError(f'Unknown shared fork: {fork}')
    if fork in ('stub', 'gap'):
        return wikipedia_text(language, run)
    if fork == 'thai_prose_lines':
        return language == 'THA' and run == 'wikipedia'
    return fork not in PANEL_FORKS


def check(shared, language):
    """Refuse unknown forks or values, the panel fork, and text forks that don't apply to this language.

    A job carries only the settings that apply to it: gap and stub where its
    text is Wikipedia text, the Thai prose line for THA in the Wikipedia run.
    Assembly treats a missing inapplicable setting as not applicable
    (`assemble._absorb_inapplicable`), so subtitle languages need no gap or
    stub labels and nothing is estimated twice. The YUE language set is a panel
    choice made in reporting, never a job label.
    """
    if not isinstance(shared, dict):
        raise ValueError('shared settings must be a mapping of fork to label')
    run = shared.get('run', FIRST_LISTED['run'])
    for fork, value in shared.items():
        if fork not in FORKS or value not in FORKS[fork]:
            raise ValueError(f'Unknown shared setting {fork}={value}')
        if fork in PANEL_FORKS:
            raise ValueError(f'{fork} is a panel choice, not a job label')
        if fork in TEXT_FORKS and fork != 'run' and not applicable(fork, language, run):
            raise ValueError(f'Shared fork {fork} does not apply to {language} in the {run} run')
    return shared


def restrict(declared, job_shared, language):
    """A named universe's settings as they apply to one language's jobs.

    Text settings that don't apply to the language are left out; everything
    else (line, run, budget, and any applicable text setting) is kept, so a job
    missing one of those can't match.
    """
    run = job_shared.get('run', FIRST_LISTED['run'])
    return {k: v for k, v in declared.items()
            if not (k in TEXT_FORKS and k != 'run' and not applicable(k, language, run)) and k not in PANEL_FORKS}


def check_order(shared_settings):
    """A named-universe declaration lists known forks with values in the registry's order."""
    for fork, values in shared_settings.items():
        if fork not in FORKS:
            raise ValueError(f'Unknown shared fork: {fork}')
        order = [v for v in FORKS[fork] if v in values]
        if list(values) != order or len(order) != len(values) or not values or values[0] != FIRST_LISTED[fork]:
            raise ValueError(f'Shared fork {fork} must list known values in the registry order {FORKS[fork]}, '
                             'starting with the first-listed one')
    return shared_settings
