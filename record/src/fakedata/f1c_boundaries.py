"""F1c: word-boundary rungs on stationary uniform copy/reset text with exact truth.

Word lengths are iid uniform on 1, 2, 3, 4. Word starts are independent uniform
syllables; a continuation copies the previous syllable with probability 0.7,
otherwise draws uniformly. Artificial lines slice the stationary stream and keep
the true flags, including continuations at a line start. No linguistic data.
Usage: python -I src/fakedata/f1c_boundaries.py {kenlm|neural} OUT.tsv [options]
"""
import argparse, csv, hashlib, importlib.util, json, math, os, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
R = load("rungs", HERE.parent / "stage5" / "rungs.py")
P = load("f1c_provenance", HERE / "f1c_provenance.py")
LENGTHS = np.array([0.25, 0.25, 0.25, 0.25])
EPS = 0.3
SURV = np.cumsum(LENGTHS[::-1])[::-1]
AGE = SURV / SURV.sum()
HAZARD = LENGTHS / SURV
ALPHA = 1 / SURV.sum()

def h_binary(p):
    p = np.asarray(p, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(p > 0, -p * np.log2(p), 0) + np.where(p < 1, -(1 - p) * np.log2(1 - p), 0)

def h_row(vocab, copy):
    """Entropy of one uniform copy/reset transition row, without an inventory-sized matrix."""
    same, other = copy + (1 - copy) / vocab, (1 - copy) / vocab
    return -same * math.log2(same) - (vocab - 1) * other * math.log2(other)

def patterns(k):
    """Enumerate equality patterns, sufficient for an exchangeable uniform inventory."""
    if k == 0:
        return [()]
    out = [(0,)]
    for _ in range(k - 1):
        out = [x + (j,) for x in out for j in range(max(x) + 2)]
    return out

def pattern_code(x):
    return sum(int(x[i] == x[j]) << n for n, (i, j) in enumerate(
        (i, j) for i in range(len(x)) for j in range(i + 1, len(x))))

def history_boundary(history, vocab):
    """Return P(history), P(next word-initial | history) by a four-age forward filter."""
    if not history:
        return 1.0, ALPHA
    mass = AGE / vocab
    for a, b in zip(history[:-1], history[1:]):
        new = np.zeros(4)
        new[0] = np.dot(mass, HAZARD) / vocab
        same = (1 - EPS) * (a == b) + EPS / vocab
        new[1:] = mass[:-1] * (1 - HAZARD[:-1]) * same
        mass = new
    return float(mass.sum()), float(np.dot(mass, HAZARD) / mass.sum())

def boundary_table(vocab, k):
    table = {}
    entropy = probability = 0.0
    for h in patterns(k):
        distinct = max(h) + 1 if h else 0
        if distinct > vocab:
            continue
        multiplicity = math.prod(range(vocab - distinct + 1, vocab + 1))
        ph, pb = history_boundary(h, vocab)
        table[pattern_code(h)] = pb
        probability += multiplicity * ph
        entropy += multiplicity * ph * float(h_binary(pb))
    if not math.isclose(probability, 1, abs_tol=1e-12):
        raise AssertionError(f"history mass {probability}")
    return table, entropy

def truth(vocab, rung, treatment, line, n=None):
    """Population entropy at the context actually available, averaged over line positions."""
    k, _, _ = R.convention(rung)
    h0, hc = math.log2(vocab), h_row(vocab, 1 - EPS)
    hf = ALPHA * h0 + (1 - ALPHA) * hc
    if rung == "0":
        return h0
    values = [h0 + float(h_binary(ALPHA)) if rung.endswith("charged") else h0]
    for c in range(1, k + 1):
        if rung == "1":
            values.append(h_row(vocab, (1 - ALPHA) * (1 - EPS)))
        elif rung.endswith("charged"):
            values.append(hf + boundary_table(vocab, c)[1])
        else:
            values.append(hf)
    n = n or line * 1000
    pos = np.arange(n) % line if treatment == "bounded" else np.arange(n)
    return float(np.asarray(values)[np.minimum(k, pos)].mean())

def quantities(vocab):
    """True stationary first-order entropies and both conditional and marginal boundary contrasts."""
    h0 = math.log2(vocab)
    hf = ALPHA * h0 + (1 - ALPHA) * h_row(vocab, 1 - EPS)
    h1 = h_row(vocab, (1 - ALPHA) * (1 - EPS))
    hj = hf + float(h_binary(ALPHA))
    return dict(h_s=h0, h_within=hf, h_prev=h1, h_free=hf, h_charged=hj,
                i_s_b_given_prev=h1 - hf, h_b_given_s_prev=hj - h1,
                h_s_given_b=h0, h_s_b=h0 + float(h_binary(ALPHA)),
                i_s_b=0.0, h_b_given_s=float(h_binary(ALPHA)))

def simulate(n, vocab, line, seed):
    """Draw a stationary renewal word process; line cuts do not create word starts."""
    rng = np.random.default_rng(seed)
    first_length = rng.choice(np.arange(1, 5), p=np.arange(1, 5) * LENGTHS / SURV.sum())
    age = rng.integers(1, first_length + 1)
    residual = first_length - age + 1
    lengths = rng.choice(np.arange(1, 5), size=n, p=LENGTHS)
    boundaries = residual + np.r_[0, np.cumsum(lengths)]
    boundaries = boundaries[boundaries < n]
    b = np.zeros(n, dtype=np.int64); b[boundaries] = 1; b[0] = int(age == 1)
    fresh = (rng.random(n) < EPS) | (b == 1); fresh[0] = True
    values = rng.integers(0, vocab, size=n)
    last = np.maximum.accumulate(np.where(fresh, np.arange(n), 0))
    return R.Corpus(values[last], b, np.arange(0, n, line))

def oracle(corpus, vocab, rung, treatment):
    """Score exactly these test outcomes under their true available-context probabilities."""
    k, _, _ = R.convention(rung)
    n = len(corpus.s); pos = np.arange(n)
    starts = corpus.starts if treatment == "bounded" else np.array([0])
    have = np.minimum(k, pos - np.repeat(starts, np.diff(np.r_[starts, n])))
    same = np.r_[False, corpus.s[1:] == corpus.s[:-1]]
    if rung == "0":
        return math.log2(vocab)
    qcopy = (1 - EPS) * same + EPS / vocab
    if rung == "1":
        q = np.where(have > 0, (1 - ALPHA) * qcopy + ALPHA / vocab, 1 / vocab)
    else:
        q = np.where((have > 0) & (corpus.b == 0), qcopy, 1 / vocab)
        if rung.endswith("charged"):
            pb = np.full(n, ALPHA)
            for c in range(2, k + 1):
                mask = have == c; ix = pos[mask]
                code = np.zeros(len(ix), dtype=np.int64)
                for bit, (a, b) in enumerate((a, b) for a in range(c) for b in range(a + 1, c)):
                    code |= (corpus.s[ix - c + a] == corpus.s[ix - c + b]).astype(np.int64) << bit
                table, _ = boundary_table(vocab, c)
                lookup = np.zeros(1 << (c * (c - 1) // 2))
                for key, value in table.items():
                    lookup[key] = value
                pb[mask] = lookup[code]
            q *= np.where(corpus.b == 1, pb, 1 - pb)
    return float(-np.log2(q).mean())

FIELDS = ["code", "estimator", "vocab", "n_train", "n_test", "n_val", "line", "seed", "treatment", "rung",
          "truth", "estimate", "estimate_minus_truth", "oracle", "oracle_minus_truth", "fit_minus_oracle",
          "raw_bits", "seconds", "fallback", "discounts", "peak_directory_bytes", "free_bytes", "reserve_bytes",
          "n_scored", "oov", "settings", "val_bits", "steps", "plugin_bits", "plugin_ref", "plugin_minus_truth", "compatibility"]

def code_id():
    sources = [Path(__file__), HERE.parent / "stage5" / "rungs.py", HERE.parent / "stage5" / "nnlm.py",
               HERE / "f1c_provenance.py", HERE / "f1c_complete.py", HERE / "f1c_summary.py",
               HERE.parent / "stage5" / "f1c_reservation.json", HERE.parent / "stage5" / "disk_space.py", HERE.parent / "stage5" / "iterables.py"]
    return hashlib.sha256(b"".join(p.read_bytes() for p in sources)).hexdigest()[:12]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("estimator", choices=("kenlm", "neural")); p.add_argument("out")
    p.add_argument("--vocabs", type=int, nargs="+", default=[600, 2000, 10000])
    p.add_argument("--n-train", type=int, default=10_000_000)
    p.add_argument("--n-test", type=int, default=100_000); p.add_argument("--n-val", type=int, default=20000)
    p.add_argument("--line", type=int, default=40); p.add_argument("--seed", type=int, default=1)
    p.add_argument("--rungs", nargs="+", choices=R.RUNGS, default=list(R.RUNGS))
    p.add_argument("--treatments", nargs="+", choices=("bounded", "running"), default=["bounded", "running"])
    p.add_argument("--settings", default="{}", help="JSON neural overrides; CPU only")
    p.add_argument("--reserve-bytes", type=int,
                   help="override aggregate additional KenLM peak including both texts/model/temp files; covered full F1c budget defaults to measured 2.7 GB")
    args = p.parse_args(); root = Path.cwd(); out = Path(args.out).resolve()
    if not out.is_relative_to(root):
        raise ValueError("output must stay inside the working directory")
    if min(args.n_train, args.n_test, args.n_val, args.line, *args.vocabs) < 1:
        raise ValueError("positive sizes required")
    if args.reserve_bytes is not None and (args.reserve_bytes <= 0 or args.estimator != "kenlm"):
        raise ValueError("reserve-bytes must be positive and is only supported for KenLM")
    if args.estimator == "neural" and (args.n_train > 1_000_000 or max(args.vocabs) > 600):
        raise ValueError("neural checks are small-scale CPU only on this shared machine")
    settings = json.loads(args.settings)
    ident = code_id()
    P.current(ident, R.RUNGS)
    key = lambda r: tuple(str(r[x]) for x in ("compatibility", "estimator", "vocab", "n_train", "n_test", "n_val", "line", "seed", "treatment", "rung", "settings"))
    done = set()
    new = not out.exists()
    if args.estimator == "neural":
        NN = load("nnlm", HERE.parent / "stage5" / "nnlm.py")
        NN.torch.set_num_threads(1)
        if set(settings) - (set(NN.SETTINGS) | set(NN.OPTIONS)): raise ValueError("unsupported neural settings")
        settings = dict(NN.SETTINGS, **settings)
    elif settings:
        raise ValueError("KenLM settings are fixed in this F1c driver")
    saved = []; tail = None; header = FIELDS
    if out.exists():
        saved, tail, header = P.read(out, FIELDS, allow_tail=True)
        saved = P.normalize(saved, truth)
        for row in saved:
            if (row["estimator"] != args.estimator or int(row["n_train"]) != args.n_train or int(row["n_test"]) != args.n_test
                    or int(row["n_val"]) != (args.n_val if args.estimator == "neural" else 0)
                    or int(row["line"]) != args.line or int(row["seed"]) != args.seed
                    or row["settings"] != json.dumps(settings, sort_keys=True)):
                raise ValueError("existing F1c rows have incompatible settings/configuration")
        done = {key(row) for row in saved}
        if len(done) != len(saved): raise ValueError("duplicate F1c checkpoint cell")
    logs = out.parent / (out.stem + "_logs")
    work = out.parent / (out.stem + "_scratch")
    owned = (out, out.with_suffix(out.suffix + ".tmp"), logs, work)
    R.disk_guard(out, 1_000_000, owned_paths=owned)
    out.parent.mkdir(parents=True, exist_ok=True)
    logs.mkdir(exist_ok=True); work.mkdir(exist_ok=True)
    if not new and (tail is not None or header != FIELDS):
        tmp = out.with_suffix(out.suffix + ".tmp")
        with tmp.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(saved)
        os.replace(tmp, out)
    with open(out, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        if new:
            writer.writeheader()
        for v in args.vocabs:
            base = args.seed * 100000 + v * 10
            tr = simulate(args.n_train, v, args.line, base + 1)
            te = simulate(args.n_test, v, args.line, base + 2)
            va = simulate(args.n_val, v, args.line, base + 3) if args.estimator == "neural" else None
            for treatment in args.treatments:
                paired = {}
                for rung in args.rungs:
                    row = dict(code=ident, estimator=args.estimator, vocab=v, n_train=args.n_train,
                               n_test=args.n_test, n_val=args.n_val if va else 0, line=args.line,
                               seed=args.seed, treatment=treatment, rung=rung, settings=json.dumps(settings, sort_keys=True),
                               compatibility=P.family(ident, args.estimator, rung))
                    if key(row) in done:
                        continue
                    ref = truth(v, rung, treatment, args.line, args.n_test)
                    oro = oracle(te, v, rung, treatment)
                    log_path = logs / f"v{v}_{treatment}_{rung}.log"
                    if args.estimator == "kenlm":
                        if rung in paired:
                            result = dict(paired[rung])
                        else:
                            result = R.estimate(tr, te, rung, treatment, work, root, log_path,
                                                reserve=args.reserve_bytes, owned_paths=owned)
                            if R.convention(rung)[1]:
                                other = rung.replace("free", "charged") if rung.endswith("free") else rung.replace("charged", "free")
                                paired[other] = dict(result, test_bits=result["joint_bits"] if rung.endswith("free") else result["conditional_bits"])
                    else:
                        result = NN.estimate_rung(tr, va, te, v, rung, treatment, device="cpu", settings=settings)
                    est = result.pop("test_bits")
                    row.update({x: result[x] for x in FIELDS if x in result and x != "settings"})
                    row.update(truth=ref, estimate=est, estimate_minus_truth=est - ref,
                               oracle=oro, oracle_minus_truth=oro - ref, fit_minus_oracle=est - oro)
                    if args.estimator == "kenlm" and rung in ("0", "1w"):
                        hp = R.plugin(tr, rung, treatment)
                        rp = truth(v, rung, treatment, args.line, args.n_train)
                        row.update(plugin_bits=hp, plugin_ref=rp, plugin_minus_truth=hp - rp)
                    R.disk_guard(out, 1_000_000, owned_paths=owned)
                    writer.writerow(row); f.flush()
                    print(f"{args.estimator} V={v} {treatment} {rung}: {est:.5f}; minus truth {est-ref:+.5f}; minus oracle {est-oro:+.5f}; {result['seconds']}s", flush=True)
    work.rmdir()
    print(f"done: {out}", flush=True)

if __name__ == "__main__":
    main()
