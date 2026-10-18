"""Training budgets B, B/2 and 3B from the first-listed option's training syllables.

Approved plan (`DECISIONS.md` 2026-10-08 and 2026-10-11; Brett 2026-10-13):
B₀ is the smallest training total in the panel, YUE included, so the curves
with and without YUE share it. B/2 is nested in B: the same prefix order, cut
earlier. 3B₀ runs for the languages whose training reaches it, compared with
B₀ on that subset; B₀ is unchanged. Every cut is a prefix of the training
documents in split order, then of the last document's lines, the largest one
whose first-listed syllables don't exceed the target. The same source lines
are then used by every option (`linguistic_inputs.prepare(budget=...)`), and
each option's realised total is reported there. Onset inventories are learned
from the B₀ prefix in every language and kept for every budget (Brett, 2026-10-13).

Input per language: `training_units` from a budget-free preparation manifest,
[[document, [syllables per source line]], ...] in split order.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import hashlib
import json

SCHEMA = 'training-budgets-v1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def total(units):
    return sum(sum(lines) for _, lines in units)


def cut(units, target):
    """The largest prefix (whole documents, then leading lines) with at most `target` syllables.

    Returned as an ordered list of [document, leading lines], so the order
    survives any JSON round trip.
    """
    if type(target) is not int or target < 1:
        raise ValueError('A budget target must be a positive integer')
    lines, used = [], 0
    for document, per_line in units:
        n = 0
        for count in per_line:
            if used + count > target:
                break
            used += count; n += 1
        if n:
            lines.append([document, n])
        if n < len(per_line):
            break
    if not lines:
        raise ValueError('The budget keeps no training line')
    return lines, used


def plan(units_by_language):
    """Budget cuts per language: B, B/2 for every language, 3B where the training reaches 3B₀."""
    for language, units in units_by_language.items():
        if (not isinstance(units, (list, tuple)) or not units
                or any(len(u) != 2 or not isinstance(u[0], str) or any(type(c) is not int or c < 0 for c in u[1])
                       for u in units)
                or len({u[0] for u in units}) != len(units)):
            raise ValueError(f'{language}: training_units must list unique documents with per-line syllable counts')
    totals = {language: total(units) for language, units in units_by_language.items()}
    smallest = min(totals, key=lambda language: (totals[language], language))
    b0 = totals[smallest]
    if b0 < 2:
        raise ValueError('The smallest training total is too small for B/2')
    reach = sorted(language for language, t in totals.items() if t >= 3 * b0)
    cuts = {}
    for language, units in units_by_language.items():
        row = {}
        for label, target in (('B', b0), ('B/2', b0 // 2), *((('3B', 3 * b0),) if language in reach else ())):
            lines, used = cut(units, target)
            row[label] = dict(target=target, realised=used, lines=lines)
        cuts[language] = row
    return dict(schema=SCHEMA, B0=b0, set_by=smallest, totals=totals, reach_3B=reach, cuts=cuts,
                units_sha256={l: hashlib.sha256(canonical(u).encode()).hexdigest() for l, u in units_by_language.items()})


TARGETS = {'B': lambda b0: b0, 'B/2': lambda b0: b0 // 2, '3B': lambda b0: 3 * b0}


def budget_argument(plan_record, language, label):
    """The `budget` argument for `prepare` for one language and budget label.

    It carries its plan's B₀ and the fingerprint of the training units the plan
    was made from, so `prepare` can recompute both cuts and refuse a mismatch.
    Onset inventories are learned from the B₀ prefix whatever the label (Brett, 2026-10-13).
    """
    row = plan_record['cuts'][language]
    if label not in row:
        raise ValueError(f'{language} has no {label} budget (3B only where the training reaches it)')
    return dict(label=label, target=row[label]['target'], B0=plan_record['B0'],
                units_sha256=plan_record['units_sha256'][language],
                lines=[list(x) for x in row[label]['lines']], onset_lines=[list(x) for x in row['B']['lines']])


def argument_for(units, b0, label):
    """The budget argument for one text variant: its own units cut to the run's fixed B₀.

    Text variants (YUE's split gaps, the Wikipedia stub and Thai prose-line
    settings) keep B₀ from the first-listed settings but cut their own text.
    """
    if label not in TARGETS:
        raise ValueError(f'Unknown budget label {label}')
    target = TARGETS[label](b0)
    if total(units) < target:
        raise ValueError(f'This text has {total(units)} training syllables, short of {label} = {target}; '
                         'a decision is needed before it can run at this budget')
    return dict(label=label, target=target, B0=b0,
                units_sha256=hashlib.sha256(canonical([list(u) for u in units]).encode()).hexdigest(),
                lines=cut(units, target)[0], onset_lines=cut(units, b0)[0])


def verify(budget, units):
    """Refuse a budget that wasn't planned from these training units."""
    if hashlib.sha256(canonical([list(u) for u in units]).encode()).hexdigest() != budget['units_sha256']:
        raise ValueError('The budget was planned from other training units')
    if budget['target'] != TARGETS[budget['label']](budget['B0']):
        raise ValueError('The budget target does not match its label and B0')
    if budget['label'] == '3B' and total(units) < budget['target']:
        raise ValueError('3B only where the training reaches it')
    if (cut(units, budget['target'])[0] != [list(x) for x in budget['lines']]
            or cut(units, budget['B0'])[0] != [list(x) for x in budget['onset_lines']]):
        raise ValueError('The budget cuts differ from those its plan gives for these training units')
    return budget
