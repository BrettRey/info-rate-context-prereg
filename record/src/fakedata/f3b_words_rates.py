"""Word-aware, rate-paired F3b; KenLM only, stationary simulated data only.

Word lengths reuse F1c's stationary uniform 1..4 renewal process. Boundaries
are independent of syllable identities; lag-m transitions continue across words.
Unlike the F1c boundary-signal variant, starts do not change the marginal.
Targets are line-averaged true plain-rung-4 densities, not conditional entropy.
S0/S1 rates are constructed first; inventory assignment then follows rate rank.
The original wordless driver and its results remain a separate legacy check.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import sys
import time
import numpy as np
import importlib.util

HERE = Path(__file__).resolve().parent
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

E = load("legacy_f3b", HERE / "f3b_estimators.py")
R = load("word_rungs", HERE.parent / "stage5/rungs.py")
D = load("disk_budget", HERE.parent / "stage5/disk_budget.py")
RUNGS = ("0", "1w", "1", "2", "3", "4") + R.RUNGS[3:]
LENGTHS = np.full(4, .25)
ALPHA = .4
SEED_BASE, SEED_STRIDE, MAX_RUN_TAG = 2**40, 4_000_000, 999_999
RATE_SEED, PAIRING_SEED = SEED_BASE+3_999_998, SEED_BASE+3_999_999
FIELDS = ["family", "pairing", "scenario", "language", "vocab", "rung", "target", "eps", "m",
          "sr", "h_conditional", "h_true", "h_est", "bias_bits", "oracle_bits", "fit_minus_oracle",
          "n_train", "n_test", "line", "train_seed", "test_seed", "word_train_seed", "word_test_seed",
          "sigma_seed", "seconds", "model_fit", "fit_key", "fallback_orders", "discounts",
          "peak_work_bytes", "free_bytes", "oov_tokens", "n_scored", "zero_backoffs"]
SUMMARY_FIELDS = ["family", "pairing", "scenario", "rung", "R_true", "R_est", "distortion",
                  "v_true", "v_est", "r_true", "r_est", "mean_bias_bits", "n_languages", "excluded_languages", "excluded_rows"]
CONTRAST_FIELDS = ["family", "pairing", "scenario", "last", "baseline", "true", "estimated", "distortion", "n_languages", "excluded_languages", "excluded_rows"]

def run_seed_base(run_tag):
    if type(run_tag) is not int or not 1 <= run_tag <= MAX_RUN_TAG:
        raise ValueError("run tag must be an integer in 1..999999; never reuse a tag for a new run")
    return SEED_BASE + (run_tag-1)*SEED_STRIDE

def seeds(family, language, run_tag=1):
    if not 0 <= language < 100_000:
        raise ValueError("language outside reserved seed namespace")
    base = run_seed_base(run_tag) + list(E.FAMILIES).index(family) * 1_000_000 + language * 10
    return dict(train_seed=base+1, test_seed=base+2, word_train_seed=base+3,
                word_test_seed=base+4, sigma_seed=base+5 if E.FAMILIES[family][1] else "")

def boundaries(n, seed):
    """F1c's size-biased first word and uniform position: stationary at token zero."""
    rng = np.random.default_rng(seed)
    first = rng.choice(np.arange(1, 5), p=np.arange(1, 5)*LENGTHS/2.5)
    age = rng.integers(1, first+1)
    residual = first-age+1
    lengths = rng.choice(np.arange(1, 5), size=n, p=LENGTHS)
    starts = residual + np.r_[0, np.cumsum(lengths)]
    b = np.zeros(n, dtype=np.int64)
    b[starts[starts < n]] = 1
    b[0] = int(age == 1)
    return b

def corpus(n, p, m, eps, sigma, line, stream_seed, word_seed):
    # Generate at least one value per residue chain even for one-token lines.
    x = (E.mapped_process(max(n, m), p, m, eps, sigma, stream_seed) if sigma is not None
         else E.B.copy_process(max(n, m), p, m, eps, stream_seed))[:n]
    return R.Corpus(x, boundaries(n, word_seed), np.arange(0, n, line))

