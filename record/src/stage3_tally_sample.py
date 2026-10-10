"""Draw the corpus sample for the counter-readings tally (DECISIONS 2026-10-10).

For each counter language and each Stage 2 source (OpenSubtitles, Wikipedia), take 5,000 non-empty text
lines evenly spaced over the whole source (row indices round(linspace(0, N-1, 5000)); text is the last TSV
column). Wikipedia's gap marker (⟂, where Stage 2 removed digits or out-of-inventory text) is treated as a
boundary, the "split" reading of the gap fork (notes/multiverse-spec.md §2.1): each gap-free stretch becomes
its own line. Revised 2026-10-10 after review (the first version took every floor(N/5000)-th row and kept
gaps as text). Writes data/interim/tally-sample/<LANG>.txt (gitignored) and a manifest of counts and hashes.
Usage: python -I src/stage3_tally_sample.py
"""
import csv, gzip, hashlib, io, json, os, sys
import numpy as np
csv.field_size_limit(sys.maxsize)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGS = ["SPA", "CAT", "ITA", "DEU", "ENG", "FRA", "SRP", "TUR", "FIN", "HUN", "EUS", "KOR", "CMN", "YUE", "VIE"]
PER_SOURCE = 5000
OUT = os.path.join(ROOT, "data", "interim", "tally-sample")

def rows(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE); next(r)
        for row in r:
            yield row[-1].replace("\n", " ").strip()

def main():
    os.makedirs(OUT, exist_ok=True); manifest = {}
    for lang in LANGS:
        lines = []
        for src in ("opensubtitles", "wikipedia"):
            path = os.path.join(ROOT, "data", "raw", src, f"{lang}.tsv.gz")
            if not os.path.exists(path):
                manifest.setdefault(lang, {})[src] = "absent"; continue
            n = sum(1 for t in rows(path) if t)
            want = set(np.round(np.linspace(0, n - 1, min(PER_SOURCE, n))).astype(int).tolist())
            got = [t for i, t in enumerate(t for t in rows(path) if t) if i in want]
            pieces = [seg.strip() for t in got for seg in t.split("⟂")]
            pieces = [seg for seg in pieces if seg]
            lines += pieces
            manifest.setdefault(lang, {})[src] = {"nonempty_lines_in_source": n, "taken": len(got),
                                                  "lines_written_after_gap_split": len(pieces),
                                                  "lines_with_gaps": sum(1 for t in got if "⟂" in t)}
        text = "\n".join(lines) + "\n"
        with open(os.path.join(OUT, f"{lang}.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        manifest[lang]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
        print(lang, {k: v for k, v in manifest[lang].items() if k != "sha256"}, flush=True)
    json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
