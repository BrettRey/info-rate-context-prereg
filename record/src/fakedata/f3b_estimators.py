"""F3b with copy and mapped dependencies, scored by either fixed estimator.

Conditional targets match F3b; reported truth includes the context lost at line starts.
Only simulated text is generated. Scores are checkpointed; model files are removed after scoring.
Usage: python -I src/fakedata/f3b_estimators.py WORK OUT_PREFIX --families local_mapped skipped_mapped
"""
import argparse, csv, hashlib, importlib.util, io, json, math, os, signal, subprocess, sys, time
from pathlib import Path
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
B = load("f3b_fitted", os.path.join(HERE, "f3b_fitted.py"))
M = load("f1_mapped", os.path.join(HERE, "f1_mapped.py"))
F, A, NN = B.F, B.A, M.NN
SPACE = load("f3b_disk_space", Path(HERE).parent / "stage5/disk_space.py")
ROOT = Path.cwd().resolve()
FAMILIES = {"local_copy": (1, False), "skipped_copy": (3, False),
            "local_mapped": (1, True), "skipped_mapped": (3, True)}
PAIRINGS = ("independent", "aligned", "opposed")
GIB = 1024 ** 3
FIELDS = ["family", "pairing", "estimator", "language", "vocab", "target", "eps", "m", "k",
          "h_conditional", "h_true", "h_est", "bias_bits", "oracle_bits", "fit_minus_oracle",
          "n_train", "n_val", "n_test", "line", "train_seed", "val_seed", "test_seed", "sigma_seed",
          "seconds", "steps", "val_bits", "device", "fallback_orders", "discounts", "peak_work_bytes",
          "min_free_bytes", "oov_tokens"]
SUMMARY_FIELDS = ["family", "pairing", "scenario", "estimator", "k", "R_true", "R_est", "distortion",
                  "mean_bias_bits", "bias_range_bits", "r_true", "r_est", "v_true", "v_est"]
CONTRAST_FIELDS = ["family", "pairing", "scenario", "estimator", "baseline", "R4_minus_R1_true",
                   "R4_minus_R1_est", "distortion"]

def local_path(path):
    p = Path(path).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError("All paths must be inside the current working directory")
    return p

def work_bytes(work):
    return int(subprocess.check_output(["du", "-sk", str(work)], text=True).split()[0]) * 1024 if Path(work).exists() else 0

def disk_check(reserve=0, announce=False, growth_baseline=None, resource_budget=None, *, work=None, owned_paths=None):
    """Reserve disk above 42 GiB and below the explicit work directory's 3 GB limit."""
    if reserve < 0:
        raise ValueError("reserve must be nonnegative")
    if resource_budget is not None and work is None:
        if growth_baseline is not None:
            used = resource_budget.check()["directory_bytes"]
            reserve = max(0, reserve - max(0, used - growth_baseline))
        record = resource_budget.check(reserve, announce=announce)
        return record["directory_bytes"], record["free_bytes"]
    if announce:
        print(subprocess.check_output(["df", "-g", "/"], text=True).rstrip(), flush=True)
    if work is None:
        raise ValueError("explicit work directory required")
    s = os.statvfs(SPACE.existing_directory(work)); free = s.f_bavail * s.f_frsize
    used = sum(work_bytes(path) for path in owned_paths) if owned_paths is not None else work_bytes(work)
    if growth_baseline is not None:
        # Use the same observation for consumed growth and the limit check.
        reserve = max(0, reserve - max(0, used - growth_baseline)) + (GIB if resource_budget is None else 0)
    SPACE.check_data(work, reserve, work_bytes)
    cap = getattr(resource_budget, "cap", None)
    cap = cap if type(cap) is int else 3_000_000_000
    if free - reserve < 42 * GIB or used + reserve > cap:
        raise RuntimeError(f"Disk stop: free={free / GIB:.3f} GiB, work={used}, reserve={reserve}")
    if resource_budget is not None:
        # The scratch reservation does not replace the supplied destination's
        # ceiling or its filesystem check. Keep both checks before the write.
        resource_budget.check(reserve, announce=False)
    return used, free

