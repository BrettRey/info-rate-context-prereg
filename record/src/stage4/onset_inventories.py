"""The Basque and Finnish onset inventories after the counts phase (DECISIONS.md 2026-10-15: "each language's
lexicon coverage (types and training tokens it lists) is reported, and each inventory is looked at when its
language is prepared, Basque's lexicon being the smallest"; STATUS 2026-10-18 names Basque and Finnish).

Reads the onset inventories (`onsets.tsv`, written by `stage3/onsets.write`) extracted from the counts archive
(job 1905289, 2026-11-02). Writes, for the languages given:
  coverage.tsv   one row per inventory file: where it sits, its declaration's option, onset source, floor,
                 source kind, the lexicon's coverage of the training types and tokens, word types without a
                 nucleus, onsets in all and legal at the selected floor, multi-phone onsets legal, and the
                 digest of its rows (identical inventories share it);
  onsets.tsv     one row per distinct inventory (by that digest) and onset (its phones, space-separated; empty
                 for a vowel-initial word) with its number of phones, word types and tokens,
                 legal at the selected floor and at floors 1, 3 and 10, and how many files hold the inventory.
Onsets are phone strings with counts; no corpus text or document names are written. Standard library only.
    python3 -I src/stage4/onset_inventories.py ROOT OUTDIR LANGUAGE...
ROOT is the extracted data/interim/counts-fir.
"""
import csv
import json
from pathlib import Path
import sys

SCHEMA = 'onsets-v2'
COVERAGE = ['run', 'language', 'variant', 'budget', 'declaration', 'option', 'settings', 'onset_source', 'floor',
            'source_kind', 'training_types', 'listed_types', 'listed_type_share', 'training_tokens', 'listed_tokens',
            'listed_token_share', 'types_without_nucleus', 'onsets', 'legal_onsets', 'legal_multi_phone',
            'rows_sha256']
ONSETS = ['language', 'option', 'onset_source', 'floor', 'rows_sha256', 'files', 'onset', 'phones', 'word_types',
          'word_tokens', 'legal_selected', 'legal_1', 'legal_3', 'legal_10']


def read(path):
    """(metadata, rows) as `stage3/onsets.read` parses them, without its registry checks."""
    with path.open(encoding='utf-8') as f:
        first = f.readline()
        if not first.startswith('# '):
            raise ValueError(f'{path}: missing onset provenance')
        meta = json.loads(first[2:])
        if meta.get('schema') != SCHEMA:
            raise ValueError(f'{path}: schema {meta.get("schema")!r}')
        rows = []
        for row in csv.DictReader(f, delimiter='\t'):
            phones = json.loads(row['onset'])
            if not isinstance(phones, list) or any(not isinstance(p, str) or not p for p in phones):
                raise ValueError(f'{path}: bad onset {row["onset"]!r}')
            rows.append(dict(phones=phones, word_types=int(row['word_types']), word_tokens=int(row['word_tokens']),
                             legal_selected=int(row['legal_selected']), legal_1=int(row['legal_1']),
                             legal_3=int(row['legal_3']), legal_10=int(row['legal_10'])))
    if any((r['word_types'] >= meta['floor']) != bool(r['legal_selected']) for r in rows):
        raise ValueError(f'{path}: legality disagrees with the floor')
    return meta, rows


def place(path, root):
    """(run, language, variant, budget, declaration) from RUN/LANG/VARIANT/BUDGET/DECL/resources/onsets.tsv;
    a check view stands where a variant does (checks/LANG/VIEW/BUDGET/DECL/...)."""
    parts = path.relative_to(root).parts
    if len(parts) != 7 or parts[5:] != ('resources', 'onsets.tsv'):
        raise ValueError(f'{path}: unexpected place')
    return parts[:5]


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    languages = sys.argv[3:]
    out.mkdir(parents=True, exist_ok=True)
    coverage, inventories = [], {}
    for path in sorted(p for p in root.rglob('onsets.tsv') if p.relative_to(root).parts[1] in languages):
        run, language, variant, budget, declaration = place(path, root)
        meta, rows = read(path)
        if meta['language'] != language:
            raise ValueError(f'{path}: language {meta["language"]!r}')
        source = meta.get('source', {})
        cover = source.get('onset_coverage') or {}
        decl = source.get('declaration') or {}
        share = lambda a, b: f'{cover[a] / cover[b]:.6f}' if cover.get(b) else ''
        coverage.append(dict(
            run=run, language=language, variant=variant, budget=budget, declaration=declaration[:12],
            option=meta['option'], settings=json.dumps(decl.get('settings', {}), sort_keys=True, ensure_ascii=False),
            onset_source=source.get('onset_source', ''), floor=meta['floor'], source_kind=source.get('kind', ''),
            training_types=cover.get('training_types', ''), listed_types=cover.get('listed_types', ''),
            listed_type_share=share('listed_types', 'training_types'),
            training_tokens=cover.get('training_tokens', ''), listed_tokens=cover.get('listed_tokens', ''),
            listed_token_share=share('listed_tokens', 'training_tokens'),
            types_without_nucleus=meta.get('types_without_nucleus', ''), onsets=len(rows),
            legal_onsets=sum(r['legal_selected'] for r in rows),
            legal_multi_phone=sum(r['legal_selected'] and len(r['phones']) > 1 for r in rows),
            rows_sha256=meta['rows_sha256']))
        key = (language, meta['option'], source.get('onset_source', ''), meta['floor'], meta['rows_sha256'])
        inventories.setdefault(key, [rows, 0])[1] += 1
    with open(out / 'coverage.tsv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COVERAGE, delimiter='\t', lineterminator='\n')
        w.writeheader(); w.writerows(coverage)
    with open(out / 'onsets.tsv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=ONSETS, delimiter='\t', lineterminator='\n')
        w.writeheader()
        for (language, option, source, floor, digest), (rows, files) in sorted(inventories.items()):
            for r in sorted(rows, key=lambda r: (-r['word_types'], r['phones'])):
                w.writerow(dict(language=language, option=option, onset_source=source, floor=floor,
                                rows_sha256=digest[:12], files=files, onset=' '.join(r['phones']),
                                phones=len(r['phones']), word_types=r['word_types'], word_tokens=r['word_tokens'],
                                legal_selected=r['legal_selected'], legal_1=r['legal_1'], legal_3=r['legal_3'],
                                legal_10=r['legal_10']))
    print(f'{len(coverage)} inventory files, {len(inventories)} distinct inventories; {out}')


if __name__ == '__main__':
    main()