def entropies(p, eps, sigma):
    pi = p if sigma is None else E.M.stationary(p, sigma, eps)
    return pi, E.F.h_marg(pi), (E.F.h_copy(p, eps) if sigma is None else E.mapped_entropy(p, sigma, eps))

def truth(p, eps, m, rung, line, sigma=None):
    """Exact population loss; no past flags are supplied at any rung.

    Independently segmented stationary residue chains imply H(S|B)=H(S).
    Plain/free context has hc iff m preceding tokens are available, otherwise hp.
    Within-word context is available with probability .6*(line-1)/line, and only
    lag 1 is visible. Charged loss adds H(B)=h_binary(.4), since histories contain
    no boundary information. These formulas include continuation line starts.
    """
    _, hp, hc = entropies(p, eps, sigma)
    if rung == "1w":
        seen = (1-ALPHA)*(line-1)/line if m == 1 else 0
    else:
        k = int(rung[0])
        seen = max(0, line-m)/line if k >= m else 0
    value = hp + seen*(hc-hp)
    if rung.endswith("charged"):
        value += -ALPHA*math.log2(ALPHA)-(1-ALPHA)*math.log2(1-ALPHA)
    return value

def oracle(c, p, eps, m, rung, line, sigma=None):
    pi, _, _ = entropies(p, eps, sigma)
    n = len(c.s)
    seen = np.arange(n) % line >= m
    if rung == "1w":
        seen &= (c.b == 0) if m == 1 else False
    elif int(rung[0]) < m:
        seen[:] = False
    q = pi[c.s].copy()
    ix = np.flatnonzero(seen)
    prev = c.s[ix-m]
    predicted = prev if sigma is None else sigma[prev]
    q[ix] = eps*p[c.s[ix]]+(1-eps)*(predicted == c.s[ix])
    if rung.endswith("charged"):
        q *= np.where(c.b == 1, ALPHA, 1-ALPHA)
    return float(-np.log2(q).mean())

def solve_eps(p, sigma, m, line, target):
    lo, hi = 1e-4, .9999
    if not truth(p, lo, m, "4", line, sigma) <= target <= truth(p, hi, m, "4", line, sigma):
        raise ValueError("Line-averaged target outside the numerical epsilon bracket")
    for _ in range(60):
        mid = (lo+hi)/2
        if truth(p, mid, m, "4", line, sigma) < target: lo = mid
        else: hi = mid
    eps = (lo+hi)/2
    if not math.isclose(truth(p, eps, m, "4", line, sigma), target, abs_tol=1e-10):
        raise ValueError("Target solver did not converge")
    return eps

def rates(targets, correlation, seed=RATE_SEED):
    x = np.log(targets)
    z = (x-x.mean())/x.std(ddof=1)
    w = np.random.default_rng(seed).normal(size=len(x))
    w -= w.mean()
    w -= (w@z)/(z@z)*z
    w /= w.std(ddof=1)
    return np.log(6.5) + x.std(ddof=1)/E.B.V*(correlation*z+math.sqrt(1-correlation**2)*w)

def assign_inventories(inventories, log_sr, pairing, seed=PAIRING_SEED):
    ordered = np.sort(inventories)
    if pairing == "independent":
        return ordered[np.random.default_rng(seed).permutation(len(ordered))]
    assignment = np.empty_like(ordered)
    # aligned = larger inventory with faster rate; opposed = larger with slower.
    assignment[np.argsort(log_sr, kind="stable")] = ordered if pairing == "aligned" else ordered[::-1]
    return assignment

