"""Sequential fake-data tuning sweep for notes/multiverse-spec.md §§2.2a, 3a.

Seeds are 1,000,000,000 + replicate*1,000,000 + vocab*50 + cell*8 + role. Replicates
are 0..999, vocabularies 2..10,000, cells 0..4 and roles 1..5 (train/test/val/map/model).
Cell+role occupies less than 50; vocab+cell+role less than 1,000,000. Thus distinct
coordinates cannot collide. All declared seeds in the existing fake-data drivers are below
20,261,010; tuning seeds lie in [1,000,000,101, 1,999,500,037]. Arbitrary undeclared
arguments to an old script are outside that claim. Mapped lags share one permutation on purpose.

Default full design: four settings, 20 cells, one paired replicate. No setting is selected here.
Models and arrays stay in memory; only a compact resumable TSV is written. CPU runs are limited
to 1M training tokens. Test traces are opt-in and never used to select a checkpoint.
Usage: python -I src/fakedata/nn_tuning.py --out OUT.tsv --scale small --device cpu
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import argparse, csv, hashlib, importlib.util, io, json, math, os, shutil, subprocess, time
import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
def load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
F = load("f1v2", os.path.join(HERE, "f1v2.py"))
M = load("f1_mapped", os.path.join(HERE, "f1_mapped.py"))
SPACE = load("tuning_disk_space", os.path.join(HERE, "..", "stage5", "disk_space.py"))
NN = load("nnlm", os.path.join(HERE, "..", "stage5", "nnlm.py"))
CELLS = (("iid", 0), ("copy", 1), ("copy", 3), ("mapped", 1), ("mapped", 3))
LABELS = ("iid", "copy1", "copy3", "mapped1", "mapped3")
SETTINGS = {
    "baseline3": {},
    "long4": dict(max_epochs=4),
    "unigram_cosine3": dict(bias_init="unigram", schedule="cosine", patience=8),
    "zero_unigram_cosine5": dict(max_epochs=5, bias_init="unigram", context_init="zero", eval_initial=True, schedule="cosine", patience=8),
    "cosine3": dict(schedule="cosine", patience=8),
    "unigram3": dict(bias_init="unigram"),
    "zero_unigram3": dict(bias_init="unigram", context_init="zero", eval_initial=True, patience=8),
    "plateau6": dict(max_epochs=6, schedule="plateau", patience=8, plateau_patience=2),
    "long6": dict(max_epochs=6),
    "zero_unigram_cosine6": dict(max_epochs=6, bias_init="unigram", context_init="zero", eval_initial=True, schedule="cosine", patience=8),
    "zero_unigram_cosine8": dict(max_epochs=8, bias_init="unigram", context_init="zero", eval_initial=True, schedule="cosine", patience=8),
}
DEFAULT_SETTINGS = tuple(SETTINGS)[:4]
FIELDS = ["run_id", "setting", "proc", "m", "vocab", "k", "replicate", "n_train", "n_val", "n_test", "line",
          "train_seed", "test_seed", "val_seed", "map_seed", "model_seed", "h_ref", "h_est", "bias", "oracle_loss",
          "reference_loss", "reference_kind", "fit_minus_oracle", "val_bits", "steps", "best_step", "epochs",
          "stopped_early", "stop_reason", "seconds", "wall_seconds", "prep_seconds", "device", "settings",
          "val_history", "lr_history", "test_history"]

def seed_for(vocab, proc, m, replicate, role):
    """Use a bounded, injective namespace apart from all declared check seeds."""
    if not 2 <= vocab <= 10000 or not 0 <= replicate <= 999 or not 1 <= role <= 5:
        raise ValueError("seed coordinates outside reserved bounds")
    return 1_000_000_000 + replicate * 1_000_000 + vocab * 50 + CELLS.index((proc, m)) * 8 + role

def existing_seeds():
    """Enumerate declared seeds, including model, mapping and consistency-check seeds."""
    seeds = {0, 1, 5, 7, 8, 11, 20261009}
    seeds.update(range(500))                       # F3a's declared replicates and bootstrap seeds
    seeds.update(900 + v for v in F.VOCABS)         # F1 mapped permutations
    for v in F.VOCABS:
        for proc, m in F.PROCS:
            for rep in (1, 2, 3):
                base = 100000 * rep + 1000 * m + F.VOCABS.index(v) * 10 + (proc != "iid")
                seeds.update(base + j for j in (1, 2, 3))
        for m in (1, 3):
            base = 5_000_000 + 1000 * m + F.VOCABS.index(v) * 10
            seeds.update(base + j for j in (1, 2, 3))
    for i in range(17):
        seeds.update((7000 + 10 * i, 8000 + 10 * i))
    for m in range(5):
        seeds.update(a + m for a in (1000, 2000, 3000, 4000))
    return seeds

def references(proc, m, p, test, k, line, sigma=None, *, mapped_oracle=False):
    """Population line-aware entropy and same-test copy oracle; mapped rows use stationary truth."""
    if proc == "mapped":
        pi = M.stationary(p, sigma, F.EPS)
        hp = F.h_marg(pi); hc = float(np.sum(pi * M.h_rows(p, sigma, F.EPS)))
        ref = float(np.mean([hp if min(k, j) < m else hc for j in range(line)]))
        if mapped_oracle:
            x = test.ravel(); q = pi[x].copy()
            have = np.minimum(k, np.arange(len(x)) % line) >= m
            indices = np.flatnonzero(have)
            q[have] = F.EPS * p[x[have]] + (1 - F.EPS) * (x[have] == sigma[x[indices - m]])
            return ref, float(-np.log2(q).mean()), "same_test_oracle"
        return ref, ref, "mapped_truth"
    ref = F.h_ref(p, k, m, line)
    x = test.ravel(); q = p[x].copy()
    if m:
        prev = np.empty_like(x); prev[:m] = -1; prev[m:] = x[:-m]
        have = np.minimum(k, np.arange(len(x)) % line) >= m
        q[have] = F.EPS * p[x[have]] + (1 - F.EPS) * (x[have] == prev[have])
    return ref, float(-np.log2(q).mean()), "same_test_oracle"

def prepare(vocab, proc, m, replicate, n_train, n_val, n_test, line, *, stationary_start=False):
    """Pair all settings on identical simulated splits and a shared mapping across lags."""
    p = F.zipf(vocab)
    seeds = {name: seed_for(vocab, proc, m, replicate, role) for name, role in (("train", 1), ("test", 2), ("val", 3), ("model", 5))}
    sigma = None
    if proc == "mapped":
        seeds["map"] = seed_for(vocab, "iid", 0, replicate, 4)
        sigma = np.random.default_rng(seeds["map"]).permutation(vocab)
    def simulate(n, seed):
        x = M.simulate(n, p, m, sigma, seed, stationary_start=stationary_start) if proc == "mapped" else F.simulate(n, p, m, seed)
        return x.reshape(-1, line)
    return p, sigma, seeds, simulate(n_train, seeds["train"]), simulate(n_val, seeds["val"]), simulate(n_test, seeds["test"])

def guard_space(work, reserve=1_000_000, limit=3 * 1024 ** 3):
    """Check the run's explicit output file or work directory before fitting/writing."""
    if reserve < 0:
        raise ValueError("reserve must be nonnegative")
    free = shutil.disk_usage(SPACE.existing_directory(work)).free
    if free - reserve < 42 * 1024 ** 3:
        raise RuntimeError("free space would fall below 42 GiB; no next cell started")
    def measure(path):
        return int(subprocess.check_output(["du", "-sk", str(path)], text=True).split()[0]) * 1024 if os.path.exists(path) else 0
    SPACE.check_data(work, reserve, measure)
    size = measure(work)
    if size + reserve >= limit:
        raise RuntimeError("working directory would exceed 3 GiB; no next cell started")

