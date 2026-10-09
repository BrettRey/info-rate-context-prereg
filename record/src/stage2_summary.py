"""Summarise the Stage 2 samples from their manifests (no figures typed by hand).

Writes results/stage2/summary_wikipedia.tsv and results/stage2/summary_opensubtitles.tsv.
"""
import collections, csv, gzip, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
M = ROOT / "results/stage2/manifest"
OUT = ROOT / "results/stage2"

rows = []
for f in sorted(M.glob("wikipedia_*.tsv.gz")):
    lang = f.name[len("wikipedia_"):-len(".tsv.gz")]
    m = list(csv.DictReader(gzip.open(f, "rt"), delimiter="\t"))
    st = collections.Counter(r["status"] for r in m)
    kept = [r for r in m if r["status"] == "kept"]
    groups = len({r["group"] for r in m})
    rows.append({"lang": lang, "row_groups": groups, "articles": len(m), "kept": st["kept"],
                 "templated": st["drop:template"], "no_prose": st["no_prose"],
                 "templated_pct": round(100 * st["drop:template"] / len(m), 1),
                 "kept_MB": round(sum(int(r["bytes"]) for r in kept) / 1e6, 1),
                 "kept_MB_share_lt_0.3": round(sum(int(r["bytes"]) for r in kept if float(r["share"]) < 0.3) / 1e6, 1)})
with open(OUT / "summary_wikipedia.tsv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t"); w.writeheader(); w.writerows(rows)

rows = []
for f in sorted(M.glob("opensubtitles_*.tsv")):
    lang = f.stem[len("opensubtitles_"):]
    if lang == "zips":
        continue
    m = list(csv.DictReader(open(f), delimiter="\t"))
    st = collections.Counter(r["status"] for r in m)
    kept = [r for r in m if r["status"] == "kept"]
    sent = sum(int(r["n_sent"]) for r in kept)
    row = {"lang": lang, "folders_tried": len(m), "kept": st["kept"],
           "kept_lines": sum(int(r["n_kept"]) for r in kept), "sentences_in_kept": sent,
           "kept_MB": round(sum(int(r["bytes_kept"]) for r in kept) / 1e6, 1)}
    for k in ("digit", "letters", "english", "music", "credit"):
        row[f"{k}_pct"] = round(100 * sum(int(r[k]) for r in kept) / sent, 2)
    rows.append(row)
with open(OUT / "summary_opensubtitles.tsv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t"); w.writeheader(); w.writerows(rows)
print("written")
