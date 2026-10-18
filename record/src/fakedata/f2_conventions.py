"""F2: fake-data check of the matched-count correction under regrouping.

Declared 2026-10-17 (notes/f2-declaration-draft-2026-10-14.md; DECISIONS.md). Fine units come from
lag-m copy chains: token t copies token t - m with probability 1 - eps, else it is a fresh draw from
p (m = 0 is independent draws). Each regrouping is applied inside each line to the same fine
material: R0 the fine units, R1 consecutive pairs, R2 a unit of class A absorbs the next unit, R3
units of class D are deleted. KenLM is trained and scored on each stream as in production
(normalised, held out). The oracle is the exact probability of each test unit under the source
process given exactly the context KenLM sees: the previous min(k, j) units of its line, and the
line start when j < k. No linguistic data.

Unseen units are handled as production handles unseen syllables under Brett's OOV rule: a unit
seen once in a cell's training text, and a test unit outside the rest, become the pooled symbol
`<rare>` (secondary analysis); escape coding (main analysis) adds the bits to spell the original
unit with production's spelling model, each coarse unit spelled from its fine units.

The 4M budget is the first half of the 8M training text (nested, as budgets are in production).

Usage: python -I src/fakedata/f2_conventions.py WORKDIR OUT_DIR {oracle|grid|summary|mc|smoke} [WORKERS]
"""
import csv, hashlib, importlib.util, json, math, os, subprocess, sys, time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import f1v2 as V2  # noqa: E402  (KenLM training and production-style scoring)

CODE_ID = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
LINES = (16, 1000)
BUDGETS = (4_000_000, 8_000_000)
SEEDS = (1, 2, 3)
N_TEST = 1_000_000
FINE_ORDERS = range(1, 7)       # k = 0..5 on fine units (this KenLM build loads orders up to 6)
COARSE_ORDERS = range(1, 6)     # k = 0..4 on coarse units
REGROUPINGS = ("R0", "R1", "R2", "R3")
SORT_MEMORY = "1G"

# Status codes for the last m fine positions in the oracle's forward pass.
V0, V1, H0, H1 = 0, 1, 2, 3     # most recent visible, second most recent visible, hidden not-in-class, hidden in-class


# ---------------------------------------------------------------- processes and classes

def process(name):
    """Inventory p, lag m and fresh-draw probability eps for each declared process."""
    if name == "sol":
        return dict(p=np.array([0.5, 0.5]), m=2, eps=0.2)
    p = V2.zipf(2000)
    return {"iid": dict(p=p, m=0, eps=1.0), "lag1": dict(p=p, m=1, eps=0.3), "lag2": dict(p=p, m=2, eps=0.3)}[name]


PROCESS_NAMES = ("sol", "iid", "lag1", "lag2")


def classes(name, v):
    """Class A (absorbs the next unit, R2) and class D (deleted, R3) as boolean masks over types."""
    rank = np.arange(1, v + 1)
    if name == "sol":
        return rank == 2, None              # type 1 absorbs the next unit; no deletion on Sol's process
    return rank % 5 == 0, rank % 10 == 0


def regroupings_for(name):
    return ("R0", "R1", "R2") if name == "sol" else REGROUPINGS


def simulate(n, p, m, eps, seed):
    """F1's copy-chain simulation with eps as a parameter; each chain is stationary from its first token."""
    rng = np.random.default_rng(seed)
    if m == 0:
        return rng.choice(len(p), size=n, p=p)
    out = np.empty(n, dtype=np.int64)
    for r in range(m):
        size = len(range(r, n, m))
        fresh = rng.random(size) < eps
        fresh[0] = True
        vals = rng.choice(len(p), size=size, p=p)
        idx = np.where(fresh, np.arange(size), 0)
        out[r::m] = vals[np.maximum.accumulate(idx)]
    return out


# ---------------------------------------------------------------- regroupings