def guarded(cmd, reserve, resource_budget=None, *, work=None):
    """Keep the remaining peak-growth reservation plus a 1 GiB monitoring margin.

    This is conservative preflight and sampled monitoring, not a filesystem quota.
    The supplied peak must cover all files together, including temporary sort files.
    """
    if reserve <= 0:
        raise ValueError("A positive peak-growth reservation is required")
    options = dict(resource_budget=resource_budget) if resource_budget is not None else dict(work=work)
    baseline, low = disk_check(reserve + (0 if resource_budget is not None else GIB), announce=True, **options)
    peak = baseline
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                used, free = disk_check(reserve, growth_baseline=baseline, **options)
                peak, low = max(peak, used), min(low, free)
        used, free = disk_check(**options)
        peak, low = max(peak, used), min(low, free)
        if proc.returncode:
            raise RuntimeError(f"KenLM exited {proc.returncode}: {err[-2000:]}")
        return out, peak, low
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM); proc.communicate()

def mapped_entropy(p, sigma, eps):
    return float(M.stationary(p, sigma, eps) @ M.h_rows(p, sigma, eps))

def solve_mapped_eps(p, sigma, target):
    """Solve stationary conditional entropy, matching the copy family's target convention."""
    if not 0 < target < F.h_marg(p):
        raise ValueError("Target must lie between zero and the fresh-draw entropy")
    lo, hi = 1e-4, 0.9999
    if not mapped_entropy(p, sigma, lo) <= target <= mapped_entropy(p, sigma, hi):
        raise ValueError("Target outside the numerical epsilon bracket")
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if mapped_entropy(p, sigma, mid) < target else (lo, mid)
    return (lo + hi) / 2

def mapped_process(n, p, m, eps, sigma, seed):
    """Draw independent stationary residue chains, applying sigma between fresh draws."""
    rng = np.random.default_rng(seed); pi = M.stationary(p, sigma, eps)
    out = np.empty(n, dtype=np.int64)
    for r in range(m):
        nr = len(range(r, n, m))
        fresh = rng.random(nr) < eps; fresh[0] = True
        vals = rng.choice(len(p), size=nr, p=p); vals[0] = rng.choice(len(p), p=pi)
        last = np.maximum.accumulate(np.where(fresh, np.arange(nr), 0))
        y = vals[last]; age = np.arange(nr) - last
        for step in range(int(age.max())):
            mask = age > step; y[mask] = sigma[y[mask]]
        out[r::m] = y
    return out

def truth(p, eps, k, m, line, sigma=None):
    if sigma is None:
        hp, hc = F.h_marg(p), F.h_copy(p, eps)
    else:
        hp, hc = F.h_marg(M.stationary(p, sigma, eps)), mapped_entropy(p, sigma, eps)
    unavailable = min(m, line) if k >= m else line
    return (unavailable * hp + (line - unavailable) * hc) / line

def oracle_bits(test, p, eps, k, m, sigma=None):
    """Score the same test tokens under their true available-context probabilities."""
    pi = p if sigma is None else M.stationary(p, sigma, eps)
    prob = pi[test].copy()
    if k >= m and test.shape[1] > m:
        prev, cur = test[:, :-m], test[:, m:]
        predicted = prev if sigma is None else sigma[prev]
        prob[:, m:] = eps * p[cur] + (1 - eps) * (cur == predicted)
    return -float(np.log2(prob).mean())

def seeds(family, language):
    m, mapped = FAMILIES[family]
    if not mapped:
        return 7000 + 10 * language, 94_000_000 + 1000 * m + 10 * language, 8000 + 10 * language, None
    base = 90_000_000 + 1_000_000 * m + 10 * language
    return base + 1, base + 3, base + 2, 95_000_000 + language

