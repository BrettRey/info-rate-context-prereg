"""Compare the estimators' fake-data check at the real B0 with the 10M grids (DECISIONS.md 2026-11-01).

Simulated data only. Inputs, copied unchanged from Fir into results/fakedata/f3b_b0/:
kenlm/f3b_wr_b0_<tag>_<family>_<pairing>.tsv (run tags 1101 at 7,908,000 and
1102 at 3,954,000 training syllables; f3b_words_rates.py) and, when present,
neural/<tag>_<family>_<pairing>_<rung>/result.tsv (run tags 2101 and 2102;
f3b_neural_words_rates.py --budget, one rung per shard). The 10M
references are results/fakedata/f3b_kenlm_1010/ and f3b_neural_2010/. Each grid
has its own draws, so estimates are compared through their distortions
(estimate minus truth), never with each other.

Writes results/fakedata/f3b_b0/comparison.tsv (contrasts) and comparison.md.
A panel that hasn't finished every language is left out of its table; each shard short of the 10M grid's panels
is listed, apart from the flagged word rungs of B0/2 KenLM runs stopped by an unseen (flag, syllable) pair, which
are absent by design (DECISIONS.md 2026-11-01) and listed as such.
    python -I src/fakedata/f3b_b0_compare.py
"""
from collections import defaultdict
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE = ROOT / "results" / "fakedata"
HERE = FAKE / "f3b_b0"
FAMILIES = ("local_copy", "local_mapped", "skipped_copy", "skipped_mapped")
PAIRINGS = ("independent", "aligned", "opposed")
SIZES = (("10M", None), ("B0", 0), ("B0/2", 1))  # index into each estimator's B0 run tags
TAGS = {"kenlm": (1101, 1102), "neural": (2101, 2102)}
SHARED = ("1w", "1", "4")  # the neural grid's rungs
NEURAL_FAMILIES = ("local_mapped", "skipped_mapped")  # the B0 neural subset
SIGN_MARK = 0.1  # descriptive, as in f3b_neural_vs_kenlm.py: true contrast at least this large, estimate of opposite sign


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def summaries(estimator, size):
    """{(family, pairing, scenario, rung): (R_true, R_est)} from complete 17-language panels."""
    if size is None:
        files = ([FAKE / "f3b_kenlm_1010" / f"t2_wr_v2_full_1010_{f}.tsv" for f in FAMILIES] if estimator == "kenlm"
                 else [FAKE / "f3b_neural_2010" / f / "result.tsv" for f in FAMILIES])
    else:
        tag = TAGS[estimator][size]
        # A shard stopped by an unseen (flag, syllable) pair is run again on the unflagged rungs as <name>_unflagged.
        files = ([HERE / "kenlm" / f"f3b_wr_b0_{tag}_{f}_{p}{s}.tsv" for f in FAMILIES for p in PAIRINGS for s in ("", "_unflagged")
                  if not s or (HERE / "kenlm" / f"f3b_wr_b0_{tag}_{f}_{p}{s}.tsv").exists()] if estimator == "kenlm"
                 else [HERE / "neural" / f"{tag}_{f}_{p}_{r}" / "result.tsv" for f in NEURAL_FAMILIES
                       for p in PAIRINGS for r in SHARED])
    out = {}
    for path in files:
        for r in (read(path) if path.exists() else []):
            if int(r["n_languages"]) == 17:
                out[(r["family"], r["pairing"], r["scenario"], r["rung"])] = (float(r["R_true"]), float(r["R_est"]))
    return out


def gaps(estimator, size):
    """(absent by design, incomplete): shards short of the 10M grid's complete panels, as 'family pairing: rungs'.
    Absent by design: a KenLM shard missing only flagged word rungs (free or charged), whose run stopped on a
    (flag, syllable) pair unseen in training and was run again on the unflagged rungs (DECISIONS.md 2026-11-01)."""
    want = set(summaries(estimator, None))
    if estimator == "neural":
        want = {k for k in want if k[0] in NEURAL_FAMILIES and k[3] in SHARED}
    short = defaultdict(set)
    for family, pairing, _, rung in want - set(summaries(estimator, size)):
        short[(family, pairing)].add(rung)
    order = {r: i for i, r in enumerate(dict.fromkeys(k[3] for k in summaries(estimator, None)))}  # the 10M files' order
    label = lambda key: f"{key[0]} {key[1]}: {', '.join(sorted(short[key], key=order.get))}"
    by_design = [label(k) for k in sorted(short) if estimator == "kenlm" and all("-" in r for r in short[k])]
    return by_design, [label(k) for k in sorted(short) if label(k) not in by_design]


def pairs(estimator):
    """The contrasts the 10M grid reports, (last, baseline)."""
    files = ([FAKE / "f3b_kenlm_1010" / f"t2_wr_v2_full_1010_{f}_contrasts.tsv" for f in FAMILIES] if estimator == "kenlm"
             else [FAKE / "f3b_neural_2010" / f / "result_contrasts.tsv" for f in FAMILIES])
    return sorted({(r["last"], r["baseline"]) for path in files for r in read(path)})


