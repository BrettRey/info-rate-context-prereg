"""F1 fake-data check of the estimator (notes/multiverse-spec.md §3a).

Simulated text with known conditional entropy: token t copies token t-m with probability 1-eps,
otherwise it is a fresh draw from a Zipf distribution p over V types. The residue classes mod m are
independent copy chains, so the true conditional entropy given the previous k tokens is
  H_k = H(p)            for k < m,
  H_k = H_copy(eps, p)  for k >= m,
where H_copy averages, over a ~ p, the entropy of the row q(a)=1-eps+eps*p_a, q(b)=eps*p_b (b != a).
KenLM (modified Kneser-Ney, order k+1) is trained on N tokens and scored on N/10 held-out tokens
from an independent run; reported: cross-entropy per token in bits (</s> excluded) minus H_k.
No linguistic data. Usage: python -I src/fakedata/f1_estimator.py WORKDIR OUT.tsv
"""
import csv, math, os, subprocess, sys, time
import numpy as np

KENLM = os.path.expanduser("~/src/kenlm/build/bin")
EPS, ZIPF_S, LINE = 0.3, 1.1, 1000           # long lines: context crosses all but 1 in 1000 tokens

def zipf(v):
    p = 1.0 / np.arange(1, v + 1) ** ZIPF_S
    return p / p.sum()

def h_true(p, eps, k, m):
    hp = -float(np.sum(p * np.log2(p)))
    if k < m:
        return hp
    q = 1 - eps + eps * p
    s = eps * (math.log2(eps) - hp)                       # sum_b eps p_b log2(eps p_b)
    rows = -q * np.log2(q) - s + eps * p * np.log2(eps * p)
    return float(np.sum(p * rows))

def simulate(n, p, m, eps, seed):
    rng = np.random.default_rng(seed)
    out = np.empty(n, dtype=np.int64)
    for r in range(m):                                    # each residue class is a copy chain
        L = len(range(r, n, m))
        fresh = rng.random(L) < eps
        fresh[0] = True
        vals = rng.choice(len(p), size=L, p=p)
        idx = np.where(fresh, np.arange(L), 0)
        out[r::m] = vals[np.maximum.accumulate(idx)]
    return out

def write(path, toks):
    with open(path, "w") as f:
        for i in range(0, len(toks), LINE):
            f.write(" ".join(f"s{t}" for t in toks[i:i + LINE]) + "\n")

def crossent(model, test):
    """Bits per token over the test file, </s> excluded, from KenLM's per-word log10 probabilities."""
    out = subprocess.run([f"{KENLM}/query", "-v", "word", model], stdin=open(test), capture_output=True, text=True, check=True).stdout
    total, n, oov = 0.0, 0, 0
    for line in out.splitlines():
        if not line or line.startswith(("Perplexity", "Total", "OOVs", "Tokens", "Name", "RSSMax", "user", "sys", "Memory")):
            continue
        for item in line.split("\t"):
            parts = item.split(" ")
            if len(parts) != 3 or "=" not in parts[0]:
                continue
            word = parts[0].rsplit("=", 1)
            if word[0] == "</s>":
                continue
            if word[1] == "0":
                oov += 1
            total += float(parts[2]); n += 1
    return -total / n * math.log2(10), n, oov

def crossent_unigram(arpa, test):
    """KenLM's binary format needs order >= 2, so the unigram rung is scored here from KenLM's own
    ARPA unigram log10 probabilities (unknown tokens get <unk>), </s> excluded."""
    lp, in1 = {}, False
    for line in open(arpa):
        line = line.rstrip("\n")
        if line.startswith("\\1-grams:"):
            in1 = True; continue
        if in1:
            if not line or line.startswith("\\"):
                break
            f = line.split("\t")
            lp[f[1]] = float(f[0])
    total, n, oov = 0.0, 0, 0
    for line in open(test):
        for w in line.split():
            if w not in lp:
                oov += 1; total += lp["<unk>"]
            else:
                total += lp[w]
            n += 1
    return -total / n * math.log2(10), n, oov

def main():
    work, out_path = sys.argv[1], sys.argv[2]
    os.makedirs(f"{work}/tmp", exist_ok=True)
    fields = ["m", "vocab", "n_train", "k", "h_true", "h_est", "bias", "oov_rate", "lmplz_s", "fallback"]
    done = set()
    if os.path.exists(out_path):
        for r in csv.DictReader(open(out_path), delimiter="\t"):
            done.add((r["m"], r["vocab"], r["n_train"], r["k"]))
    w = open(out_path, "a", newline="")
    wr = csv.DictWriter(w, fieldnames=fields, delimiter="\t")
    if not done:
        wr.writeheader()
    for v in (600, 2000, 10000):
        p = zipf(v)
        for m in (1, 2, 3, 4):
            for n in (5_000_000, 10_000_000, 30_000_000):
                if all((str(m), str(v), str(n), str(k)) in done for k in range(5)):
                    continue
                train, test = f"{work}/train.txt", f"{work}/test.txt"
                write(train, simulate(n, p, m, EPS, seed=1000 + m))
                write(test, simulate(n // 10, p, m, EPS, seed=2000 + m))
                for k in range(5):
                    if (str(m), str(v), str(n), str(k)) in done:
                        continue
                    arpa, binm = f"{work}/m.arpa", f"{work}/m.bin"
                    t0 = time.time(); fb = False
                    cmd = [f"{KENLM}/lmplz", "-o", str(k + 1), "-S", "30%", "-T", f"{work}/tmp"]
                    r = subprocess.run(cmd, stdin=open(train), stdout=open(arpa, "w"), stderr=subprocess.PIPE, text=True)
                    if r.returncode != 0:                 # record when discounts needed the fallback
                        fb = True
                        subprocess.run(cmd + ["--discount_fallback"], stdin=open(train), stdout=open(arpa, "w"), stderr=subprocess.DEVNULL, check=True)
                    t1 = time.time() - t0
                    if k == 0:
                        h, ntok, oov = crossent_unigram(arpa, test)
                        os.remove(arpa)
                    else:
                        subprocess.run([f"{KENLM}/build_binary", arpa, binm], capture_output=True, check=True)
                        os.remove(arpa)
                        h, ntok, oov = crossent(binm, test)
                        os.remove(binm)
                    ht = h_true(p, EPS, k, m)
                    wr.writerow({"m": m, "vocab": v, "n_train": n, "k": k, "h_true": round(ht, 4), "h_est": round(h, 4),
                                 "bias": round(h - ht, 4), "oov_rate": round(oov / ntok, 6), "lmplz_s": round(t1, 1), "fallback": fb})
                    w.flush()
                os.remove(train); os.remove(test)
    print("done")

if __name__ == "__main__":
    main()
