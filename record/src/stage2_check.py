"""Integrity check for every Stage 2 sample: the manifests and the corpus files agree.

For each subtitle language: kept folders are unique; every kept folder's n_kept equals
its line count in data/raw/opensubtitles/<LANG>.tsv.gz; no (folder, line) pair repeats; no
folder appears in the text without a kept manifest row. For each Wikipedia sample the same
with articles and n_sent. Prints one line per sample and exits non-zero on any failure.

Usage: .venv/bin/python -I src/stage2_check.py
"""
import collections
import csv
import gzip
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
M = ROOT / "results/stage2/manifest"
fail = 0

def check(name, manifest_rows, key, count_field, text_path, item_col, line_col):
    global fail
    keys = [r[key] for r in manifest_rows if r["status"] == "kept"]
    dup_manifest = len(keys) - len(set(keys))   # a film or article kept twice
    kept = {r[key]: int(r[count_field]) for r in manifest_rows if r["status"] == "kept"}
    per = collections.Counter()
    pairs = set()
    dup_lines = 0
    with gzip.open(text_path, "rt", encoding="utf-8") as f:
        next(f)
        for row in f:
            parts = row.rstrip("\n").split("\t", 4)
            item, line = parts[item_col], parts[line_col]
            per[item] += 1
            if (item, line) in pairs:
                dup_lines += 1
            pairs.add((item, line))
    mismatch = sum(1 for k, n in kept.items() if per.get(k, 0) != n)
    stray = sum(1 for k in per if k not in kept)
    ok = not (dup_manifest or mismatch or stray or dup_lines)
    fail += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {len(kept)} kept, {sum(per.values())} lines; "
          f"duplicate manifest rows {dup_manifest}, count mismatches {mismatch}, "
          f"stray items {stray}, duplicate lines {dup_lines}")

for f in sorted(M.glob("opensubtitles_*.tsv")):
    lang = f.stem[len("opensubtitles_"):]
    text = ROOT / f"data/raw/opensubtitles/{lang}.tsv.gz"
    if lang == "zips" or not text.exists():
        continue
    rows = list(csv.DictReader(open(f), delimiter="\t"))
    check(f"subtitles {lang}", rows, "folder", "n_kept", text, 1, 3)

for f in sorted(M.glob("wikipedia_*.tsv.gz")):
    name = f.name[len("wikipedia_"):-len(".tsv.gz")]
    text = ROOT / f"data/raw/wikipedia/{name}.tsv.gz"
    if not text.exists():
        continue
    rows = list(csv.DictReader(gzip.open(f, "rt"), delimiter="\t"))
    check(f"wikipedia {name}", rows, "article", "n_sent", text, 1, 2)

sys.exit(1 if fail else 0)
