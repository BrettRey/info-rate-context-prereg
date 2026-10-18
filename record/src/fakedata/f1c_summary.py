"""Collect F1c rung errors, exact stationary truths and held-out boundary contrasts.
Usage: python -I src/fakedata/f1c_summary.py OUT_DIR INPUT.tsv [INPUT.tsv ...]
"""
import csv, importlib.util, io, json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f1c", HERE / "f1c_boundaries.py")
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)

def main():
    out = Path(sys.argv[1]).resolve()
    if not out.is_relative_to(Path.cwd()):
        raise ValueError("outputs must stay inside the working directory")
    F.P.current(F.code_id(), F.R.RUNGS)
    rows = []
    for path in sys.argv[2:]:
        path = Path(path).resolve()
        if not path.is_relative_to(Path.cwd()): raise ValueError("inputs must stay inside the working directory")
        loaded, _, _ = F.P.read(path, F.FIELDS)
        rows.extend(loaded)
    rows = F.P.normalize(rows, F.truth)
    # Later inputs replace earlier rows for the same cell; source hashes remain visible.
    keys = ("compatibility", "estimator", "vocab", "n_train", "n_test", "n_val", "line", "seed", "treatment", "rung", "settings")
    rows = list({tuple(r[k] for k in keys): r for r in rows}.values())
    vocabs = sorted({int(r["vocab"]) for r in rows})
    truths = {str(v): F.quantities(v) for v in vocabs}
    truths["process"] = dict(length_distribution=F.LENGTHS.tolist(), continuation_copy=1 - F.EPS,
                             boundary_rate=F.ALPHA, marginal="uniform", cross_word="independent",
                             line_cut="fixed syllable count; true word flags preserved",
                             higher_free="H(S | k plain syllables, current B)",
                             higher_charged="H(S, B | k plain syllables)")
    configurations = sorted({(int(r["vocab"]), r["treatment"], int(r["line"]), int(r["n_test"])) for r in rows})
    truths["rung_reference"] = [dict(vocab=v, treatment=t, line=line, n_test=n,
                                     rungs={k: F.truth(v, k, t, line, n) for k in F.R.RUNGS})
                                for v, t, line, n in configurations]
    completed = {(int(r["vocab"]), r["treatment"], r["rung"]) for r in rows
                 if r["estimator"] == "kenlm" and int(r["n_train"]) == 10_000_000
                 and int(r["n_test"]) == 100000 and int(r["line"]) == 40 and int(r["seed"]) == 1
                 and r["settings"] == "{}" and r["compatibility"] == F.P.family(F.code_id(), "kenlm", r["rung"])}
    expected = [(v, t, k) for v in (600, 2000, 10000) for t in ("bounded", "running") for k in F.R.RUNGS]
    status = dict(expected=len(expected), completed=len(completed), source_hashes=sorted({r["code"] for r in rows}),
                  missing=[dict(vocab=v, treatment=t, rung=k) for v, t, k in expected if (v, t, k) not in completed])
    groups = {}
    names = ("compatibility", "estimator", "vocab", "n_train", "n_test", "n_val", "line", "seed", "treatment", "settings")
    for row in rows:
        groups.setdefault(tuple(row[n] for n in names), {})[row["rung"]] = row
    contrasts = []
    for key, r in groups.items():
        if not all(x in r for x in ("1", "1b-free", "1b-charged")):
            continue
        item = dict(zip(names, key))
        item["code"] = ",".join(sorted({r[x]["code"] for x in ("1", "1b-free", "1b-charged")}))
        for label, a, b in (("i_s_b_given_prev", "1", "1b-free"),
                            ("h_b_given_s_prev", "1b-charged", "1"),
                            ("h_b_given_prev", "1b-charged", "1b-free")):
            for field in ("truth", "estimate", "oracle"):
                item[f"{label}_{field}"] = float(r[a][field]) - float(r[b][field])
        contrasts.append(item)
    contrast_fields = list(names) + ["code"] + [f"{label}_{field}" for label in
        ("i_s_b_given_prev", "h_b_given_s_prev", "h_b_given_prev") for field in ("truth", "estimate", "oracle")]
    artifacts = {"f1c_truth.json": json.dumps(truths, indent=2) + "\n",
                 "f1c_grid_status.json": json.dumps(status, indent=2) + "\n"}
    for name, values, fields in (("f1c_errors.tsv", rows, F.FIELDS), ("f1c_contrasts.tsv", contrasts, contrast_fields)):
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(values); artifacts[name] = buffer.getvalue()
    F.R.disk_guard(out, sum(len(v.encode()) for v in artifacts.values()) + 65536)
    out.mkdir(parents=True, exist_ok=True)
    for name, value in artifacts.items():
        path = out / name; tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(value); os.replace(tmp, path)
    print(f"{len(rows)} rung rows; {len(contrasts)} contrast rows; inventories {vocabs}")
    print("stationary truth (bits):")
    for v in vocabs:
        q = F.quantities(v)
        print(v, " ".join(f"{k}={value:.6f}" for k, value in q.items()))

if __name__ == "__main__":
    main()