def code_id():
    paths = (__file__, F.__file__, M.__file__, NN.__file__, SPACE.__file__)
    digest = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as source:
            digest.update(source.read())
    return digest.hexdigest()[:16]

def _reject_json_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)

def _validate_training_record(row):
    """Check the saved writer schema and relationships without refitting the model."""
    settings = json.loads(row["settings"], parse_constant=_reject_json_constant)
    expected = NN.SETTINGS | SETTINGS[row["setting"]]
    if not isinstance(settings, dict) or set(settings) - (set(expected) | {"record_test"}) or set(expected) - set(settings):
        raise ValueError("invalid settings schema")
    for name, value in settings.items():
        default = (NN.SETTINGS | NN.OPTIONS)[name]
        if isinstance(default, bool):
            valid = type(value) is bool
        elif isinstance(default, int):
            valid = type(value) is int and value >= (0 if name == "seed" else 1)
        elif isinstance(default, float):
            valid = type(value) in (int, float) and math.isfinite(value) and value > 0
        else:
            valid = type(value) is str
        if not valid:
            raise ValueError("invalid setting value")
        if name not in ("dim", "hidden", "seed", "record_test") and value != expected[name]:
            raise ValueError("settings disagree with selected preset")
    if settings["seed"] != int(row["model_seed"]) or ("record_test" in settings and settings["record_test"] is not True):
        raise ValueError("invalid model seed or trace setting")
    steps = int(row["steps"]); best_step = int(row["best_step"])
    per_epoch = math.ceil(int(row["n_train"]) / settings["batch"])
    if not 0 <= best_step <= steps <= per_epoch * settings["max_epochs"] or int(row["epochs"]) != math.ceil(steps / per_epoch):
        raise ValueError("invalid step or epoch record")
    stopped = row["stopped_early"] == "True"
    if row["stop_reason"] != ("validation_patience" if stopped else "max_epochs") or (not stopped and steps != per_epoch * settings["max_epochs"]):
        raise ValueError("inconsistent stopping record")
    histories = {}
    for field in ("val_history", "lr_history", "test_history"):
        values = json.loads(row[field], parse_constant=_reject_json_constant)
        if not isinstance(values, list):
            raise ValueError("invalid history container")
        previous = -1
        for pair in values:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("invalid history entry")
            step, value = pair
            if type(step) is not int or not previous < step <= steps or type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("invalid history step or value")
            if field == "lr_history" and value <= 0:
                raise ValueError("nonpositive learning rate")
            previous = step
        histories[field] = values
    every = max(1, per_epoch // settings["evals_per_epoch"])
    evaluation_steps = ([0] if settings.get("eval_initial", False) else []) + list(range(every, steps + 1, every))
    for field in ("val_history", "lr_history"):
        if [pair[0] for pair in histories[field]] != evaluation_steps:
            raise ValueError("history disagrees with evaluation schedule")
    if [pair[0] for pair in histories["test_history"]] != (evaluation_steps if settings.get("record_test", False) else []):
        raise ValueError("test history disagrees with trace setting")
    validation = dict(histories["val_history"])
    if best_step not in validation or not math.isclose(validation[best_step], float(row["val_bits"]), rel_tol=0, abs_tol=5.1e-6):
        raise ValueError("checkpoint disagrees with validation record")
    if settings.get("record_test", False) and not math.isclose(
            dict(histories["test_history"])[best_step], float(row["h_est"]), rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("test estimate disagrees with retained checkpoint trace")
    _validate_training_replay(row, NN.OPTIONS | settings, histories, per_epoch)


def _validate_training_replay(row, settings, histories, per_epoch):
    """Reject impossible training traces, allowing the writer's loss rounding.

    Validation history rounds to five decimals. Keep both feasible improvement
    decisions near 1e-4 instead of changing that threshold or rejecting a valid
    unrounded trace. The selected checkpoint's final loss is unrounded.
    """
    # State: selected step, possible best-loss interval, patience counters, LR.
    states = {(None, math.inf, math.inf, 0, 0, settings["lr"])}
    total = per_epoch * settings["max_epochs"]
    for (step, loss), (_, recorded_lr) in zip(histories["val_history"], histories["lr_history"]):
        lower, upper = max(0.0, loss - 5.1e-6), loss + 5.1e-6
        if step == int(row["best_step"]):
            lower = upper = float(row["val_bits"])
        following = set()
        for selected, best_lo, best_hi, bad, lr_bad, rate in states:
            if bad >= settings["patience"]:
                continue  # The writer would already have stopped.
            if step and settings["schedule"] == "cosine":
                update = step - 1; warm = settings["warmup_steps"]
                if update < warm:
                    ratio = (update + 1) / warm
                else:
                    phase = (update - warm) / max(1, total - warm - 1)
                    ratio = settings["min_lr_ratio"] + (1 - settings["min_lr_ratio"]) * (1 + math.cos(math.pi * phase)) / 2
                rate = settings["lr"] * ratio
            if not math.isclose(rate, recorded_lr, rel_tol=1e-12, abs_tol=1e-15):
                continue
            branches = []
            if selected is None or lower < best_hi - 1e-4:
                branches.append((step, lower, min(upper, best_hi - 1e-4), 0, 0))
            if selected is not None and upper >= best_lo - 1e-4:
                branches.append((selected, best_lo, min(best_hi, upper + 1e-4), bad + 1, lr_bad + 1))
            for chosen, lo, hi, patience, lr_patience in branches:
                if lo > hi:
                    continue
                next_rate = rate
                if settings["schedule"] == "plateau" and lr_patience >= settings["plateau_patience"]:
                    next_rate = max(settings["lr"] * settings["min_lr_ratio"], rate * settings["plateau_factor"])
                    lr_patience = 0
                following.add((chosen, lo, hi, patience, lr_patience, next_rate))
        states = following
        if not states:
            raise ValueError("history contradicts checkpoint, patience or learning-rate schedule")
    stopped = row["stopped_early"] == "True"
    if not any(selected == int(row["best_step"]) and (bad >= settings["patience"]) == stopped
               for selected, _, _, bad, _, _ in states):
        raise ValueError("impossible checkpoint selection or patience stopping")
    if stopped and histories["val_history"][-1][0] != int(row["steps"]):
        raise ValueError("patience stop must coincide with the last evaluation")

def resume_keys(path, run_id):
    """Validate committed rows, then discard an unterminated final record for retry.

    The writer's terminal newline commits a row. Validate the complete prefix before
    repairing anything; corruption or another configuration must leave the file intact.
    """
    if not os.path.exists(path):
        return set()
    with open(path, "rb") as f:
        content = f.read()
    end = content.rfind(b"\n") + 1
    if not end:
        raise ValueError("output header is incomplete")
    tail = content[end:]
    if b"\t" in tail and tail.split(b"\t", 1)[0] != run_id.encode():
        raise ValueError("output contains another configuration; use a new output")
    try:
        reader = csv.DictReader(io.StringIO(content[:end].decode(), newline=""), delimiter="\t", strict=True)
        if reader.fieldnames != FIELDS:
            raise ValueError("output header does not match this sweep")
        rows = list(reader)
    except (UnicodeError, csv.Error) as e:
        raise ValueError("output contains a corrupt complete record") from e
    if any(r.get("run_id") != run_id or any(v is None for v in r.values()) or None in r for r in rows):
        raise ValueError("output contains another configuration or an incomplete row; use a new output")
    try:
        integers = ("m", "vocab", "k", "replicate", "n_train", "n_val", "n_test", "line",
                    "train_seed", "test_seed", "val_seed", "model_seed", "steps", "best_step", "epochs")
        reals = ("h_ref", "h_est", "bias", "reference_loss", "fit_minus_oracle", "val_bits", "seconds",
                 "wall_seconds", "prep_seconds")
        for r in rows:
            for field in integers:
                if int(r[field]) < 0:
                    raise ValueError("negative integer field")
            for field in reals:
                if not math.isfinite(float(r[field])):
                    raise ValueError("nonfinite result")
                if field not in ("bias", "fit_minus_oracle") and float(r[field]) < 0:
                    raise ValueError("negative loss or duration")
            if r["proc"] == "mapped":
                int(r["map_seed"])
                if r["reference_kind"] != "mapped_truth" or r["oracle_loss"] != "":
                    raise ValueError("invalid mapped reference")
            elif r["reference_kind"] != "same_test_oracle" or not math.isfinite(float(r["oracle_loss"])) or float(r["oracle_loss"]) < 0:
                raise ValueError("invalid oracle reference")
            if r["setting"] not in SETTINGS or (r["proc"], int(r["m"])) not in CELLS:
                raise ValueError("unknown setting or process")
            if int(r["k"]) not in (1, 4) or not 2 <= int(r["vocab"]) <= 10000 or not 0 <= int(r["replicate"]) <= 999:
                raise ValueError("invalid coordinates")
            if any(int(r[f]) < 1 for f in ("n_train", "n_val", "n_test", "line", "steps", "epochs")):
                raise ValueError("invalid size or training record")
            if r["stopped_early"] not in ("True", "False") or r["stop_reason"] not in ("max_epochs", "validation_patience") or r["device"] not in ("cpu", "mps"):
                raise ValueError("invalid training metadata")
            if any(int(r[f]) % int(r["line"]) for f in ("n_train", "n_val", "n_test")):
                raise ValueError("split size is not a multiple of line length")
            for field, expected in (("bias", float(r["h_est"]) - float(r["h_ref"])),
                                    ("fit_minus_oracle", float(r["h_est"]) - float(r["reference_loss"])),
                                    ("reference_loss", float(r["h_ref"] if r["proc"] == "mapped" else r["oracle_loss"]))):
                if not math.isclose(float(r[field]), expected, rel_tol=1e-9, abs_tol=1e-9):
                    raise ValueError("inconsistent result fields")
            _validate_training_record(r)
    except (ValueError, TypeError) as e:
        raise ValueError("output contains a corrupt complete row; use a new output") from e
    keys = [(r["setting"], r["proc"], r["m"], r["vocab"], r["k"], r["replicate"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate completed rows")
    if tail:
        with open(path, "r+b") as f:
            f.truncate(end)
    return set(keys)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scale", choices=("small", "full"), default="small")
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--vocabs", type=int, nargs="+")
    parser.add_argument("--n-train", type=int); parser.add_argument("--n-val", type=int); parser.add_argument("--n-test", type=int)
    parser.add_argument("--line", type=int, default=1000)
    parser.add_argument("--ks", type=int, nargs="+", choices=(1, 4), default=[1, 4])
    parser.add_argument("--processes", choices=LABELS, nargs="+", default=list(LABELS))
    parser.add_argument("--settings", choices=tuple(SETTINGS), nargs="+", default=list(DEFAULT_SETTINGS))
    parser.add_argument("--replicates", type=int, nargs="+", default=[0])
    parser.add_argument("--dim", type=int); parser.add_argument("--hidden", type=int)
    parser.add_argument("--record-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-seconds", type=float, default=21600)
    parser.add_argument("--large-ratio", type=float, default=6.0, help="CPU-measured 10,000/600-type ratio, assumed transferable to MPS")
    args = parser.parse_args()
    full = args.scale == "full"
    vlist = args.vocabs or ([600, 10000] if full else [20, 600])
    n_train = args.n_train or (10_000_000 if full else 100_000)
    n_val = args.n_val or (500_000 if full else 20_000); n_test = args.n_test or (1_000_000 if full else 50_000)
    dim = args.dim if args.dim is not None else (128 if full else 32)
    hidden = args.hidden if args.hidden is not None else (512 if full else 128)
    for value in (vlist, args.ks, args.processes, args.settings, args.replicates):
        if len(value) != len(set(value)):
            parser.error("duplicate coordinates")
    if args.line < 5 or any(n < args.line or n % args.line for n in (n_train, n_val, n_test)):
        parser.error("token budgets must be positive multiples of line length; line >= 5")
    if not args.max_seconds > 0 or not args.large_ratio > 0 or min(dim, hidden) < 1:
        parser.error("time, ratio and dimensions must be positive")
    for v in vlist:
        for rep in args.replicates:
            seed_for(v, "iid", 0, rep, 1)
    if args.device == "cpu" and n_train > 1_000_000 and not args.dry_run:
        parser.error("CPU runs are limited to 1M training tokens")
    root = os.path.realpath(os.getcwd()); out = os.path.realpath(args.out)
    if os.path.commonpath((root, out)) != root:
        parser.error("output must remain inside the working directory")
    config = dict(code=code_id(), torch=torch.__version__, device=args.device, vocabs=vlist, ks=args.ks,
                  processes=args.processes, settings={name: SETTINGS[name] for name in args.settings}, replicates=args.replicates,
                  n_train=n_train, n_val=n_val, n_test=n_test, line=args.line, dim=dim, hidden=hidden, record_test=args.record_test)
    run_id = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]
    hours = sum(60 * (NN.SETTINGS | SETTINGS[name])["max_epochs"] / 3 * (args.large_ratio if v > 600 else 1)
                * n_train / 10_000_000 for name in args.settings for v in vlist for _ in args.processes for _ in args.ks for _ in args.replicates) / 3600
    print(f"run {run_id}: {len(args.settings)*len(vlist)*len(args.processes)*len(args.ks)*len(args.replicates)} rows; assumed upper-budget training time {hours:.2f}h (excludes traces/setup)", flush=True)
    print(f"seed audit: existing maximum {max(existing_seeds())}; tuning namespace starts at 1000000101", flush=True)
    if args.dry_run:
        print(json.dumps(config, sort_keys=True), flush=True); return
    if args.device == "mps" and not torch.backends.mps.is_available():
        parser.error("MPS is unavailable; no CPU fallback for a full run")
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    guard_space(out); os.makedirs(os.path.dirname(out), exist_ok=True)
    done = resume_keys(out, run_id); new = not os.path.exists(out); t0 = time.perf_counter(); completed = 0
    with open(out, "a", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        if new:
            wr.writeheader(); f.flush()
        for rep in args.replicates:
            for v in vlist:
                for label in args.processes:
                    proc, m = CELLS[LABELS.index(label)]
                    key = lambda name, k: (name, proc, str(m), str(v), str(k), str(rep))
                    if all(key(name, k) in done for name in args.settings for k in args.ks):
                        continue
                    guard_space(out); prep0 = time.perf_counter()
                    p, sigma, seeds, tr, va, te = prepare(v, proc, m, rep, n_train, n_val, n_test, args.line)
                    prep_seconds = time.perf_counter() - prep0
                    for k in args.ks:
                        href, reference, kind = references(proc, m, p, te, k, args.line, sigma)
                        for name in args.settings:
                            if key(name, k) in done:
                                continue
                            settings = dict(SETTINGS[name], dim=dim, hidden=hidden, seed=seeds["model"])
                            if args.record_test:
                                settings["record_test"] = True
                            predicted = 60 * (NN.SETTINGS | settings)["max_epochs"] / 3 * (args.large_ratio if v > 600 else 1) * n_train / 10_000_000
                            if time.perf_counter() - t0 + predicted > args.max_seconds:
                                print(f"launch budget reached; {completed} new rows, resume with the same command", flush=True); return
                            guard_space(out); wall0 = time.perf_counter()
                            r = NN.estimate(tr, va, te, v, k, device=args.device, settings=settings, tuning=True)
                            row = dict(run_id=run_id, setting=name, proc=proc, m=m, vocab=v, k=k, replicate=rep,
                                       n_train=tr.size, n_val=va.size, n_test=te.size, line=args.line,
                                       h_ref=href, h_est=r["test_bits"], bias=r["test_bits"] - href,
                                       oracle_loss=reference if kind == "same_test_oracle" else "", reference_loss=reference,
                                       reference_kind=kind, fit_minus_oracle=r["test_bits"] - reference, val_bits=r["val_bits"],
                                       steps=r["steps"], best_step=r["best_step"], epochs=r["epochs"], stopped_early=r["stopped_early"],
                                       stop_reason=r["stop_reason"], seconds=r["seconds"], wall_seconds=time.perf_counter() - wall0,
                                       prep_seconds=prep_seconds, device=r["device"], settings=json.dumps(r["settings"], sort_keys=True),
                                       val_history=json.dumps(r["history"]), lr_history=json.dumps(r["lr_history"]),
                                       test_history=json.dumps(r.get("test_history", [])))
                            for split in ("train", "test", "val", "map", "model"):
                                row[split + "_seed"] = seeds.get(split, "")
                            guard_space(out)
                            wr.writerow(row); f.flush(); done.add(key(name, k)); completed += 1
                            print(f"{name} {proc}{m} V={v} k={k}: bias {row['bias']:+.5f}, gap {row['fit_minus_oracle']:+.5f}, {r['steps']} steps, {r['seconds']}s, {r['stop_reason']}", flush=True)
                    del tr, va, te
                    if args.device == "mps":
                        torch.mps.empty_cache()
    print(f"done: {completed} new rows, {len(done)} total", flush=True)

if __name__ == "__main__":
    main()
