"""F1 with a mapped dependency (side agent, 2026-10-09): a syllable predicts a *different* syllable later.

Token t is sigma(token t-m) with probability 1 - EPS, otherwise a fresh Zipf draw, for a fixed random
permutation sigma of the inventory. Unlike the copy process, tied input and output embeddings give no
shortcut: the model has to learn sigma. Each residue class mod m is a Markov chain with transitions
T(a -> b) = (1 - EPS)[b = sigma(a)] + EPS p_b; its stationary distribution pi solves
pi_b = (1 - EPS) pi_{sigma^-1(b)} + EPS p_b (computed by iteration). True entropy given k previous
tokens: H(pi) for k < m (the residue chains are independent), sum_a pi_a H(T(a, .)) for k >= m.
Runs both estimators at lag 1 (sanity) and lag 3, 600/2,000/10,000 types, 10M training tokens, lines
of 1,000, k = 1-4. No linguistic data.
Usage: python -I src/fakedata/f1_mapped.py WORKDIR OUT.tsv [--kenlm-only]
(--kenlm-only skips the neural fits, leaving their columns empty, so KenLM can run while the GPU is busy.)
"""
import csv, importlib.util, math, os, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
def load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
F = load("f1v2", os.path.join(HERE, "f1v2.py"))
NN = load("nnlm", os.path.join(HERE, "..", "stage5", "nnlm.py"))
L, N, N_VAL, EPS = 1000, 10_000_000, 500_000, F.EPS

def stationary(p, sigma, eps, iters=2000):
    inv = np.argsort(sigma); pi = p.copy()
    for _ in range(iters):
        new = (1 - eps) * pi[inv] + eps * p
        if np.max(np.abs(new - pi)) < 1e-15:
            break
        pi = new
    return new / new.sum()

def h_rows(p, sigma, eps):
    """Entropy of each row T(a, .): mass 1-eps+eps*p_sigma(a) on sigma(a), eps*p_b elsewhere."""
    s_all = float(np.sum(eps * p * np.log2(eps * p)))
    q = 1 - eps + eps * p[sigma]
    return -q * np.log2(q) - (s_all - eps * p[sigma] * np.log2(eps * p[sigma]))

def truth(p, sigma, eps, k, m):
    pi = stationary(p, sigma, eps)
    hp = -float(np.sum(pi * np.log2(pi)))
    hc = float(np.sum(pi * h_rows(p, sigma, eps)))
    return float(np.mean([hp if min(k, j) < m else hc for j in range(L)]))

def simulate(n, p, m, sigma, seed):
    rng = np.random.default_rng(seed)
    out = np.empty(n, dtype=np.int64)
    for r in range(m):
        Lr = len(range(r, n, m))
        fresh = rng.random(Lr) < EPS; fresh[0] = True
        vals = rng.choice(len(p), size=Lr, p=p)
        last = np.maximum.accumulate(np.where(fresh, np.arange(Lr), 0))
        y = vals[last]; d = np.arange(Lr) - last                  # apply sigma d times
        step = 0
        while True:
            mask = d > step
            if not mask.any():
                break
            y[mask] = sigma[y[mask]]; step += 1
        out[r::m] = y
    return out

def lines(x):
    n = (len(x) // L) * L
    return x[:n].reshape(-1, L)

def kenlm_bits(work, tr, te, k):
    F.write(f"{work}/train.txt", tr.ravel(), L); F.write(f"{work}/test.txt", te.ravel(), L)
    F.lmplz(k + 1, f"{work}/train.txt", f"{work}/m.arpa", f"{work}/tmp", f"{work}/logs/mapped_k{k}.log")
    subprocess.run([f"{F.KENLM}/build_binary", f"{work}/m.arpa", f"{work}/m.bin"], capture_output=True, check=True)
    h = F.score_model(f"{work}/m.bin", f"{work}/test.txt")[1]
    for f_ in ("m.arpa", "m.bin", "train.txt", "test.txt"):
        os.remove(f"{work}/{f_}")
    return h

def main():
    work, out = sys.argv[1], sys.argv[2]
    kenlm_only = "--kenlm-only" in sys.argv[3:]
    for d in (work, f"{work}/tmp", f"{work}/logs"):
        os.makedirs(d, exist_ok=True)
    rows = []
    for v in F.VOCABS:
        p = F.zipf(v)
        sigma = np.random.default_rng(900 + v).permutation(v)
        for m in (1, 3):
            base = 5_000_000 + 1000 * m + F.VOCABS.index(v) * 10
            tr = lines(simulate(N, p, m, sigma, base + 1)); te = lines(simulate(F.N_TEST, p, m, sigma, base + 2))
            va = lines(simulate(N_VAL, p, m, sigma, base + 3))
            for k in (1, 2, 3, 4):
                ref = truth(p, sigma, EPS, k, m)
                hk = kenlm_bits(work, tr, te, k)
                r = None if kenlm_only else NN.estimate(tr, va, te, v, k)
                row = {"proc": "mapped", "m": m, "vocab": v, "n_train": tr.size, "line": L, "k": k, "h_ref": round(ref, 5),
                       "kenlm": round(hk, 5), "kenlm_bias": round(hk - ref, 5), "ffnn": round(r["test_bits"], 5) if r else "",
                       "ffnn_bias": round(r["test_bits"] - ref, 5) if r else "", "ffnn_seconds": r["seconds"] if r else ""}
                rows.append(row)
                print(row, flush=True)
    with open(out, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"); wr.writeheader(); wr.writerows(rows)
    print("done", out, flush=True)

if __name__ == "__main__":
    main()