def panels(config, seed_factory=seeds):
    """Deterministic metadata for every panel; validate target feasibility before writes."""
    out = {}
    for family in config["families"]:
        m, mapped = E.FAMILIES[family]
        for pairing in config["pairings"]:
            for scenario, correlation in E.B.R_SCEN.items():
                sr = rates(config["targets"], correlation, config["rate_seed"])
                inventories = assign_inventories(config["inventories"], sr, pairing, config["pairing_seed"])
                for i, v in enumerate(inventories):
                    sd = seed_factory(family, i, config["run_tag"])
                    p = E.F.zipf(v)
                    sigma = np.random.default_rng(sd["sigma_seed"]).permutation(v) if mapped else None
                    eps = solve_eps(p, sigma, m, config["line"], config["targets"][i])
                    pi, hp, hc = entropies(p, eps, sigma)
                    out[family, pairing, scenario, i] = dict(family=family, pairing=pairing, scenario=scenario,
                        language=i, vocab=int(v), m=m, target=config["targets"][i], eps=eps,
                        sr=float(np.exp(sr[i])), h_conditional=hc, **sd)
    return out

def fit_key(row, rung):
    # Rates/scenario/pairing do not affect a fit. Boundary free/charged losses
    # share a fitted joint model; never reuse between different input streams.
    identity = {k: row[k] for k in ("family", "language", "vocab", "eps", "train_seed", "test_seed",
                                  "word_train_seed", "word_test_seed", "sigma_seed")}
    identity["rung"] = rung.replace("charged", "free")
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

def checkpoint(path, config, metadata, *, fields=FIELDS, identity=fit_key):
    if not path.exists() or not path.stat().st_size: return [], None
    data = path.read_bytes()
    end = data.rfind(b"\n")+1
    if not end: raise ValueError("Incomplete checkpoint header")
    reader = csv.DictReader(io.StringIO(data[:end].decode(), newline=""), delimiter="\t", strict=True)
    if reader.fieldnames != fields: raise ValueError("Unknown word/rate checkpoint schema")
    rows = list(reader)
    seen = set()
    for row in rows:
        if None in row or any(v is None for v in row.values()): raise ValueError("Corrupt complete checkpoint row")
        key = row["family"], row["pairing"], row["scenario"], int(row["language"])
        rung = row["rung"]
        if key not in metadata or rung not in config["rungs"] or (*key, rung) in seen:
            raise ValueError("Unexpected or duplicate checkpoint key")
        seen.add((*key, rung))
        expected = metadata[key]
        for field, value in expected.items():
            if isinstance(value, float):
                if not math.isclose(float(row[field]), value, rel_tol=1e-10, abs_tol=1e-10):
                    raise ValueError(f"Checkpoint {field} differs from configuration")
            elif row[field] != str(value): raise ValueError(f"Checkpoint {field} differs from configuration")
        if any(int(row[f]) != config[f] for f in ("n_train", "n_test", "line")):
            raise ValueError("Checkpoint budget differs from configuration")
        if row["fit_key"] != identity(expected, rung): raise ValueError("Checkpoint fit identity differs")
        p = E.F.zipf(expected["vocab"])
        sigma = (np.random.default_rng(expected["sigma_seed"]).permutation(len(p))
                 if E.FAMILIES[key[0]][1] else None)
        ref = truth(p, expected["eps"], expected["m"], rung, config["line"], sigma)
        nums = {f: float(row[f]) for f in ("h_true", "h_est", "bias_bits", "oracle_bits", "fit_minus_oracle", "seconds")}
        if (not all(math.isfinite(v) for v in nums.values()) or nums["seconds"] < 0
                or any(nums[f] <= 0 for f in ("h_true", "h_est", "oracle_bits"))):
            raise ValueError("Invalid checkpoint score")
        if not all(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10) for a,b in (
                (nums["h_true"],ref), (nums["bias_bits"],nums["h_est"]-ref),
                (nums["fit_minus_oracle"],nums["h_est"]-nums["oracle_bits"]))):
            raise ValueError("Inconsistent checkpoint score")
        if int(row["n_scored"]) != config["n_test"] or int(row["model_fit"]) not in (0,1):
            raise ValueError("Incomplete checkpoint score")
        if any(int(row[f]) < 0 for f in ("peak_work_bytes", "free_bytes", "oov_tokens", "zero_backoffs")) or int(row["oov_tokens"]) > config["n_test"]:
            raise ValueError("Invalid checkpoint resource record")
        if not isinstance(json.loads(row["discounts"]), (dict, str)):
            raise ValueError("Invalid discount metadata")
        if row["fallback_orders"]:
            for order in row["fallback_orders"].split(","):
                if not 1 <= int(order) <= int(rung[0])+1: raise ValueError("Invalid fallback order")
    return rows, end if end < len(data) else None

