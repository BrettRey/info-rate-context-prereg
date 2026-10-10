"""Second estimator (notes/multiverse-spec.md §2.2a): a feed-forward neural model that sees exactly the
k previous syllables of the line (a Bengio-style fixed-context model).

Syllables are embedded with shared vectors; the k context embeddings are concatenated and passed
through one hidden layer plus a direct linear path; output logits are the result's dot product with
the (tied) syllable embeddings, plus a bias. Tying lets the model put probability on a syllable it has
just seen k places back, which is how it can learn dependencies that skip over intervening syllables
without having seen the whole context. The softmax is over syllables only, so the score is directly
comparable with KenLM's normalised score. Training stops early on validation text; the test set is
scored once, with the best validation checkpoint.

Settings (SETTINGS) are fixed on fake data before any real estimate.
"""
import math, time
import numpy as np
import torch
from torch import nn

SETTINGS = dict(dim=128, hidden=512, lr=1e-3, batch=4096, max_epochs=3, evals_per_epoch=4, patience=2, seed=0)

class FixedContextLM(nn.Module):
    def __init__(self, vocab, k, dim, hidden):
        super().__init__()
        self.vocab = vocab
        self.emb = nn.Embedding(vocab + 1, dim)            # index `vocab` is the line-start marker
        self.ff = nn.Sequential(nn.Linear(k * dim, hidden), nn.ReLU(), nn.Linear(hidden, dim))
        self.lin = nn.Linear(k * dim, dim, bias=False)
        self.bias = nn.Parameter(torch.zeros(vocab))

    def forward(self, ctx):
        e = self.emb(ctx).flatten(1)
        z = self.ff(e) + self.lin(e)
        return z @ self.emb.weight[: self.vocab].T + self.bias

def contexts(lines, k, vocab):
    """lines: int array (n_lines, L). Returns (targets, contexts) with contexts padded by the start marker."""
    n, L = lines.shape
    pad = np.concatenate([np.full((n, k), vocab, dtype=np.int64), lines], axis=1)
    ctx = np.stack([pad[:, j:j + L] for j in range(k)], axis=2)       # (n, L, k): oldest first
    return lines.reshape(-1), ctx.reshape(-1, k)

def _loss_bits(model, tgt, ctx, device, batch=16384):
    model.eval(); total = 0.0
    with torch.no_grad():
        for i in range(0, len(tgt), batch):
            c = torch.as_tensor(ctx[i:i + batch], device=device); t = torch.as_tensor(tgt[i:i + batch], device=device)
            total += nn.functional.cross_entropy(model(c), t, reduction="sum").item()
    model.train()
    return total / len(tgt) / math.log(2)

def estimate(train, val, test, vocab, k, device=None, settings=None, log=None):
    """train/val/test: int arrays (n_lines, L). Returns dict with test bits per syllable and training record."""
    s = dict(SETTINGS, **(settings or {}))
    device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
    torch.manual_seed(s["seed"]); rng = np.random.default_rng(s["seed"])
    ttr, ctr = contexts(train, k, vocab); tva, cva = contexts(val, k, vocab); tte, cte = contexts(test, k, vocab)
    model = FixedContextLM(vocab, k, s["dim"], s["hidden"]).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=s["lr"])
    n = len(ttr); steps_per_epoch = math.ceil(n / s["batch"]); eval_every = max(1, steps_per_epoch // s["evals_per_epoch"])
    best, best_state, bad, history, t0, step = float("inf"), None, 0, [], time.time(), 0
    ctr_t = torch.as_tensor(ctr, device=device); ttr_t = torch.as_tensor(ttr, device=device)
    for epoch in range(s["max_epochs"]):
        perm = torch.as_tensor(rng.permutation(n), device=device)
        for b in range(steps_per_epoch):
            idx = perm[b * s["batch"]:(b + 1) * s["batch"]]
            loss = nn.functional.cross_entropy(model(ctr_t[idx]), ttr_t[idx])
            opt.zero_grad(); loss.backward(); opt.step(); step += 1
            if step % eval_every == 0:
                v = _loss_bits(model, tva, cva, device)
                history.append((step, round(v, 5)))
                if log: log(f"  k={k} step {step} val {v:.4f} ({time.time() - t0:.0f}s)")
                if v < best - 1e-4:
                    best, bad = v, 0
                    best_state = {kk: vv.detach().clone() for kk, vv in model.state_dict().items()}
                else:
                    bad += 1
                if bad >= s["patience"]:
                    break
        if bad >= s["patience"]:
            break
    model.load_state_dict(best_state)
    return {"test_bits": _loss_bits(model, tte, cte, device), "val_bits": best, "steps": step,
            "seconds": round(time.time() - t0, 1), "history": history, "settings": s, "device": device}
