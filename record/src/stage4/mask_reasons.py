"""Each language's masks read by reason, after the counts phase (DECISIONS.md 2026-10-15: "each language's mask is
read by reason, and any reason at 1% of lines or more is looked at").

Reads the masks extracted from the counts archive (job 1905289, 2026-11-02): the first counts pass of each run
and language (counts-first), each text variant's counts mask, each preparation's removal mask, and each check
view's. For every mask and reason it writes the lines masked for that reason, the mask's lines (all its
documents), the share, and whether the count recomputed from the documents equals the mask's own summary.
Reasons are the pipeline's codes. Failure messages can quote corpus words, so they go only to a separate file,
kept private: for each mask and reason at the threshold or above, its most frequent messages.
Standard library only.
    python3 -I src/stage4/mask_reasons.py ROOT OUT.tsv MESSAGES.tsv [WORKERS]
ROOT is the extracted data/interim/counts-fir.
"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
import json
from pathlib import Path
import sys

THRESHOLD = 0.01
TOP_MESSAGES = 20
FIELDS = ['run', 'language', 'kind', 'variant', 'budget', 'documents', 'lines', 'masked_lines', 'reason',
          'reason_lines', 'share', 'at_threshold', 'declarations', 'messages', 'summary_matches']


def describe(path, root):
    """(run, language, kind, variant, budget) from the mask's place in the counts tree."""
    parts = path.relative_to(root).parts
    if parts[0] == 'checks':  # checks/LANG/VIEW/BUDGET/removal-mask.json
        return 'checks', parts[1], 'removal', parts[2], parts[3]
    run, language = parts[0], parts[1]
    if parts[2] == 'counts-first':  # RUN/LANG/counts-first/counts-mask.json
        return run, language, 'counts-first', '', ''
    if parts[3] == 'counts':  # RUN/LANG/VARIANT/counts/counts-mask.json
        return run, language, 'counts', parts[2], ''
    return run, language, 'removal', parts[2], parts[3]  # RUN/LANG/VARIANT/BUDGET/removal-mask.json


def tally(job):
    path, root = job
    mask = json.loads(path.read_text(encoding='utf-8'))
    run, language, kind, variant, budget = describe(path, root)
    if mask.get('language') != language:
        raise ValueError(f'{path}: mask language {mask.get("language")!r}')
    lines = sum(d['n_lines'] for d in mask['documents'].values())
    masked, by_reason, declarations, messages = 0, Counter(), {}, {}
    for document in mask['documents'].values():
        masked += len(document['masked_lines'])
        for reasons in document['masked_lines'].values():
            # A line counts once per reason, as the pipeline's own summary counts it.
            for reason in {r['reason'] for r in reasons}:
                by_reason[reason] += 1
                declarations.setdefault(reason, set()).update(
                    r['declaration'] for r in reasons if r['reason'] == reason and r.get('declaration') is not None)
                messages.setdefault(reason, Counter()).update(
                    {r.get('detail', r['reason']) for r in reasons if r['reason'] == reason})
    summary = mask.get('summary', {})
    rows, private = [], []
    if summary.get('masked_lines') != masked:
        raise ValueError(f'{path}: masked lines {masked} against the summary\'s {summary.get("masked_lines")}')
    for reason, count in sorted(by_reason.items()):
        share = count / lines if lines else 0.0
        stored = summary.get('by_reason', {}).get(reason, {}).get('lines')
        rows.append(dict(run=run, language=language, kind=kind, variant=variant, budget=budget,
                         documents=len(mask['documents']), lines=lines, masked_lines=masked, reason=reason,
                         reason_lines=count, share=f'{share:.6f}', at_threshold=int(share >= THRESHOLD),
                         declarations=' '.join(map(str, sorted(declarations[reason]))),
                         messages=len(messages[reason]), summary_matches=int(stored == count)))
        if share >= THRESHOLD:
            for message, n in messages[reason].most_common(TOP_MESSAGES):
                private.append(dict(run=run, language=language, kind=kind, variant=variant, budget=budget,
                                    reason=reason, lines=n, message=' '.join(str(message).split())))
    if not by_reason:
        rows.append(dict(run=run, language=language, kind=kind, variant=variant, budget=budget,
                         documents=len(mask['documents']), lines=lines, masked_lines=0, reason='', reason_lines=0,
                         share='0.000000', at_threshold=0, declarations='', messages=0,
                         summary_matches=int(not summary.get('by_reason'))))
    return rows, private


def main():
    root, out, private_out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    paths = sorted(p for name in ('counts-mask.json', 'removal-mask.json') for p in root.rglob(name))
    with ProcessPoolExecutor(workers) as pool:
        results = list(pool.map(tally, [(p, root) for p in paths]))
    rows = [r for result, _ in results for r in result]
    private = [r for _, result in results for r in result]
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter='\t', lineterminator='\n')
        w.writeheader(); w.writerows(rows)
    with open(private_out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['run', 'language', 'kind', 'variant', 'budget', 'reason', 'lines', 'message'],
                           delimiter='\t', lineterminator='\n')
        w.writeheader(); w.writerows(private)
    print(f'{len(paths)} masks; {len(rows)} rows; {sum(r["at_threshold"] for r in rows)} at or above '
          f'{THRESHOLD:.0%}; summary mismatches {sum(1 - r["summary_matches"] for r in rows)}')


if __name__ == '__main__':
    main()