def summarise(rows, config):
    summary, contrasts = [], []
    groups = sorted({(r["family"],r["pairing"],r["scenario"]) for r in rows})
    rungs, languages = config["rungs"], len(config["inventories"])
    for group in groups:
        selected = [r for r in rows if (r["family"],r["pairing"],r["scenario"]) == group]
        keys = [(int(r["language"]),r["rung"]) for r in selected]
        expected = {(i,k) for i in range(languages) for k in rungs}
        if len(keys) != len(set(keys)) or not set(keys).issubset(expected): raise ValueError("Invalid panel keys")
        if set(keys) != expected: continue
        excluded = {int(r["language"]) for r in selected if int(r["oov_tokens"]) > 0}
        eligible = [i for i in range(languages) if i not in excluded]
        if len(eligible) < 3:
            continue  # Correlation and dispersion ratios need a nondegenerate panel.
        table = {(int(r["language"]),r["rung"]):r for r in selected}
        sr = np.log([float(table[i,rungs[0]]["sr"]) for i in eligible])
        tru = np.array([[float(table[i,k]["h_true"]) for k in rungs] for i in eligible])
        est = np.array([[float(table[i,k]["h_est"]) for k in rungs] for i in eligible])
        rt,vt,ct = E.A.ladder(np.log(tru),sr)
        re,ve,ce = E.A.ladder(np.log(est),sr)
        common = dict(zip(("family","pairing","scenario"),group), n_languages=len(eligible),
                      excluded_languages=len(excluded), excluded_rows=len(excluded)*len(rungs))
        for j,k in enumerate(rungs):
            summary.append(dict(**common,rung=k,R_true=rt[j],R_est=re[j],distortion=re[j]-rt[j],
                v_true=vt[j],v_est=ve[j],r_true=ct[j],r_est=ce[j],mean_bias_bits=float((est[:,j]-tru[:,j]).mean())))
        for last in ("4","4-free","4-charged"):
            for baseline in ("1","1w"):
                if last in rungs and baseline in rungs:
                    a,b = rungs.index(last),rungs.index(baseline)
                    dt,de = rt[a]-rt[b],re[a]-re[b]
                    contrasts.append(dict(**common,last=last,baseline=baseline,true=dt,estimated=de,distortion=de-dt))
    return summary,contrasts

