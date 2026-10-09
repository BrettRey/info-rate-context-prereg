"""F1b: the F1 estimator check with short lines (side agent, 2026-10-09), for the line-bounded mode.

The same lag-m copy process as F1, cut into lines of 15 tokens; contexts stop at each line, as in
line-bounded estimates of subtitle text. A token at position j of a line has min(k, j) tokens of
context, so the true per-token entropy is the mean over positions of H_{min(k,j)}. KenLM's
end-of-line token (</s>) is left out of the average, but the probability KenLM gives it still lowers
the other tokens' probabilities; that cost is part of the bias reported here.
Usage: python -I src/fakedata/f1b_short_lines.py WORKDIR OUT.tsv
"""
import csv, importlib.util, os, subprocess, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("f1", os.path.join(HERE, "f1_estimator.py"))
f1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(f1)
LINE = 15

def h_true_lines(p, eps, k, m, line=LINE):
    return float(np.mean([f1.h_true(p, eps, min(k, j), m) for j in range(line)]))

def write(path, toks, line=LINE):
    with open(path, "w") as f:
        for i in range(0, len(toks) - line + 1, line):
            f.write(" ".join(f"s{t}" for t in toks[i:i + line]) + "\n")

def main():
    work, out_path = sys.argv[1], sys.argv[2]
    os.makedirs(f"{work}/tmp", exist_ok=True)
    fields = ["m", "vocab", "n_train", "line", "k", "h_true", "h_est", "bias", "oov_rate", "lmplz_s", "fallback"]
    with open(out_path, "w", newline="") as w:
        wr = csv.DictWriter(w, fieldnames=fields, delimiter="\t"); wr.writeheader()
        n = 10_000_000
        for v in (600, 2000, 10000):
            p = f1.zipf(v)
            for m in (1, 2, 4):
                train, test = f"{work}/train.txt", f"{work}/test.txt"
                write(train, f1.simulate(n, p, m, f1.EPS, seed=3000 + m))
                write(test, f1.simulate(n // 10, p, m, f1.EPS, seed=4000 + m))
                for k in range(5):
                    arpa, binm = f"{work}/m.arpa", f"{work}/m.bin"
                    t0 = time.time(); fb = False
                    cmd = [f"{f1.KENLM}/lmplz", "-o", str(k + 1), "-S", "30%", "-T", f"{work}/tmp"]
                    r = subprocess.run(cmd, stdin=open(train), stdout=open(arpa, "w"), stderr=subprocess.PIPE, text=True)
                    if r.returncode != 0:
                        fb = True
                        subprocess.run(cmd + ["--discount_fallback"], stdin=open(train), stdout=open(arpa, "w"), stderr=subprocess.DEVNULL, check=True)
                    t1 = time.time() - t0
                    if k == 0:
                        h, ntok, oov = f1.crossent_unigram(arpa, test); os.remove(arpa)
                    else:
                        subprocess.run([f"{f1.KENLM}/build_binary", arpa, binm], capture_output=True, check=True)
                        os.remove(arpa); h, ntok, oov = f1.crossent(binm, test); os.remove(binm)
                    ht = h_true_lines(p, f1.EPS, k, m)
                    wr.writerow({"m": m, "vocab": v, "n_train": n, "line": LINE, "k": k, "h_true": round(ht, 4), "h_est": round(h, 4),
                                 "bias": round(h - ht, 4), "oov_rate": round(oov / ntok, 6), "lmplz_s": round(t1, 1), "fallback": fb})
                    w.flush()
                os.remove(train); os.remove(test)
    print("done")

if __name__ == "__main__":
    main()
