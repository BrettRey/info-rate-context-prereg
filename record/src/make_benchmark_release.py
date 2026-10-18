"""Assemble the estimator-benchmark release (component 7 of notes/data-release-plan-2026-10-10.md):
simulated data only, no corpus text, no NS. Copies a whitelist of fake-data results and the code that
made them into OUTDIR, strips local paths from text files, and writes the datasheet, licences and a
SHA-256 manifest. Nothing is published; rerun as further results land.
Usage: python -I src/make_benchmark_release.py [OUTDIR]   (default release/benchmarks)
"""
import hashlib, os, re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "release" / "benchmarks"
RESULTS = [  # (file in results/fakedata, check it belongs to)
    ("f1v2_long.tsv", "F1, KenLM"), ("f1v2_long_oracle.tsv", "F1, KenLM"), ("f1v2_short.tsv", "F1, KenLM"),
    ("f1v2_short_oracle.tsv", "F1, KenLM"), ("f1v2_ablation.tsv", "F1, KenLM"), ("f1b_short_lines.tsv", "F1, KenLM"),
    ("f1_mapped_kenlm.tsv", "F1, KenLM"), ("f1_checks.md", "F1, KenLM"),
    ("f1_neural_final.tsv", "F1, neural"), ("f1_neural_final_s2.tsv", "F1, neural"), ("f1_neural_final_s3.tsv", "F1, neural"),
    ("f1c_kenlm_10m_final.tsv", "F1c"), ("f1c_contrasts.tsv", "F1c"), ("f1c_truth.json", "F1c"), ("f1c_summary.txt", "F1c"),
    ("f3a_oracle.tsv", "F3a"), ("f3a_design_17.tsv", "F3a"), ("f3a_design_15.tsv", "F3a"),
    ("f3a_design_settings_17.tsv", "F3a"), ("f3a_design_settings_15.tsv", "F3a"),
    ("f3b_local.tsv", "F3b, KenLM"), ("f3b_skipped.tsv", "F3b, KenLM"), ("f3b_estimators_full.tsv", "F3b, KenLM"),
    ("f3b_estimators_full_contrasts.tsv", "F3b, KenLM"), ("f3b_estimators_full.md", "F3b, KenLM"),
]
CODE = ["src/fakedata", "src/stage5", "src/stage6"]
TESTS = re.compile(r"tests/test_(f1|f3|nn|nnlm|neural|runner|stage6|b2)\w*\.py$")
PATHS = [(str(ROOT) + "/", ""), ("/Users/brettreynolds/projects/codex-work/info-rate-context/", ""), ("/Users/brettreynolds/", "~/")]
TEXT = {".py", ".tsv", ".md", ".txt", ".json", ".sh", ".cff"}

def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix in TEXT:
        s = src.read_text(encoding="utf-8")
        for a, b in PATHS:
            s = s.replace(a, b)
        if "/Users/" in s:
            sys.exit(f"local path left in {src}")
        dst.write_text(s, encoding="utf-8")
    else:
        shutil.copy2(src, dst)

def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    present, missing = [], []
    for name, check in RESULTS:
        src = ROOT / "results" / "fakedata" / name
        if src.exists():
            copy(src, OUT / "results" / name); present.append((name, check))
        else:
            missing.append((name, check))
    for d in CODE:
        for src in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" not in src.parts:
                copy(src, OUT / src.relative_to(ROOT))
    for src in sorted((ROOT / "tests").glob("test_*.py")):
        if TESTS.search(str(src.relative_to(ROOT))):
            copy(src, OUT / src.relative_to(ROOT))
    for name in ("README.md", "LICENSE-CODE", "LICENSE-DATA", "CITATION.cff"):
        copy(ROOT / "release" / "templates" / "benchmarks" / name, OUT / name)
    with open(OUT / "results" / "INCLUDED.tsv", "w", encoding="utf-8") as f:
        f.write("file\tcheck\tstatus\n")
        for name, check in present: f.write(f"{name}\t{check}\tincluded\n")
        for name, check in missing: f.write(f"{name}\t{check}\tnot yet available\n")
    lines = []
    for p in sorted(OUT.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.sha256":
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(OUT)}")
    (OUT / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(present)} result files, {len(missing)} not yet available, {len(lines)} files in all")
    for name, check in missing: print("  pending:", name)

if __name__ == "__main__":
    main()