def publish(prefix, rows, config, resource_budget=None):
    summary, contrasts = summarise(rows,config)
    E.write_tsv(Path(str(prefix)+".tsv"),summary,SUMMARY_FIELDS, resource_budget=resource_budget)
    E.write_tsv(Path(str(prefix)+"_contrasts.tsv"),contrasts,CONTRAST_FIELDS, resource_budget=resource_budget)
    total = len(config["families"])*len(config["pairings"])*2*len(config["inventories"])*len(config["rungs"])
    oov_rows = sum(int(row["oov_tokens"]) > 0 for row in rows)
    excluded = {(row["family"],row["pairing"],row["scenario"],int(row["language"]))
                for row in rows if int(row["oov_tokens"]) > 0}
    excluded_rows = sum((row["family"],row["pairing"],row["scenario"],int(row["language"])) in excluded for row in rows)
    report = ["# Word-aware, rate-paired F3b", "", f"Status: {'complete' if len(rows)==total else 'partial'}; {len(rows)}/{total} score cells.",
        "", "Simulated data only; CPU KenLM. Stationary uniform word lengths 1–4, independent of syllable identity. "
        "Lagged dependencies continue across words. No start/continuation marginal signal is added. "
        "True densities and oracle losses include unavailable context at artificial line starts.", "",
        "Targets mean true line-averaged plain rung 4. S0/S1 impose r=0/−0.8 and v=0.9 at that rung. "
        "Independent inventories use a fixed random permutation (finite samples may correlate by chance); "
        "aligned means larger/faster; opposed means larger/slower. Assignment is scenario-specific.", "",
        "The summary and contrasts TSVs contain complete language-by-rung panels only. "
        "Both R4−R1 and R4−R1w are reported. Flagged higher rungs follow the provisional F1c convention: "
        "plain syllable histories, with only the current flag supplied (free) or predicted (charged).", "",
        f"Code identity: `{config['code']}`. Run tag: {config['run_tag']}; injective 4,000,000-seed blocks above 2**40. "
        "Exact configuration/source/environment equality is required on resume. "
        "A non-newline-terminated tail is retried; corrupt complete rows are rejected.", "",
        "Models and generated texts are deleted after scoring. Sampled disk guards and reservations do not "
        "guarantee the floor against unbounded writes or external allocations between observations. "
        f"OOV exclusions: {oov_rows} affected score rows; {len(excluded)} language-panel memberships; "
        f"{excluded_rows} saved rows excluded from all rung comparisons and contrasts. "
        "A language with any OOV rung is excluded at every rung; fewer than three eligible languages suppresses the panel. "
        "Plain-rung scores are retained for diagnosis; word/flagged fits reject unsupported test targets. "
        "free_bytes is the monitored minimum for plain fits and the preflight observation for F1c fits. "
        "Resource observations on reused fits refer to the original fit. "
        "Word ARPA zero backoffs are encoded with a finite log sentinel that underflows to zero; "
        "zero_backoffs records the count, and scoring rejects any zero-probability target.", ""]
    E.disk_check(1_000_000, resource_budget=resource_budget, work=Path(prefix).parent)
    path = Path(str(prefix)+".md"); tmp=Path(str(path)+".tmp")
    tmp.write_text("\n".join(report)); os.replace(tmp,path)
    return summary,contrasts

def estimate(work, label, tr, te, rung, line, peak_bytes, resource_budget=None,
             sort_memory="30%", word_sort_memory="256M"):
    if rung in ("1","2","3","4"):
        train,test = work/"train.txt",work/"test.txt"
        width = len(str(max(int(tr.s.max()),int(te.s.max()))))+3
        E.disk_check((len(tr.s)+len(te.s))*width,announce=True, resource_budget=resource_budget, work=work)
        try:
            E.F.write(str(train),tr.s,line); E.F.write(str(test),te.s,line)
            result = E.kenlm_estimate(work,label,train,test,int(rung),peak_reserve_bytes=peak_bytes, sort_memory=sort_memory, resource_budget=resource_budget)
            result.update(n_scored=len(te.s))
            result["free_bytes"] = result["min_free_bytes"]
            result["zero_backoffs"] = 0
            return {k:result[k] for k in ("h_est","seconds","fallback_orders","discounts","peak_work_bytes","free_bytes","oov_tokens","n_scored","zero_backoffs")}
        finally:
            train.unlink(missing_ok=True); test.unlink(missing_ok=True)
    # F1c's class-normalised explicit prediction windows and compressed ARPA.
    result = R.estimate(tr,te,rung,"bounded",work/"word-fit",work,work/"logs"/(label+".log"),
                        reserve=peak_bytes,check=len(tr.s)<=100_000, sort_memory=word_sort_memory,
                        resource_budget=resource_budget)
    fallback_orders, _ = E.F.discounts((work/"logs"/(label+".log")).read_text())
    return dict(h_est=result["test_bits"],seconds=result["seconds"],fallback_orders=",".join(map(str,fallback_orders)),
                discounts=json.dumps(result["discounts"]),peak_work_bytes=result["peak_directory_bytes"],
                free_bytes=result["free_bytes"],oov_tokens=result["oov"],n_scored=result["n_scored"],zero_backoffs=result["zero_backoffs"],
                **({"paired_h_est":result["joint_bits"] if rung.endswith("free") else result["conditional_bits"]}
                   if "joint_bits" in result else {}))