def kenlm_estimate(work, logname, train, test, k, peak_reserve_bytes=None,
                   sort_memory="30%", resource_budget=None):
    """Use the existing fitter and normalised scorer, with serial disk guards."""
    arpa, binm = work / "m.arpa", work / "m.bin"
    log = work / "logs" / f"{logname}.log"
    # Run the unchanged F1 fitter in a child group so its temporary writes are monitored.
    code = ("import importlib.util,json,sys; s=importlib.util.spec_from_file_location('f',sys.argv[1]); "
            "f=importlib.util.module_from_spec(s); s.loader.exec_module(f); "
            "used,seconds,log=f.lmplz(int(sys.argv[2]),*sys.argv[3:7],sort_memory=sys.argv[7]); "
            "print(json.dumps({'seconds':seconds,'fallback':f.discounts(log)[0],"
            "'discounts':f.discounts(log)[1]}))")
    t0 = time.perf_counter()
    # No cap: a large input must not silently shrink its reservation. A measured
    # aggregate peak can override this conservative small-fixture extrapolation.
    reserve = peak_reserve_bytes if peak_reserve_bytes is not None else train.stat().st_size * 45 + 100_000_000
    options = dict(resource_budget=resource_budget) if resource_budget is not None else dict(work=work)
    try:
        out, peak, low = guarded([sys.executable, "-I", "-B", "-c", code, F.__file__, str(k + 1),
                                  str(train), str(arpa), str(work / "tmp"), str(log), sort_memory], reserve, **options)
        fit = json.loads(out)
        _, peak2, low2 = guarded([f"{F.KENLM}/build_binary", str(arpa), str(binm)], arpa.stat().st_size, **options)
        arpa.unlink()
        raw, h, ns, oov = F.score_model(str(binm), str(test))
        return dict(h_est=h, seconds=time.perf_counter() - t0, steps="", val_bits="", device="",
                    fallback_orders=",".join(map(str, fit["fallback"])), discounts=json.dumps(fit["discounts"]),
                    peak_work_bytes=max(peak, peak2), min_free_bytes=min(low, low2), oov_tokens=oov)
    finally:
        for path in (arpa, binm):
            path.unlink(missing_ok=True)
        for path in (work / "tmp").iterdir():
            if path.is_file(): path.unlink()

def write_tsv(path, rows, fields=None, resource_budget=None):
    tmp = Path(str(path) + ".tmp")
    disk_check(1_000_000, resource_budget=resource_budget, work=path, owned_paths=(path, tmp))
    with open(tmp, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields or list(rows[0]), delimiter="\t", lineterminator="\n")
        wr.writeheader(); wr.writerows(rows)
    os.replace(tmp, path)

