"""The fixed T1 13-fit comparison; simulated text only, sequential, resumable.

Full run (the lead runs the GPU):
  python -I -B src/fakedata/nn_compare.py --scale full --device mps
CPU smoke run:
  python -I -B src/fakedata/nn_compare.py --scale small --device cpu
Use a separate output for small runs; full defaults to results/fakedata/nn_compare_gpu.tsv.
No checkpoint files are written. Validation histories retain full precision for replay.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import argparse
import csv
import hashlib
import io
import json
import math
import os
import time
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("compare_tuning", os.path.join(HERE, "nn_tuning.py"))
T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)
NN, np, torch = T.NN, T.np, T.torch

CELLS = (("mapped", 1, 1), ("mapped", 1, 4), ("mapped", 3, 4),
         ("copy", 1, 1), ("copy", 3, 4), ("iid", 0, 4))
PAIR = ("zero_unigram_cosine5", "zero_unigram_cosine8")
STOPPING = dict(keep_best_validation=True, eval_final=True)
FIELDS = T.FIELDS + ["final_evaluated", "initial_distribution"]
FULL = dict(vocab=10000, replicate=1, n_train=10_000_000, n_val=500_000,
            n_test=1_000_000, line=1000, dim=128, hidden=512)
SMALL = dict(FULL, vocab=20, n_train=1000, n_val=200, n_test=500, line=100, dim=8, hidden=16)


def candidates(proc, m, k):
    return PAIR + (("unigram_cosine3",) if (proc, m, k) == ("copy", 3, 4) else ())


def design():
    return [(name, proc, m, k) for proc, m, k in CELLS for name in candidates(proc, m, k)]


def seeds_for(config, proc, m):
    seeds = {name: T.seed_for(config["vocab"], proc, m, config["replicate"], role)
             for name, role in (("train", 1), ("test", 2), ("val", 3), ("model", 5))}
    if proc == "mapped":
        seeds["map"] = T.seed_for(config["vocab"], "iid", 0, config["replicate"], 4)
    return seeds


def settings_for(config, name, seeds):
    return NN.SETTINGS | T.SETTINGS[name] | STOPPING | dict(
        dim=config["dim"], hidden=config["hidden"], seed=seeds["model"])


def run_config(scale, device, overrides=None):
    values = dict(FULL if scale == "full" else SMALL)
    if overrides:
        if scale == "full":
            raise ValueError("full comparison is fixed; size overrides are only for CPU smoke tests")
        values.update(overrides)
    if not 2 <= values["vocab"] <= 10000 or min(values["dim"], values["hidden"]) < 1:
        raise ValueError("invalid vocabulary or dimensions")
    if values["line"] < 5 or any(values[n] < values["line"] or values[n] % values["line"]
                                    for n in ("n_train", "n_val", "n_test")):
        raise ValueError("budgets must be positive multiples of line length; line >= 5")
    with open(__file__, "rb") as f:
        code = hashlib.sha256(f.read() + T.code_id().encode()).hexdigest()[:16]
    return dict(values, scale=scale, device=device, code=code, torch=torch.__version__,
                fits=design(), stopping=STOPPING, stationary_start=True,
                presets={name: T.SETTINGS[name] for name in (*PAIR, "unigram_cosine3")})


def run_id(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def estimated_seconds(config):
    # Decision record: roughly seven minutes for a 3-epoch 10,000-type GPU fit.
    # An epoch-cap estimate, without reductions for early stopping or setup overhead.
    return sum(settings_for(config, name, seeds_for(config, proc, m))["max_epochs"] / 3 * 420
               * config["n_train"] / FULL["n_train"] for name, proc, m, k in design())


def make_row(config, name, proc, m, k, result, seeds, href, oracle, prep_seconds, wall_seconds):
    estimate = result["test_bits"]
    row = dict(run_id=run_id(config), setting=name, proc=proc, m=m, vocab=config["vocab"], k=k,
               replicate=config["replicate"], n_train=config["n_train"], n_val=config["n_val"],
               n_test=config["n_test"], line=config["line"], h_ref=href, h_est=estimate,
               bias=estimate-href, oracle_loss=oracle, reference_loss=oracle,
               reference_kind="same_test_oracle", fit_minus_oracle=estimate-oracle,
               val_bits=result["val_bits"], seconds=result["seconds"], wall_seconds=wall_seconds,
               prep_seconds=prep_seconds, device=result["device"],
               settings=json.dumps(result["settings"], sort_keys=True),
               val_history=json.dumps(result["validation_losses"]),
               lr_history=json.dumps(result["lr_history"]), test_history="[]",
               initial_distribution="stationary" if proc == "mapped" else "zipf")
    for field in ("steps", "best_step", "epochs", "stopped_early", "stop_reason", "final_evaluated"):
        row[field] = result[field]
    for split in ("train", "test", "val", "map", "model"):
        row[split + "_seed"] = seeds.get(split, "")
    return row


def _validate_row(row, config):
    """Verify fixed coordinates, paired seeds, full-precision training replay and losses."""
    name, proc, m, k = row["setting"], row["proc"], int(row["m"]), int(row["k"])
    if (name, proc, m, k) not in design():
        raise ValueError("row is outside the 13-fit design")
    for field in ("vocab", "replicate", "n_train", "n_val", "n_test", "line"):
        if int(row[field]) != config[field]:
            raise ValueError("row disagrees with configured coordinates")
    seeds = seeds_for(config, proc, m)
    for split in ("train", "test", "val", "map", "model"):
        if row[split + "_seed"] != str(seeds.get(split, "")):
            raise ValueError("row disagrees with paired seeds")
    s = settings_for(config, name, seeds)
    stored_settings = json.loads(row["settings"], parse_constant=T._reject_json_constant)
    if (not isinstance(stored_settings, dict) or stored_settings != s
            or any(type(stored_settings[key]) is not type(value) for key, value in s.items())):
        raise ValueError("row disagrees with configured model settings")
    if row["device"] != config["device"] or row["reference_kind"] != "same_test_oracle":
        raise ValueError("invalid device or reference")
    if row["initial_distribution"] != ("stationary" if proc == "mapped" else "zipf"):
        raise ValueError("invalid initial distribution")
    for field in ("h_ref", "h_est", "bias", "oracle_loss", "reference_loss", "fit_minus_oracle",
                  "val_bits", "seconds", "wall_seconds", "prep_seconds"):
        value = float(row[field])
        if not math.isfinite(value) or (field not in ("bias", "fit_minus_oracle") and value < 0):
            raise ValueError("invalid loss or duration")
    for field, expected in (("bias", float(row["h_est"]) - float(row["h_ref"])),
                            ("fit_minus_oracle", float(row["h_est"]) - float(row["oracle_loss"])),
                            ("reference_loss", float(row["oracle_loss"]))):
        if not math.isclose(float(row[field]), expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("inconsistent reference or bias")
    validate_training(row, config, s)


def validate_training(row, config, s):
    """Replay a full-precision record with the fixed cosine/stopping options.

    Shared with the final F1 check; callers validate coordinates and settings.
    """
    per_epoch = math.ceil(config["n_train"] / s["batch"])
    total = per_epoch * s["max_epochs"]; every = max(1, per_epoch // s["evals_per_epoch"])
    steps, best_step = int(row["steps"]), int(row["best_step"])
    if not 1 <= steps <= total or int(row["epochs"]) != math.ceil(steps / per_epoch):
        raise ValueError("invalid training budget record")
    if row["stopped_early"] not in ("True", "False") or row["final_evaluated"] not in ("True", "False"):
        raise ValueError("invalid boolean metadata")
    stopped = row["stopped_early"] == "True"; final = row["final_evaluated"] == "True"
    if row["stop_reason"] != ("validation_patience" if stopped else "max_epochs") or (not stopped and steps != total):
        raise ValueError("invalid stopping reason")
    evaluation_steps = ([0] if s.get("eval_initial", False) else []) + list(range(every, steps+1, every))
    needs_final = not evaluation_steps or evaluation_steps[-1] != steps
    if final != needs_final or (final and stopped):
        raise ValueError("invalid terminal evaluation record")
    if final:
        evaluation_steps.append(steps)
    histories = {}
    for field in ("val_history", "lr_history"):
        pairs = json.loads(row[field], parse_constant=T._reject_json_constant)
        if not isinstance(pairs, list) or len(pairs) != len(evaluation_steps):
            raise ValueError("invalid history length")
        for pair, step in zip(pairs, evaluation_steps):
            if (not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int or pair[0] != step
                    or type(pair[1]) not in (int, float) or not math.isfinite(pair[1]) or pair[1] < 0):
                raise ValueError("invalid history pair")
        histories[field] = pairs
    if row["test_history"] != "[]":
        raise ValueError("comparison does not collect test traces")
    best, selected, anchor, bad = math.inf, None, math.inf, 0
    for (step, loss), (_, rate) in zip(histories["val_history"], histories["lr_history"]):
        if bad >= s["patience"]:
            raise ValueError("training continued after patience stop")
        if step == 0:
            expected_rate = s["lr"]
        else:
            phase = (step - 1) / max(1, total - 1)
            ratio = NN.OPTIONS["min_lr_ratio"] + (1-NN.OPTIONS["min_lr_ratio"]) * (1+math.cos(math.pi*phase))/2
            expected_rate = s["lr"] * ratio
        if not math.isclose(rate, expected_rate, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("invalid cosine learning rate")
        if loss < best:
            best, selected = loss, step
        if final and step == steps:
            continue
        if loss < anchor - 1e-4:
            anchor, bad = loss, 0
        else:
            bad += 1
    if selected != best_step or best != float(row["val_bits"]):
        raise ValueError("selected checkpoint is not the lowest validation loss")
    if stopped != (bad >= s["patience"]) or (stopped and evaluation_steps[-1] != steps):
        raise ValueError("invalid patience stopping record")


def resume_keys(path, config):
    """Validate all committed records before discarding an unterminated final row."""
    if not os.path.exists(path):
        return set()
    with open(path, "rb") as f:
        content = f.read()
    end = content.rfind(b"\n") + 1
    if not end:
        raise ValueError("output header is incomplete")
    tail = content[end:]; identity = run_id(config)
    if b"\t" in tail and tail.split(b"\t", 1)[0] != identity.encode():
        raise ValueError("torn row belongs to another configuration")
    try:
        reader = csv.DictReader(io.StringIO(content[:end].decode(), newline=""), delimiter="\t", strict=True)
        if reader.fieldnames != FIELDS:
            raise ValueError("output header does not match this comparison")
        done = set()
        for row in reader:
            if row.get("run_id") != identity or None in row or any(v is None for v in row.values()):
                raise ValueError("mixed configuration or incomplete committed row")
            _validate_row(row, config)
            key = (row["setting"], row["proc"], int(row["m"]), int(row["k"]))
            if key in done:
                raise ValueError("duplicate completed fit")
            done.add(key)
    except (UnicodeError, csv.Error, TypeError, KeyError, ValueError) as error:
        raise ValueError("corrupt or mixed comparison output; use its original configuration or a new file") from error
    if tail:
        with open(path, "r+b") as f:
            f.truncate(end)
    return done


def run(config, out):
    NN_device = config["device"]
    if NN_device == "cpu" and config["n_train"] > 1_000_000:
        raise ValueError("CPU runs are limited to 1M training tokens")
    if NN_device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS is unavailable; no CPU fallback")
    root = os.path.realpath(os.getcwd()); out = os.path.realpath(out)
    if os.path.commonpath((root, out)) != root:
        raise ValueError("output must remain inside the working directory")
    done = resume_keys(out, config)
    T.guard_space(out); os.makedirs(os.path.dirname(out), exist_ok=True)
    new = not os.path.exists(out); completed = 0
    torch.set_num_threads(1)
    # Interop threads are process-wide and can only be set before the first fit.
    with open(out, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        if new:
            writer.writeheader(); f.flush()
        for proc, m, k in CELLS:
            names = candidates(proc, m, k)
            if all((name, proc, m, k) in done for name in names):
                continue
            T.guard_space(out); start = time.perf_counter()
            p, sigma, seeds, tr, va, te = T.prepare(config["vocab"], proc, m, config["replicate"],
                                                 config["n_train"], config["n_val"], config["n_test"],
                                                 config["line"], stationary_start=True)
            prep_seconds = time.perf_counter() - start
            href, oracle, _ = T.references(proc, m, p, te, k, config["line"], sigma, mapped_oracle=True)
            for name in names:
                if (name, proc, m, k) in done:
                    continue
                T.guard_space(out); start = time.perf_counter()
                result = NN.estimate(tr, va, te, config["vocab"], k, device=NN_device,
                                     settings=settings_for(config, name, seeds), tuning=True)
                row = make_row(config, name, proc, m, k, result, seeds, href, oracle, prep_seconds,
                               time.perf_counter() - start)
                _validate_row({key: str(value) for key, value in row.items()}, config)
                T.guard_space(out)
                writer.writerow(row); f.flush(); os.fsync(f.fileno())
                done.add((name, proc, m, k)); completed += 1
                print(f"{proc}{m} k={k} {name}: bias {row['bias']:+.6f}, fit-oracle {row['fit_minus_oracle']:+.6f}, "
                      f"selected {row['best_step']}/{row['steps']}, epochs {row['epochs']}, "
                      f"final_evaluated={row['final_evaluated']}, {row['seconds']}s", flush=True)
                del result
                if NN_device == "mps":
                    torch.mps.empty_cache()
            del tr, va, te
    print(f"done: {completed} new fits, {len(done)}/13 total", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=("small", "full"), default="small")
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--out")
    for name in ("vocab", "n_train", "n_val", "n_test", "line", "dim", "hidden"):
        parser.add_argument("--" + name.replace("_", "-"), type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    overrides = {key: getattr(args, key) for key in SMALL if key != "replicate" and getattr(args, key, None) is not None}
    try:
        config = run_config(args.scale, args.device, overrides)
        print(f"run {run_id(config)}: 13 fits, replicate 1; GPU epoch-cap estimate "
              f"{estimated_seconds(config)/3600:.2f}h, excludes setup; no candidate selected", flush=True)
        print(f"seed audit: existing maximum {max(T.existing_seeds())}; comparison minimum "
              f"{min(seed for proc, m, k in CELLS for seed in seeds_for(config, proc, m).values())}", flush=True)
        if args.dry_run:
            print(json.dumps(config, sort_keys=True)); return
        out = args.out or ("results/fakedata/nn_compare_gpu.tsv" if args.scale == "full"
                           else "results/fakedata/nn_compare_cpu.tsv")
        torch.set_num_interop_threads(1)
        run(config, out)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