def run_grid(work, prefix, families=tuple(E.FAMILIES), inventories=E.B.INV, targets=E.B.TARGET,
             pairings=E.PAIRINGS, rungs=RUNGS, n_train=E.B.N, n_test=E.F.N_TEST, line=E.B.LINE,
             peak_bytes=1_700_000_000, word_peak_bytes=2_700_000_000, run_tag=1,
             process_cap_bytes=4_000_000_000, reservation_dir=None, margin_bytes=2*D.GIB,
             sort_memory="30%", word_sort_memory="256M"):
    work,prefix = E.local_path(work),E.local_path(prefix)
    seed_base = run_seed_base(run_tag)
    reservation_dir = E.local_path(reservation_dir or work.parent / "shared-reservations")
    # Shared bookkeeping cannot be inside a process's measured work directory.
    if reservation_dir.is_relative_to(work) or work.is_relative_to(reservation_dir):
        raise ValueError("Shared reservation directory must be separate from process work")
    for memory in (sort_memory, word_sort_memory):
        if not re.fullmatch(r"(?:[1-9][0-9]?%|100%|[1-9][0-9]*[KMGT])", memory):
            raise ValueError("Invalid KenLM sort memory; use a positive percentage or K/M/G/T size")
    if type(process_cap_bytes) is not int or process_cap_bytes < max(peak_bytes, word_peak_bytes):
        raise ValueError("Process cap must cover both declared peak reservations")
    if type(margin_bytes) is not int or margin_bytes < 2*D.GIB:
        raise ValueError("At least 2 GiB above the 40 GiB floor required")
    inventories,targets = list(map(int,inventories)),list(map(float,targets))
    if len(inventories)<3 or len(inventories)!=len(targets) or len(inventories)>=100_000:
        raise ValueError("Need 3..99,999 languages and one target per inventory")
    if any(v<2 for v in inventories) or any(not math.isfinite(t) or t<=0 for t in targets) or np.std(np.log(targets))<=1e-12:
        raise ValueError("Invalid inventories or targets; target spread required")
    if (not families or not pairings or not rungs or not set(families)<=set(E.FAMILIES)
            or not set(pairings)<=set(E.PAIRINGS) or not set(rungs)<=set(RUNGS)
            or any(len(x)!=len(set(x)) for x in (families,pairings,rungs))):
        raise ValueError("Invalid or duplicate grid coordinates")
    if min(n_train,n_test,line,peak_bytes,word_peak_bytes)<1 or n_train%line or n_test%line:
        raise ValueError("Positive whole-line budgets and reservation required")
    sources = [Path(__file__),Path(E.__file__),Path(E.B.__file__),Path(E.F.__file__),Path(E.M.__file__),
               Path(E.NN.__file__),Path(E.A.__file__),Path(R.__file__),HERE.parent/"stage5/f1c_reservation.json",Path(D.__file__), Path(D.SPACE.__file__)]
    config = dict(schema="f3b-words-rates-v2",families=list(families),pairings=list(pairings),rungs=list(rungs),
        inventories=inventories,targets=targets,n_train=n_train,n_test=n_test,line=line,peak_bytes=peak_bytes,
        word_peak_bytes=word_peak_bytes, run_tag=run_tag, process_cap_bytes=process_cap_bytes,
        reservation_dir=str(reservation_dir), margin_bytes=margin_bytes,
        sort_memory=sort_memory, word_sort_memory=word_sort_memory,
        lengths=LENGTHS.tolist(),target_kind="line-averaged-plain-4",cross_word="uninterrupted-lag-transition",
        boundary_signal=False,rate_seed=seed_base+3_999_998,pairing_seed=seed_base+3_999_999,
        environment=dict(python=sys.version,numpy=np.__version__,kenlm_module=hashlib.sha256(Path(E.F.kenlm.__file__).read_bytes()).hexdigest(),
            binaries={name:hashlib.sha256((Path(E.F.KENLM)/name).read_bytes()).hexdigest() for name in ("lmplz","build_binary")},
            omp_threads=os.environ.get("OMP_NUM_THREADS"),cpu_only=True),
        code=hashlib.sha256(b"".join(p.read_bytes() for p in sources)).hexdigest())
    meta,density = Path(str(prefix)+"_config.json"),Path(str(prefix)+"_densities.tsv")
    if meta.exists():
        try: saved=json.loads(meta.read_text())
        except (ValueError,UnicodeError) as exc: raise ValueError("Invalid checkpoint provenance") from exc
        if saved!=config: raise ValueError("Different configuration; use a new output prefix")
    elif density.exists() and density.read_bytes().partition(b"\n")[2]:
        raise ValueError("Saved scores require configuration provenance")
    metadata = panels(config)
    rows,tail = checkpoint(density,config,metadata)
    with D.DiskBudget(work, reservation_dir, process_cap_bytes, margin_bytes, prefix=prefix) as budget:
        return run_reserved_grid(work, prefix, config, metadata, rows, tail, budget)

