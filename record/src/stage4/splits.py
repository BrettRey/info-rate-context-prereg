"""The document split for one language, chosen once.

Whole groups only (a film's folder; every episode of a series is one group;
`DECISIONS.md` 2026-10-08), in one seeded shuffle per language: test is filled
first, then validation, and the rest is training. Sizes are syllable targets
counted under the first-listed option after the common mask; a split takes
whole groups until it reaches its target, so it overshoots by less than one
group, and the realised sizes are recorded. Documents with no retained
syllables are excluded and listed, never silently dropped.

The default sizes (test 1,000,000, validation 500,000 syllables, the same in
every language) are the recommendation in `notes/p3-split-sizes-2026-10-13.md`,
not yet settled by Brett.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import hashlib
import json
import random

SCHEMA = 'document-split-v1'
SEED = 20261013
DEFAULT_SIZES = {'test': 1_000_000, 'validation': 500_000}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def language_seed(language, seed=SEED):
    return int(hashlib.sha256(f'{seed}:{language}'.encode()).hexdigest()[:16], 16)


def make_split(rows, language, *, test=DEFAULT_SIZES['test'], validation=DEFAULT_SIZES['validation'], seed=SEED):
    """rows: dicts with document, group and syllables (first-listed, after the mask)."""
    rows = [dict(r) for r in rows]
    if not rows:
        raise ValueError('A split needs documents')
    for r in rows:
        if (set(r) != {'document', 'group', 'syllables'} or not isinstance(r['document'], str) or not r['document']
                or not isinstance(r['group'], str) or not r['group']
                or type(r['syllables']) is not int or r['syllables'] < 0):
            raise ValueError('Each row needs a document, a group and a nonnegative integer syllable count')
    if len({r['document'] for r in rows}) != len(rows):
        raise ValueError('Document IDs must be unique')
    if type(test) is not int or type(validation) is not int or test < 1 or validation < 1:
        raise ValueError('Held-out sizes must be positive integers')
    excluded = sorted(r['document'] for r in rows if r['syllables'] == 0)
    groups = {}
    for r in sorted((r for r in rows if r['syllables'] > 0), key=lambda r: r['document']):
        groups.setdefault(r['group'], []).append(r)
    order = sorted(groups)
    random.Random(language_seed(language, seed)).shuffle(order)
    targets = {'test': test, 'validation': validation}
    splits = {'test': [], 'validation': [], 'train': []}
    realised = {'test': 0, 'validation': 0, 'train': 0}
    chosen = {'test': [], 'validation': [], 'train': []}
    current = 'test'
    for group in order:
        if current != 'train' and realised[current] >= targets[current]:
            current = 'validation' if current == 'test' else 'train'
        if current != 'train' and realised[current] >= targets[current]:
            current = 'train'
        members = groups[group]
        splits[current].extend(r['document'] for r in members)
        realised[current] += sum(r['syllables'] for r in members)
        chosen[current].append(group)
    if realised['test'] < test or realised['validation'] < validation or not splits['train']:
        raise ValueError(f'{language}: corpus too small for the held-out sizes '
                         f'(test {realised["test"]}/{test}, validation {realised["validation"]}/{validation}, '
                         f'training documents {len(splits["train"])})')
    record = dict(schema=SCHEMA, language=language, seed=seed, language_seed=language_seed(language, seed),
                  targets=targets, realised_syllables=realised,
                  documents={k: len(v) for k, v in splits.items()}, groups={k: len(v) for k, v in chosen.items()},
                  excluded_no_syllables=excluded,
                  rows_sha256=hashlib.sha256(canonical(sorted(rows, key=lambda r: r['document'])).encode()).hexdigest())
    return {'train': splits['train'], 'validation': splits['validation'], 'test': splits['test']}, record
