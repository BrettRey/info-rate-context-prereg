"""Compare the neural and KenLM F3b grids on the shared rungs (1w, 1, 4).

Inputs are the finished result files copied into this repository:
results/fakedata/f3b_neural_2010/<family>/ (run tag 2010) and
results/fakedata/f3b_kenlm_1010/ (run tag 1010). The two grids share the design
but not the draws, so each estimate is compared with its own truth: the
comparison is between distortions (estimate minus truth), never between raw
estimates.

Writes results/fakedata/f3b_neural_vs_kenlm.tsv (contrasts),
f3b_neural_vs_kenlm_rungs.tsv (rung-level R and r) and f3b_neural_vs_kenlm.md.
"""

import csv
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE = ROOT / "results" / "fakedata"
NEURAL = FAKE / "f3b_neural_2010"
KENLM = FAKE / "f3b_kenlm_1010"
FAMILIES = ("local_copy", "local_mapped", "skipped_copy", "skipped_mapped")
RUNGS = ("1w", "1", "4")
BASELINES = ("1w", "1")
# Descriptive marker only, not a pass/fail threshold: a contrast whose true
# value is at least this large and whose estimate has the opposite sign.
SIGN_MARK = 0.1


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def complete(row):
    return row["n_languages"] == "17" and row["excluded_languages"] == "0" and row["excluded_rows"] == "0"


def load():
    contrasts, rungs, sources = {}, {}, []
    for fam in FAMILIES:
        for est, cpath, rpath in (
            ("neural", NEURAL / fam / "result_contrasts.tsv", NEURAL / fam / "result.tsv"),
            ("kenlm", KENLM / f"t2_wr_v2_full_1010_{fam}_contrasts.tsv", KENLM / f"t2_wr_v2_full_1010_{fam}.tsv"),
        ):
            sources += [(cpath, sha(cpath)), (rpath, sha(rpath))]
            for r in read(cpath):
                if r["family"] != fam or not complete(r):
                    sys.exit(f"incomplete or mislabelled contrast row in {cpath}: {r}")
                if r["last"] == "4" and r["baseline"] in BASELINES:
                    key = (fam, r["pairing"], r["scenario"], r["baseline"], est)
                    if key in contrasts:
                        sys.exit(f"duplicate contrast {key}")
                    contrasts[key] = (float(r["true"]), float(r["estimated"]), float(r["distortion"]))
            for r in read(rpath):
                if r["family"] != fam or not complete(r):
                    sys.exit(f"incomplete or mislabelled rung row in {rpath}: {r}")
                if r["rung"] in RUNGS:
                    key = (fam, r["pairing"], r["scenario"], r["rung"], est)
                    if key in rungs:
                        sys.exit(f"duplicate rung {key}")
                    rungs[key] = {k: float(r[k]) for k in ("R_true", "R_est", "distortion", "r_true", "r_est")}
    return contrasts, rungs, sources


