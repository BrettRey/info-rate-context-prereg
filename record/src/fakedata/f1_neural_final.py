"""Final neural F1: fixed zero_unigram_cosine5, simulated check text only.

Full run (lead's GPU): python -I -B src/fakedata/f1_neural_final.py --scale full --device mps
CPU smoke: python -I -B src/fakedata/f1_neural_final.py --scale small --device cpu
84 full cells: iid/copy lags 1–4 plus stationary mapped lags 1/3, three inventories,
k=1–4. Copy/iid splits and seeds reproduce f1_neural.py; mapped seeds/permutations
reproduce f1_mapped.py with stationary_start=True for seed 1. --seed selects 1/2/3;
copy/iid text matches KenLM F1v2, and mapped split seeds are separate per seed.
The permutation and model seed stay fixed. No error bound.
No test traces or checkpoint files. Resume requires identical code/configuration.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("final_compare", os.path.join(HERE, "nn_compare.py"))
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
T, NN, np, torch = C.T, C.NN, C.np, C.torch
F, M = T.F, T.M
SETTING = "zero_unigram_cosine5"
CELLS = F.PROCS + (("mapped", 1), ("mapped", 3))
FULL = dict(vocabs=F.VOCABS, seed=1, n_train=10_000_000, n_val=500_000,
            n_test=F.N_TEST, line=1000, dim=128, hidden=512)
SMALL = dict(FULL, vocabs=(7, 11, 20), n_train=1000, n_val=200, n_test=500,
             line=100, dim=8, hidden=16)
CHECK_TOLERANCE = 1e-6
FIELDS = C.FIELDS + ["estimator", "seed", "oracle_disc", "check1_max_error"]


def design(config):
    return [(proc, m, v, k) for v in config["vocabs"] for proc, m in CELLS for k in range(1, 5)]


def seeds_for(config, proc, m, vocab):
    index = list(config["vocabs"]).index(vocab)
    if proc == "mapped":
        # Preserve seed 1 exactly; reserve 6M/7M for the new mapped splits.
        # These are below the entire tuning namespace (>= 1 billion).
        base = 5_000_000 + (config["seed"]-1)*1_000_000 + 1000*m + index*10
    else:
        base = 100000*config["seed"] + 1000*m + index*10 + (proc != "iid")
    seeds = {name: base+offset for name, offset in (("train", 1), ("test", 2), ("val", 3))}
    # Original F1 neural used NN.SETTINGS's seed=0 for every model.
    seeds["model"] = 0
    if proc == "mapped":
        seeds["map"] = 900 + vocab
    return seeds


def settings_for(config):
    return NN.SETTINGS | NN.OPTIONS | T.SETTINGS[SETTING] | C.STOPPING | dict(
        dim=config["dim"], hidden=config["hidden"], seed=0)


def run_config(scale, device, overrides=None, *, seed=1):
    if scale not in ("small", "full") or device not in ("cpu", "mps"):
        raise ValueError("unknown scale or device")
    values = dict(FULL if scale == "full" else SMALL, seed=seed)
    if overrides:
        if scale == "full":
            raise ValueError("full F1 design is fixed; overrides are only for CPU smoke tests")
        if set(overrides) - set(SMALL):
            raise ValueError("unknown size override")
        values.update(overrides)
    values["vocabs"] = tuple(values["vocabs"])
    if (not values["vocabs"] or len(set(values["vocabs"])) != len(values["vocabs"])
            or any(not 2 <= v <= 10000 for v in values["vocabs"])
            or min(values["dim"], values["hidden"]) < 1
            or type(values["seed"]) is not int or values["seed"] not in (1, 2, 3)):
        raise ValueError("invalid inventories, dimensions or check seed")
    if values["line"] < 5 or any(values[n] < values["line"] or values[n] % values["line"]
                                    for n in ("n_train", "n_val", "n_test")):
        raise ValueError("budgets must be positive multiples of line length; line >= 5")
    digest = hashlib.sha256()
    for path in (__file__, C.__file__):
        with open(path, "rb") as f:
            digest.update(f.read())
    digest.update(T.code_id().encode())
    return dict(values, scale=scale, device=device, code=digest.hexdigest()[:16],
                torch=torch.__version__, setting=SETTING, settings=settings_for(values),
                stationary_start=True, check1_tolerance=CHECK_TOLERANCE)


run_id = C.run_id


def prepare(config, proc, m, vocab):
    p = F.zipf(vocab); seeds = seeds_for(config, proc, m, vocab)
    sigma = np.random.default_rng(seeds["map"]).permutation(vocab) if proc == "mapped" else None
    def split(name, count):
        if proc == "mapped":
            x = M.simulate(count, p, m, sigma, seeds[name], stationary_start=True)
        else:
            x = F.simulate(count, p, m, seeds[name])
        return x.reshape(-1, config["line"])
    return p, sigma, seeds, split("train", config["n_train"]), split("val", config["n_val"]), split("test", config["n_test"])


def scorer_check():
    """Exercise estimate with final controls, comparing every scorer call to a
    float64 explicit sum over all outcomes, including the restored checkpoint.
    Contexts are independently constructed with line-start padding. CPU only.
    """
    torch.set_num_threads(1)
    splits = [np.random.default_rng(seed).integers(0, 3, (2, 5), dtype=np.int64)
              for seed in (7, 8, 11)]
    original = NN._loss_bits; errors = []
    s = settings_for(dict(dim=4, hidden=8))
    for k in (1, 4):
        expected = {}
        for data in splits[1:]:
            contexts = [[3]*max(0, k-j) + list(line[max(0, j-k):j])
                        for line in data for j in range(len(line))]
            expected[data.ravel().tobytes()] = np.asarray(contexts, dtype=np.int64)
        def checked(model, targets, contexts, device, batch, return_count=False):
            if not np.array_equal(contexts, expected[targets.tobytes()]):
                raise ValueError("check (1) failed: context/line padding differs")
            result = original(model, targets, contexts, device, batch, return_count=return_count)
            scored = result[0] if return_count else result
            total = 0.0
            with torch.no_grad():
                for token, context in zip(targets, contexts):
                    logits = model(torch.as_tensor(context[None, :], device=device)).detach().cpu().numpy()[0].astype(np.float64)
                    weights = np.exp(logits - logits.max())
                    probability = weights[int(token)] / sum(float(w) for w in weights)
                    total -= math.log2(probability)
            error = abs(scored - total / len(targets)); errors.append(error)
            if not math.isfinite(error) or error > CHECK_TOLERANCE:
                raise ValueError(f"check (1) failed: direct-sum discrepancy {error} bits")
            return result
        with mock.patch.object(NN, "_loss_bits", side_effect=checked):
            NN.estimate(*splits, 3, k, device="cpu", settings=s)
    return max(errors)


def make_row(config, proc, m, vocab, k, result, seeds, ref, oracle, prep_seconds, wall_seconds, check_error):
    row = C.make_row(dict(config, vocab=vocab, replicate=1), SETTING, proc, m, k,
                     result, seeds, ref, oracle, prep_seconds, wall_seconds)
    row.update(run_id=run_id(config), estimator="ffnn", seed=config["seed"],
               oracle_disc=oracle-ref, check1_max_error=check_error)
    return row


def row_key(row):
    return row["proc"], int(row["m"]), int(row["vocab"]), int(row["k"])


def validate_row(row, config):
    proc, m, vocab, k = row_key(row)
    if (proc, m, vocab, k) not in design(config) or row["setting"] != SETTING or row["estimator"] != "ffnn":
        raise ValueError("row is outside the fixed F1 design")
    if int(row["seed"]) != config["seed"] or int(row["replicate"]) != 1:
        raise ValueError("invalid check seed")
    for name in ("n_train", "n_val", "n_test", "line"):
        if int(row[name]) != config[name]:
            raise ValueError("row disagrees with budgets")
    seeds = seeds_for(config, proc, m, vocab)
    for name in ("train", "test", "val", "map", "model"):
        if row[name+"_seed"] != str(seeds.get(name, "")):
            raise ValueError("row disagrees with check seeds")
    s = settings_for(config)
    stored = json.loads(row["settings"], parse_constant=T._reject_json_constant)
    if (not isinstance(stored, dict) or stored != s
            or any(type(stored[key]) is not type(value) for key, value in s.items())):
        raise ValueError("row disagrees with fixed model settings")
    if row["device"] != config["device"] or row["reference_kind"] != "same_test_oracle":
        raise ValueError("invalid device/reference")
    if row["initial_distribution"] != ("stationary" if proc == "mapped" else "zipf"):
        raise ValueError("invalid initial distribution")
    for name in ("h_ref", "h_est", "bias", "oracle_loss", "reference_loss", "fit_minus_oracle",
                 "oracle_disc", "val_bits", "seconds", "wall_seconds", "prep_seconds", "check1_max_error"):
        value = float(row[name])
        if not math.isfinite(value) or (name not in ("bias", "fit_minus_oracle", "oracle_disc") and value < 0):
            raise ValueError("invalid loss or duration")
    if float(row["check1_max_error"]) > CHECK_TOLERANCE:
        raise ValueError("failed scorer check")
    for name, expected in (("bias", float(row["h_est"])-float(row["h_ref"])),
                           ("fit_minus_oracle", float(row["h_est"])-float(row["oracle_loss"])),
                           ("oracle_disc", float(row["oracle_loss"])-float(row["h_ref"])),
                           ("reference_loss", float(row["oracle_loss"]))):
        if not math.isclose(float(row[name]), expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("inconsistent oracle/bias")
    p = F.zipf(vocab)
    sigma = np.random.default_rng(seeds["map"]).permutation(vocab) if proc == "mapped" else None
    # Validate the inexpensive population truth; do not regenerate million-token splits on resume.
    ref, _, _ = T.references(proc, m, p, np.zeros((1, config["line"]), dtype=np.int64),
                             k, config["line"], sigma, mapped_oracle=True)
    if not math.isclose(float(row["h_ref"]), ref, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("invalid population reference")
    C.validate_training(row, config, s)


def resume_keys(path, config):
    """Validate every complete record before repairing an unterminated last row."""
    if not os.path.exists(path):
        return set()
    with open(path, "rb") as f:
        content = f.read()
    end = content.rfind(b"\n") + 1
    if not end:
        raise ValueError("incomplete output header")
    tail = content[end:]; identity = run_id(config)
    if b"\t" in tail and tail.split(b"\t", 1)[0] != identity.encode():
        raise ValueError("torn row belongs to another configuration")
    try:
        reader = csv.DictReader(io.StringIO(content[:end].decode(), newline=""), delimiter="\t", strict=True)
        if reader.fieldnames != FIELDS:
            raise ValueError("output header does not match final F1")
        done = set()
        for row in reader:
            if row.get("run_id") != identity or None in row or any(v is None for v in row.values()):
                raise ValueError("mixed configuration or incomplete committed row")
            validate_row(row, config); key = row_key(row)
            if key in done:
                raise ValueError("duplicate completed cell")
            done.add(key)
    except (UnicodeError, csv.Error, TypeError, KeyError, ValueError) as error:
        raise ValueError("corrupt or mixed final F1 output; use its original configuration or a new file") from error
    if tail:
        with open(path, "r+b") as f:
            f.truncate(end)
    return done


def estimated_seconds(config):
    # Decision record's GPU observations: ~1 minute (600 types), ~7 (10,000)
    # for three epochs. Linearly interpolate 2,000: ~114s. Cap at five epochs.
    return sum((60 + (v-600)*360/9400) * 5/3 * config["n_train"]/FULL["n_train"]
               for proc, m, v, k in design(config))


def default_output(config):
    suffix = f"_s{config['seed']}" + ("_cpu" if config["scale"] == "small" else "")
    return f"results/fakedata/f1_neural_final{suffix}.tsv"


def run(config, out):
    device = config["device"]
    if device == "cpu" and config["n_train"] > 1_000_000:
        raise ValueError("CPU runs are limited to 1M training tokens")
    if device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS is unavailable; no CPU fallback")
    root = os.path.realpath(os.getcwd()); out = os.path.realpath(out)
    if os.path.commonpath((root, out)) != root:
        raise ValueError("output must remain inside the working directory")
    if out == os.path.realpath(os.path.join(root, "results/fakedata/f1_neural_final.tsv")):
        raise ValueError("legacy seed-1 output is reserved for its frozen code; use a new file")
    torch.set_num_threads(1)
    T.guard_space(out)
    check_error = scorer_check()
    print(f"check (1): direct sum agrees, maximum error {check_error:.3g} bits (CPU, k=1/4)", flush=True)
    done = resume_keys(out, config)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    new = not os.path.exists(out); completed = 0
    with open(out, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        if new:
            writer.writeheader(); f.flush()
        for vocab in config["vocabs"]:
            for proc, m in CELLS:
                if all((proc, m, vocab, k) in done for k in range(1, 5)):
                    continue
                T.guard_space(out); start = time.perf_counter()
                p, sigma, seeds, tr, va, te = prepare(config, proc, m, vocab)
                prep_seconds = time.perf_counter()-start
                for k in range(1, 5):
                    if (proc, m, vocab, k) in done:
                        continue
                    T.guard_space(out)
                    ref, oracle, _ = T.references(proc, m, p, te, k, config["line"], sigma, mapped_oracle=True)
                    start = time.perf_counter()
                    result = NN.estimate(tr, va, te, vocab, k, device=device, settings=settings_for(config))
                    row = make_row(config, proc, m, vocab, k, result, seeds, ref, oracle,
                                   prep_seconds, time.perf_counter()-start, check_error)
                    validate_row({key: str(value) for key, value in row.items()}, config)
                    T.guard_space(out)
                    writer.writerow(row); f.flush(); os.fsync(f.fileno())
                    done.add((proc, m, vocab, k)); completed += 1
                    print(f"{proc}{m} V={vocab} k={k}: bias {row['bias']:+.6f}, oracle-pop {row['oracle_disc']:+.6f}, "
                          f"fit-oracle {row['fit_minus_oracle']:+.6f}, selected {row['best_step']}/{row['steps']}, "
                          f"epochs {row['epochs']}, early={row['stopped_early']}, {row['seconds']}s", flush=True)
                    del result
                    if device == "mps":
                        torch.mps.empty_cache()
                del tr, va, te
    print(f"done: {completed} new fits, {len(done)}/{len(design(config))} total", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=("small", "full"), default="small")
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--seed", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--out")
    parser.add_argument("--vocabs", type=int, nargs="+")
    for name in ("n_train", "n_val", "n_test", "line", "dim", "hidden"):
        parser.add_argument("--"+name.replace("_", "-"), type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    overrides = {name: getattr(args, name) for name in SMALL if name != "seed" and getattr(args, name, None) is not None}
    try:
        config = run_config(args.scale, args.device, overrides, seed=args.seed)
        print(f"run {run_id(config)}: {len(design(config))} fits, check seed {config['seed']}; GPU epoch-cap estimate "
              f"{estimated_seconds(config)/3600:.2f}h, excludes setup; fixed {SETTING}", flush=True)
        if args.dry_run:
            print(json.dumps(config, sort_keys=True)); return
        out = args.out or default_output(config)
        torch.set_num_interop_threads(1)
        run(config, out)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
