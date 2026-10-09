"""F3b: how far the estimator alone moves R_k (notes/multiverse-spec.md §3a).

Seventeen fake languages, each with its own inventory size (Zipf, 600 to 10,000 types) and a lag-1
copy process ("local" family: dependence between adjacent tokens) or a lag-m copy process ("skipped"
family, the stress test). Each language's copy rate eps is solved so that its true conditional entropy
at k >= m hits a target density between 4 and 6 bits; inventory size and target density are paired
independently, aligned (larger inventory, higher density) or opposed. The true density is the same at
every k >= m, so the true R_k is constant across those rungs: any drift in the estimated R_k with k
comes from the estimator. Syllable rates per scenario: S0, no trade-off (r = 0); S1, a trade-off
(r = -0.8), both with v = 0.9, built exactly in-sample from the true densities.

KenLM at orders 2-5 (k = 1-4) on 10M training tokens per language, scored on 1M held-out tokens,
lines of 1,000 tokens, references at the context actually available. No linguistic data.
Usage: python -I src/fakedata/f3b_fitted.py WORKDIR OUT.tsv {local|skipped}
"""
import csv, importlib.util, os, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
F = load("f1v2", os.path.join(HERE, "f1v2.py"))
A = load("a", os.path.join(HERE, "..", "stage6", "analysis.py"))

L, N, LINE, KS = 17, 10_000_000, 1000, (1, 2, 3, 4)
INV = np.round(np.geomspace(600, 10000, L)).astype(int)
TARGET = np.linspace(4.0, 6.0, L)
V, R_SCEN = 0.9, {"S0": 0.0, "S1": -0.8}

def solve_eps(p, target):
    lo, hi = 1e-4, 0.9999
    for _ in range(60):
        mid = (lo + hi) / 2
        (lo, hi) = (mid, hi) if F.h_copy(p, mid) < target else (lo, mid)
    return (lo + hi) / 2

def copy_process(n, p, m, eps, seed):
    rng = np.random.default_rng(seed)
    out = np.empty(n, dtype=np.int64)
    for r in range(m):
        Lr = len(range(r, n, m))
        fresh = rng.random(Lr) < eps; fresh[0] = True
        vals = rng.choice(len(p), size=Lr, p=p)
        idx = np.where(fresh, np.arange(Lr), 0)
        out[r::m] = vals[np.maximum.accumulate(idx)]
    return out

def ref(p, eps, k, m):
    hp, hc = F.h_marg(p), F.h_copy(p, eps)
    return float(np.mean([hp if min(k, j) < m else hc for j in range(LINE)]))

def rates(log_id, r, rng):
    """log SR with sample correlation r and SD ratio v to log ID, exactly."""
    z = (log_id - log_id.mean()) / log_id.std(ddof=1)
    w = rng.normal(size=len(z)); w = w - (w @ z) / (z @ z) * z; w = w / w.std(ddof=1)
    # log ID = mean + v * sd_sr * (r * zs + ...): choose sd_sr so SD(log ID)/SD(log SR) = v
    sd_sr = log_id.std(ddof=1) / V
    zs = r * z + np.sqrt(1 - r ** 2) * w
    return np.log(6.5) + sd_sr * zs / zs.std(ddof=1)

def main():
    work, out, family = sys.argv[1], sys.argv[2], sys.argv[3]
    m = 1 if family == "local" else 3
    os.makedirs(f"{work}/tmp", exist_ok=True); os.makedirs(f"{work}/logs", exist_ok=True)
    pairings = {"independent": np.random.default_rng(5).permutation(L), "aligned": np.arange(L), "opposed": np.arange(L)[::-1]}
    rows = []
    for pname, order in pairings.items():
        est = np.zeros((L, len(KS))); tru = np.zeros((L, len(KS)))
        for i in range(L):
            v, target = INV[i], TARGET[order[i]]
            p = F.zipf(v); eps = solve_eps(p, target)
            train, test = f"{work}/train.txt", f"{work}/test.txt"
            F.write(train, copy_process(N, p, m, eps, 7000 + 10 * i), LINE)
            F.write(test, copy_process(F.N_TEST, p, m, eps, 8000 + 10 * i), LINE)
            for j, k in enumerate(KS):
                arpa, binm = f"{work}/m.arpa", f"{work}/m.bin"
                F.lmplz(k + 1, train, arpa, f"{work}/tmp", f"{work}/logs/{family}_{pname}_l{i}_k{k}.log")
                subprocess.run([f"{F.KENLM}/build_binary", arpa, binm], capture_output=True, check=True)
                os.remove(arpa)
                est[i, j] = F.score_model(binm, test)[1]          # normalised (lines of 1,000: negligible difference)
                os.remove(binm)
                tru[i, j] = ref(p, eps, k, m)
            os.remove(train); os.remove(test)
            print(f"{pname} language {i}: V={v} target={target:.2f} eps={eps:.4f} est={np.round(est[i], 3)}", flush=True)
        for sname, r in R_SCEN.items():
            log_sr = rates(np.log(tru[:, -1]), r, np.random.default_rng(11))
            R_true = A.ladder(np.log(tru), log_sr)[0]
            R_est = A.ladder(np.log(est), log_sr)[0]
            for j, k in enumerate(KS):
                rows.append({"family": family, "pairing": pname, "scenario": sname, "k": k, "R_true": round(R_true[j], 4),
                             "R_est": round(R_est[j], 4), "distortion": round(R_est[j] - R_true[j], 4),
                             "mean_bias_bits": round(float(np.mean(est[:, j] - tru[:, j])), 4),
                             "bias_range_bits": f"{np.min(est[:, j] - tru[:, j]):.3f}..{np.max(est[:, j] - tru[:, j]):.3f}"})
    with open(out, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t"); wr.writeheader(); wr.writerows(rows)
    print("done", out)

if __name__ == "__main__":
    main()
