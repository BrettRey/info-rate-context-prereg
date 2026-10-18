"""F2's neural subset: the production neural estimator on F2's regrouped streams.

Declared 2026-10-17 (DECISIONS.md; Brett: "yes, run it on HF"). The model is production's
(`src/stage5/nnlm.py`, `FixedContextLM`) with production's settings, passed in as JSON written from
`production.neural_settings()`. Training and test text and pooling are those of F2's KenLM cells
(`f2_conventions.py`: same seeds, same `<rare>` rule); validation text is 500k fine units from a
separate seed per process and line length. Escape bits are joined later from the matching KenLM
cells, whose pooling is the same (checked by count). Simulated data only.

Subsets (DECISIONS.md, 2026-10-17): `small` is every cell whose vocabulary stays near the F3b runs' (Sol's
process; lag 2's fine units and deletion); `timing` is one fit each of lag 2's pairs and partial merge
(vocabularies of about 222k and 65k), timed with their GPU memory, so the rest can be costed for Brett;
`merge` is lag 2's partial merge, every line length, seed and k (Brett chose it from the costed options,
2026-10-17; lag 2's pairs aren't run).

Usage: python -I -B src/fakedata/f2_neural.py OUT_TSV SETTINGS_JSON --device {cuda,mps,cpu} [--subset all|small|timing|merge] [--small]
"""
import argparse, csv, hashlib, importlib.util, json, os, sys, time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import f2_conventions as F  # noqa: E402

_spec = importlib.util.spec_from_file_location("f2_nnlm", HERE.parent / "stage5" / "nnlm.py")
NN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NN)
import torch  # noqa: E402

PROCS = ("sol", "lag2")
BUDGET = 8_000_000
N_VAL = 500_000
KS = (1, 2, 4)
CODE_ID = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
# Earlier versions of this file whose rows a resumed run keeps: they differ from this one only in which cells a
# subset selects, not in how a fit is made.
SAME_FITS = {CODE_ID, "e11d841436c6"}
NN_CODE = hashlib.sha256((HERE.parent / "stage5" / "nnlm.py").read_bytes()).hexdigest()[:12]
FIELDS = ["code", "f2_code", "nn_code", "settings_sha256", "proc", "R", "line", "budget", "seed", "k", "n_train",
          "n_val", "n_test", "n_fine_test", "vocab", "n_pooled_val", "n_pooled_test", "test_bits", "val_bits",
          "n_scored", "best_step", "steps", "epochs", "stopped_early", "seconds", "device", "peak_gpu_mb", "error"]


class Corpus:
    """Flat unit ids and line starts (no word flags), as the production estimator reads them."""

    def __init__(self, ids, line_id):
        self.s = np.asarray(ids, dtype=np.int64)
        self.b = np.zeros_like(self.s)
        self.starts = np.flatnonzero(np.r_[True, np.diff(line_id) != 0]).astype(np.int64)


def val_seed(name, line):
    return F.seeds_for(name, line)["test"] + 5000


