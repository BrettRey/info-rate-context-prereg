"""Compare the Stage 2 rerun under the amended mojibake rule with the previous sample.

Reads, per language: the new per-file audit (results/stage2/mojibake/opensubtitles_<LANG>.tsv),
the new folder manifest (results/stage2/manifest/opensubtitles_<LANG>.tsv) and the previous
manifest from git at a given commit. Writes results/stage2/mojibake/comparison.tsv and .md.
Counts only; no text is read or written.

Usage: .venv/bin/python -I src/stage2_mojibake_compare.py BASE_COMMIT LANG [LANG ...]
"""
import csv
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "results/stage2/mojibake"
MANIFEST = ROOT / "results/stage2/manifest"
# The 2026-10-11 scan (DECISIONS.md), on Stage 2 output after its filters.
SCAN = {"THA": 1309, "FRA": 8, "VIE": 5, "TUR": 2}


def rows(text):
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def compare(base, lang):
    audit = rows((AUDIT / f"opensubtitles_{lang}.tsv").read_text())
    new = rows((MANIFEST / f"opensubtitles_{lang}.tsv").read_text())
    old = rows(subprocess.run(["git", "-C", str(ROOT), "show", f"{base}:results/stage2/manifest/opensubtitles_{lang}.tsv"],
                              check=True, capture_output=True, text=True).stdout)
    sample = [a for a in audit if a["in_sample"] == "1"]
    kept_new = {(r["folder"], r["file"]) for r in new if r["status"] == "kept"}
    kept_old = {(r["folder"], r["file"]) for r in old if r["status"] == "kept"}
    used = [a for a in sample if (a["folder"], a["file"]) in kept_new]
    return {
        "language": lang,
        "files_tried": len(sample),
        "files_dropped": sum(a["decision"] == "file_dropped" for a in sample),
        "files_unreadable": sum(a["decision"].startswith("error:") for a in sample),
        "flagged_lines_dropped_in_kept_files": sum(int(a["flagged"]) for a in used),
        "kept_files_with_flagged_lines": sum(int(a["flagged"]) > 0 for a in used),
        "flagged_lines_all_files_tried": sum(int(a["flagged"]) for a in sample),
        "scan_2026_10_11": SCAN.get(lang, 0),
        "kept_folders_old": len(kept_old), "kept_folders_new": len(kept_new),
        "kept_files_only_old": len(kept_old - kept_new), "kept_files_only_new": len(kept_new - kept_old),
        "kept_lines_old": sum(int(r["n_kept"]) for r in old if r["status"] == "kept"),
        "kept_lines_new": sum(int(r["n_kept"]) for r in new if r["status"] == "kept"),
    }


def main():
    base, langs = sys.argv[1], sys.argv[2:]
    table = [compare(base, lang) for lang in langs]
    with open(AUDIT / "comparison.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]), delimiter="\t", lineterminator="\n")
        w.writeheader(); w.writerows(table)
    head = ["Language", "Files tried", "Files dropped", "Flagged lines dropped from kept files", "Scan (2026-10-11)",
            "Kept files changed (old only / new only)", "Kept lines old", "Kept lines new"]
    out = ["# Stage 2 rerun under the amended mojibake rule", "",
           f"Previous sample: the manifests at commit {base}. Per-file audits: `opensubtitles_<LANG>.tsv` in this folder. "
           "The scan counted lines in Stage 2's previous output (after its filters); the rule now runs on every "
           "extracted line before them, so its counts include lines the old filters dropped.", "",
           "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in table:
        out.append(f"| {r['language']} | {r['files_tried']} | {r['files_dropped']} | {r['flagged_lines_dropped_in_kept_files']} | "
                   f"{r['scan_2026_10_11']} | {r['kept_files_only_old']} / {r['kept_files_only_new']} | "
                   f"{r['kept_lines_old']:,} | {r['kept_lines_new']:,} |")
    (AUDIT / "comparison.md").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
