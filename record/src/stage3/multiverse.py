"""Count/ownership universes and separate one-at-a-time boundary checks.

Preparation-level one-at-a-time checks (the onset source and floor, Brett
2026-10-15) are declared in PREPARATION_CHECKS. Both kinds run as check views
(`check_views`): preparations of their own declarations, which the counts phase
prepares and the entropy phase scores apart from the universes.

REGISTRY is the per-language/option view of the authoritative counter and
boundary declarations. Fixed-row diagnostics and undefined checks stay visible,
but neither enters the universe cross product or sensitivity-check enumeration.
FIN-C is listed for calibration and excluded from universes/checks by default.
"""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import sys


def _load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


S = _load('stage3_segment', Path(__file__).with_name('segment.py'))
C = S.C


def _entry(language, option):
    scope = (language, option)
    forks = [dict(fork, target='counter_options') for _, fork in sorted(C.FORKS.items()) if scope in fork['options']]
    # T8 main tools were selected on 2026-10-10. Second tools are reported
    # one at a time against those mains, never crossed as universe forks.
    tool_checks = []
    if language == 'JPN':
        tool_checks.append(dict(row=55, setting='reader', values=('fugashi', 'pyopenjtalk'),
                                target='counter_options', options=(scope,), kind='reported-tool-alternative'))
    elif language == 'THA':
        tool_checks.append(dict(row=56, setting='tool', values=('tltk', 'thaig2p'),
                                target='counter_options', options=(scope,), kind='reported-tool-alternative'))
        forks.append(dict(row=57, setting='segmenter', values=('newmm', 'attacut'),
                          target='counter_options', options=(scope,)))
    if language in {'CMN', 'YUE', 'VIE'}:
        segmenters = {'CMN': ('jieba', 'pkuseg'), 'YUE': ('pycantonese', 'cantoseg'),
                      'VIE': ('underthesea', 'pyvi')}
        forks.append(dict(row={'CMN': 58, 'YUE': 59, 'VIE': 60}[language],
                          setting='segmenter', values=segmenters[language],
                          target='counter_options', options=(scope,)))
    # The lead's revised convention selects two ownership universes. The table's
    # joint unit remains callable as a diagnostic, outside that declared fork.
    ownership = S.BOUNDARY_ROWS[49]
    forks.append(dict(ownership, row=49, values=('left', 'right'), target='settings'))
    checks, diagnostics, unmeasured = tool_checks, [], []
    for row in range(45, 54):
        if row == 49:
            diagnostics.append(dict(ownership, row=row, values=('left', 'joint'),
                                    kind='undeclared-joint-ownership-diagnostic'))
            continue
        definition = S.BOUNDARY_ROWS.get(row)
        if definition is not None and scope in definition['options']:
            item = dict(definition, row=row, kind=definition.get('kind', 'one-at-a-time-check'))
            (diagnostics if row == 47 else checks).append(item)
        elif row == 48 and scope == ('FRA', 'B'):
            unmeasured.append({'row': row, 'reason': S.UNDEFINED_ROWS[row], 'kind': 'undefined-check'})
    return {'forks': tuple(forks), 'checks': tuple(checks), 'diagnostics': tuple(diagnostics),
            'unmeasured_checks': tuple(unmeasured), 'calibration_only': scope == ('FIN', 'C')}


REGISTRY = {language: {option: _entry(language, option) for option in options}
            for language, options in C.COUNTERS.items()}


def _baseline(language, option):
    # Explicit tool defaults keep registry outputs self-contained even though
    # the main tool is no longer a dimension of the cross product.
    native = ({'reader': 'fugashi'} if language == 'JPN' else
              {'tool': 'tltk'} if language == 'THA' else {})
    return {'language': language, 'option': option,
            'counter_options': {'chained_ties': C.DEFAULT_CHAINED_TIES,
                                **native,
                                **{fork['setting']: fork['values'][0] for fork in REGISTRY[language][option]['forks']
                                   if fork['target'] == 'counter_options'}},
            'settings': S.settings_for(language, option)}


def universes(language, *, include_calibration=False):
    """Deterministic cross product of applicable count forks and ownership."""
    if language not in REGISTRY:
        raise ValueError('Unknown language')
    result = []
    for option, entry in REGISTRY[language].items():
        if entry['calibration_only'] and not include_calibration:
            continue
        forks = entry['forks']
        for values in itertools.product(*(fork['values'] for fork in forks)):
            current = _baseline(language, option)
            for fork, value in zip(forks, values):
                current[fork['target']][fork['setting']] = value
            result.append(current)
    return tuple(result)


def checks(language, *, include_calibration=False):
    """Each alternative versus a fresh default; count/ownership forks never vary."""
    if language not in REGISTRY:
        raise ValueError('Unknown language')
    result = []
    for option, entry in REGISTRY[language].items():
        if entry['calibration_only'] and not include_calibration:
            continue
        for check in entry['checks']:
            for alternative in check['values'][1:]:
                base = _baseline(language, option)
                other = _baseline(language, option)
                target = check.get('target', 'settings')
                other[target][check['setting']] = alternative
                result.append({'row': check['row'], 'setting': check['setting'],
                               'target': target,
                               'alternative': alternative, 'default': base, 'changed': other})
    return tuple(result)