def build(name, line, seed, R, budget, n_val, n_test):
    """Training, validation and test corpora for one cell, pooled as F2's KenLM cells pool."""
    pr = F.process(name)
    A, D = F.classes(name, len(pr["p"]))
    cls = A if R == "R2" else D
    seeds = F.seeds_for(name, line)
    train = F.regroup(F.simulate(max(F.BUDGETS) if budget == BUDGET else budget, pr["p"], pr["m"], pr["eps"],
                                 seeds["train"](seed))[:budget], line, R, cls)
    val = F.regroup(F.simulate(n_val, pr["p"], pr["m"], pr["eps"], val_seed(name, line)), line, R, cls)
    test = F.regroup(F.simulate(n_test, pr["p"], pr["m"], pr["eps"], seeds["test"]), line, R, cls)
    toks = {split: F.tokens(u) for split, u in (("train", train), ("val", val), ("test", test))}
    counts = Counter(toks["train"])
    kept = sorted(t for t, n in counts.items() if n > 1)
    ids = {t: i for i, t in enumerate(kept)}
    rare = len(kept) if len(kept) < len(counts) else None
    vocab = len(kept) + (rare is not None)
    def encode(split):
        out = [ids.get(t, rare) for t in toks[split]]
        if rare is None and any(v is None for v in out):
            raise RuntimeError(f"{name} {R} L{line} s{seed}: unseen {split} units but no pooled symbol in training")
        return np.array(out, dtype=np.int64)
    enc = {split: encode(split) for split in toks}
    corpora = {split: Corpus(enc[split], u["line_id"]) for split, u in (("train", train), ("val", val), ("test", test))}
    pooled = {split: int((enc[split] == rare).sum()) if rare is not None else 0 for split in ("val", "test")}
    return corpora, vocab, pooled, test["n_fine"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("settings")
    ap.add_argument("--device", required=True, choices=("cuda", "mps", "cpu"))
    ap.add_argument("--small", action="store_true", help="CPU smoke test: tiny sizes, one cell")
    ap.add_argument("--subset", default="all", choices=("all", "small", "timing", "merge"))
    a = ap.parse_args()
    settings_bytes = Path(a.settings).read_bytes()
    settings = json.loads(settings_bytes)
    settings_sha = hashlib.sha256(settings_bytes).hexdigest()[:16]
    if a.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA requested but unavailable")
    torch.set_num_threads(1)
    budget, n_val, n_test = (BUDGET, N_VAL, F.N_TEST) if not a.small else (32_000, 4_000, 8_000)
    if a.small:
        settings = dict(settings, dim=8, hidden=16, max_epochs=1)
    cells = [(n, L, s, R) for n in PROCS for L in F.LINES for s in F.SEEDS for R in F.regroupings_for(n)]
    ks = KS
    if a.subset == "small":
        cells = [c for c in cells if c[0] == "sol" or c[3] in ("R0", "R3")]
    elif a.subset == "timing":
        cells, ks = [("lag2", 1000, 1, "R1"), ("lag2", 1000, 1, "R2")], (1,)
    elif a.subset == "merge":
        cells = [c for c in cells if c[0] == "lag2" and c[3] == "R2"]
    if a.small:
        cells = cells[:2]
    done = set()
    if os.path.exists(a.out):
        for r in csv.DictReader(open(a.out), delimiter="\t"):
            if r["code"] in SAME_FITS and r["settings_sha256"] == settings_sha and not r["error"]:
                done.add((r["proc"], r["R"], int(r["line"]), int(r["seed"]), int(r["k"])))
    new = not os.path.exists(a.out)
    with open(a.out, "a", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        if new:
            wr.writeheader(); f.flush()
        for name, line, seed, R in cells:
            if all((name, R, line, seed, k) in done for k in ks):
                continue
            corpora, vocab, pooled, n_fine = build(name, line, seed, R, budget, n_val, n_test)
            for k in ks:
                if (name, R, line, seed, k) in done:
                    continue
                t0 = time.time()
                if a.device == "cuda":
                    torch.cuda.reset_peak_memory_stats()
                base = dict(code=CODE_ID, f2_code=F.CODE_ID, nn_code=NN_CODE, settings_sha256=settings_sha,
                            proc=name, R=R, line=line, budget=budget, seed=seed, k=k, vocab=vocab,
                            n_train=len(corpora["train"].s), n_val=len(corpora["val"].s),
                            n_test=len(corpora["test"].s), n_fine_test=n_fine, device=a.device)
                try:
                    res = NN.estimate(corpora["train"], corpora["val"], corpora["test"], vocab, k, device=a.device,
                                      settings=settings)
                except torch.OutOfMemoryError as e:  # recorded, so the timing fits can say what memory they need
                    wr.writerow(dict(base, seconds=round(time.time() - t0, 1), error=f"out of memory: {str(e)[:160]}",
                                     peak_gpu_mb=round(torch.cuda.max_memory_allocated() / 2**20) if a.device == "cuda" else ""))
                    f.flush(); os.fsync(f.fileno())
                    print(f"{name} {R} L{line} s{seed} k={k}: out of memory after {time.time() - t0:.0f} s", flush=True)
                    torch.cuda.empty_cache()
                    continue
                if res["n_scored"] != len(corpora["test"].s):
                    raise RuntimeError("the estimator scored a different number of test units")
                wr.writerow(dict(code=CODE_ID, f2_code=F.CODE_ID, nn_code=NN_CODE, settings_sha256=settings_sha,
                                 proc=name, R=R, line=line, budget=budget, seed=seed, k=k,
                                 n_train=len(corpora["train"].s), n_val=len(corpora["val"].s),
                                 n_test=len(corpora["test"].s), n_fine_test=n_fine, vocab=vocab,
                                 n_pooled_val=pooled["val"], n_pooled_test=pooled["test"],
                                 test_bits=round(res["test_bits"], 6), val_bits=round(res["val_bits"], 6),
                                 n_scored=res["n_scored"], best_step=res["best_step"], steps=res["steps"],
                                 epochs=res["epochs"], stopped_early=res["stopped_early"],
                                 seconds=round(time.time() - t0, 1), device=res["device"], error="",
                                 peak_gpu_mb=round(torch.cuda.max_memory_allocated() / 2**20) if a.device == "cuda" else ""))
                f.flush(); os.fsync(f.fileno())
                print(f"{name} {R} L{line} s{seed} k={k}: {res['test_bits']:.4f} bits/unit, "
                      f"best step {res['best_step']}/{res['steps']}, {time.time() - t0:.0f} s", flush=True)
                if a.device == "cuda":
                    torch.cuda.empty_cache()
            del corpora
    print("done", flush=True)


if __name__ == "__main__":
    main()