def main():
    contrasts, rungs, sources = load()
    cells = sorted({k[:4] for k in contrasts})
    if len(cells) != len(FAMILIES) * 3 * 2 * len(BASELINES):
        sys.exit(f"expected 48 contrast cells, found {len(cells)}")
    rows = []
    for cell in cells:
        n, k = contrasts.get(cell + ("neural",)), contrasts.get(cell + ("kenlm",))
        if n is None or k is None:
            sys.exit(f"cell missing an estimator: {cell}")
        rows.append(cell + k + n)
    head = ["family", "pairing", "scenario", "baseline",
            "kenlm_true", "kenlm_est", "kenlm_distortion",
            "neural_true", "neural_est", "neural_distortion"]
    with open(FAKE / "f3b_neural_vs_kenlm.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(head)
        w.writerows(rows)

    rcells = sorted({k[:4] for k in rungs})
    with open(FAKE / "f3b_neural_vs_kenlm_rungs.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["family", "pairing", "scenario", "rung"]
                   + [f"{e}_{m}" for e in ("kenlm", "neural") for m in ("R_true", "R_est", "distortion", "r_true", "r_est")])
        for cell in rcells:
            vals = []
            for e in ("kenlm", "neural"):
                d = rungs.get(cell + (e,))
                if d is None:
                    sys.exit(f"rung cell missing an estimator: {cell}")
                vals += [d["R_true"], d["R_est"], d["distortion"], d["r_true"], d["r_est"]]
            w.writerow(list(cell) + vals)

    def span(fams, base, est):
        idx = 6 if est == "kenlm" else 9
        ds = [r[idx] for r in rows if r[0] in fams and r[3] == base]
        return min(ds), max(ds), max(abs(x) for x in ds)

    def flips(est):
        t, e = (4, 5) if est == "kenlm" else (7, 8)
        return [r for r in rows if abs(r[t]) >= SIGN_MARK and r[t] * r[e] < 0]

    local, skipped = FAMILIES[:2], FAMILIES[2:]
    out = ["# F3b: neural against KenLM on the shared rungs", "",
           "Simulated data only. Neural: run tag 2010, settings `zero_unigram_cosine5`, rungs 1w, 1 and 4; "
           "`local_copy` on the laptop's Apple GPU, the other three families on Hugging Face L4s (CUDA). "
           "KenLM: run tag 1010, all 14 rungs, of which 1w, 1 and 4 are used here. Both at 10,000,000 training and "
           "1,000,000 test syllables, 17 fake languages, pairings independent, aligned and opposed, scenarios S0 and S1. "
           "The two run tags draw different texts from the same design, so each estimate is set against its own truth "
           "and only the distortions (estimate minus truth) are compared. Every panel is complete (17 languages, no exclusions).", "",
           "## Distortion of the contrasts (bits)", "",
           "| Families | Contrast | KenLM min | KenLM max | KenLM max abs | Neural min | Neural max | Neural max abs |",
           "|---|---|---:|---:|---:|---:|---:|---:|"]
    for name, fams in (("local", local), ("skipped", skipped)):
        for base in BASELINES:
            k, n = span(fams, base, "kenlm"), span(fams, base, "neural")
            out.append(f"| {name} | R4 − R{base} | {k[0]:+.3f} | {k[1]:+.3f} | {k[2]:.3f} | {n[0]:+.3f} | {n[1]:+.3f} | {n[2]:.3f} |")
    out += ["", f"Sign reversals (true contrast at least {SIGN_MARK} bits in size, estimate of the opposite sign; "
            "a descriptive marker, not a pass/fail threshold):", ""]
    for est in ("kenlm", "neural"):
        fl = flips(est)
        label = "KenLM" if est == "kenlm" else "Neural"
        out.append(f"- {label}: {len(fl)} of {len(rows)}"
                   + ("" if not fl else ": " + "; ".join(
                       f"{r[0]} {r[1]} {r[2]} R4 − R{r[3]} (true {r[4 if est == 'kenlm' else 7]:+.3f}, "
                       f"estimate {r[5 if est == 'kenlm' else 8]:+.3f})" for r in fl)))
    out += ["", "## Every contrast cell", "",
            "| Family | Pairing | Scenario | Contrast | KenLM true | KenLM est | KenLM dist | Neural true | Neural est | Neural dist |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        out.append(f"| {r[0]} | {r[1]} | {r[2]} | R4 − R{r[3]} | " + " | ".join(f"{x:+.3f}" for x in r[4:]) + " |")
    out += ["", "## Sources", "", "Rung-level R and r for both estimators: `f3b_neural_vs_kenlm_rungs.tsv`.", ""]
    for p, h in sources:
        out.append(f"- `{Path(p).relative_to(ROOT)}` sha256 `{h}`")
    out.append(f"- `src/fakedata/f3b_neural_vs_kenlm.py` sha256 `{sha(__file__)}`")
    (FAKE / "f3b_neural_vs_kenlm.md").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
