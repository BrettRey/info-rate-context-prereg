"""Second estimator (notes/multiverse-spec.md §2.2a): a feed-forward neural model that sees exactly the
k previous syllables of the line (a Bengio-style fixed-context model).

Syllables are embedded with shared vectors; the k context embeddings are concatenated and passed
through one hidden layer plus a direct linear path; output logits are the result's dot product with
the (tied) syllable embeddings, plus a bias. Tying lets the model put probability on a syllable it has
just seen k places back, which is how it can learn dependencies that skip over intervening syllables
without having seen the whole context. The softmax is over syllables only, so the score is directly
comparable with KenLM's normalised score. Training stops early on validation text; the test set is
scored once, with the best validation checkpoint.

Settings (SETTINGS) are fixed on fake data before any real estimate. Optional tuning controls leave
the defaults unchanged; test traces require explicit tuning mode and never select a checkpoint.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage5_nnlm_iterables", _BoundaryPath(__file__).with_name("iterables.py"))
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import math, time
import numpy as np
import torch
from torch import nn

SETTINGS = dict(dim=128, hidden=512, lr=1e-3, batch=4096, max_epochs=3, evals_per_epoch=4, patience=2, seed=0)
OPTIONS = dict(schedule="none", min_lr_ratio=0.1, warmup_steps=0, plateau_patience=2,
               plateau_factor=0.5, bias_init="zero", bias_alpha=0.5, context_init="default",
               eval_initial=False, record_test=False, eval_batch=16384,
               keep_best_validation=False, eval_final=False)

class FixedContextLM(nn.Module):
    @_boundary
    def __init__(self, vocab, k, dim, hidden):
        super().__init__()
        self.vocab = vocab
        self.emb = nn.Embedding(vocab + 1, dim)            # index `vocab` is the line-start marker
        self.ff = nn.Sequential(nn.Linear(k * dim, hidden), nn.ReLU(), nn.Linear(hidden, dim))
        self.lin = nn.Linear(k * dim, dim, bias=False)
        self.bias = nn.Parameter(torch.zeros(vocab))

    @_boundary
    def forward(self, ctx):
        e = self.emb(ctx).flatten(1)
        z = self.ff(e) + self.lin(e)
        return z @ self.emb.weight[: self.vocab].T + self.bias

class RungLM(nn.Module):
    """Predict syllables with a free current flag, or joint flag/syllable outcomes."""
    @_boundary
    def __init__(self, vocab, k, dim, hidden, free=False, charged=False):
        super().__init__()
        self.vocab, self.k, self.free, self.charged = vocab, k, free, charged
        self.emb = nn.Embedding(vocab + 2, dim)  # line-start and word-start markers
        width = k * dim + (2 if free else 0)
        out = 2 * dim if charged else dim
        self.ff = nn.Sequential(nn.Linear(width, hidden), nn.ReLU(), nn.Linear(hidden, out))
        self.lin = nn.Linear(width, out, bias=False)
        self.bias = nn.Parameter(torch.zeros(2 * vocab if charged else vocab))

    @_boundary
    def forward(self, ctx):
        e = self.emb(ctx[:, :self.k]).flatten(1)
        if self.free:
            e = torch.cat((e, nn.functional.one_hot(ctx[:, -1], 2).to(e.dtype)), dim=1)
        z = self.ff(e) + self.lin(e)
        if self.charged:
            z = z.reshape(-1, 2, self.emb.embedding_dim)
            return (z @ self.emb.weight[:self.vocab].T).flatten(1) + self.bias
        return z @ self.emb.weight[:self.vocab].T + self.bias

@_boundary
def rung_contexts(corpus, vocab, rung, treatment):
    """Build exactly k plain previous syllables; only free rungs receive the current flag."""
    if treatment not in ("bounded", "running"):
        raise ValueError("treatment must be bounded or running")
    k = 0 if rung == "0" else (1 if rung.startswith("1") else int(rung[0]))
    starts = corpus.starts if treatment == "bounded" else np.array([0])
    start_at = np.repeat(starts, np.diff(np.r_[starts, len(corpus.s)]))
    pos = np.arange(len(corpus.s))
    ctx = np.full((len(pos), k), vocab, dtype=np.int64)
    for j in range(k):
        ix = pos - k + j
        keep = ix >= start_at
        ctx[keep, j] = corpus.s[ix[keep]]
    if rung == "1w":
        ctx[corpus.b == 1, 0] = vocab + 1
    if rung.endswith("free"):
        ctx = np.column_stack((ctx, corpus.b))
    tgt = corpus.s + vocab * corpus.b if rung.endswith("charged") else corpus.s
    return tgt, ctx

@_boundary(arrays=('lines',))
def contexts(lines, k, vocab):
    """lines: int array (n_lines, L). Returns (targets, contexts) with contexts padded by the start marker."""
    n, L = lines.shape
    pad = np.concatenate([np.full((n, k), vocab, dtype=np.int64), lines], axis=1)
    ctx = np.stack([pad[:, j:j + L] for j in range(k)], axis=2)       # (n, L, k): oldest first
    return lines.reshape(-1), ctx.reshape(-1, k)

@_boundary
def _loss_bits(model, tgt, ctx, device, batch=16384, return_count=False, documents=None):
    """Mean loss, optionally paired with the number of targets actually scored."""
    model.eval(); total = 0.0; n_scored = 0
    doc_losses = None
    if documents is not None:
        if (not documents or len({d['document'] for d in documents}) != len(documents)
                or any(type(d['n_tokens']) is not int or d['n_tokens'] <= 0 for d in documents)
                or sum(d['n_tokens'] for d in documents) != len(tgt)):
            raise ValueError('document target counts must partition the test targets')
        bounds = np.cumsum([d['n_tokens'] for d in documents])
        doc_losses = np.zeros(len(documents))
    with torch.no_grad():
        for i in range(0, len(tgt), batch):
            c = torch.as_tensor(ctx[i:i + batch], device=device); t = torch.as_tensor(tgt[i:i + batch], device=device)
            logits = model(c)
            total += nn.functional.cross_entropy(logits, t, reduction="sum").item()
            if doc_losses is not None:
                # Same forward pass and checkpoint. Preserve the legacy aggregate
                # summation, while retaining token losses for the document totals.
                losses = nn.functional.cross_entropy(logits, t, reduction='none').detach().cpu().numpy()
                owners = np.searchsorted(bounds, np.arange(i,i+len(t)), side='right')
                np.add.at(doc_losses, owners, losses.astype(float)/math.log(2))
            n_scored += len(t)
    model.train()
    bits = total / len(tgt) / math.log(2)
    if doc_losses is not None:
        return bits, n_scored, [dict(d,loss_sum_bits=float(loss)) for d,loss in zip(documents,doc_losses)]
    return (bits, n_scored) if return_count else bits

@_boundary(arrays=('targets',))
def initialize(model, targets, bias_init="zero", bias_alpha=0.5, context_init="default"):
    """Start at the smoothed training outcome unigram; optionally zero context logits.

    Charged rungs use joint (boundary flag, syllable) outcomes. Free rungs
    pool the syllable counts across flags; all context/flag output paths are zero.
    """
    with torch.no_grad():
        if bias_init == "unigram":
            counts = np.bincount(targets, minlength=model.bias.numel()).astype(float) + bias_alpha
            if np.any(counts <= 0):
                raise ValueError("unseen types need positive bias_alpha")
            model.bias.copy_(torch.as_tensor(np.log(counts / counts.sum()), dtype=model.bias.dtype, device=model.bias.device))
        if context_init == "zero":
            model.ff[-1].weight.zero_(); model.ff[-1].bias.zero_(); model.lin.weight.zero_()

def _settings(settings, vocab, k, tuning):
    """Validate shared fit controls, allowing the context-free rung k=0."""
    s = dict(SETTINGS, **(settings or {}))
    o = dict(OPTIONS, **s)
    if set(s) - (set(SETTINGS) | set(OPTIONS)):
        raise ValueError("unknown settings")
    if o["schedule"] not in ("none", "cosine", "plateau") or o["bias_init"] not in ("zero", "unigram") or o["context_init"] not in ("default", "zero"):
        raise ValueError("unknown schedule or initialization")
    if o["record_test"] and not tuning:
        raise ValueError("test traces require tuning=True")
    if any(s[a] < 1 for a in ("dim", "hidden", "batch", "max_epochs", "evals_per_epoch", "patience")) or k < 0 or vocab < 1:
        raise ValueError("sizes, epochs and patience must be positive")
    if o["eval_batch"] < 1 or o["bias_alpha"] < 0 or s["lr"] <= 0 or not 0 < o["min_lr_ratio"] <= 1:
        raise ValueError("invalid learning rate, evaluation batch or smoothing")
    if o["warmup_steps"] < 0 or o["plateau_patience"] < 1 or not 0 < o["plateau_factor"] < 1:
        raise ValueError("invalid schedule controls")
    if o["warmup_steps"] and o["schedule"] != "cosine":
        raise ValueError("warmup_steps requires cosine schedule")
    if o["schedule"] == "plateau" and s["patience"] <= o["plateau_patience"]:
        raise ValueError("early-stop patience must allow evaluations after a learning-rate reduction")
    return s

def _validate_splits(train, val, test, vocab):
    for split in (train, val, test):
        tokens = split.s if hasattr(split, "s") else split
        ndim = 1 if hasattr(split, "s") else 2
        if tokens.ndim != ndim or not tokens.size or not np.issubdtype(tokens.dtype, np.integer) or tokens.min() < 0 or tokens.max() >= vocab:
            raise ValueError("splits must be nonempty integer line arrays or corpora within the vocabulary")

@_boundary(arrays=('train', 'val', 'test'))
def estimate(train, val, test, vocab, k, device=None, settings=None, log=None, tuning=False, test_documents=None):
    """train/val/test: int arrays (n_lines, L). Returns dict with test bits per syllable and training record."""
    if k < 1:
        raise ValueError("context size must be positive")
    s = _settings(settings, vocab, k, tuning)
    _validate_splits(train, val, test, vocab)
    device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
    torch.manual_seed(s["seed"])
    if hasattr(train, "s"):
        # The runner has already reduced starts to effective line/document bounds.
        ttr, ctr = rung_contexts(train, vocab, str(k), "bounded")
        tva, cva = rung_contexts(val, vocab, str(k), "bounded")
        tte, cte = rung_contexts(test, vocab, str(k), "bounded")
    else:
        ttr, ctr = contexts(train, k, vocab); tva, cva = contexts(val, k, vocab); tte, cte = contexts(test, k, vocab)
    model = FixedContextLM(vocab, k, s["dim"], s["hidden"]).to(device)
    return _fit(model, ttr, ctr, tva, cva, tte, cte, device, s, k, log, test_documents)

@_boundary
def estimate_rung(train, val, test, vocab, rung, treatment, device="cpu", settings=None, log=None, tuning=False, test_documents=None):
    """Score the word-aware ladder with the same contexts and outcome costs as KenLM."""
    k = 0 if rung == "0" else (1 if rung.startswith("1") else int(rung[0]))
    s = _settings(settings, vocab, k, tuning)
    _validate_splits(train, val, test, vocab)
    torch.manual_seed(s["seed"])
    ttr, ctr = rung_contexts(train, vocab, rung, treatment)
    tva, cva = rung_contexts(val, vocab, rung, treatment)
    tte, cte = rung_contexts(test, vocab, rung, treatment)
    model = RungLM(vocab, k, s["dim"], s["hidden"], rung.endswith("free"), rung.endswith("charged")).to(device)
    return _fit(model, ttr, ctr, tva, cva, tte, cte, device, s, rung, log, test_documents)

def _fit(model, ttr, ctr, tva, cva, tte, cte, device, s, k, log, test_documents=None):
    """Shared initialization, schedules, checkpoint selection and held-out scoring."""
    o = dict(OPTIONS, **s)
    rng = np.random.default_rng(s["seed"])
    if not len(ttr) or not len(tva) or not len(tte):
        raise ValueError("nonempty splits required")
    initialize(model, ttr, o["bias_init"], o["bias_alpha"], o["context_init"])
    opt = torch.optim.Adam(model.parameters(), lr=s["lr"])
    n = len(ttr); steps_per_epoch = math.ceil(n / s["batch"]); eval_every = max(1, steps_per_epoch // s["evals_per_epoch"])
    total_steps = steps_per_epoch * s["max_epochs"]
    if o["warmup_steps"] >= total_steps:
        raise ValueError("warmup must finish before the training budget")
    best, best_state, bad, history, t0, step = float("inf"), None, 0, [], time.time(), 0
    best_step, lr_bad, lr_history, test_history, stopped_early = 0, 0, [], [], False
    validation_losses, final_evaluated = [], False
    if o["eval_initial"]:
        best = _loss_bits(model, tva, cva, device, o["eval_batch"])
        best_state = {kk: vv.detach().clone() for kk, vv in model.state_dict().items()}
        history.append((0, round(best, 5))); lr_history.append((0, s["lr"]))
        validation_losses.append((0, best))
        if o["record_test"]:
            test_history.append((0, _loss_bits(model, tte, cte, device, o["eval_batch"])))
    # Patience keeps its inherited significant-improvement anchor, independently
    # of the optional minimum-loss checkpoint. Small gains may accumulate.
    patience_best = best

    def evaluate(final=False):
        nonlocal best, best_state, best_step, patience_best, bad, lr_bad
        v = _loss_bits(model, tva, cva, device, o["eval_batch"])
        history.append((step, round(v, 5)))
        validation_losses.append((step, v))
        lr_history.append((step, opt.param_groups[0]["lr"]))
        if o["record_test"]:
            test_history.append((step, _loss_bits(model, tte, cte, device, o["eval_batch"])))
        if log: log(f"  k={k} step {step} val {v:.4f} ({time.time() - t0:.0f}s)")
        significant = v < patience_best - 1e-4
        select = v < best if o["keep_best_validation"] else significant
        if select:
            best, best_step = v, step
            best_state = {kk: vv.detach().clone() for kk, vv in model.state_dict().items()}
        # A terminal evaluation selects a checkpoint but cannot stop training
        # that has already ended or change the recorded stopping reason.
        if final:
            return
        if significant:
            patience_best, bad, lr_bad = v, 0, 0
        else:
            bad += 1; lr_bad += 1
        if o["schedule"] == "plateau" and lr_bad >= o["plateau_patience"]:
            opt.param_groups[0]["lr"] = max(s["lr"] * o["min_lr_ratio"], opt.param_groups[0]["lr"] * o["plateau_factor"])
            lr_bad = 0
    ctr_t = torch.as_tensor(ctr, device=device); ttr_t = torch.as_tensor(ttr, device=device)
    for epoch in range(s["max_epochs"]):
        perm = torch.as_tensor(rng.permutation(n), device=device)
        for b in range(steps_per_epoch):
            if o["schedule"] == "cosine":
                warm = o["warmup_steps"]
                if step < warm:
                    ratio = (step + 1) / warm
                else:
                    phase = (step - warm) / max(1, total_steps - warm - 1)
                    ratio = o["min_lr_ratio"] + (1 - o["min_lr_ratio"]) * (1 + math.cos(math.pi * phase)) / 2
                opt.param_groups[0]["lr"] = s["lr"] * ratio
            idx = perm[b * s["batch"]:(b + 1) * s["batch"]]
            loss = nn.functional.cross_entropy(model(ctr_t[idx]), ttr_t[idx])
            opt.zero_grad(); loss.backward(); opt.step(); step += 1
            if step % eval_every == 0:
                evaluate()
                if bad >= s["patience"]:
                    stopped_early = True
                    break
        if bad >= s["patience"]:
            break
    if o["eval_final"] and (not history or history[-1][0] != step):
        evaluate(final=True)
        final_evaluated = True
    model.load_state_dict(best_state)
    if test_documents is None:
        test_bits, n_scored = _loss_bits(model, tte, cte, device, o["eval_batch"], return_count=True)
    else:
        test_bits, n_scored, document_scores = _loss_bits(model, tte, cte, device, o['eval_batch'],
                                                       return_count=True, documents=test_documents)
    result = {"test_bits": test_bits, "n_scored": n_scored, "val_bits": best, "steps": step,
              "seconds": round(time.time() - t0, 1), "history": history, "settings": s, "device": device,
              "best_step": best_step, "epochs": epoch + 1, "stopped_early": stopped_early,
              "stop_reason": "validation_patience" if stopped_early else "max_epochs", "lr_history": lr_history,
              "final_evaluated": final_evaluated, "validation_losses": validation_losses}
    if test_documents is not None:
        result['test_documents'] = document_scores
    if o["record_test"]:
        result["test_history"] = test_history
    return result
