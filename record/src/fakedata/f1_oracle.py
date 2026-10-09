"""Same-test oracle loss for F1 version 2 rows (check 2 of the revised F1 checks, DECISIONS 2026-10-09).

For each row, the test tokens are regenerated from their seed (the test set doesn't depend on the
training budget) and scored with the true probability at the context actually available: for a lag-m
copy process with c >= m previous tokens in the line, p = (1 - eps)[x_t = x_{t-m}] + eps p(x_t);
otherwise the Zipf marginal. Adds oracle_loss, oracle_disc (oracle minus the population reference,
i.e. test-sample variation) and fit_minus_oracle (the normalised KenLM loss minus the oracle loss).
Usage: python -I src/fakedata/f1_oracle.py IN.tsv OUT.tsv
"""
import csv, importlib.util, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("f1v2", os.path.join(HERE, "f1v2.py")); F = importlib.util.module_from_spec(s); s.loader.exec_module(F)

def oracle_losses(proc, m, v, line, seed):
    p = F.zipf(v)
    base = 100000 * seed + 1000 * m + F.VOCABS.index(v) * 10 + (0 if proc == "iid" else 1)
    x = F.simulate(F.N_TEST, p, m, base + 2)
    x = x[: (len(x) // line) * line]
    pos = np.arange(len(x)) % line
    marg = -np.log2(p[x])
    out = {}
    for k in range(5):
        if m == 0:
            out[k] = float(marg.mean()); continue
        have = np.minimum(k, pos) >= m
        prev = np.empty_like(x); prev[m:] = x[:-m]; prev[:m] = -1
        same = (x == prev)
        q = np.where(have, (1 - F.EPS) * same + F.EPS * p[x], p[x])
        out[k] = float((-np.log2(q)).mean())
    return out

def main():
    src, dst = sys.argv[1], sys.argv[2]
    rows = list(csv.DictReader(open(src), delimiter="\t"))
    cache = {}
    for r in rows:
        key = (r["proc"], int(r["m"]), int(r["vocab"]), int(r["line"]), int(r["seed"]))
        if key not in cache:
            cache[key] = oracle_losses(*key)
        o = cache[key][int(r["k"])]
        r["oracle_loss"] = round(o, 5)
        r["oracle_disc"] = round(o - float(r["h_ref"]), 5)
        r["fit_minus_oracle"] = round(float(r["h_norm"]) - o, 5)
    with open(dst, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"); wr.writeheader(); wr.writerows(rows)
    print(len(rows), "rows,", len(cache), "test sets ->", dst)

if __name__ == "__main__":
    main()
