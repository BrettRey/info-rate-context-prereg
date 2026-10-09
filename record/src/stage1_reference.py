"""Stage 1: reproduce the reference numbers in SPEC.md from InfoRateData.csv.

Follows the computation given in SPEC.md (speaker means, then language means).
Prints the spec's expected value beside each computed one. Output: results/stage1/.
"""
import pathlib

import pandas as pd
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parents[1]
d = pd.read_csv(ROOT / "data/ref/InfoRateData.csv", sep="\t")

# Row count: the paper reports 2265 data points; the spec says the CSV has 2288.
print(f"rows={len(d)} languages={d.Language.nunique()} "
      f"speakers={d.Speaker.nunique()} texts={d.Text.nunique()}")
print("NA per column:", d.isna().sum().to_dict())
print("rows per language:", d.groupby("Language").size().to_dict())

d["SR"] = d.NS / d.Duration
d["IR"] = d.SR * d.ID
d["ShIR"] = d.SR * d.ShE
nsv = d[d.Language == "VIE"].groupby("Text").NS.first()
d["SemIR"] = d.Text.map(nsv) / d.Duration

sp = d.groupby(["Language", "Speaker"])[["SR", "IR", "ShIR", "SemIR"]].mean().reset_index()
lg = sp.groupby("Language")[["SR", "IR", "ShIR", "SemIR"]].mean()
cv = lambda x: x.std() / x.mean() * 100

# SDIR: syllabic density ratio against Vietnamese, averaged over texts.
# Direction NS_VIE / NS_L (higher = denser), as the authors' NSVR (InfoRate.Rmd lines 205-207).
ns_lt = d.groupby(["Language", "Text"]).NS.first().unstack()
sdir = (1 / ns_lt.div(ns_lt.loc["VIE"], axis=1)).mean(axis=1)

L = d.groupby("Language")[["ID", "ShE"]].first().join(lg)
L["SDIR"] = sdir

cv_pop = lambda x: x.std(ddof=0) / x.mean() * 100

# Expected values: the spec's table, and the Elicit audit's recalculation
# (notes/elicit-audit-39-bits-critique-2026-09-28.md, C05, C10-C13).
# The two disagree on weighting and SD conventions; both are unverified.
nan = float("nan")
rows = [
    ("mean IR, mean of lang means", lg.IR.mean(), 39.15, 39.25),
    ("mean IR, rows", d.IR.mean(), 39.15, nan),
    ("mean ShE x SR, mean of lang means", lg.ShIR.mean(), 56.71, 56.94),
    ("mean ShE x SR, rows", d.ShIR.mean(), 56.71, 56.71),
    ("pooled CV SR, rows", cv(d.SR), 17.3, nan),
    ("pooled CV IR, rows", cv(d.IR), 13.0, nan),
    ("pooled CV SR, speaker means", cv(sp.SR), 17.3, nan),
    ("pooled CV IR, speaker means", cv(sp.IR), 13.0, nan),
    ("CV lang means SR (sample SD)", cv(lg.SR), 13.9, 13.95),
    ("CV lang means ShE x SR (sample SD)", cv(lg.ShIR), 12.6, 12.58),
    ("CV lang means ID x SR (sample SD)", cv(lg.IR), 8.6, 8.45),
    ("CV lang means ID x SR (population SD)", cv_pop(lg.IR), 8.6, nan),
    ("CV lang means semantic rate (sample SD)", cv(lg.SemIR), 10.3, 10.65),
    ("CV lang means semantic rate (population SD)", cv_pop(lg.SemIR), 10.3, 10.33),
    ("r(SR, ID), 17 lang means", stats.pearsonr(L.SR, L.ID)[0], -0.83, -0.834),
    ("r(SR, ShE), 17 lang means", stats.pearsonr(L.SR, L.ShE)[0], -0.55, -0.553),
    ("r(SR, SDIR), 17 lang means", stats.pearsonr(L.SR, L.SDIR)[0], -0.83, -0.83),
    ("r(SR, ID), rows", stats.pearsonr(d.SR, d.ID)[0], -0.69, nan),
]
print(f"\n{'quantity':44} {'computed':>9} {'spec':>7} {'elicit':>7}")
for name, got, spec, elicit in rows:
    print(f"{name:44} {got:9.3f} {spec:7.2f} {elicit:7.2f}")
print("p for r(SR, ID), lang means:", stats.pearsonr(L.SR, L.ID)[1])
print("p for r(SR, ShE), lang means:", stats.pearsonr(L.SR, L.ShE)[1])