def run_reserved_grid(work, prefix, config, metadata, rows, tail, resource_budget):
    n_train,n_test,line = (config[key] for key in ("n_train","n_test","line"))
    peak_bytes,word_peak_bytes = config["peak_bytes"],config["word_peak_bytes"]
    rungs = config["rungs"]
    meta,density = Path(str(prefix)+"_config.json"),Path(str(prefix)+"_densities.tsv")
    E.disk_check(1_000_000, resource_budget=resource_budget, work=Path(prefix).parent)
    work.mkdir(parents=True,exist_ok=True); prefix.parent.mkdir(parents=True,exist_ok=True)
    for directory in ("logs","tmp"): (work/directory).mkdir(exist_ok=True)
    if not meta.exists():
        tmp=Path(str(meta)+".tmp"); tmp.write_text(json.dumps(config,indent=2)+"\n"); os.replace(tmp,meta)
    if tail is not None:
        with density.open("r+b") as f: f.truncate(tail)
    done = {(r["family"],r["pairing"],r["scenario"],int(r["language"]),r["rung"]) for r in rows}
    cache = {(r["fit_key"],r["rung"]):{f:r[f] for f in ("h_est","fallback_orders","discounts","peak_work_bytes","free_bytes","oov_tokens","n_scored","zero_backoffs")} for r in rows}
    publish(prefix,rows,config,resource_budget=resource_budget)
    new = not density.exists() or not density.stat().st_size
    with density.open("a",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS,delimiter="\t",lineterminator="\n")
        if new: writer.writeheader(); f.flush()
        for key,base in metadata.items():
            pending=[rung for rung in rungs if (*key,rung) not in done]
            if not pending: continue
            p=E.F.zipf(base["vocab"])
            sigma=(np.random.default_rng(base["sigma_seed"]).permutation(len(p)) if E.FAMILIES[key[0]][1] else None)
            tr=te=None
            try:
                for rung in pending:
                    identity=fit_key(base,rung)
                    model_fit=int((identity,rung) not in cache)
                    if not model_fit: result=dict(cache[identity,rung],seconds=0)
                    else:
                        if tr is None:
                            tr=corpus(n_train,p,base["m"],base["eps"],sigma,line,base["train_seed"],base["word_train_seed"])
                            te=corpus(n_test,p,base["m"],base["eps"],sigma,line,base["test_seed"],base["word_test_seed"])
                        reserve = peak_bytes if rung in ("1","2","3","4") else word_peak_bytes
                        result=estimate(work,"_".join(map(str,(*key,rung))),tr,te,rung,line,reserve,resource_budget=resource_budget,
                                        sort_memory=config["sort_memory"],word_sort_memory=config["word_sort_memory"])
                        if "paired_h_est" in result:
                            other=rung.replace("free","charged") if rung.endswith("free") else rung.replace("charged","free")
                            cache[identity,other]=dict(result,h_est=result.pop("paired_h_est"))
                            cache[identity,other].pop("paired_h_est",None)
                        cache[identity,rung]=dict(result)
                    if te is None:
                        te=corpus(n_test,p,base["m"],base["eps"],sigma,line,base["test_seed"],base["word_test_seed"])
                    ref=truth(p,base["eps"],base["m"],rung,line,sigma)
                    oro=oracle(te,p,base["eps"],base["m"],rung,line,sigma)
                    row=dict(base,rung=rung,n_train=n_train,n_test=n_test,line=line,h_true=ref,
                        bias_bits=float(result["h_est"])-ref,oracle_bits=oro,fit_minus_oracle=float(result["h_est"])-oro,
                        model_fit=model_fit,fit_key=identity,**result)
                    E.disk_check(1_000_000, resource_budget=resource_budget, work=Path(prefix).parent)
                    writer.writerow(row); f.flush(); os.fsync(f.fileno())
                    rows.append(row); done.add((*key,rung)); publish(prefix,rows,config,resource_budget=resource_budget)
                    print(f"{' '.join(map(str,key))} {rung}: truth={ref:.6f} estimate={float(result['h_est']):.6f} fit={model_fit}",flush=True)
            finally:
                del tr,te
    summary,contrasts=publish(prefix,rows,config,resource_budget=resource_budget)
    return rows,summary,contrasts

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work"); parser.add_argument("prefix")
    parser.add_argument("--small",action="store_true")
    parser.add_argument("--families",nargs="+",choices=E.FAMILIES,default=list(E.FAMILIES))
    parser.add_argument("--pairings",nargs="+",choices=E.PAIRINGS,default=list(E.PAIRINGS))
    parser.add_argument("--rungs",nargs="+",choices=RUNGS,default=list(RUNGS))
    parser.add_argument("--inventories",nargs="+",type=int)
    parser.add_argument("--targets",nargs="+",type=float)
    parser.add_argument("--n-train",type=int); parser.add_argument("--n-test",type=int)
    parser.add_argument("--line",type=int,default=1000)
    parser.add_argument("--peak-bytes",type=int,default=1_700_000_000,
                        help="aggregate growth estimate; must be validated for a new full-scale process")
    parser.add_argument("--word-peak-bytes",type=int,default=2_700_000_000,
                        help="word-window aggregate growth estimate; F1c calibration is only a sizing reference")
    parser.add_argument("--run-tag",type=int,required=True,
                        help="unique integer 1..999999 for this run; preserve on resume; same tag across its shards")
    parser.add_argument("--process-cap-bytes",type=int,default=4_000_000_000)
    parser.add_argument("--reservation-dir",required=True,help="shared lock/ledger directory for all concurrent processes")
    parser.add_argument("--margin-bytes",type=int,default=2*D.GIB)
    parser.add_argument("--sort-memory",default="30%",help="plain lmplz -S (default unchanged)")
    parser.add_argument("--word-sort-memory",default="256M",help="word-window lmplz -S (default unchanged)")
    args=parser.parse_args()
    run_grid(args.work,args.prefix,args.families,args.inventories or ([20,40,60] if args.small else E.B.INV),
             args.targets or ([2.,2.3,2.6] if args.small else E.B.TARGET),args.pairings,args.rungs,
             args.n_train or (100_000 if args.small else E.B.N),args.n_test or (10_000 if args.small else E.F.N_TEST),
             args.line,args.peak_bytes,args.word_peak_bytes,args.run_tag,args.process_cap_bytes,
             args.reservation_dir,args.margin_bytes,args.sort_memory,args.word_sort_memory)

if __name__=="__main__": main()