def summarise(rows, inventories, ks, rate_reference_k=4, rate_seeds=None):
    """Propagate densities through Stage 6 using the original exact S0/S1 construction."""
    ks = list(ks)
    if not ks or len(ks) != len(set(ks)):
        raise ValueError("Rungs must be nonempty and unique")
    summary, contrasts = [], []
    groups = sorted(set((r["family"], r["pairing"], r["estimator"]) for r in rows))
    for family, pairing, estimator in groups:
        sel = [r for r in rows if (r["family"], r["pairing"], r["estimator"]) == (family, pairing, estimator)]
        keys = [(int(r["language"]), int(r["k"])) for r in sel]
        expected = {(i, k) for i in range(len(inventories)) for k in ks}
        if len(keys) != len(set(keys)) or not set(keys).issubset(expected):
            raise ValueError("Duplicate or unexpected panel keys")
        if set(keys) != expected: continue
        sel.sort(key=lambda r: (int(r["language"]), ks.index(int(r["k"]))))
        tru = np.array([float(r["h_true"]) for r in sel]).reshape(len(inventories), len(ks))
        est = np.array([float(r["h_est"]) for r in sel]).reshape(tru.shape)
        for scenario, r in B.R_SCEN.items():
            # Legacy copy panel seeds are retained for regression; mapped panels use a fresh seed.
            panel_seed = (rate_seeds or {"copy": 11, "mapped": 96_000_000})["mapped" if FAMILIES[family][1] else "copy"]
            # Reconstruct the fixed true anchor even when its fitted rung was omitted.
            anchor = []
            for i in range(len(inventories)):
                row = next(t for t in sel if int(t["language"]) == i)
                if rate_reference_k in ks:
                    anchor.append(tru[i, ks.index(rate_reference_k)])
                else:
                    p = F.zipf(int(row["vocab"]))
                    sigma = (np.random.default_rng(int(row["sigma_seed"])).permutation(len(p))
                             if FAMILIES[family][1] else None)
                    anchor.append(truth(p, float(row["eps"]), rate_reference_k, int(row["m"]), int(row["line"]), sigma))
            log_sr = B.rates(np.log(anchor), r, np.random.default_rng(panel_seed))
            rt, vt, ct = A.ladder(np.log(tru), log_sr); re, ve, ce = A.ladder(np.log(est), log_sr)
            for j, k in enumerate(ks):
                bias = est[:, j] - tru[:, j]
                summary.append(dict(family=family, pairing=pairing, scenario=scenario, estimator=estimator, k=k,
                                    R_true=round(rt[j], 4), R_est=round(re[j], 4), distortion=round(re[j] - rt[j], 4),
                                    mean_bias_bits=round(float(bias.mean()), 4),
                                    bias_range_bits=f"{bias.min():.3f}..{bias.max():.3f}",
                                    r_true=round(ct[j], 6), r_est=round(ce[j], 6),
                                    v_true=round(vt[j], 6), v_est=round(ve[j], 6)))
            if 1 in ks and 4 in ks:
                first, last = ks.index(1), ks.index(4)
                dt, de = rt[last] - rt[first], re[last] - re[first]
                contrasts.append(dict(family=family, pairing=pairing, scenario=scenario, estimator=estimator,
                                      baseline="k=1", R4_minus_R1_true=dt, R4_minus_R1_est=de, distortion=de - dt))
    return summary, contrasts

def pairing_orders(n):
    return {"independent": np.random.default_rng(5).permutation(n),
            "aligned": np.arange(n), "opposed": np.arange(n)[::-1]}

