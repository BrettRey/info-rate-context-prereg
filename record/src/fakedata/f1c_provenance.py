"""Pinned per-rung scientific compatibility, never inferred from today's code ID."""
import ast, csv, io, json, math
from pathlib import Path

HERE = Path(__file__).resolve().parent

def policy():
    value = json.loads((HERE / "f1c_compatibility.json").read_text())
    if value.get("schema") != "f1c-compatibility-v1":
        raise ValueError("unknown F1c compatibility policy")
    return value["codes"]

def family(code, estimator, rung):
    try:
        return policy()[code][estimator][rung]
    except KeyError as exc:
        raise ValueError(f"unverified F1c source/rung: {code} {estimator} {rung}") from exc

def current(code, rungs):
    for estimator in ("kenlm", "neural"):
        for rung in rungs:
            family(code, estimator, rung)

def normalize(rows, truth=None):
    result = []
    for original in rows:
        row = dict(original)
        if None in row or any(v is None for v in row.values()):
            raise ValueError("incomplete F1c record")
        expected_family = family(row["code"], row["estimator"], row["rung"])
        if row.get("compatibility") and row["compatibility"] != expected_family:
            raise ValueError("F1c row claims an incompatible provenance family")
        row["compatibility"] = expected_family
        try:
            settings = json.loads(row["settings"])
        except json.JSONDecodeError:
            settings = ast.literal_eval(row["settings"])
        if not isinstance(settings, dict): raise ValueError("F1c settings must be a mapping")
        row["settings"] = json.dumps(settings, sort_keys=True, allow_nan=False)
        for key in ("vocab", "n_train", "n_test", "line"):
            if int(row[key]) < 1: raise ValueError("invalid F1c experiment size")
        if row.get("n_scored") == "" and row["estimator"] == "neural":
            # This archived scorer predates count instrumentation, but its
            # complete batch loop must finish before a result can be returned.
            # Only an explicitly audited source can imply the missing count.
            inferred = json.loads((HERE / "f1c_compatibility.json").read_text()).get("legacy_full_score_sources", [])
            if row["code"] in inferred:
                row["n_scored"] = row["n_test"]
        try:
            scored = int(row["n_scored"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("invalid F1c scored count") from exc
        if scored != int(row["n_test"]):
            raise ValueError("incomplete F1c scoring: n_scored must equal n_test")
        if int(row["n_val"]) < 0 or int(row["seed"]) < 0 or row["treatment"] not in ("bounded", "running"):
            raise ValueError("invalid F1c experiment configuration")
        values = {k: float(row[k]) for k in ("truth", "estimate", "oracle", "estimate_minus_truth", "oracle_minus_truth", "fit_minus_oracle")}
        if not all(math.isfinite(v) for v in values.values()): raise ValueError("nonfinite F1c score")
        comparisons = [(values["estimate_minus_truth"], values["estimate"] - values["truth"]),
                       (values["oracle_minus_truth"], values["oracle"] - values["truth"]),
                       (values["fit_minus_oracle"], values["estimate"] - values["oracle"])]
        if truth is not None:
            comparisons.append((values["truth"], truth(int(row["vocab"]), row["rung"], row["treatment"], int(row["line"]), int(row["n_test"]))))
        if any(not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10) for a, b in comparisons):
            raise ValueError("inconsistent F1c score/reference arithmetic")
        result.append(row)
    return result

def read(path, fields, allow_tail=False):
    content = Path(path).read_bytes(); end = content.rfind(b"\n") + 1
    if not end: raise ValueError("incomplete F1c header")
    if end != len(content) and not allow_tail: raise ValueError("unterminated F1c record")
    reader = csv.DictReader(io.StringIO(content[:end].decode(), newline=""), delimiter="\t", strict=True)
    optional = {"compatibility", "plugin_bits", "plugin_ref", "plugin_minus_truth"}
    schemas = (fields, [f for f in fields if f != "compatibility"],
               [f for f in fields if f not in optional])
    if reader.fieldnames not in schemas:
        raise ValueError("unrecognized F1c header")
    rows = list(reader)
    for row in rows:
        for field in optional:
            row.setdefault(field, "")
    return rows, end if end != len(content) else None, reader.fieldnames
