"""F1 version 2: fake-data check of the estimator (notes/multiverse-spec.md §3a, declared 2026-10-09).

Processes with known conditional entropy: independent Zipf draws ("iid") and lag-m copy processes
(token t copies token t-m with probability 1-EPS, else a fresh Zipf draw). The reference at order k
is the entropy at the context actually available: the mean over line positions j of H_min(k, j),
because KenLM's context starts afresh at each line.

Per model: KenLM's log is kept, with the discounts it used at every order and whether each fell
back. Each test token is scored raw and normalised over syllable outcomes (its probability divided
by 1 - P(</s> | h) - P(<unk> | h)), so the cost of predicting line ends can be seen. Plug-in entropy
at k = 0 and 1 is computed on the training sample. A separate ablation varies the fallback discounts.
No linguistic data.

Usage: python -I src/fakedata/f1v2.py WORKDIR OUT_DIR {long|short|ablation}
"""
import csv, hashlib, math, os, re, subprocess, sys, time
import numpy as np
import kenlm

KENLM = os.path.expanduser("~/src/kenlm/build/bin")
EPS, ZIPF_S = 0.3, 1.1
VOCABS = (600, 2000, 10000)
PROCS = (("iid", 0), ("copy", 1), ("copy", 2), ("copy", 3), ("copy", 4))
N_TEST = 1_000_000
CODE_ID = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:12]

def zipf(v):
    p = 1.0 / np.arange(1, v + 1) ** ZIPF_S
    return p / p.sum()

def h_marg(p):
    return -float(np.sum(p * np.log2(p)))

def h_copy(p, eps):
    hp = h_marg(p)
    q = 1 - eps + eps * p
    s = eps * (math.log2(eps) - hp)
    return float(np.sum(p * (-q * np.log2(q) - s + eps * p * np.log2(eps * p))))

def h_at(p, c, m):
    """True conditional entropy given c previous tokens."""
    return h_marg(p) if (m == 0 or c < m) else h_copy(p, EPS)

def h_ref(p, k, m, line):
    return float(np.mean([h_at(p, min(k, j), m) for j in range(line)]))

def simulate(n, p, m, seed):
    rng = np.random.default_rng(seed)
    if m == 0:
        return rng.choice(len(p), size=n, p=p)
    out = np.empty(n, dtype=np.int64)
    for r in range(m):
        L = len(range(r, n, m))
        fresh = rng.random(L) < EPS
        fresh[0] = True
        vals = rng.choice(len(p), size=L, p=p)
        idx = np.where(fresh, np.arange(L), 0)
        out[r::m] = vals[np.maximum.accumulate(idx)]
    return out