def read_checkpoint(density, config):
    """Validate every committed row and its provenance before repairing the tail."""
    if not density.exists() or not density.stat().st_size:
        return [], None
    content = density.read_bytes(); end = content.rfind(b"\n") + 1
    if not end:
        raise ValueError("Incomplete checkpoint header")
    try:
        reader = csv.DictReader(io.StringIO(content[:end].decode(), newline=""), delimiter="\t", strict=True)
        if reader.fieldnames != FIELDS:
            raise ValueError("Checkpoint header does not match this runner")
        rows = list(reader)
        done = set(); orders = pairing_orders(len(config["inventories"]))
        for row in rows:
            if None in row or any(v is None for v in row.values()):
                raise ValueError("Incomplete newline-terminated checkpoint row")
            family, pairing, estimator = row["family"], row["pairing"], row["estimator"]
            i, k = int(row["language"]), int(row["k"])
            if (family not in config["families"] or pairing not in config["pairings"] or estimator not in config["estimators"]
                    or not 0 <= i < len(config["inventories"]) or k not in config["ks"]):
                raise ValueError("Checkpoint key is outside this configuration")
            key = family, pairing, estimator, i, k
            if key in done: raise ValueError("Duplicate checkpoint key")
            done.add(key)
            m, mapped = FAMILIES[family]; tr, va, te, sigma_seed = seeds(family, i)
            expected = dict(vocab=config["inventories"][i], m=m, n_train=config["n_train"], n_test=config["n_test"],
                            line=config["line"], train_seed=tr, test_seed=te,
                            n_val=config["n_val"] if estimator == "ffnn" else 0)
            for field, value in expected.items():
                if int(row[field]) != value: raise ValueError(f"Checkpoint {field} differs from configuration")
            for field, value in (("sigma_seed", sigma_seed if mapped else ""), ("val_seed", va if estimator == "ffnn" else "")):
                if row[field] != str(value): raise ValueError(f"Checkpoint {field} differs from configuration")
            target = config["targets"][int(orders[pairing][i])]
            if float(row["target"]) != target: raise ValueError("Checkpoint target differs from configuration")
            numbers = {field: float(row[field]) for field in
                       ("eps", "target", "h_conditional", "h_true", "h_est", "bias_bits", "oracle_bits", "fit_minus_oracle", "seconds")}
            if not all(math.isfinite(v) for v in numbers.values()): raise ValueError("Nonfinite checkpoint result")
            if not 0 < numbers["eps"] < 1 or any(numbers[f] <= 0 for f in ("h_true", "h_est", "h_conditional")):
                raise ValueError("Invalid entropy or epsilon")
            for field in ("peak_work_bytes", "min_free_bytes", "oov_tokens"):
                if int(row[field]) < 0: raise ValueError("Invalid resource or OOV count")
            if int(row["oov_tokens"]) > config["n_test"]: raise ValueError("Invalid OOV count")
            if estimator == "ffnn":
                if int(row["steps"]) < 1 or not math.isfinite(float(row["val_bits"])) or row["device"] != config["device"]:
                    raise ValueError("Invalid neural training record")
                if row["discounts"] or row["fallback_orders"] or int(row["oov_tokens"]):
                    raise ValueError("Invalid neural metadata")
            else:
                if row["steps"] or row["val_bits"] or row["device"] or not isinstance(json.loads(row["discounts"]), dict):
                    raise ValueError("Invalid KenLM training record")
                if row["fallback_orders"]:
                    for order in row["fallback_orders"].split(","):
                        if not 1 <= int(order) <= k + 1: raise ValueError("Invalid fallback order")
            p = F.zipf(expected["vocab"])
            sigma = np.random.default_rng(sigma_seed).permutation(len(p)) if mapped else None
            hc = mapped_entropy(p, sigma, numbers["eps"]) if mapped else F.h_copy(p, numbers["eps"])
            comparisons = ((numbers["h_conditional"], hc), (hc, target),
                           (numbers["h_true"], truth(p, numbers["eps"], k, m, config["line"], sigma)),
                           (numbers["bias_bits"], numbers["h_est"] - numbers["h_true"]),
                           (numbers["fit_minus_oracle"], numbers["h_est"] - numbers["oracle_bits"]))
            if any(not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10) for a, b in comparisons):
                raise ValueError("Checkpoint numerical metadata is inconsistent")
    except (UnicodeError, csv.Error, TypeError, KeyError, OverflowError) as exc:
        raise ValueError("Corrupt complete checkpoint row") from exc
    return rows, end if end < len(content) else None

def publish(prefix, rows, config):
    """Refresh complete panels, including empty tables, at every checkpoint."""
    summary, contrasts = summarise(rows, config["inventories"], config["ks"],
                                   config["rate_reference_k"], config["rate_seeds"])
    write_tsv(Path(str(prefix) + ".tsv"), summary, SUMMARY_FIELDS)
    write_tsv(Path(str(prefix) + "_contrasts.tsv"), contrasts, CONTRAST_FIELDS)
    total = (len(config["families"]) * len(config["pairings"]) * len(config["estimators"])
             * len(config["inventories"]) * len(config["ks"]))
    status = "complete" if len(rows) == total else "partial"
    md = ["# F3b estimator summary", "", f"Run status: {status}; {len(rows)}/{total} fitted cells checkpointed.", "",
          f"Simulated data only; {len(config['inventories'])} languages; {config['n_train']:,} training and "
          f"{config['n_test']:,} test tokens per cell; line length {config['line']}.", "",
          "Only complete language-by-rung panels appear in the tables. Truth includes unavailable context at line starts. "
          "Targets apply after context becomes available. Inventory pairings concern density, not rate. "
          f"Rates are anchored to true k={config['rate_reference_k']} independently of requested fitted rungs. "
          "The contrast uses k=1, the existing F3b baseline; no word-boundary rung is simulated. "
          "Distortions are reported without a pass/fail threshold.", "",
          "| Family | Estimator | Maximum absolute R distortion | Maximum absolute contrast distortion |",
          "|---|---|---:|---:|"]
    for family in config["families"]:
        for estimator in config["estimators"]:
            sr = [r for r in summary if (r["family"], r["estimator"]) == (family, estimator)]
            cr = [r for r in contrasts if (r["family"], r["estimator"]) == (family, estimator)]
            if sr:
                cd = f"{max(abs(r['distortion']) for r in cr):.4f}" if cr else "not computed"
                md.append(f"| {family} | {estimator} | {max(abs(r['distortion']) for r in sr):.4f} | {cd} |")
    md += ["", f"Rate seeds: {config['rate_seeds']}. Different copy/mapped seeds change the residual rate panel. "
           "Mapped stream and permutation seeds are in the 90–95 million range. The original independent pairing "
           "(seed 5) is shared; copy train/test seeds are retained for regression. Both estimators see identical "
           "train/test streams; only the neural model uses independent validation text. Neural SETTINGS, including "
           "seed 0, are unchanged. KenLM OOV tokens retain the legacy score and are counted in the density table.", ""]
    disk_check(1_000_000, work=Path(prefix).parent)
    path = Path(str(prefix) + ".md"); tmp = Path(str(path) + ".tmp")
    tmp.write_text("\n".join(md)); os.replace(tmp, path)
    return summary, contrasts

