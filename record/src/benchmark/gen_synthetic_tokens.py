"""Synthetic token streams for timing KenLM. Integer tokens only; no linguistic data.
Usage: python gen.py OUT N_TOKENS VOCAB REGIME SEED   (REGIME: iid | markov)"""
import sys, numpy as np
out, n, v, regime, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], int(sys.argv[5])
rng = np.random.default_rng(seed)
p = 1.0 / np.arange(1, v + 1) ** 1.1; p /= p.sum()
if regime == "iid":
    toks = rng.choice(v, size=n, p=p)
else:   # first-order Markov: each state prefers a small random successor set, Zipf-weighted
    succ = rng.choice(v, size=(v, 50), p=p)
    w = 1.0 / np.arange(1, 51) ** 1.2; w /= w.sum()
    toks = np.empty(n, dtype=np.int64); toks[0] = 0
    picks = rng.choice(50, size=n, p=w); jump = rng.random(n) < 0.1; rnd = rng.choice(v, size=n, p=p)
    for i in range(1, n):
        toks[i] = rnd[i] if jump[i] else succ[toks[i - 1], picks[i]]
with open(out, "w") as f:
    for i in range(0, n, 20):
        f.write(" ".join(f"s{t}" for t in toks[i:i + 20]) + "\n")
