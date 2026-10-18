"""The training-budget plateau report (Brett, 2026-10-11, decision 5).

Δ_k = H_k(B/2) − H_k(B) per language, universe and rung, reported continuously,
with the change in the headline contrast R4 − R1w between the two budgets. 0.05
bits is an operational warning column only; nothing is dropped or filtered. On
the languages that reach 3B the same is reported for H_k(B) − H_k(3B).

Inputs are score records as assembly reads them (`identity.shared.budget` holds
the budget label) and, for the contrast, assembled groups at each budget.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage6_plateau_iterables", _BoundaryPath(__file__).resolve().parents[1] / "stage5/iterables.py")
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import json
import math

WARNING_BITS = 0.05


def _meta(record):
    return record.get('metadata', record['identity'])


def _key(record):
    meta = _meta(record)
    shared = {k: v for k, v in meta['shared'].items() if k != 'budget'}
    # Estimator settings live in the immutable identity, not in runner metadata.
    estimator = dict(record['identity'].get('estimator', {'name': 'kenlm'}))
    estimator.pop('vocab', None)  # the inventory follows the budget's own training text
    return json.dumps([meta['language'], meta['options'], shared, estimator], sort_keys=True)


@_boundary
def deltas(records, smaller='B/2', larger='B', warning=WARNING_BITS):
    """Rows of H_k at two budgets for every universe both budgets scored."""
    by = {}
    for r in records:
        label = _meta(r)['shared'].get('budget')
        if label in (smaller, larger):
            key = (_key(r), label)
            if key in by:
                raise ValueError(f'two records for one universe at budget {label}')
            by[key] = r
    rows, unpaired = [], []
    for key in sorted({k for k, _ in by}):
        a, b = by.get((key, smaller)), by.get((key, larger))
        if a is None or b is None:
            unpaired.append(json.loads(key)); continue
        language, options, shared, estimator = json.loads(key)
        for rung in sorted(set(a['scores']) & set(b['scores'])):
            h_small, h_large = a['scores'][rung]['id_bits'], b['scores'][rung]['id_bits']
            delta = h_small - h_large
            rows.append(dict(language=language, options=options, shared=shared, estimator=estimator['name'],
                             rung=rung, budgets=[smaller, larger], H_smaller=h_small, H_larger=h_large,
                             delta_bits=delta, warning=bool(math.isfinite(delta) and delta > warning)))
    return dict(rows=rows, unpaired=unpaired, warning_bits=warning)


@_boundary
def headline(group, contrast=('4', '1w')):
    """Family-weighted mean of R4 − R1w over an assembled group's universes."""
    rungs = list(group['rungs'])
    values = [row[rungs.index(contrast[0])] - row[rungs.index(contrast[1])] for row in group['R']]
    weights = list(group['family_weights'])
    kept = [(v, w) for v, w in zip(values, weights) if math.isfinite(v)]
    total = sum(w for _, w in kept)
    return sum(v * w for v, w in kept) / total if total else float('nan')


@_boundary
def contrast_change(group_smaller, group_larger):
    """R4 − R1w at each budget and its change (smaller budget minus larger)."""
    a, b = headline(group_smaller), headline(group_larger)
    return dict(R4_minus_R1w_smaller=a, R4_minus_R1w_larger=b, change=a - b)


@_boundary
def markdown(result):
    lines = [f"| Language | Rung | H at {result['rows'][0]['budgets'][0] if result['rows'] else 'B/2'} | "
             f"H at {result['rows'][0]['budgets'][1] if result['rows'] else 'B'} | Δ (bits) | Above {result['warning_bits']} |",
             '|---|---|---:|---:|---:|---|']
    for r in result['rows']:
        lines.append(f"| {r['language']} | {r['rung']} | {r['H_smaller']:.4f} | {r['H_larger']:.4f} | "
                     f"{r['delta_bits']:+.4f} | {'yes' if r['warning'] else ''} |")
    if result['unpaired']:
        lines.append(f"\nUnpaired universes (scored at one budget only): {len(result['unpaired'])}.")
    return '\n'.join(lines) + '\n'