def run_grid(work, prefix, families, estimators, inventories=B.INV, targets=B.TARGET,
             pairings=PAIRINGS, ks=B.KS, n_train=B.N, n_val=M.N_VAL, n_test=F.N_TEST,
             line=B.LINE, device="cpu", threads=2, rate_reference_k=4, rate_seeds=None, kenlm_peak_bytes=None):
    """Fit each fake cell once; retain checkpointed scores and complete panel summaries."""
    work, prefix = local_path(work), local_path(prefix)
    inventories, targets, ks = list(map(int, inventories)), list(map(float, targets)), sorted(ks)
    if any(len(v) != len(set(v)) for v in (families, estimators, pairings, ks)):
        raise ValueError("Duplicate grid coordinates")
    if not families or not estimators or not pairings or not ks or any(v < 2 for v in inventories):
        raise ValueError("Grid coordinates must be nonempty and inventories at least two")
    if not set(families).issubset(FAMILIES) or not set(pairings).issubset(PAIRINGS) or not set(estimators).issubset({"kenlm", "ffnn"}):
        raise ValueError("Unknown grid coordinate")
    if line < 1 or threads < 1 or rate_reference_k not in B.KS or (kenlm_peak_bytes is not None and kenlm_peak_bytes <= 0):
        raise ValueError("Invalid line length, threads, rate anchor or peak reservation")
    rate_seeds = dict(rate_seeds or {"copy": 11, "mapped": 96_000_000})
    if set(rate_seeds) != {"copy", "mapped"} or any(not isinstance(v, int) or v < 0 for v in rate_seeds.values()):
        raise ValueError("Rate seeds must be nonnegative integers for copy and mapped")
    if len(inventories) < 3 or len(inventories) != len(targets):
        raise ValueError("Need at least three languages for S0/S1, with one target per inventory")
    if min(targets) <= 0 or max(targets) >= min(F.h_marg(F.zipf(v)) for v in inventories):
        raise ValueError("Every target must be attainable for every inventory pairing")
    if any(n < line or n % line for n in (n_train, n_val, n_test)) or min(ks) < 1:
        raise ValueError("Token budgets must be positive whole lines; k must be positive")
    # The inherited copy solver clamps to this bracket. Refuse infeasible targets
    # before creating any output instead of writing a checkpoint that cannot resume.
    if any(not FAMILIES[family][1] for family in families):
        orders = pairing_orders(len(inventories))
        for i, vocab in enumerate(inventories):
            p = F.zipf(vocab)
            lo, hi = F.h_copy(p, 1e-4), F.h_copy(p, 0.9999)
            for pairing in pairings:
                if not lo <= targets[int(orders[pairing][i])] <= hi:
                    raise ValueError("Copy target outside the numerical epsilon bracket")
    NN.torch.set_num_threads(threads)
    config = dict(families=list(families), estimators=list(estimators), inventories=inventories, targets=targets,
                  pairings=list(pairings), ks=ks, n_train=n_train, n_val=n_val, n_test=n_test, line=line,
                  device=device, threads=threads, neural_settings=NN.SETTINGS, rate_reference_k=rate_reference_k,
                  rate_seeds=rate_seeds, kenlm_peak_bytes=kenlm_peak_bytes,
                  environment=dict(python=sys.version, numpy=np.__version__, torch=NN.torch.__version__,
                    kenlm_module=hashlib.sha256(Path(F.kenlm.__file__).read_bytes()).hexdigest(),
                    kenlm_binaries={n: hashlib.sha256((Path(F.KENLM) / n).read_bytes()).hexdigest()
                                    for n in ("lmplz", "build_binary")}),
                  code=hashlib.sha256(b"".join(Path(p).read_bytes() for p in
                       (__file__, B.__file__, F.__file__, M.__file__, NN.__file__, A.__file__, SPACE.__file__))).hexdigest())
    meta, density = Path(str(prefix) + "_config.json"), Path(str(prefix) + "_densities.tsv")
    if meta.exists():
        try: saved = json.loads(meta.read_text())
        except (ValueError, UnicodeError) as exc: raise ValueError("Invalid checkpoint provenance") from exc
        if saved != config: raise ValueError("Output prefix already has a different configuration; use a new prefix")
    elif density.exists() and density.read_bytes().partition(b"\n")[2]:
        raise ValueError("Saved density rows require their configuration sidecar; use a new prefix")
    rows, torn_end = read_checkpoint(density, config)
    disk_check(1_000_000, work=work)
    disk_check(1_000_000, work=prefix.parent)
    work.mkdir(parents=True, exist_ok=True); prefix.parent.mkdir(parents=True, exist_ok=True)
    for d in ("logs", "tmp"): (work / d).mkdir(exist_ok=True)
    if not meta.exists():
        tmp = Path(str(meta) + ".tmp"); tmp.write_text(json.dumps(config, indent=2) + "\n"); os.replace(tmp, meta)
    if torn_end is not None:
        with density.open("r+b") as f: f.truncate(torn_end)
    done = {(r["family"], r["pairing"], r["estimator"], int(r["language"]), int(r["k"])) for r in rows}
    orders = pairing_orders(len(inventories))
    publish(prefix, rows, config)
    new_density = not density.exists() or density.stat().st_size == 0
    with open(density, "a", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        if new_density: wr.writeheader(); f.flush()
        for family in families:
            m, mapped = FAMILIES[family]
            for pairing in pairings:
                for i, v in enumerate(inventories):
                    if all((family, pairing, e, i, k) in done for e in estimators for k in ks): continue
                    p = F.zipf(v); target = targets[int(orders[pairing][i])]
                    tr_seed, va_seed, te_seed, sigma_seed = seeds(family, i)
                    sigma = np.random.default_rng(sigma_seed).permutation(v) if mapped else None
                    eps = solve_mapped_eps(p, sigma, target) if mapped else B.solve_eps(p, target)
                    conditional = mapped_entropy(p, sigma, eps) if mapped else F.h_copy(p, eps)
                    make = lambda n, seed: (mapped_process(n, p, m, eps, sigma, seed) if mapped else
                                           B.copy_process(n, p, m, eps, seed)).reshape(-1, line)
                    disk_check(n_train * 6 + n_test * 6, announce=True, work=work)
                    tr, te = make(n_train, tr_seed), make(n_test, te_seed)
                    va = make(n_val, va_seed) if "ffnn" in estimators else None
                    train, test = work / "train.txt", work / "test.txt"
                    try:
                        if "kenlm" in estimators:
                            F.write(str(train), tr.ravel(), line); F.write(str(test), te.ravel(), line)
                        for estimator in estimators:
                            for k in ks:
                                key = family, pairing, estimator, i, k
                                if key in done: continue
                                if estimator == "kenlm":
                                    peak_options = {} if kenlm_peak_bytes is None else {"peak_reserve_bytes": kenlm_peak_bytes}
                                    result = kenlm_estimate(work, f"{family}_{pairing}_l{i}_k{k}", train, test, k, **peak_options)
                                else:
                                    r = NN.estimate(tr, va, te, v, k, device=device)
                                    used, free = disk_check(work=work)
                                    result = dict(h_est=r["test_bits"], seconds=r["seconds"], steps=r["steps"],
                                                  val_bits=r["val_bits"], device=r["device"], fallback_orders="",
                                                  discounts="", peak_work_bytes=used, min_free_bytes=free, oov_tokens=0)
                                ht = truth(p, eps, k, m, line, sigma); ho = oracle_bits(te, p, eps, k, m, sigma)
                                row = dict(family=family, pairing=pairing, estimator=estimator, language=i, vocab=v,
                                           target=target, eps=eps, m=m, k=k, h_conditional=conditional, h_true=ht,
                                           bias_bits=result["h_est"] - ht, oracle_bits=ho,
                                           fit_minus_oracle=result["h_est"] - ho, n_train=n_train,
                                           n_val=n_val if estimator == "ffnn" else 0, n_test=n_test, line=line,
                                           train_seed=tr_seed, val_seed=va_seed if estimator == "ffnn" else "",
                                           test_seed=te_seed, sigma_seed=sigma_seed if mapped else "", **result)
                                disk_check(1_000_000, work=prefix.parent)
                                wr.writerow(row); f.flush(); rows.append(row); done.add(key)
                                publish(prefix, rows, config)
                                print(f"{family} {pairing} l{i} V={v} {estimator} k={k}: "
                                      f"truth={ht:.5f} estimated={result['h_est']:.5f} ({result['seconds']:.1f}s)", flush=True)
                    finally:
                        train.unlink(missing_ok=True); test.unlink(missing_ok=True)
                    del tr, te, va
    summary, contrasts = publish(prefix, rows, config)
    return rows, summary, contrasts

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work"); ap.add_argument("prefix")
    ap.add_argument("--families", nargs="+", choices=FAMILIES, default=list(FAMILIES))
    ap.add_argument("--estimators", nargs="+", choices=("kenlm", "ffnn"), default=["kenlm"])
    ap.add_argument("--pairings", nargs="+", choices=PAIRINGS, default=list(PAIRINGS))
    ap.add_argument("--ks", nargs="+", type=int, choices=B.KS, default=list(B.KS))
    ap.add_argument("--small", action="store_true")
    ap.add_argument("--n-train", type=int); ap.add_argument("--n-val", type=int); ap.add_argument("--n-test", type=int)
    ap.add_argument("--inventories", nargs="+", type=int); ap.add_argument("--targets", nargs="+", type=float)
    ap.add_argument("--device", choices=("cpu", "mps"), default="cpu"); ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--rate-reference-k", type=int, choices=B.KS, default=4)
    ap.add_argument("--copy-rate-seed", type=int, default=11); ap.add_argument("--mapped-rate-seed", type=int, default=96_000_000)
    ap.add_argument("--kenlm-peak-bytes", type=int, help="measured aggregate peak growth, before the extra 1 GiB guard margin")
    args = ap.parse_args()
    run_grid(args.work, args.prefix, args.families, args.estimators,
             inventories=args.inventories or ([20, 100, 600] if args.small else B.INV),
             targets=args.targets or ([2.0, 2.5, 3.0] if args.small else B.TARGET), pairings=args.pairings, ks=args.ks,
             n_train=args.n_train or (1_000_000 if args.small else B.N),
             n_val=args.n_val or (10_000 if args.small else M.N_VAL),
             n_test=args.n_test or (20_000 if args.small else F.N_TEST), device=args.device, threads=args.threads,
             rate_reference_k=args.rate_reference_k, rate_seeds={"copy": args.copy_rate_seed, "mapped": args.mapped_rate_seed},
             kenlm_peak_bytes=args.kenlm_peak_bytes)

if __name__ == "__main__": main()