# Preparation-level settings: they move syllable boundaries, never counts, so like
# the boundary rows they are one-at-a-time sensitivity checks against the default,
# not forks, measured by their changed-label share and deciding nothing (Brett,
# 2026-10-15). The source check is at the default floor; the floor checks are on
# the lexicon-listed inventory. Languages with fixed units learn no onsets.
NO_ONSET_INVENTORY = frozenset({'CMN', 'YUE', 'VIE', 'KOR', 'JPN', 'THA'})
PREPARATION_DEFAULTS = {'onset_source': 'lexicon', 'floor': 3}
PREPARATION_CHECKS = (
    {'setting': 'onset_source', 'values': ('lexicon', 'all-types'), 'kind': 'one-at-a-time-check',
     'decided': 'Brett, 2026-10-15'},
    {'setting': 'floor', 'values': (3, 1, 10), 'kind': 'one-at-a-time-check', 'decided': 'Brett, 2026-10-15'},
)


def preparation_checks(language):
    """Each preparation-level alternative versus the default preparation settings."""
    if language not in REGISTRY:
        raise ValueError('Unknown language')
    if language in NO_ONSET_INVENTORY:
        return ()
    result = []
    for check in PREPARATION_CHECKS:
        if check['values'][0] != PREPARATION_DEFAULTS[check['setting']]:
            raise ValueError('A preparation check must list its default first')
        for alternative in check['values'][1:]:
            result.append({'setting': check['setting'], 'target': 'preparation', 'kind': check['kind'],
                           'alternative': alternative, 'default': dict(PREPARATION_DEFAULTS),
                           'changed': dict(PREPARATION_DEFAULTS, **{check['setting']: alternative})})
    return tuple(result)


def _view_id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()[:16]


# Checks the production pipeline cannot apply, reported as unmeasured rather than run
# (Brett, 2026-10-10: unmeasured rows are reported as such). Codex review, 2026-10-16.
UNMEASURED_CHECKS = {
    52: 'whole-phrase G2P exists only in segment.segment_text; the production pipeline transcribes '
        'words in isolation, so both arms would read alike',
}
# Row 51 (stress) where the production G2P is Epitran: its maps and rules for these
# languages write no stress mark, so no phone carries stress and both arms are the
# same text (Codex review, 2026-10-16; tests/test_p9_checks.py reads the maps).
NO_STRESS_G2P = ('HUN', 'ITA', 'SRP', 'TUR')
UNMEASURED_IN = {(51, language): 'the production G2P (Epitran) writes no stress marks for this language, so no '
                                 'phone carries stress and both arms are the same text' for language in NO_STRESS_G2P}


def unmeasured_reason(language, row):
    """Why a declared check can't be measured in this language, or None."""
    return UNMEASURED_IN.get((row, language), UNMEASURED_CHECKS.get(row))


def unmeasured_checks(language):
    """Declared checks left out of the check views, with the reason."""
    return tuple(dict(row=c['row'], setting=c['setting'], alternative=c['alternative'], declaration=c['default'],
                      reason=unmeasured_reason(language, c['row'])) for c in checks(language)
                 if unmeasured_reason(language, c['row']) is not None)


def check_views(language):
    """The one-at-a-time checks as preparations (Brett's checks; design in DECISIONS.md, 2026-10-16).

    Each view names the declarations one check preparation covers and the
    preparation settings it uses: a boundary check holds its option's default
    declaration and the changed one; the preparation checks share a
    default-settings view of the first-listed declaration, and each changes one
    setting of it. A mask or preparation that records a view's id covers exactly
    these declarations, as one without covers the universes.
    """
    views = []
    for c in checks(language):
        if unmeasured_reason(language, c['row']) is not None:
            continue
        definition = dict(kind='boundary', row=c['row'], setting=c['setting'], target=c['target'],
                          alternative=c['alternative'], declarations=[c['default'], c['changed']],
                          preparation=dict(PREPARATION_DEFAULTS))
        views.append(dict(definition, id=_view_id(definition)))
    first = universes(language)[0]
    prepared = preparation_checks(language)
    if prepared:
        base = dict(kind='preparation-default', declarations=[first], preparation=dict(PREPARATION_DEFAULTS))
        views.append(dict(base, id=_view_id(base)))
        for c in prepared:
            definition = dict(kind='preparation', setting=c['setting'], alternative=c['alternative'],
                              declarations=[first], preparation=dict(c['changed']), default=_view_id(base))
            views.append(dict(definition, id=_view_id(definition)))
    return tuple(views)


def check_view(language, view_id):
    """One check view by id; refused if this registry doesn't declare it."""
    found = [v for v in check_views(language) if v['id'] == view_id]
    if len(found) != 1:
        raise ValueError(f'{language}: no check view {view_id}')
    return found[0]


def declarations(language, *, include_calibration=False, check=None):
    """What a mask or preparation covers: the universes, or one check view's declarations."""
    if check is None:
        return universes(language, include_calibration=include_calibration)
    if include_calibration:
        raise ValueError('A check view covers its own declarations, not calibration options')
    return tuple(check_view(language, check)['declarations'])


def enumerate_language(language, *, include_calibration=False):
    return {'universes': universes(language, include_calibration=include_calibration),
            'checks': checks(language, include_calibration=include_calibration),
            'preparation_checks': preparation_checks(language)}
