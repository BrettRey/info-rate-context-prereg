"""Report final neural F1 cost and the same-test oracle's sampling discrepancy.

Usage: python -I -B src/fakedata/f1_neural_final_summary.py [OUT.tsv ...]
Accepts the frozen seed-1 output too. Sample standard deviations (ddof=1)
are reported per cell only when seeds 1, 2 and 3 are present. No cost bound.
"""
import argparse
import csv
import json
import math
import os
import statistics

METRICS = ("bias", "oracle_disc", "fit_minus_oracle")

def reject_constant(value):
    raise ValueError(f"nonfinite settings constant: {value}")


def summarize(paths):
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    groups = {}; settings = None; seeds_seen = set(); count = 0
    for path in paths:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f, delimiter="\t", strict=True))
        if not rows or any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError("empty or incomplete output")
        if len({r["run_id"] for r in rows}) != 1 or not rows[0]["run_id"]:
            raise ValueError("mixed or missing run IDs")
        file_seeds = {int(r["seed"]) for r in rows}
        if len(file_seeds) != 1 or not file_seeds <= {1, 2, 3}:
            raise ValueError("each file must hold one check seed (1, 2 or 3)")
        seed = file_seeds.pop()
        if seed in seeds_seen:
            raise ValueError("duplicate seed across files")
        seeds_seen.add(seed)
        for row in rows:
            stored = json.loads(row["settings"], parse_constant=reject_constant)
            if (row["setting"] != "zero_unigram_cosine5" or not isinstance(stored, dict)
                    or stored.get("seed") != 0 or row["model_seed"] != "0"
                    or stored.get("keep_best_validation") is not True
                    or stored.get("eval_final") is not True or stored.get("max_epochs") != 5):
                raise ValueError("invalid fixed model settings")
            canonical = json.dumps(stored, sort_keys=True)
            if settings is not None and canonical != settings:
                raise ValueError("mixed model settings across rows/files")
            settings = canonical
            key = (row["proc"], int(row["m"]), int(row["vocab"]), int(row["k"]))
            group = groups.setdefault(key, {})
            if seed in group:
                raise ValueError("duplicate cell")
            for field in METRICS + ("seconds", "h_ref", "h_est", "oracle_loss"):
                if not math.isfinite(float(row[field])):
                    raise ValueError("nonfinite result")
            ref, fitted, oracle = (float(row[f]) for f in ("h_ref", "h_est", "oracle_loss"))
            for field, expected in zip(METRICS, (fitted-ref, oracle-ref, fitted-oracle)):
                if not math.isclose(float(row[field]), expected, rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("inconsistent oracle decomposition")
            if group and not math.isclose(ref, float(next(iter(group.values()))["h_ref"]), rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("population reference differs across seeds")
            group[seed] = row; count += 1
    print(f"Fixed zero_unigram_cosine5; check seeds {','.join(map(str, sorted(seeds_seen)))}; settings={settings}")
    print("oracle-pop reports each sample's discrepancy. Across-seed mean and sample SD (ddof=1) require all three seeds per cell. No cost bound.")
    complete = 0
    for (proc, m, vocab, k), group in sorted(groups.items(), key=lambda item: (item[0][2], item[0][0], item[0][1], item[0][3])):
        for seed, row in sorted(group.items()):
            print(f"{proc}{m} V={vocab} k={k} seed={seed}: "
                  f"bias={float(row['bias']):+.6f}, oracle-pop={float(row['oracle_disc']):+.6f}, "
                  f"fit-oracle={float(row['fit_minus_oracle']):+.6f}, selected_step={row['best_step']}, "
                  f"steps={row['steps']}, epochs={row['epochs']}, early={row['stopped_early']}, "
                  f"final_evaluated={row['final_evaluated']}, seconds={row['seconds']}")
        if set(group) == {1, 2, 3}:
            values = [[float(group[s][field]) for s in (1, 2, 3)] for field in METRICS]
            print("  across seeds 1,2,3: " + "; ".join(
                f"{label} mean={statistics.mean(v):+.6f}, sd={statistics.stdev(v):.6f}"
                for label, v in zip(("bias", "oracle-pop", "fit-oracle"), values)))
            complete += 1
        else:
            print("  across-seed mean/SD pending: missing seeds " + ",".join(map(str, sorted({1, 2, 3}-set(group)))))
    print(f"{count} fits recorded; {len(groups)}/84 cells; {complete} cells with all three seeds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["results/fakedata/f1_neural_final.tsv"])
    try:
        summarize(parser.parse_args().paths)
    except (ValueError, KeyError, csv.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
