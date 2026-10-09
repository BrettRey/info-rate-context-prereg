"""F3a: the Stage 6 analysis on fake data with oracle (true) information densities
(notes/multiverse-spec.md §3a). No corpus and no estimator: this checks aggregation, R_k, v_k, r_k,
the language bootstrap and paired rung differences against known truth.

Panel shape from the authors' CSV (Language, Speaker, Text only; 2,288 readings). Syllable rates:
log SR = a_l + speaker + text (shared across languages) + language-by-text + reading noise. True
densities per scenario: log ID_lk = m_k + v * sd_a * (r_k * z_l + sqrt(1 - r_k^2) * w_l), z the
standardised language effect. S0: r_k = 0 everywhere; S1: r_k = -0.8 everywhere; S2: r_k = -0.8 at
k = 0 and 1w, 0 from k = 1 on. v = 0.9 throughout.

Experiment "fixed": the 17 language effects and densities fixed (in-sample correlation and SD ratio
exact), speakers, texts and noise redrawn; truth R_k = SD(a + log ID)/SD(a). Experiment "redrawn":
language effects and densities redrawn each replicate from the population; truth is the population
R_k = sqrt(1 + v^2 + 2 r v), which is what the language bootstrap's interval claims to cover.

The spreads below are simulation settings chosen to be plausible, not estimates from the data.
Usage: python -I src/fakedata/f3a_oracle.py OUT.tsv [--zero-noise]
"""
import csv, importlib.util, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("a", os.path.join(HERE, "..", "stage6", "analysis.py"))
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)

RUNGS = ["0", "1w", "1", "2", "3", "4"]
M_K = np.log([7.5, 5.5, 5.0, 4.6, 4.4, 4.3])          # mean log ID per rung (irrelevant to R_k)
MU, SD_A = np.log(6.5), 0.14                           # language effect: mean and SD of log SR
SD_SPK, SD_TXT, SD_LT, SD_E = 0.08, 0.05, 0.03, 0.04  # speaker, shared text, language x text, reading
V = 0.9
SCEN = {"S0": [0, 0, 0, 0, 0, 0], "S1": [-0.8] * 6, "S2": [-0.8, -0.8, 0, 0, 0, 0]}
N_REP, N_BOOT, LEVEL = 500, 2000, 0.90

def panel():
    rows = list(csv.DictReader(open(os.path.join(HERE, "..", "..", "data", "ref", "InfoRateData.csv")), delimiter="\t"))
    lang = np.array([r["Language"] for r in rows]); spk = np.array([r["Speaker"] for r in rows]); txt = np.array([r["Text"] for r in rows])
    return lang, spk, txt

RUNG_VAR = 0.3                                        # each rung's own variation around the shared pattern

def densities(a, r, rng, exact):
    z = (a - a.mean()) / a.std(ddof=1) if exact else (a - MU) / SD_A
    if exact:
        z = z / z.std(ddof=1)
    w0 = rng.normal(size=len(a))
    cols = []
    for k in range(len(RUNGS)):
        w = w0 + RUNG_VAR * rng.normal(size=len(a))
        if exact:                                    # orthogonalise against z in-sample, unit sample SD
            w = w - (w @ z) / (z @ z) * z; w = w / w.std(ddof=1)
        else:
            w = w / np.sqrt(1 + RUNG_VAR ** 2)
        sd = a.std(ddof=1) if exact else SD_A
        cols.append(M_K[k] + V * sd * (r[k] * z + np.sqrt(1 - r[k] ** 2) * w))
    return np.stack(cols, axis=1)

def readings(a_by_lang, lang, spk, txt, rng, zero):
    langs = np.unique(lang)
    li = np.searchsorted(langs, lang)
    if zero:
        return a_by_lang[li]
    su, si = np.unique(spk, return_inverse=True); tu, ti = np.unique(txt, return_inverse=True)
    lt = np.char.add(lang, txt); ltu, lti = np.unique(lt, return_inverse=True)
    return (a_by_lang[li] + rng.normal(0, SD_SPK, len(su))[si] + rng.normal(0, SD_TXT, len(tu))[ti]
            + rng.normal(0, SD_LT, len(ltu))[lti] + rng.normal(0, SD_E, len(lang)))

