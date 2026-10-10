"""F1 for the second estimator (notes/multiverse-spec.md §2.2a): the fixed-context neural model on the
same cells, seeds and test sets as KenLM's F1 version 2 rows (lines of 1,000, 10M training tokens,
seed 1), so the two estimators compare directly. Validation text from a separate seed (base + 3).
Reports test bits per syllable, the reference at the available context, the same-test oracle loss,
and fitted minus oracle. Settings are those in src/stage5/nnlm.py, fixed before this run.
Usage: python -I src/fakedata/f1_neural.py OUT.tsv
"""
import csv, importlib.util, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
def load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
F = load("f1v2", os.path.join(HERE, "f1v2.py"))
O = load("f1_oracle", os.path.join(HERE, "f1_oracle.py"))
NN = load("nnlm", os.path.join(HERE, "..", "stage5", "nnlm.py"))

L, N, N_VAL, SEED = 1000, 10_000_000, 500_000, 1

def lines(x):
    n = (len(x) // L) * L
    return x[:n].reshape(-1, L)

def main():
    out = sys.argv[1]
    done = set()
    if os.path.exists(out):
        done = {(r["proc"], r["m"], r["vocab"], r["k"]) for r in csv.DictReader(open(out), delimiter="\t")}
    new = not os.path.exists(out)
    fields = ["estimator", "proc", "m", "vocab", "n_train", "line", "seed", "k", "h_ref", "h_est", "bias", "oracle_loss", "fit_minus_oracle",
              "val_bits", "steps", "seconds", "device", "settings"]
    with open(out, "a", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        if new:
            wr.writeheader()
        for v in F.VOCABS:
            p = F.zipf(v)
            for proc, m in F.PROCS:
                if all((proc, str(m), str(v), str(k)) in done for k in (1, 2, 3, 4)):
                    continue
                base = 100000 * SEED + 1000 * m + F.VOCABS.index(v) * 10 + (0 if proc == "iid" else 1)
                tr = lines(F.simulate(N, p, m, base + 1)); te = lines(F.simulate(F.N_TEST, p, m, base + 2))
                va = lines(F.simulate(N_VAL, p, m, base + 3))
                orc = O.oracle_losses(proc, m, v, L, SEED)
                for k in (1, 2, 3, 4):
                    if (proc, str(m), str(v), str(k)) in done:
                        continue
                    r = NN.estimate(tr, va, te, v, k)
                    ref = F.h_ref(p, k, m, L)
                    wr.writerow({"estimator": "ffnn", "proc": proc, "m": m, "vocab": v, "n_train": tr.size, "line": L, "seed": SEED, "k": k,
                                 "h_ref": round(ref, 5), "h_est": round(r["test_bits"], 5), "bias": round(r["test_bits"] - ref, 5),
                                 "oracle_loss": round(orc[k], 5), "fit_minus_oracle": round(r["test_bits"] - orc[k], 5),
                                 "val_bits": round(r["val_bits"], 5), "steps": r["steps"], "seconds": r["seconds"], "device": r["device"],
                                 "settings": ";".join(f"{a}={b}" for a, b in r["settings"].items())})
                    f.flush()
                    print(f"{proc}{m} V={v} k={k}: est {r['test_bits']:.4f} ref {ref:.4f} bias {r['test_bits'] - ref:+.4f} ({r['seconds']}s)", flush=True)
    print("done", flush=True)

if __name__ == "__main__":
    main()
