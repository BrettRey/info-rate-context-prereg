"""Summarise the corpus tally of counter readings: largest effect per row, and its class
under Brett's cut of 2026-10-10 (freeze under 0.05% of syllables in every language).

Usage: python -I src/stage3_tally_summary.py TALLY_DIR OUT.tsv
Reads TALLY_DIR/reading-tally-<LANG>.tsv for 15 languages; writes numbers only
(no word types or text) to OUT.tsv and a Markdown table to stdout.
"""
import csv
import sys
from collections import defaultdict

LANGS = "SPA CAT ITA DEU ENG FRA SRP TUR FIN HUN EUS KOR CMN YUE VIE".split()
THRESHOLD = 0.0005          # 0.05% of syllables
EXCLUDED = {6: "historical rule nobody proposes", 7: "historical rule nobody proposes"}
# Comparisons whose affected words lie outside the row's environment (DECISIONS 2026-10-10, B2/B3):
# set aside, and a row left with none is unmeasured.
ARTEFACT = {(5, "FIN", "C′"), (23, "TUR", "B")}
# Rows whose alternative is a defect, not a proposal (Brett, 2026-10-10).
DEFECT = {29, 37}
SPLITS = set(range(45, 54))  # rows about boundaries, ownership, spelling or phones, not counts
# Alternatives the readings table labels as diagnostics, not proposals (row 14: "an alphabet-mismatch diagnostic").
DIAGNOSTIC = {(14, "undecoded_legacy_symbols")}
# Alternatives that bound a choice rather than propose one (row 13: the rarest attested entry).
BOUND = {(13, "lowest_frequency_entry")}


def load(tally_dir):
    rows, titles, lines = [], {}, {}
    for lang in LANGS:
        with open(f"{tally_dir}/reading-tally-{lang}.tsv", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                row = int(r["row"]); titles[row] = r["title"]; lines[lang] = int(r["lines"])
                rows.append(dict(r, row=row))
    return rows, titles, lines


def summarise(rows, titles):
    by_row = defaultdict(list)
    for r in rows:
        by_row[r["row"]].append(r)
    out = []
    for row in sorted(titles):
        allmeasured = [r for r in by_row[row] if r["status"] in ("covered", "partial") and r["code_syllables"]]
        artefact = [r for r in allmeasured if (row, r["language"], r["option"]) in ARTEFACT]
        measured = [r for r in allmeasured if (row, r["alternative"]) not in DIAGNOSTIC
                    and (row, r["language"], r["option"]) not in ARTEFACT]
        diag = [r for r in allmeasured if (row, r["alternative"]) in DIAGNOSTIC]
        best = None
        for r in measured:
            share = abs(int(r["difference"])) / int(r["code_syllables"])
            if best is None or share > best[0]:
                best = (share, r)
        failed = sum(int(r.get("failed_lines") or 0) for r in measured)
        if "(fixed)" in titles[row]:
            cls = "fixed (the alternative is the defect it fixed)"
        elif row in DEFECT:
            cls = "fixed (Brett: the alternative is a defect)"
        elif row in EXCLUDED:
            cls = "excluded (" + EXCLUDED[row] + ")"
        elif row in SPLITS:
            cls = "outside the count rule (boundaries, not counts)"
        elif best is None and artefact:
            cls = "not measured (the tally's figure is an artefact)"
        elif best is None:
            cls = "not measured (no alternative implemented)"
        elif best[0] >= THRESHOLD:
            cls = "frozen at default (Brett: the alternative is a bound, reported)" if (row, best[1]["alternative"]) in BOUND else "fork"
        else:
            cls = "frozen at default"
        r = best[1] if best else {}
        out.append(dict(
            row=row, title=titles[row], cls=cls,
            language=r.get("language", ""), option=r.get("option", ""), alternative=r.get("alternative", ""),
            difference=r.get("difference", ""), code_syllables=r.get("code_syllables", ""),
            syllable_share=f"{best[0]:.6f}" if best else "",
            token_share=r.get("changed_token_share", ""),
            comparisons=len(measured), partial=sum(x["status"] == "partial" for x in measured),
            failed_lines_summed=failed,
            artefact=" ".join(f"{r['language']} {r['option']} {r['alternative']} {r['difference']} of {r['code_syllables']}" for r in artefact),
            diagnostic=" ".join(f"{r['language']} {r['option']} {r['alternative']} {r['difference']} of {r['code_syllables']}" for r in diag),
            languages_measured=" ".join(sorted({x["language"] for x in measured}))))
    return out


def pct(x):
    x = 100 * float(x)
    return "0" if x == 0 else (f"{x:.2g}%" if x < 1 else f"{x:.1f}%")


def main():
    tally_dir, out_path = sys.argv[1], sys.argv[2]
    rows, titles, lines = load(tally_dir)
    out = summarise(rows, titles)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), delimiter="\t", lineterminator="\n")
        w.writeheader(); w.writerows(out)
    print("| Row | Reading | Largest effect: language, option, alternative | Syllables changed | Tokens changed | Class |")
    print("|---|---|---|---:|---:|---|")
    measured = sorted((o for o in out if o["syllable_share"]), key=lambda o: -float(o["syllable_share"]))
    for o in measured:
        print(f"| {o['row']} | {o['title']} | {o['language']} {o['option']}, `{o['alternative']}` | "
              f"{pct(o['syllable_share'])} ({int(o['difference']):+d} of {int(o['code_syllables']):,}) | "
              f"{pct(o['token_share'] or 0)} | {o['cls']} |")
    print()
    for cls in ("not measured (no alternative implemented)", "not measured (the tally's figure is an artefact)",
                "outside the count rule (boundaries, not counts)"):
        print(f"{cls}: " + ", ".join(f"{o['row']} ({o['title']})" for o in out if o["cls"] == cls))
    print()
    for o in out:
        if o["artefact"]:
            print(f"artefact set aside, row {o['row']}: {o['artefact']}")
        if o["diagnostic"]:
            print(f"diagnostic, row {o['row']}: {o['diagnostic']}")
    print()
    print("lines per language: " + ", ".join(f"{k} {v:,}" for k, v in lines.items()))


if __name__ == "__main__":
    main()