def main():
    out, zero = sys.argv[1], "--zero-noise" in sys.argv
    lang, spk, txt = panel()
    langs = np.unique(lang); L = len(langs)
    rng = np.random.default_rng(20261009)
    a_fixed = rng.normal(MU, SD_A, L)
    w_out = open(out, "w", newline="")
    fields = ["experiment", "scenario", "rung", "truth", "mean_est", "bias", "rmse", "lang_coverage", "lang_width",
              "panel_coverage", "panel_basic_coverage", "panel_width", "pair_truth", "pair_bias", "lang_pair_coverage", "panel_pair_coverage", "panel_basic_pair_coverage", "n_rep"]
    wr = csv.DictWriter(w_out, fieldnames=fields, delimiter="\t"); wr.writeheader()
    n_rep = 3 if zero else N_REP
    for exp in ("fixed", "redrawn"):
        for sname, r in SCEN.items():
            ests, truths, cov, wid, pairs, ptruth, pcov, pcv, pwd, ppcv, bcv, bpcv = [], [], [], [], [], [], [], [], [], [], [], []
            log_id_fixed = densities(a_fixed, r, np.random.default_rng(7), exact=True)
            for rep in range(n_rep):
                if exp == "fixed":
                    a, log_id = a_fixed, log_id_fixed
                    truth = A.ladder(log_id, a)[0]
                else:
                    a = rng.normal(MU, SD_A, L); log_id = densities(a, r, rng, exact=False)
                    truth = np.array([np.sqrt(1 + V ** 2 + 2 * rk * V) for rk in r])
                sr = np.exp(readings(a, lang, spk, txt, rng, zero))
                _, msr = A.language_means(lang, spk, sr)
                est = A.ladder(log_id, np.log(msr))[0]
                boot = A.bootstrap(log_id, np.log(msr), n_boot=200 if zero else N_BOOT, seed=rep)
                lo, hi = A.interval(boot, LEVEL)
                dlo, dhi = A.interval(boot - boot[:, [1]], LEVEL)          # paired change from 1w
                pb = A.panel_bootstrap(lang, spk, txt, sr, log_id, langs, n_boot=200 if zero else 1000, seed=rep)
                plo, phi = A.interval(pb, LEVEL); pdlo, pdhi = A.interval(pb - pb[:, [1]], LEVEL)
                blo, bhi = A.basic_interval(est, pb, LEVEL); bdlo, bdhi = A.basic_interval(est - est[1], pb - pb[:, [1]], LEVEL)
                bcv.append((blo <= truth) & (truth <= bhi)); bpcv.append((bdlo <= truth - truth[1]) & (truth - truth[1] <= bdhi))
                pcv.append((plo <= truth) & (truth <= phi)); pwd.append(phi - plo)
                ppcv.append((pdlo <= truth - truth[1]) & (truth - truth[1] <= pdhi))
                ests.append(est); truths.append(truth); cov.append((lo <= truth) & (truth <= hi)); wid.append(hi - lo)
                pairs.append(est - est[1]); ptruth.append(truth - truth[1]); pcov.append((dlo <= truth - truth[1]) & (truth - truth[1] <= dhi))
            ests, truths = np.array(ests), np.array(truths)
            pairs, ptruth = np.array(pairs), np.array(ptruth)
            for k, rung in enumerate(RUNGS):
                wr.writerow({"experiment": exp, "scenario": sname, "rung": rung, "truth": round(truths[:, k].mean(), 4),
                             "mean_est": round(ests[:, k].mean(), 4), "bias": round((ests[:, k] - truths[:, k]).mean(), 4),
                             "rmse": round(np.sqrt(((ests[:, k] - truths[:, k]) ** 2).mean()), 4),
                             "lang_coverage": round(np.mean([c[k] for c in cov]), 3), "lang_width": round(np.mean([x[k] for x in wid]), 4),
                             "panel_coverage": round(np.mean([c[k] for c in pcv]), 3), "panel_basic_coverage": round(np.mean([c[k] for c in bcv]), 3), "panel_width": round(np.mean([x[k] for x in pwd]), 4),
                             "pair_truth": round(ptruth[:, k].mean(), 4), "pair_bias": round((pairs[:, k] - ptruth[:, k]).mean(), 4),
                             "lang_pair_coverage": "" if k == 1 else round(np.mean([c[k] for c in pcov]), 3),
                             "panel_pair_coverage": "" if k == 1 else round(np.mean([c[k] for c in ppcv]), 3),
                             "panel_basic_pair_coverage": "" if k == 1 else round(np.mean([c[k] for c in bpcv]), 3), "n_rep": n_rep})
    w_out.close()
    print("done", out)

if __name__ == "__main__":
    main()