def contrasts(estimator, size):
    """{(family, pairing, scenario, last, baseline): (true, estimated)}: differences of rung-level R, as the
    grids' own contrast tables are (checked against f3b_kenlm_1010), so single-rung shards combine."""
    R = summaries(estimator, size)
    out = {}
    for (family, pairing, scenario, rung) in R:
        for last, baseline in pairs(estimator):
            if rung == last and (family, pairing, scenario, baseline) in R:
                a, b = R[(family, pairing, scenario, last)], R[(family, pairing, scenario, baseline)]
                out[(family, pairing, scenario, last, baseline)] = (a[0] - b[0], a[1] - b[1])
    return out


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    rows, lines, absent = [], [], {}
    for estimator in ("kenlm", "neural"):
        grids = {}
        for name, size in SIZES:
            grids[name] = contrasts(estimator, size)
            if size is not None:
                absent[(estimator, name)] = gaps(estimator, size)
        keys = sorted(set(grids["10M"]) & (set(grids["B0"]) | set(grids["B0/2"])))
        for key in keys:
            row = dict(estimator=estimator, family=key[0], pairing=key[1], scenario=key[2], last=key[3], baseline=key[4])
            for name, _ in SIZES:
                if key in grids[name]:
                    t, e = grids[name][key]
                    row[f"true_{name}"], row[f"estimated_{name}"], row[f"distortion_{name}"] = t, e, e - t
            rows.append(row)
    fields = ["estimator", "family", "pairing", "scenario", "last", "baseline"] + [
        f"{k}_{n}" for n, _ in SIZES for k in ("true", "estimated", "distortion")]
    with open(HERE / "comparison.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n", restval="")
        w.writeheader(); w.writerows(rows)
    lines += ["# Fake-data check at the real B0: distortion of the contrasts against the 10M grids", "",
              "Simulated data only (DECISIONS.md 2026-11-01). Distortion is the estimated contrast minus the true "
              "one, in bits; each grid has its own draws. B0 = 7,908,000 and B0/2 = 3,954,000 training syllables "
              "(the real B0, 7,907,758, in whole lines of 1,000); 1,000,000 test syllables throughout. KenLM rows are "
              "every contrast of the 10M grid; neural rows the mapped families at rungs 1w, 1 and 4. A cell is shown "
              "where 10M and at least one B0 size have it. Sign reversal: a true contrast of at least 0.1 bits estimated with the "
              "opposite sign (a descriptive marker, not a pass/fail threshold).", ""]
    for estimator in ("kenlm", "neural"):
        mine = [r for r in rows if r["estimator"] == estimator]
        lines += [f"## {'KenLM' if estimator == 'kenlm' else 'Neural'}", ""]
        if not mine:
            lines += ["No complete B0 panel yet.", ""]
        else:
            lines += ["| Families | Contrast | " + " | ".join(f"max abs {n}" for n, _ in SIZES)
                      + " | " + " | ".join(f"reversals {n}" for n, _ in SIZES) + " |",
                      "|---|---|" + "---:|" * (2 * len(SIZES))]
            for group in ("local", "skipped"):
                for last, baseline in sorted({(r["last"], r["baseline"]) for r in mine}):
                    cells = [r for r in mine if r["family"].startswith(group) and (r["last"], r["baseline"]) == (last, baseline)]
                    if not cells:
                        continue
                    mx, rev = [], []
                    for n, _ in SIZES:
                        have = [r for r in cells if f"distortion_{n}" in r]
                        mx.append(f"{max(abs(r[f'distortion_{n}']) for r in have):.3f}" if have else "")
                        rev.append(f"{sum(abs(r[f'true_{n}']) >= SIGN_MARK and r[f'true_{n}'] * r[f'estimated_{n}'] < 0 for r in have)} of {len(have)}"
                                   if have else "")
                    lines.append(f"| {group} | R{last} − R{baseline} | " + " | ".join(mx) + " | " + " | ".join(rev) + " |")
            lines.append("")
        for n, _ in SIZES[1:]:
            by_design, incomplete = absent[(estimator, n)]
            if incomplete:
                lines.append(f"Not complete at {n}: {'; '.join(incomplete)}.")
            if by_design:
                lines.append(f"Absent by design at {n} (runs stopped on a (flag, syllable) pair unseen in training and run "
                             f"again on the unflagged rungs; DECISIONS.md 2026-11-01): {'; '.join(by_design)}.")
        lines.append("")
    (HERE / "comparison.md").write_text("\n".join(lines).rstrip() + "\n")
    print(f"{len(rows)} contrast rows; {HERE / 'comparison.md'}")


if __name__ == "__main__":
    main()
