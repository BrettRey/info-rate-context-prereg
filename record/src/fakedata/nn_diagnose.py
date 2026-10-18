"""CPU controls for the neural estimator's iid loss floor, using simulated text only.

Usage: python -I src/fakedata/nn_diagnose.py OUT.json
"""
import importlib.util, json, math, os, sys, time
import numpy as np
import torch
from torch import nn

HERE = os.path.dirname(os.path.abspath(__file__))
def load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
F = load("f1v2", os.path.join(HERE, "f1v2.py"))
NN = load("nnlm_legacy", os.path.join(HERE, "..", "..", "tests", "nnlm_legacy.py"))
Original = NN.FixedContextLM

def control(vocab, k, dim, hidden, kind, counts):
    """Isolate bias, ReLU and output tying while retaining the default parameter scale."""
    model = Original(vocab, k, dim, hidden)
    if kind == "linear":
        model.ff = nn.Identity()
        model.forward = lambda c: model.lin(model.emb(c).flatten(1)) @ model.emb.weight[:vocab].T + model.bias
    if kind == "untied":
        model.out = nn.Parameter(model.emb.weight[:vocab].detach().clone())
        model.forward = lambda c: (model.ff(model.emb(c).flatten(1)) + model.lin(model.emb(c).flatten(1))) @ model.out.T + model.bias
    with torch.no_grad():
        if kind in ("zero", "unigram_zero", "bias_only", "bias_exact"):
            model.ff[-1].weight.zero_(); model.ff[-1].bias.zero_(); model.lin.weight.zero_()
        if kind in ("unigram", "unigram_zero", "bias_exact"):
            q = (counts + 0.5) / (counts.sum() + 0.5 * vocab)
            model.bias.copy_(torch.as_tensor(np.log(q), dtype=model.bias.dtype))
    if kind in ("bias_only", "bias_exact"):
        for name, param in model.named_parameters():
            param.requires_grad_(name == "bias")
    return model

def main():
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    result = {"torch": torch.__version__, "threads": 1, "seed_namespace": 3_000_000_000, "runs": [], "checks": [], "timing": []}
    for v in (20, 600):
        p = F.zipf(v); base = 3_000_000_000 + v * 100
        tr, va, te = [F.simulate(n, p, 0, base + j).reshape(-1, 1000) for j, n in enumerate((100_000, 20_000, 50_000), 1)]
        counts = np.bincount(tr.ravel(), minlength=v)
        oracle = float(-np.log2(p[te]).mean())
        cases = [("default3", "default", 3, 1e-3), ("default30", "default", 30, 1e-3),
                 ("low_lr30", "default", 30, 3e-4), ("high_lr30", "default", 30, 3e-3),
                 ("linear30", "linear", 30, 1e-3), ("untied30", "untied", 30, 1e-3),
                 ("unigram3", "unigram", 3, 1e-3), ("unigram_zero3", "unigram_zero", 3, 1e-3),
                 ("zero30", "zero", 30, 1e-3), ("bias_only30", "bias_only", 30, 1e-3),
                 ("bias_exact3", "bias_exact", 3, 1e-3)]
        for name, kind, epochs, lr in cases:
            NN.FixedContextLM = lambda v_, k_, d_, h_: control(v_, k_, d_, h_, kind, counts)
            r = NN.estimate(tr, va, te, v, 4, device="cpu", settings=dict(max_epochs=epochs, patience=999, lr=lr, seed=base + 5))
            row = {"vocab": v, "case": name, "oracle_loss": oracle, "fit_minus_oracle": r["test_bits"] - oracle,
                   "bias": r["test_bits"] - F.h_marg(p), "val_bits": r["val_bits"], "steps": r["steps"],
                   "seconds": r["seconds"], "history": r["history"]}
            result["runs"].append(row)
            print(f"V={v} {name}: gap {row['fit_minus_oracle']:+.6f}, {r['steps']} steps, {r['seconds']}s", flush=True)
        NN.FixedContextLM = Original
        tgt, ctx = NN.contexts(te, 4, v)
        exact = control(v, 4, 128, 512, "bias_exact", counts)
        q = (counts + 0.5) / (counts.sum() + 0.5 * v)
        direct = float(-np.log2(q[tgt]).mean())
        for batch in (257, 16384):
            scored = NN._loss_bits(exact, tgt, ctx, "cpu", batch=batch)
            result["checks"].append(dict(vocab=v, batch=batch, numpy_bits=direct, torch_bits=scored, difference=scored - direct))
        with torch.no_grad():
            exact.bias.copy_(torch.as_tensor(np.log(p), dtype=exact.bias.dtype))
        result["checks"].append(dict(vocab=v, population_oracle=oracle, represented_bits=NN._loss_bits(exact, tgt, ctx, "cpu")))
    for v in (600, 10000):
        p = F.zipf(v); base = 3_100_000_000 + v * 100
        tr, va, te = [F.simulate(n, p, 0, base + j).reshape(-1, 1000) for j, n in enumerate((20_000, 4000, 4000), 1)]
        t0 = time.perf_counter()
        r = NN.estimate(tr, va, te, v, 4, device="cpu", settings=dict(max_epochs=3, patience=999, seed=base + 5))
        row = dict(vocab=v, n_train=tr.size, n_val=va.size, n_test=te.size, k=4, batch=4096, steps=r["steps"], seconds=r["seconds"], wall_seconds=time.perf_counter() - t0)
        result["timing"].append(row); print("timing", row, flush=True)
    with open(sys.argv[1], "w") as f:
        json.dump(result, f, indent=2)

if __name__ == "__main__":
    main()