def regroup(x, line, R, cls):
    """Coarse units of the fine stream x, cut into lines of `line` units, inside each line.

    Returns a dict of arrays: a (first fine id), b (second fine id or -1), start (fine position of
    the unit's first fine unit), j (index of the unit within its line) and n_fine.
    """
    n = (len(x) // line) * line
    x = x[:n]
    pos = np.arange(n)
    if R == "R0":
        start = pos
    elif R == "R1":
        if line % 2:
            raise ValueError("pairs need an even line length")
        start = pos[::2]
    elif R == "R2":
        a_mask = cls[x]
        line_first = pos - pos % line
        last_out = np.maximum.accumulate(np.where(~a_mask, pos, -1))
        run_end = pos - np.maximum(last_out, line_first - 1)      # class-A run ending at t, within the line
        before = np.zeros(n, dtype=np.int64)
        before[1:] = run_end[:-1]
        before[pos % line == 0] = 0
        start = pos[before % 2 == 0]                               # unit boundaries
    elif R == "R3":
        start = pos[~cls[x]]
    else:
        raise ValueError(R)
    a = x[start]
    b = np.full(len(start), -1, dtype=np.int64)
    if R == "R1":
        b = x[start + 1]
    elif R == "R2":
        two = cls[a] & (start % line < line - 1)
        b[two] = x[start[two] + 1]
    line_id = start // line
    first = np.searchsorted(line_id, line_id, side="left")
    j = np.arange(len(start)) - first
    return dict(a=a, b=b, start=start, j=j, line_id=line_id, n_fine=n)


def tokens(units):
    a, b = units["a"], units["b"]
    return [f"s{p}" if q < 0 else f"s{p}_{q}" for p, q in zip(a.tolist(), b.tolist())]


def spellings(units):
    """Each unit's label for escape coding: one character per fine unit (its 'segments')."""
    return [chr(0x4E00 + p) + ("" if q < 0 else chr(0x4E00 + q)) for p, q in zip(units["a"].tolist(), units["b"].tolist())]


def write_units(path, units, toks=None):
    """One text line per fine line that keeps at least one unit."""
    toks = tokens(units) if toks is None else toks
    cut = np.flatnonzero(np.diff(units["line_id"])) + 1
    with open(path, "w") as f:
        for lo, hi in zip(np.r_[0, cut], np.r_[cut, len(toks)]):
            f.write(" ".join(toks[lo:hi]) + "\n")


# ---------------------------------------------------------------- oracle

def boundary_joint(m, eps, pc1, line):
    """J[b, c] = P(position b of a line is a unit boundary, and the classes of b-1 .. b-m are c), for R2.

    The line starts at stationarity with a boundary at b = 0. The chain runs over (c_{t-1}, ...,
    c_{t-m}, beta_t); the unit at a boundary t absorbs t + 1 when x_t is in class A, so beta_{t+1}
    = 0 exactly when beta_t = 1 and c_t = 1. For m = 0, J has one column, P(boundary at b).
    """
    configs = list(np.ndindex(*(2,) * m))
    states = [(cs, beta) for cs in configs for beta in (0, 1)]
    index = {st: i for i, st in enumerate(states)}
    T = np.zeros((len(states), len(states)))
    for (cs, beta), i in index.items():
        p1 = ((1 - eps) * cs[m - 1] + eps * pc1) if m else pc1
        for c, pr in ((1, p1), (0, 1 - p1)):
            T[i, index[(((c,) + cs[:-1]) if m else (), 0 if (beta == 1 and c == 1) else 1)]] += pr
    dist = np.zeros(len(states))
    for cs in configs:
        dist[index[(cs, 1)]] = np.prod([pc1 if c else 1 - pc1 for c in cs])
    J = np.empty((line, len(configs)))
    for b in range(line):
        J[b] = [dist[index[(cs, 1)]] for cs in configs]
        dist = dist @ T
    return J


def point_prior(m, config):
    """A prior putting all its mass on one class configuration of the m positions before the window."""
    prior = np.zeros((2,) * m)
    prior[config] = 1.0
    return prior


def free_prior(m, pc1):
    """Stationary classes of the m positions before t with no conditioning (independent chains)."""
    if m == 0:
        return np.ones(())
    one = np.array([1 - pc1, pc1])
    return one if m == 1 else np.outer(one, one)


class Forward:
    """Exact forward pass over the hidden statuses of the last m fine positions.

    A visible fine unit's probability depends on its classmate (the unit m positions back): a
    visible classmate s gives (1 - eps)[y = s] + eps p(y); a hidden one of class c gives
    (1 - eps) p(y)[y in c] / p(c) + eps p(y). Deleted units (R3) are hidden members of class D and
    are emitted silently; the closure over any number of deletions is a constant matrix because
    the chance of a deletion depends only on the classmate's status.
    """

    def __init__(self, p, m, eps, cls, deletion):
        self.p, self.m, self.eps, self.deletion = p, m, eps, deletion
        self.cls = np.zeros(len(p), dtype=bool) if cls is None else cls
        self.pc = np.array([p[~self.cls].sum(), p[self.cls].sum()])
        if m == 0:
            return
        S = 16 if m == 2 else 4
        self.S = S
        self.mate = np.array([s % 4 for s in range(S)]) if m == 2 else np.arange(S)
        first = np.array([s // 4 for s in range(S)]) if m == 2 else np.arange(S)
        self.emit_next = np.where(first == V0, V1, first) if m == 2 else np.zeros(S, dtype=int)
        if m == 2:
            self.emit_next = 4 * V0 + self.emit_next
        pD = self.pc[1] if deletion else 0.0
        q = {V0: eps * pD, V1: eps * pD, H0: eps * pD, H1: (1 - eps) + eps * pD}
        self.q = np.array([q[c] for c in self.mate]) if deletion else np.zeros(S)
        Dm = np.zeros((S, S))
        if deletion:
            for s in range(S):
                Dm[s, 4 * H1 + first[s] if m == 2 else H1] += self.q[s]
        self.closure = np.linalg.inv(np.eye(S) - Dm)

    def start(self, prior, N):
        alpha = np.zeros((N, self.S))
        if self.m == 1:
            alpha[:, H0], alpha[:, H1] = prior[0], prior[1]
        else:
            for c1 in (0, 1):
                for c2 in (0, 1):
                    alpha[:, 4 * (H0 + c1) + (H0 + c2)] = prior[c1, c2]
        return alpha

    def logp(self, obs, n_target, prior, silent_first, silent_between, chunk=200_000, window=False):
        """log2 P(the last n_target columns of obs | the earlier columns), per row (in chunks, to bound memory).

        With window=True, also log2 P(the earlier columns) under the prior: (window, target).
        """
        if len(obs) > chunk:
            parts = [self.logp(obs[i:i + chunk], n_target, prior, silent_first, silent_between, chunk, window)
                     for i in range(0, len(obs), chunk)]
            return tuple(np.concatenate(z) for z in zip(*parts)) if window else np.concatenate(parts)
        N, L = obs.shape
        p, eps = self.p, self.eps
        if self.m == 0:
            norm = (1 - self.pc[1]) if self.deletion else 1.0
            target = np.log2(p[obs[:, L - n_target:]] / norm).sum(1)
            return (np.log2(p[obs[:, :L - n_target]] / norm).sum(1), target) if window else target
        alpha = self.start(prior, N)
        out = np.zeros(N)
        before = np.zeros(N)
        for t in range(L):
            if (t == 0 and silent_first) or (t > 0 and silent_between):
                alpha = alpha @ self.closure
            y = obs[:, t]
            py = p[y]
            cy = self.cls[y]
            es = np.zeros((N, 4))
            if t >= 1:
                es[:, V0] = (1 - eps) * (y == obs[:, t - 1]) + eps * py
            if t >= 2:
                es[:, V1] = (1 - eps) * (y == obs[:, t - 2]) + eps * py
            es[:, H0] = (1 - eps) * py * (~cy) / self.pc[0] + eps * py
            if self.pc[1] > 0:
                es[:, H1] = (1 - eps) * py * cy / self.pc[1] + eps * py
            w = alpha * es[:, self.mate]
            z = w.sum(1)
            zt = z
            if t == 0 and not silent_first and self.deletion:
                zt = z / (alpha * (1 - self.q)[None, :]).sum(1)     # the first unit is known to be a survivor
            if t >= L - n_target:
                out += np.log2(zt)
            else:
                before += np.log2(zt)
            nxt = np.zeros_like(alpha)
            for s in range(self.S):
                nxt[:, self.emit_next[s]] += w[:, s]
            alpha = nxt / z[:, None]
        return (before, out) if window else out


def r2_mixture(fw, m, eps, pc1, line, x, a, b, start, wvis, tlen, cls, rows_all):
    """Exact bits for R2 units whose context doesn't show the line start.

    The window (w fine units) may start at any boundary b with b + w at most the line's last
    position. P(window, unit) is summed over those b, each weighted by the exact joint probability
    of a boundary at b and each class configuration of the m positions before it (`boundary_joint`);
    the window's likelihood under each configuration comes from the forward pass. A class-A unit
    stands alone only at the line's last position, and a merged unit can't start there.
    """
    J = boundary_joint(m, eps, pc1, line)
    configs = list(np.ndindex(*(2,) * m))
    out = np.empty(len(rows_all))
    keys = np.stack([wvis[rows_all], tlen[rows_all]], 1)
    for key in np.unique(keys, axis=0):
        w_, t_ = (int(v) for v in key)
        sel = np.flatnonzero((keys == key).all(1))
        rows = rows_all[sel]
        cols = [x[start[rows] - w_ + i] for i in range(w_)] + [a[rows]] + ([b[rows]] if t_ == 2 else [])
        obs = np.stack(cols, 1)
        mid = J[:line - 1 - w_].sum(0)          # boundaries b with the unit starting before the last position
        end = J[line - 1 - w_]                  # the unit starting at the last position
        alone = cls[a[rows]] & (b[rows] < 0)
        ok_mid = ~alone                          # an A unit can't stand alone before the last position
        ok_end = np.full(len(rows), t_ == 1)     # nor can a merged unit start at it
        lw, lt = [], []
        for c in configs:
            prior = point_prior(m, c) if m else np.ones(())
            w_c, t_c = fw.logp(obs, t_, prior, False, False, window=True)
            lw.append(w_c); lt.append(t_c)
        lw, lt = np.stack(lw, 1), np.stack(lt, 1)
        top = lw.max(1, keepdims=True)
        win = 2.0 ** (lw - top)
        num = (win * 2.0 ** lt * (mid[None, :] * ok_mid[:, None] + end[None, :] * ok_end[:, None])).sum(1)
        den = (win * (mid + end)[None, :]).sum(1)
        out[sel] = -np.log2(num / den)
    return out


def oracle(name, R, line, k, units, x, cls, pr=None):
    """Exact bits for each coarse unit given the previous min(k, j) units of its line, and spans."""
    pr = process(name) if pr is None else pr
    p, m, eps = pr["p"], pr["m"], pr["eps"]
    a, b, start, j = units["a"], units["b"], units["start"], units["j"]
    G = len(a)
    g = np.arange(G)
    nw = np.minimum(k, j)
    reach = j < k
    deletion = R == "R3"
    use_cls = cls if R in ("R2", "R3") else None
    fw = Forward(p, m, eps, use_cls, deletion)
    pc1 = fw.pc[1]
    bits = np.empty(G)
    span = start - start[g - nw]
    if not deletion:
        wvis = span
        tlen = 1 + (b >= 0)
        if m == 0:
            full = np.ones(G, dtype=bool)
            pa, pb = p[a], np.where(b >= 0, p[np.maximum(b, 0)], 1.0)
        else:
            full = wvis >= m
        if m > 0:
            mate1 = x[np.maximum(start - m, 0)]
            pa = (1 - eps) * (a == mate1) + eps * p[a]
            mate2 = a if m == 1 else x[np.maximum(start - 1, 0)]
            bb = np.maximum(b, 0)
            pb = np.where(b >= 0, (1 - eps) * (bb == mate2) + eps * p[bb], 1.0)
        bits[full] = -np.log2(pa[full] * pb[full])
        free = free_prior(m, pc1)
        mixed = ~reach if R == "R2" else np.zeros(G, dtype=bool)
        rest = np.flatnonzero(~full & ~mixed)
        keys = np.stack([wvis[rest], tlen[rest]], 1)
        for key in np.unique(keys, axis=0):
            w_, t_ = (int(v) for v in key)
            rows = rest[(keys == key).all(1)]
            cols = [x[start[rows] - w_ + i] for i in range(w_)] + [a[rows]] + ([b[rows]] if t_ == 2 else [])
            bits[rows] = -fw.logp(np.stack(cols, 1), t_, free, False, False)
        if mixed.any():
            bits[mixed] = r2_mixture(fw, m, eps, pc1, line, x, a, b, start, wvis, tlen, cls, np.flatnonzero(mixed))
        return bits, span
    free = free_prior(m, pc1)
    for key in np.unique(np.stack([nw, reach], 1), axis=0):
        n_, r_ = (int(v) for v in key)
        rows = g[(nw == n_) & (reach == bool(r_))]
        obs = np.stack([a[rows - n_ + i] for i in range(n_ + 1)], 1)
        bits[rows] = -fw.logp(obs, 1, free, bool(r_), True)
    return bits, span


# ---------------------------------------------------------------- KenLM

_ESCAPE = {}


def escape_module():
    """Production's escape coding (`src/stage4/escape.py`): its pooled symbol and spelling model."""
    if "E" not in _ESCAPE:
        spec = importlib.util.spec_from_file_location("f2_escape", HERE.parents[1] / "src/stage4/escape.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["f2_escape"] = module
        spec.loader.exec_module(module)
        _ESCAPE["E"] = module
    return _ESCAPE["E"]


def pool(train_toks, test_toks, train_labels, test_labels):
    """Production's pooling and escape cost for one cell (Brett, 2026-10-15: "hapax is fine").

    Returns the pooled training and test tokens, the escape bits summed over the pooled test
    units, and the counts of pooled test units and training hapax types.
    """
    E = escape_module()
    POOLED = sys.modules["escape_linguistic_inputs"].POOLED
    counts = Counter(train_toks)
    kept = {t for t, n in counts.items() if n > 1}
    train_pooled = [t if t in kept else POOLED for t in train_toks]
    test_pooled = [t if t in kept else POOLED for t in test_toks]
    hapax = sorted({lab for t, lab in zip(train_toks, train_labels) if t not in kept})
    alphabet = {c for lab in set(train_labels) for c in lab}
    pooled_idx = [i for i, t in enumerate(test_pooled) if t == POOLED]
    if pooled_idx and not hapax:
        raise RuntimeError("pooled test units but no pooled symbol in training")
    spelling = E.Spelling(hapax, alphabet) if hapax else None
    escape = sum(spelling.bits(test_labels[i]) for i in pooled_idx) if pooled_idx else 0.0
    return train_pooled, test_pooled, escape, len(pooled_idx), len(hapax)


def kenlm_bits(work, train, test, order, tag):
    arpa, binm = f"{work}/{tag}.arpa", f"{work}/{tag}.bin"
    logp = f"{work}/logs/{tag}.log"
    used, secs, log = V2.lmplz(order, train, arpa, f"{work}/tmp", logp, None, sort_memory=SORT_MEMORY)
    fell, stats = V2.discounts(log)
    if order == 1:
        hr, hn, ns, oov = V2.score_unigram(arpa, test)
    else:
        subprocess.run([f"{V2.KENLM}/build_binary", arpa, binm], capture_output=True, check=True)
        hr, hn, ns, oov = V2.score_model(binm, test)
        os.remove(binm)
    os.remove(arpa)
    return dict(h_raw=hr, h_norm=hn, n_scored=ns, oov=oov, lmplz_s=round(secs, 1),
                fallback_orders=",".join(map(str, fell)) if used else "")


# ---------------------------------------------------------------- stages

def seeds_for(name, line):
    i, L = PROCESS_NAMES.index(name), LINES.index(line)
    return dict(test=990_000 + 10 * i + L, train=lambda s: 100_000 * s + 10 * i + L)


def test_path(work, name, line, R):
    return f"{work}/test/{name}_L{line}_{R}.txt"


ORACLE_FIELDS = ["code", "proc", "R", "line", "k", "n_coarse", "n_fine", "bits_per_coarse", "corrected",
                 "span_mean", "span_q10", "span_q50", "span_q90", "share_line_start"]


def run_oracle(work, out_dir, names=PROCESS_NAMES, lines=LINES):
    """Write each regrouped test set and its oracle, once per process and line length."""
    os.makedirs(f"{work}/test", exist_ok=True)
    rows = []
    for name in names:
        pr = process(name)
        A, D = classes(name, len(pr["p"]))
        for line in lines:
            x = simulate(N_TEST, pr["p"], pr["m"], pr["eps"], seeds_for(name, line)["test"])
            for R in regroupings_for(name):
                cls = A if R == "R2" else D
                units = regroup(x, line, R, cls)
                write_units(test_path(work, name, line, R), units)
                for k in (range(len(FINE_ORDERS)) if R == "R0" else range(len(COARSE_ORDERS))):
                    bits, span = oracle(name, R, line, k, units, x, cls)
                    q = np.quantile(span, [0.1, 0.5, 0.9])
                    rows.append(dict(code=CODE_ID, proc=name, R=R, line=line, k=k, n_coarse=len(bits),
                                     n_fine=units["n_fine"], bits_per_coarse=round(bits.mean(), 6),
                                     corrected=round(bits.sum() / units["n_fine"], 6),
                                     span_mean=round(span.mean(), 4), span_q10=q[0], span_q50=q[1], span_q90=q[2],
                                     share_line_start=round(float((units["j"] < k).mean()), 4)))
                print(f"oracle {name} L{line} {R} done", flush=True)
    with open(f"{out_dir}/f2_oracle.tsv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=ORACLE_FIELDS, delimiter="\t")
        wr.writeheader()
        wr.writerows(rows)


CELL_FIELDS = ["code", "proc", "R", "line", "budget", "seed", "k", "n_coarse_test", "n_fine_test", "h_raw", "h_norm",
               "corrected_escape", "corrected_pooled", "corrected_raw", "escape_bits", "n_pooled_test", "n_hapax_train",
               "n_scored", "oov", "lmplz_s", "fallback_orders"]


def cell_name(name, line, budget, seed, R):
    return f"{name}_L{line}_n{budget}_s{seed}_{R}"


def run_cell(work, out_dir, name, line, budget, seed, R):
    tag = cell_name(name, line, budget, seed, R)
    frag = Path(out_dir) / "cells" / f"{tag}.tsv"
    if frag.exists() and frag.read_text().split("\n")[1].startswith(CODE_ID):
        return tag, "skipped"
    t0 = time.time()
    pr = process(name)
    A, D = classes(name, len(pr["p"]))
    cls = A if R == "R2" else D
    cw = f"{work}/cells/{tag}"
    for d in (cw, f"{cw}/tmp", f"{cw}/logs"):
        os.makedirs(d, exist_ok=True)
    x = simulate(max(BUDGETS), pr["p"], pr["m"], pr["eps"], seeds_for(name, line)["train"](seed))[:budget]
    units = regroup(x, line, R, cls)
    xt = simulate(N_TEST, pr["p"], pr["m"], pr["eps"], seeds_for(name, line)["test"])
    tunits = regroup(xt, line, R, cls)
    test_toks = tokens(tunits)
    if Path(test_path(work, name, line, R)).read_text().split() != test_toks:
        raise RuntimeError(f"{tag}: the cell's test units differ from the ones the oracle scored")
    train_pooled, test_pooled, escape, n_pooled, n_hapax = pool(tokens(units), test_toks, spellings(units), spellings(tunits))
    train, test = f"{cw}/train.txt", f"{cw}/test.txt"
    write_units(train, units, train_pooled)
    write_units(test, tunits, test_pooled)
    n_coarse, n_fine = len(test_pooled), tunits["n_fine"]
    del x, xt, units, tunits, train_pooled, test_pooled
    rows = []
    for order in (FINE_ORDERS if R == "R0" else COARSE_ORDERS):
        r = kenlm_bits(cw, train, test, order, f"o{order}")
        if r["n_scored"] != n_coarse or r["oov"]:
            raise RuntimeError(f"{tag}: scored {r['n_scored']} of {n_coarse} test units, {r['oov']} unknown")
        rows.append(dict(code=CODE_ID, proc=name, R=R, line=line, budget=budget, seed=seed, k=order - 1,
                         n_coarse_test=n_coarse, n_fine_test=n_fine, h_raw=round(r["h_raw"], 6),
                         h_norm=round(r["h_norm"], 6),
                         corrected_escape=round((r["h_norm"] * n_coarse + escape) / n_fine, 6),
                         corrected_pooled=round(r["h_norm"] * n_coarse / n_fine, 6),
                         corrected_raw=round(r["h_raw"] * n_coarse / n_fine, 6), escape_bits=round(escape, 3),
                         n_pooled_test=n_pooled, n_hapax_train=n_hapax, n_scored=r["n_scored"],
                         oov=r["oov"], lmplz_s=r["lmplz_s"], fallback_orders=r["fallback_orders"]))
    os.remove(train); os.remove(test)
    frag.parent.mkdir(parents=True, exist_ok=True)
    tmp = frag.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=CELL_FIELDS, delimiter="\t")
        wr.writeheader()
        wr.writerows(rows)
    os.replace(tmp, frag)
    return tag, f"{time.time() - t0:.0f} s"


def grid(names=PROCESS_NAMES, lines=LINES, budgets=BUDGETS, seeds=SEEDS):
    return [(n, L, b, s, R) for n in names for L in lines for b in budgets for s in seeds for R in regroupings_for(n)]


def consistency_check(work):
    """F1's check with a small sort buffer: the Python scorer must agree with KenLM's query tool."""
    p = V2.zipf(600)
    train, test = f"{work}/c_train.txt", f"{work}/c_test.txt"
    V2.write(train, V2.simulate(300_000, p, 1, 7), 1000)
    V2.write(test, V2.simulate(50_000, p, 1, 8), 1000)
    V2.lmplz(3, train, f"{work}/c.arpa", f"{work}/tmp", f"{work}/logs/consistency.log", sort_memory=SORT_MEMORY)
    subprocess.run([f"{V2.KENLM}/build_binary", f"{work}/c.arpa", f"{work}/c.bin"], capture_output=True, check=True)
    a, _, n1, _ = V2.score_model(f"{work}/c.bin", test)
    b, n2 = V2.query_crossent(f"{work}/c.bin", test)
    for name in ("c_train.txt", "c_test.txt", "c.arpa", "c.bin"):
        os.remove(f"{work}/{name}")
    if abs(a - b) > 1e-6 or n1 != n2:
        raise SystemExit(f"STOP: Python scorer {a:.7f} ({n1} tokens) disagrees with query {b:.7f} ({n2} tokens)")
    print(f"consistency check passed: {a:.6f} bits, {n1} tokens", flush=True)


def run_grid(work, out_dir, workers, cells):
    for d in (f"{out_dir}/cells", f"{work}/tmp", f"{work}/logs"):
        os.makedirs(d, exist_ok=True)
    consistency_check(work)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_cell, work, out_dir, *c): c for c in cells}
        for fut in as_completed(futs):
            tag, how = fut.result()
            print(f"cell {tag}: {how}", flush=True)


# ---------------------------------------------------------------- simulation check of the oracle

def plugin_conditional(ctx, out):
    """Plug-in H(out | ctx) in bits from integer codes."""
    def h(codes):
        _, c = np.unique(codes, return_counts=True)
        q = c / c.sum()
        return -float(np.sum(q * np.log2(q)))
    joint = ctx * (int(out.max()) + 1) + out
    return h(joint) - h(ctx)


def context_codes(units, k, base):
    """One integer per coarse unit for the previous min(k, j) units of its line and the line-start flag."""
    code = units["a"] * base + (units["b"] + 1)
    G = len(code)
    j = units["j"]
    ctx = (j < k).astype(np.int64)
    for i in range(1, k + 1):
        prev = np.where(j >= i, code[np.maximum(np.arange(G) - i, 0)], -1)
        ctx = ctx * (base * base + 1) + (prev + 1)
    return ctx, code


def mc_check(n, line, ks, seed=5, v=4, m=2, eps=0.3):
    """Oracle cross-entropy minus plug-in conditional entropy on one long simulated stream, small inventory.

    A correct oracle gives a difference near zero (the KL divergence of the oracle from the truth,
    plus sampling noise); the declared approximations show up as a positive difference.
    """
    p = V2.zipf(v)
    A = np.arange(v) == 1
    D = np.arange(v) == 2
    x = simulate(n, p, m, eps, seed)
    pr = dict(p=p, m=m, eps=eps)
    out = []
    for R, cls in (("R0", None), ("R1", None), ("R2", A), ("R3", D)):
        units = regroup(x, line, R, cls)
        for k in ks:
            bits, _ = oracle("mc", R, line, k, units, x, cls, pr)
            ctx, code = context_codes(units, k, v + 1)
            hp = plugin_conditional(ctx, code)
            out.append(dict(R=R, line=line, m=m, k=k, oracle=bits.mean(), plugin=hp, diff=bits.mean() - hp))
    return out


# ---------------------------------------------------------------- summary

SUMMARY_FIELDS = ["proc", "R", "line", "budget", "k", "comparison", "k_fine", "span_mean", "n_seeds",
                  "oracle_fine", "oracle_coarse", "kenlm_fine", "kenlm_coarse", "kenlm_coarse_sd",
                  "convention", "estimator_fine", "estimator_coarse", "total", "kenlm_difference",
                  "convention_pct", "total_pct", "pooled_share_fine", "pooled_share_coarse",
                  "kenlm_fine_pooled", "kenlm_coarse_pooled", "total_pooled"]


def summarize(out_dir):
    """Join the KenLM cells with the oracle; every density in bits per fine unit."""
    oracle_rows = list(csv.DictReader(open(f"{out_dir}/f2_oracle.tsv"), delimiter="\t"))
    orc = {(r["proc"], r["R"], int(r["line"]), int(r["k"])): r for r in oracle_rows}
    cells = {}
    for frag in sorted(Path(out_dir, "cells").glob("*.tsv")):
        for r in csv.DictReader(open(frag), delimiter="\t"):
            if r["code"] != CODE_ID:
                continue
            key = (r["proc"], r["R"], int(r["line"]), int(r["budget"]), int(r["k"]))
            cells.setdefault(key, []).append((float(r["corrected_escape"]), float(r["corrected_pooled"]),
                                              int(r["n_pooled_test"]) / int(r["n_coarse_test"])))
    out = []
    for (name, R, line, budget, k), vals in sorted(cells.items()):
        if R == "R0":
            continue
        o = orc[(name, R, line, k)]
        span = float(o["span_mean"])
        coarse = np.array(vals)
        for comparison, kf in (("same_k", k), ("matched_span", int(round(span)))):
            fine = cells.get((name, "R0", line, budget, kf))
            if not fine:  # matched spans beyond the largest fine order are not reported
                continue
            fine = np.array(fine)
            of, oc = float(orc[(name, "R0", line, kf)]["corrected"]), float(o["corrected"])
            kf_mean, kc_mean = fine[:, 0].mean(), coarse[:, 0].mean()
            out.append(dict(proc=name, R=R, line=line, budget=budget, k=k, comparison=comparison, k_fine=kf,
                            span_mean=span, n_seeds=len(vals), oracle_fine=round(of, 5), oracle_coarse=round(oc, 5),
                            kenlm_fine=round(kf_mean, 5), kenlm_coarse=round(kc_mean, 5),
                            kenlm_coarse_sd=round(float(np.std(coarse[:, 0], ddof=1)), 5) if len(vals) > 1 else "",
                            convention=round(oc - of, 5), estimator_fine=round(kf_mean - of, 5),
                            estimator_coarse=round(kc_mean - oc, 5), total=round(kc_mean - of, 5),
                            kenlm_difference=round(kc_mean - kf_mean, 5),
                            convention_pct=round(100 * (oc - of) / of, 2), total_pct=round(100 * (kc_mean - of) / of, 2),
                            pooled_share_fine=round(fine[:, 2].mean(), 5), pooled_share_coarse=round(coarse[:, 2].mean(), 5),
                            kenlm_fine_pooled=round(fine[:, 1].mean(), 5), kenlm_coarse_pooled=round(coarse[:, 1].mean(), 5),
                            total_pooled=round(coarse[:, 1].mean() - of, 5)))
    with open(f"{out_dir}/f2_summary.tsv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, delimiter="\t")
        wr.writeheader()
        wr.writerows(out)
    return out


# ---------------------------------------------------------------- main

def main():
    work, out_dir, part = sys.argv[1], sys.argv[2], sys.argv[3]
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    for d in (work, f"{work}/tmp", f"{work}/logs", out_dir):
        os.makedirs(d, exist_ok=True)
    if part == "oracle":
        run_oracle(work, out_dir)
    elif part == "grid":
        run_grid(work, out_dir, workers, grid())
    elif part == "summary":
        summarize(out_dir)
    elif part == "smoke":
        run_oracle(work, out_dir, names=("lag2",), lines=(16,))
        run_grid(work, out_dir, 1, [("lag2", 16, 8_000_000, 1, "R0")])
    elif part == "mc":
        rows = []
        for m in (0, 1, 2):
            for line in (16, 1000):
                rows += mc_check(20_000_000, line, range(4), m=m)
        with open(f"{out_dir}/f2_oracle_check.tsv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=["code", "R", "line", "m", "k", "oracle", "plugin", "diff"], delimiter="\t")
            wr.writeheader()
            for r in rows:
                wr.writerow(dict(code=CODE_ID, **{k_: (round(v_, 6) if isinstance(v_, float) else v_) for k_, v_ in r.items()}))
    else:
        raise SystemExit(f"unknown part {part}")
    print("done", flush=True)


if __name__ == "__main__":
    main()
