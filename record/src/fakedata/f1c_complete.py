"""Continue the 40-line F1c grid using explicitly pinned per-rung compatibility.
Usage: python -I -B src/fakedata/f1c_complete.py V1.tsv FINAL.tsv --reserve-bytes CALIBRATED_PEAK
"""
import argparse, csv, importlib.util, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
F = load("f1c", HERE / "f1c_boundaries.py")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source"); parser.add_argument("out")
    parser.add_argument("--reserve-bytes", type=int,
                        help="calibrated aggregate additional peak including both texts and all model/temp files; forwarded to every driver fit")
    args = parser.parse_args()
    if args.reserve_bytes is not None and args.reserve_bytes <= 0:
        raise ValueError("reserve-bytes must be positive")
    root = Path.cwd(); source, out = [Path(x).resolve() for x in (args.source, args.out)]
    if source == out or not all(p.is_relative_to(root) for p in (source, out)):
        raise ValueError("use distinct input/output files inside the working directory")
    current = F.code_id(); F.P.current(current, F.R.RUNGS)
    def validated(path):
        rows, _, _ = F.P.read(path, F.FIELDS)
        rows = F.P.normalize(rows, F.truth)
        for row in rows:
            if (row["estimator"] != "kenlm" or int(row["n_train"]) != 10_000_000 or int(row["n_test"]) != 100000
                    or int(row["line"]) != 40 or int(row["seed"]) != 1 or row["settings"] != "{}"
                    or int(row["n_val"]) != 0 or int(row["vocab"]) not in (600, 2000, 10000)):
                raise ValueError("F1c continuation rows have incompatible configuration")
        keys = [(r["vocab"], r["treatment"], r["rung"], r["compatibility"]) for r in rows]
        if len(set(keys)) != len(keys): raise ValueError("duplicate continuation cell")
        return rows
    if not out.exists():
        rows = validated(source)
        if any(r["code"] != "2a93a902294b" for r in rows):
            raise ValueError("v1 source must have its pinned source fingerprint")
        owned = (out, out.with_suffix(out.suffix + ".tmp"),
                 out.parent / (out.stem + "_logs"), out.parent / (out.stem + "_scratch"))
        F.R.disk_guard(out, 1_000_000, owned_paths=owned)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=F.FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(r for r in rows if r["rung"] not in ("0", "1w"))
    for v in (600, 2000, 10000):
        for treatment in ("bounded", "running"):
            rows = validated(out)
            done = {r["rung"] for r in rows if int(r["vocab"]) == v and r["treatment"] == treatment
                    and r["compatibility"] == F.P.family(current, "kenlm", r["rung"])}
            needed = [r for r in F.R.RUNGS if r not in done]
            if needed:
                print(f"finish V={v} {treatment}: {', '.join(needed)}", flush=True)
                command = [sys.executable, "-I", "-B", str(HERE / "f1c_boundaries.py"), "kenlm", str(out),
                           "--vocabs", str(v), "--treatments", treatment, "--rungs", *needed]
                if args.reserve_bytes is not None:
                    command += ["--reserve-bytes", str(args.reserve_bytes)]
                subprocess.run(command, check=True)
    print("complete: 66 full-scale cells", flush=True)

if __name__ == "__main__": main()
