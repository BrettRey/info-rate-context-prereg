"""Fixed-settings neural F3b on stationary simulated word/rate panels.

Sequential fits, held-out validation, bounded lines, no saved model/text files.
The full design matches f3b_words_rates (14 rungs, four families, three pairings,
S0/S1, 17 languages, 10M/1M train/test, lines of 1000). Validation uses 500K.
Only dimensions and budgets may be reduced for the CPU smoke design.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import importlib.util

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


W = load("neural_f3b_words", HERE / "f3b_words_rates.py")
F1 = load("neural_f3b_final", HERE / "f1_neural_final.py")
NN, torch, np, D = F1.NN, F1.torch, F1.np, W.D
# KenLM's entire reserved range ends below 2**43. These blocks never intersect
# it or any earlier F1/F1c/F3b/tuning namespace, for any supported run tag.
SEED_BASE = 2**44
FIELDS = W.FIELDS + ["estimator", "run_tag", "n_val", "val_seed", "word_val_seed",
    "model_seed", "setting", "settings", "device", "steps", "best_step", "epochs",
    "stopped_early", "stop_reason", "final_evaluated", "val_bits", "val_history",
    "lr_history", "test_history", "fit_seconds", "wall_seconds"]
FIT_FIELDS = ["h_est", "seconds", "fallback_orders", "discounts", "peak_work_bytes",
    "free_bytes", "oov_tokens", "n_scored", "zero_backoffs", "settings", "device",
    "steps", "best_step", "epochs", "stopped_early", "stop_reason", "final_evaluated",
    "val_bits", "val_history", "lr_history", "test_history", "fit_seconds", "wall_seconds"]


def seed_base(run_tag):
    W.run_seed_base(run_tag)  # Shared bounds, separate namespace.
    return SEED_BASE + (run_tag - 1) * W.SEED_STRIDE


def fit_coordinates(config):
    """Unique fits without expensive full-inventory truth/epsilon solving.

    For fixed family/language/vocab the text seeds, target and permutation are
    fixed. Pairing/scenario change only rates, so repeated triples share a fit.
    """
    coordinates = set()
    for correlation in W.E.B.R_SCEN.values():
        rates = W.rates(config["targets"], correlation, config["rate_seed"])
        for pairing in config["pairings"]:
            inventories = W.assign_inventories(config["inventories"], rates, pairing, config["pairing_seed"])
            for family in config["families"]:
                for i,v in enumerate(inventories):
                    for rung in config["rungs"]:
                        coordinates.add((family,i,int(v),rung))
    return sorted(coordinates)


def seeds(family, language, run_tag):
    if type(language) is not int or not 0 <= language < 100_000:
        raise ValueError("language outside reserved neural seed namespace")
    base = seed_base(run_tag) + list(W.E.FAMILIES).index(family)*1_000_000 + language*10
    return dict(train_seed=base+1, test_seed=base+2, word_train_seed=base+3,
        word_test_seed=base+4, sigma_seed=base+5 if W.E.FAMILIES[family][1] else "",
        val_seed=base+6, word_val_seed=base+7, model_seed=0)


def fit_key(row, rung, config):
    # Each free/charged model is a separate fit; never normalize away the suffix.
    keys = ("family", "language", "vocab", "eps", "train_seed", "test_seed",
            "word_train_seed", "word_test_seed", "sigma_seed", "val_seed", "word_val_seed", "model_seed")
    identity = {key: row[key] for key in keys}
    identity.update(rung=rung, settings=config["settings"], code=config["code"],
        n_train=config["n_train"], n_val=config["n_val"], n_test=config["n_test"],
        line=config["line"], treatment="bounded", estimator="ffnn")
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def configuration(*, small=False, device="cpu", run_tag, families=tuple(W.E.FAMILIES),
        pairings=W.E.PAIRINGS, rungs=W.RUNGS, inventories=None, targets=None,
        n_train=None, n_val=None, n_test=None, line=None, dim=None, hidden=None,
        process_cap_bytes=100_000_000, margin_bytes=2*D.GIB):
    base = seed_base(run_tag)
    if device not in ("cpu", "mps"):
        raise ValueError("device must be cpu or mps")
    overrides = (inventories, targets, n_train, n_val, n_test, line, dim, hidden)
    if not small and any(value is not None for value in overrides):
        raise ValueError("full budgets/inventories/settings are fixed; size overrides require --small")
    defaults = (dict(inventories=[20,40,60], targets=[2.,2.3,2.6], n_train=100_000,
                     n_val=10_000, n_test=10_000, line=1000, dim=16, hidden=32) if small else
                dict(inventories=list(W.E.B.INV), targets=list(W.E.B.TARGET), n_train=W.E.B.N,
                     n_val=F1.FULL["n_val"], n_test=W.E.F.N_TEST, line=W.E.B.LINE, dim=128, hidden=512))
    values = dict(zip(("inventories","targets","n_train","n_val","n_test","line","dim","hidden"), overrides))
    values = {key: defaults[key] if value is None else value for key,value in values.items()}
    inventories = list(map(int, values.pop("inventories")))
    targets = list(map(float, values.pop("targets")))
    if (not 3 <= len(inventories) < 100_000 or len(inventories) != len(targets)
            or any(v < 2 for v in inventories) or any(not math.isfinite(t) or t <= 0 for t in targets)
            or np.std(np.log(targets)) <= 1e-12):
        raise ValueError("need nondegenerate positive targets and 3..99999 inventories")
    if (not families or not pairings or not rungs or not set(families) <= set(W.E.FAMILIES)
            or not set(pairings) <= set(W.E.PAIRINGS) or not set(rungs) <= set(W.RUNGS)
            or any(len(x) != len(set(x)) for x in (families,pairings,rungs))):
        raise ValueError("invalid or duplicate grid coordinates")
    if (any(type(value) is not int or value < 1 for value in values.values())
            or any(values[key] % values["line"] for key in ("n_train","n_val","n_test"))):
        raise ValueError("positive dimensions and whole-line budgets required")
    if device == "cpu" and values["n_train"] > 1_000_000:
        raise ValueError("CPU smoke runs limited to 1M training tokens")
    if (type(process_cap_bytes) is not int or process_cap_bytes < 1_000_000
            or type(margin_bytes) is not int or margin_bytes < 2*D.GIB):
        raise ValueError("at least 1MB cap and 2GiB disk margin required")
    sources = [Path(__file__), Path(W.__file__), Path(W.E.__file__), Path(W.E.B.__file__),
        Path(W.E.A.__file__), Path(W.R.__file__), Path(D.__file__), Path(F1.__file__), Path(F1.C.__file__)]
    code = hashlib.sha256(b"".join(path.read_bytes() for path in sources) + F1.T.code_id().encode()).hexdigest()
    return dict(values, schema="neural-f3b-words-rates-v1", estimator="ffnn", small=small,
        device=device, run_tag=run_tag, families=list(families), pairings=list(pairings), rungs=list(rungs),
        inventories=inventories, targets=targets, settings=F1.settings_for(values), setting=F1.SETTING,
        lengths=W.LENGTHS.tolist(), target_kind="line-averaged-plain-4", boundary_signal=False,
        cross_word="uninterrupted-lag-transition", treatment="bounded", seed_base=SEED_BASE,
        rate_seed=base+3_999_998, pairing_seed=base+3_999_999, process_cap_bytes=process_cap_bytes,
        margin_bytes=margin_bytes, code=code,
        environment=dict(python=sys.version, numpy=np.__version__, torch=torch.__version__,
                         cpu_threads=1, interop_threads=1))


def validate_neural(row, config):
    if (row["estimator"] != "ffnn" or int(row["run_tag"]) != config["run_tag"]
            or row["setting"] != F1.SETTING or row["device"] != config["device"]
            or int(row["n_val"]) != config["n_val"]):
        raise ValueError("neural checkpoint configuration differs")
    stored = json.loads(row["settings"], parse_constant=F1.T._reject_json_constant)
    s = config["settings"]
    if stored != s or any(type(stored[k]) is not type(v) for k,v in s.items()):
        raise ValueError("neural checkpoint settings differ")
    for key in ("fit_seconds", "wall_seconds", "val_bits"):
        if not math.isfinite(float(row[key])) or float(row[key]) < 0:
            raise ValueError("invalid neural duration/loss")
    if (int(row["oov_tokens"]) != 0 or int(row["zero_backoffs"]) != 0
            or row["fallback_orders"] or json.loads(row["discounts"]) != {}):
        raise ValueError("invalid neural scoring metadata")
    if (int(row["model_fit"]) == 1 and float(row["seconds"]) != float(row["fit_seconds"])
            or int(row["model_fit"]) == 0 and float(row["seconds"]) != 0):
        raise ValueError("invalid reused-fit duration")
    F1.C.validate_training(row, config, s)


def checkpoint(path, config, metadata):
    rows, tail = W.checkpoint(path, config, metadata, fields=FIELDS,
                             identity=lambda row,rung: fit_key(row,rung,config))
    fits = {}
    for row in rows:
        validate_neural(row, config)
        # Reused rows must describe the same score, resources and training run.
        record = {k:row[k] for k in FIT_FIELDS if k != "seconds"}
        if row["fit_key"] in fits and record != fits[row["fit_key"]]:
            raise ValueError("inconsistent reused neural fit")
        fits[row["fit_key"]] = record
    return rows, tail


def estimate(tr, va, te, vocab, rung, config, resource_budget):
    preflight = resource_budget.check(1_000_000)
    start = time.perf_counter()
    kwargs = dict(device=config["device"], settings=config["settings"])
    if rung in ("1", "2", "3", "4"):
        result = NN.estimate(tr, va, te, vocab, int(rung), **kwargs)
    else:
        result = NN.estimate_rung(tr, va, te, vocab, rung, "bounded", **kwargs)
    elapsed = time.perf_counter() - start
    postflight = resource_budget.check(1_000_000)
    row = {key:result[key] for key in ("settings", "device", "steps", "best_step", "epochs",
        "stopped_early", "stop_reason", "final_evaluated", "val_bits", "n_scored")}
    row.update(h_est=result["test_bits"], seconds=result["seconds"], fit_seconds=result["seconds"],
        wall_seconds=elapsed, settings=json.dumps(result["settings"], sort_keys=True),
        val_history=json.dumps(result["validation_losses"]), lr_history=json.dumps(result["lr_history"]),
        test_history="[]", fallback_orders="", discounts="{}", oov_tokens=0, zero_backoffs=0,
        peak_work_bytes=max(preflight["directory_bytes"],postflight["directory_bytes"]),
        free_bytes=min(preflight["free_bytes"],postflight["free_bytes"]))
    del result
    if config["device"] == "mps":
        torch.mps.empty_cache()
    return row


def publish(prefix, rows, config, budget):
    summary, contrasts = W.summarise(rows, config)
    W.E.write_tsv(Path(str(prefix)+".tsv"), summary, W.SUMMARY_FIELDS, resource_budget=budget)
    W.E.write_tsv(Path(str(prefix)+"_contrasts.tsv"), contrasts, W.CONTRAST_FIELDS, resource_budget=budget)
    # Prose explaining conventions and commands lives in the dated task log.
    return summary, contrasts


def run_grid(work, prefix, *, reservation_dir, **options):
    config = configuration(**options)
    work, prefix, shared = map(W.E.local_path, (work, prefix, reservation_dir))
    if not prefix.is_relative_to(work):
        raise ValueError("neural output prefix must be inside its measured work directory")
    if (work.is_relative_to(shared) or shared.is_relative_to(work)
            or prefix.is_relative_to(shared) or shared.is_relative_to(prefix)):
        raise ValueError("shared reservations must be separate from work/output")
    config["reservation_dir"] = str(shared)
    if config["device"] == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS unavailable; no CPU fallback")
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    meta, density = Path(str(prefix)+"_config.json"), Path(str(prefix)+"_densities.tsv")
    if meta.exists():
        if json.loads(meta.read_text()) != config:
            raise ValueError("different neural configuration; use a new prefix")
    elif density.exists() and density.read_bytes().partition(b"\n")[2]:
        raise ValueError("saved neural scores require provenance")
    metadata = W.panels(config, seed_factory=seeds)
    rows, tail = checkpoint(density, config, metadata)
    with D.DiskBudget(work, shared, config["process_cap_bytes"], config["margin_bytes"], prefix=prefix) as budget:
        budget.check(1_000_000)
        work.mkdir(parents=True, exist_ok=True); prefix.parent.mkdir(parents=True, exist_ok=True)
        if not meta.exists():
            tmp = Path(str(meta)+".tmp")
            tmp.write_text(json.dumps(config, indent=2)+"\n"); os.replace(tmp, meta)
        if tail is not None:
            with density.open("r+b") as stream:
                stream.truncate(tail)
        cache = {row["fit_key"]:{key:row[key] for key in FIT_FIELDS} for row in rows}
        done = {(r["family"],r["pairing"],r["scenario"],int(r["language"]),r["rung"]) for r in rows}
        publish(prefix, rows, config, budget)
        new = not density.exists() or not density.stat().st_size
        with density.open("a", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            if new:
                writer.writeheader(); stream.flush()
            for key, base in metadata.items():
                pending = [rung for rung in config["rungs"] if (*key,rung) not in done]
                if not pending:
                    continue
                p = W.E.F.zipf(base["vocab"])
                sigma = (np.random.default_rng(base["sigma_seed"]).permutation(len(p))
                         if W.E.FAMILIES[key[0]][1] else None)
                tr = va = te = None
                try:
                    for rung in pending:
                        identity = fit_key(base, rung, config)
                        model_fit = int(identity not in cache)
                        if model_fit:
                            if tr is None:
                                budget.check(1_000_000)
                                tr, va, te = [W.corpus(config["n_"+name],p,base["m"],base["eps"],sigma,
                                    config["line"],base[stream_seed],base[word_seed]) for name,stream_seed,word_seed in (
                                        ("train","train_seed","word_train_seed"),
                                        ("val","val_seed","word_val_seed"),("test","test_seed","word_test_seed"))]
                            result = estimate(tr, va, te, len(p), rung, config, budget)
                            cache[identity] = dict(result)
                        else:
                            result = dict(cache[identity], seconds=0)
                        if te is None:
                            te = W.corpus(config["n_test"],p,base["m"],base["eps"],sigma,config["line"],
                                          base["test_seed"],base["word_test_seed"])
                        ref = W.truth(p,base["eps"],base["m"],rung,config["line"],sigma)
                        oracle = W.oracle(te,p,base["eps"],base["m"],rung,config["line"],sigma)
                        row = dict(base, rung=rung, estimator="ffnn", run_tag=config["run_tag"],
                            setting=F1.SETTING, n_train=config["n_train"], n_val=config["n_val"],
                            n_test=config["n_test"], line=config["line"], h_true=ref,
                            bias_bits=float(result["h_est"])-ref, oracle_bits=oracle,
                            fit_minus_oracle=float(result["h_est"])-oracle, model_fit=model_fit,
                            fit_key=identity, **result)
                        validate_neural({k:str(v) for k,v in row.items()}, config)
                        if int(row["n_scored"]) != config["n_test"] or not math.isfinite(float(row["h_est"])):
                            raise ValueError("incomplete or nonfinite neural score")
                        budget.check(1_000_000)
                        writer.writerow(row); stream.flush(); os.fsync(stream.fileno())
                        rows.append(row); done.add((*key,rung))
                        publish(prefix, rows, config, budget)
                        print(f"{' '.join(map(str,key))} {rung}: truth={ref:.6f} estimate={float(row['h_est']):.6f} "
                              f"fit={model_fit} selected={row['best_step']}/{row['steps']} early={row['stopped_early']}", flush=True)
                finally:
                    del tr, va, te
        summary, contrasts = publish(prefix, rows, config, budget)
    return rows, summary, contrasts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work"); parser.add_argument("prefix")
    parser.add_argument("--small", action="store_true")
    parser.add_argument("--device", choices=("cpu","mps"), default="cpu")
    parser.add_argument("--run-tag", type=int, required=True)
    parser.add_argument("--reservation-dir", required=True)
    parser.add_argument("--process-cap-bytes", type=int, default=100_000_000)
    parser.add_argument("--margin-bytes", type=int, default=2*D.GIB)
    parser.add_argument("--families", nargs="+", choices=W.E.FAMILIES, default=list(W.E.FAMILIES))
    parser.add_argument("--pairings", nargs="+", choices=W.E.PAIRINGS, default=list(W.E.PAIRINGS))
    parser.add_argument("--rungs", nargs="+", choices=W.RUNGS, default=list(W.RUNGS))
    parser.add_argument("--inventories", nargs="+", type=int)
    parser.add_argument("--targets", nargs="+", type=float)
    for name in ("n_train","n_val","n_test","line","dim","hidden"):
        parser.add_argument("--"+name.replace("_","-"), type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = vars(parser.parse_args())
    work, prefix, shared, dry = (args.pop(name) for name in ("work","prefix","reservation_dir","dry_run"))
    try:
        config = configuration(**args)
        if dry:
            cells = len(config["families"])*len(config["pairings"])*2*len(config["inventories"])*len(config["rungs"])
            print(f"score cells={cells}; unique fits={len(fit_coordinates(config))}")
            print(json.dumps(config, sort_keys=True)); return
        run_grid(work, prefix, reservation_dir=shared, **args)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
