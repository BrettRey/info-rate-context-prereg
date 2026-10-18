"""Spreads of log syllable rate in the authors' data, and the language-level relation between rate and
density, as settings for the F3a design analysis (DECISIONS 2026-10-10). Uses only what Stage 1 already
used: SR = NS / Duration per reading and ID per language, from data/ref/InfoRateData.csv (Coupé et al.
2019, CC BY 4.0). No pipeline count and no ratio to NS.

Method of moments on the crossed design: log SR = language + shared text + speaker (within language)
+ language-by-text + reading residual. Each spread is the SD of the corresponding means, with the
expected share of the finer terms subtracted from its variance; the uncorrected SD is reported too.
Usage: python -I src/stage1_spread_estimates.py OUT.json
"""
import csv, json, math, os, sys
from collections import defaultdict
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = list(csv.DictReader(open(os.path.join(ROOT, "data", "ref", "InfoRateData.csv"), encoding="utf-8"), delimiter="\t"))
lang = np.array([r["Language"] for r in rows]); spk = np.array([r["Speaker"] for r in rows]); txt = np.array([r["Text"] for r in rows])
y = np.log(np.array([float(r["NS"]) / float(r["Duration"]) for r in rows]))
idl = {}
for r in rows:
    idl.setdefault(r["Language"], float(r["ID"]))

def group_mean(values, keys):
    acc = defaultdict(list)
    for v, k in zip(values, keys):
        acc[k].append(v)
    means = {k: float(np.mean(v)) for k, v in acc.items()}
    sizes = {k: len(v) for k, v in acc.items()}
    return means, sizes

m_l, n_l = group_mean(y, lang)
r1 = y - np.array([m_l[l] for l in lang])
# shared text effect: average over languages of each language's text mean
lt_means, lt_n = group_mean(r1, list(zip(lang, txt)))
by_text = defaultdict(list)
for (l, t), v in lt_means.items():
    by_text[t].append(v)
t_eff = {t: float(np.mean(v)) for t, v in by_text.items()}
r2 = r1 - np.array([t_eff[t] for t in txt])
s_means, s_n = group_mean(r2, spk)
r3 = r2 - np.array([s_means[s] for s in spk])
lt2, lt2_n = group_mean(r3, list(zip(lang, txt)))
e = r3 - np.array([lt2[(l, t)] for l, t in zip(lang, txt)])
var_e = float(np.var(e, ddof=1))
def corrected(var_means, mean_n, finer):
    return math.sqrt(max(0.0, var_means - finer / mean_n))
sd = {}
var_lt = float(np.var(list(lt2.values()), ddof=1)); n_lt = float(np.mean(list(lt2_n.values())))
sd["reading"] = math.sqrt(var_e)
sd["language_by_text"] = corrected(var_lt, n_lt, var_e)
var_s = float(np.var(list(s_means.values()), ddof=1)); n_s = float(np.mean(list(s_n.values())))
sd["speaker"] = corrected(var_s, n_s, var_e + sd["language_by_text"] ** 2)
var_t = float(np.var(list(t_eff.values()), ddof=1)); n_t = len(set(lang))
sd["text"] = corrected(var_t, n_t, sd["language_by_text"] ** 2 + (var_e + sd["speaker"] ** 2) / 10)
langs = sorted(m_l)
a = np.array([m_l[l] for l in langs]); lid = np.log(np.array([idl[l] for l in langs]))
sd["language"] = float(np.std(a, ddof=1))
out = dict(source="data/ref/InfoRateData.csv (Coupé et al. 2019)", readings=len(rows), languages=len(langs),
           sd_log_sr=sd,
           uncorrected=dict(language_by_text=math.sqrt(var_lt), speaker=math.sqrt(var_s), text=math.sqrt(var_t)),
           v_language=float(np.std(lid, ddof=1) / np.std(a, ddof=1)),
           r_language=float(np.corrcoef(a, lid)[0, 1]),
           note="v = SD(log ID) / SD(language-mean log SR); r = their correlation across languages; both from the paper's ID values.")
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps(out, indent=1))