def write(path, toks, line):
    n = (len(toks) // line) * line
    with open(path, "w") as f:
        for i in range(0, n, line):
            f.write(" ".join(f"s{t}" for t in toks[i:i + line]) + "\n")
    return n

def lmplz(order, train, arpa, tmp, log_path, fallback_values=None):
    """Run lmplz; on a discount failure only, retry with the fallback. Returns (fallback_used, seconds)."""
    cmd = [f"{KENLM}/lmplz", "-o", str(order), "-S", "30%", "-T", tmp]
    t0 = time.time()
    r = subprocess.run(cmd, stdin=open(train), stdout=open(arpa, "w"), stderr=subprocess.PIPE, text=True)
    log = r.stderr
    used = False
    if r.returncode != 0:
        if "BadDiscountException" not in log and "Could not calculate Kneser-Ney discounts" not in log:
            raise RuntimeError(f"lmplz failed for another reason:\n{log[-2000:]}")
        used = True
        fb = ["--discount_fallback"] + ([str(x) for x in fallback_values] if fallback_values else [])
        r2 = subprocess.run(cmd + fb, stdin=open(train), stdout=open(arpa, "w"), stderr=subprocess.PIPE, text=True)
        log = log + "\n=== retry with " + " ".join(fb) + " ===\n" + r2.stderr
        if r2.returncode != 0:
            raise RuntimeError(f"lmplz failed with the fallback:\n{r2.stderr[-2000:]}")
    with open(log_path, "w") as f:
        f.write(log)
    return used, time.time() - t0, log

def discounts(log):
    """Discounts per order from lmplz's Statistics block, and which orders fell back."""
    fell = sorted(int(x) + 1 for x in re.findall(r"Substituting fallback discounts for order (\d+)", log))
    stats = {}
    for m in re.finditer(r"^(\d+) (\d+) D1=([\d.]+) D2=([\d.]+) D3\+=([\d.]+)", log, re.M):
        stats[int(m.group(1))] = (float(m.group(3)), float(m.group(4)), float(m.group(5)))
    return fell, stats

def arpa_unigrams(arpa):
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
    return lp

def score_unigram(arpa, test):
    lp = arpa_unigrams(arpa)
    z = sum(10 ** v for w, v in lp.items() if w not in ("</s>", "<s>", "<unk>"))
    raw = norm = 0.0; n = oov = 0
    for line in open(test):
        for w in line.split():
            v = lp.get(w)
            if v is None:
                v = lp["<unk>"]; oov += 1
            raw += v; norm += v - math.log10(z); n += 1
    c = -math.log2(10) / n
    return raw * c, norm * c, n, oov

def score_model(binm, test):
    m = kenlm.Model(binm)
    raw = norm = 0.0; n = oov = 0
    s, s2, tmp = kenlm.State(), kenlm.State(), kenlm.State()
    for line in open(test):
        m.BeginSentenceWrite(s)
        for w in line.split():
            v = m.BaseScore(s, w, s2)
            if w not in m:
                oov += 1
            pe = 10 ** m.BaseScore(s, "</s>", tmp)
            pu = 10 ** m.BaseScore(s, "<unk>", tmp)
            raw += v; norm += v - math.log10(1 - pe - pu); n += 1
            s, s2 = s2, s
    c = -math.log2(10) / n
    return raw * c, norm * c, n, oov

def query_crossent(binm, test):
    """KenLM's own query tool, for the consistency check of score_model (</s> excluded)."""
    out = subprocess.run([f"{KENLM}/query", "-v", "word", binm], stdin=open(test), capture_output=True, text=True, check=True).stdout
    total, n = 0.0, 0
    for line in out.splitlines():
        for item in line.split("\t"):
            parts = item.split(" ")
            if len(parts) == 3 and "=" in parts[0] and parts[0].rsplit("=", 1)[0] != "</s>":
                total += float(parts[2]); n += 1
    return -total / n * math.log2(10), n

def plugin(toks, v, line):
    """Plug-in entropy on the training sample: unigram, and conditional on the previous token within a line."""
    toks = toks[: (len(toks) // line) * line]
    _, cu = np.unique(toks, return_counts=True)
    pu = cu / cu.sum()
    h0 = -float(np.sum(pu * np.log2(pu)))
    i = np.arange(len(toks) - 1)
    keep = (i + 1) % line != 0                       # pairs within a line only
    a, b = toks[:-1][keep], toks[1:][keep]
    _, cp = np.unique(a * v + b, return_counts=True)
    _, ca = np.unique(a, return_counts=True)
    n = cp.sum()
    h_joint = -float(np.sum(cp / n * np.log2(cp / n)))
    h_prev = -float(np.sum(ca / n * np.log2(ca / n)))
    return h0, h_joint - h_prev

FIELDS = ["code", "proc", "m", "vocab", "n_train", "line", "seed", "k", "h_ref", "h_raw", "h_norm", "bias_raw", "bias_norm",
          "plugin", "plugin_ref", "plugin_bias", "fallback_orders", "discounts", "fallback_setting", "h_val_raw", "n_scored", "oov", "lmplz_s"]

def run_cell(work, wr, done, proc, m, v, n, line, seed, fallback_values=None, setting="default", val_path=None):
    p = zipf(v)
    key = lambda k: (proc, str(m), str(v), str(n), str(line), str(seed), str(k), setting)
    if all(key(k) in done for k in range(5)):
        return
    train, test = f"{work}/train.txt", f"{work}/test.txt"
    base = 100000 * seed + 1000 * m + VOCABS.index(v) * 10 + (0 if proc == "iid" else 1)
    tr = simulate(n, p, m, base + 1)
    n_written = write(train, tr, line)
    write(test, simulate(N_TEST, p, m, base + 2), line)
    h0p, h1p = plugin(tr, v, line)
    del tr
    val = None
    if val_path:
        val = f"{work}/val.txt"
        write(val, simulate(N_TEST, p, m, base + 3), line)
    for k in range(5):
        if key(k) in done:
            continue
        arpa, binm = f"{work}/m.arpa", f"{work}/m.bin"
        logp = f"{work}/logs/{proc}{m}_v{v}_n{n}_L{line}_s{seed}_k{k}_{setting}.log"
        used, secs, log = lmplz(k + 1, train, arpa, f"{work}/tmp", logp, fallback_values)
        fell, stats = discounts(log)
        if k == 0:
            hr, hn, ns, oov = score_unigram(arpa, test)
            hv = score_unigram(arpa, val)[0] if val else ""
        else:
            subprocess.run([f"{KENLM}/build_binary", arpa, binm], capture_output=True, check=True)
            hr, hn, ns, oov = score_model(binm, test)
            hv = score_model(binm, val)[0] if val else ""
            os.remove(binm)
        os.remove(arpa)
        ref = h_ref(p, k, m, line)
        pl, plref = (h0p, h_marg(p)) if k == 0 else ((h1p, h_at(p, 1, m)) if k == 1 else ("", ""))
        wr.writerow({"code": CODE_ID, "proc": proc, "m": m, "vocab": v, "n_train": n_written, "line": line, "seed": seed, "k": k,
                     "h_ref": round(ref, 5), "h_raw": round(hr, 5), "h_norm": round(hn, 5), "bias_raw": round(hr - ref, 5),
                     "bias_norm": round(hn - ref, 5), "plugin": "" if pl == "" else round(pl, 5),
                     "plugin_ref": "" if plref == "" else round(plref, 5), "plugin_bias": "" if pl == "" else round(pl - plref, 5),
                     "fallback_orders": ",".join(map(str, fell)) if used else "",
                     "discounts": ";".join(f"{o}:{a}/{b}/{c}" for o, (a, b, c) in sorted(stats.items())),
                     "fallback_setting": setting, "h_val_raw": "" if hv == "" else round(hv, 5),
                     "n_scored": ns, "oov": oov, "lmplz_s": round(secs, 1)})
    os.remove(train); os.remove(test)
    if val:
        os.remove(val)

def consistency_check(work):
    """score_model must agree with KenLM's query tool on a small model before anything runs."""
    p = zipf(600); train, test = f"{work}/c_train.txt", f"{work}/c_test.txt"
    write(train, simulate(300_000, p, 1, 7), 1000); write(test, simulate(50_000, p, 1, 8), 1000)
    lmplz(3, train, f"{work}/c.arpa", f"{work}/tmp", f"{work}/logs/consistency.log")
    subprocess.run([f"{KENLM}/build_binary", f"{work}/c.arpa", f"{work}/c.bin"], capture_output=True, check=True)
    a, _, n1, _ = score_model(f"{work}/c.bin", test)
    b, n2 = query_crossent(f"{work}/c.bin", test)
    for f_ in ("c_train.txt", "c_test.txt", "c.arpa", "c.bin"):
        os.remove(f"{work}/{f_}")
    if abs(a - b) > 1e-6 or n1 != n2:
        raise SystemExit(f"STOP: Python scorer {a:.7f} ({n1} tokens) disagrees with query {b:.7f} ({n2} tokens)")
    print(f"consistency check passed: {a:.6f} bits, {n1} tokens", flush=True)

def main():
    work, out_dir, part = sys.argv[1], sys.argv[2], sys.argv[3]
    for d in (work, f"{work}/tmp", f"{work}/logs", out_dir):
        os.makedirs(d, exist_ok=True)
    consistency_check(work)
    out = f"{out_dir}/f1v2_{part}.tsv"
    done = set()
    if os.path.exists(out):
        for r in csv.DictReader(open(out), delimiter="\t"):
            if r["code"] == CODE_ID:
                done.add((r["proc"], r["m"], r["vocab"], r["n_train"], r["line"], r["seed"], r["k"], r["fallback_setting"]))
    new = not os.path.exists(out)
    with open(out, "a", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t")
        if new:
            wr.writeheader()
        if part == "long":
            for seed in (1, 2, 3):
                for v in VOCABS:
                    for proc, m in PROCS:
                        for n in (5_000_000, 10_000_000, 30_000_000):
                            run_cell(work, wr, done, proc, m, v, n, 1000, seed); f.flush()
        elif part == "short":
            for seed in (1, 2, 3):
                for v in VOCABS:
                    for proc, m in PROCS:
                        run_cell(work, wr, done, proc, m, v, 10_000_000, 15, seed); f.flush()
        elif part == "ablation":
            settings = {"default": None, "low": (0.25, 0.5, 0.75), "high": (0.75, 1.5, 2.0)}
            for proc, m in (("copy", 1), ("copy", 2)):
                for name, vals in settings.items():
                    run_cell(work, wr, done, proc, m, 2000, 10_000_000, 1000, 1, fallback_values=vals, setting=name, val_path=True); f.flush()
    print("done", flush=True)

if __name__ == "__main__":
    main()
