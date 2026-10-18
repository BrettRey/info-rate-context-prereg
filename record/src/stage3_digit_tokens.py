"""Extract the digit and Latin-letter tokens of the read texts, with local context, for the readings
writer (decision 9 (a), Brett 2026-10-11: a read-only Codex run on a separated payload, blind to NS).

Reads ONLY data/ref/texts.tsv (the read texts, Coupé et al. 2019 SM Text S3, CC BY 4.0). It never opens
the readings table (InfoRateData.csv) or any NS value, and computes no syllable count. Output goes to
OUTDIR, which must be outside any repository: payload.tsv (one row per token) and languages.tsv.
Optional library cardinals come from num2words when it is importable:
    uv run --no-project --with num2words==0.5.14 python -I src/stage3_digit_tokens.py OUTDIR
"""
import csv, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXTS = ROOT / "data/ref/texts.tsv"
UNSPACED = {"CMN", "YUE", "JPN", "THA"}          # no spaces between words
LETTER_LANGS = {"CMN", "YUE", "JPN", "KOR", "THA"}  # Latin letters count as tokens to read (DECISIONS 2026-10-09)
N2W = {"CAT": "ca", "CMN": "zh", "DEU": "de", "ENG": "en", "EUS": "eu", "FIN": "fi", "FRA": "fr", "HUN": "hu",
       "ITA": "it", "JPN": "ja", "KOR": "ko", "SPA": "es", "SRP": "sr", "THA": "th", "TUR": "tr", "VIE": "vi", "YUE": "zh"}
DIGIT = "0-9０-９"
LATIN = "A-Za-zＡ-Ｚａ-ｚ"
SPACED_TOKEN = re.compile(rf"\S*[{DIGIT}]\S*(?:\s[{DIGIT}]{{2,}}\S*)*")
UNSPACED_TOKEN = re.compile(rf"[{DIGIT}{LATIN}]+(?:[.:．：][{DIGIT}]+)*")
LETTER_TOKEN = re.compile(rf"\S*[{LATIN}]\S*")
TRAIL = ".,;!?)»\"”’。、！？"


def tokens(lang, text):
    found = []
    if lang in UNSPACED:
        found = [(m.start(), m.end()) for m in UNSPACED_TOKEN.finditer(text)
                 if re.search(rf"[{DIGIT}]", m.group()) or lang in LETTER_LANGS]
    else:
        found = [(m.start(), m.end()) for m in SPACED_TOKEN.finditer(text)]
        if lang in LETTER_LANGS:
            found += [(m.start(), m.end()) for m in LETTER_TOKEN.finditer(text)
                      if not any(a <= m.start() < b for a, b in found)]
    out = []
    for a, b in sorted(found):
        while b > a and text[b - 1] in TRAIL:
            b -= 1
        if b > a:
            out.append((a, b))
    return out


def cardinals(lang, token):
    try:
        from num2words import num2words
    except ImportError:
        return "", "num2words not available"
    parts = []
    for g in re.findall(rf"[{DIGIT}]+", token):
        n = int(g.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
        try:
            parts.append(f"{g} = {num2words(n, lang=N2W[lang])}")
        except (NotImplementedError, KeyError, OverflowError) as e:
            return "", f"num2words has no '{N2W[lang]}' ({type(e).__name__})"
    return "; ".join(parts), "num2words 0.5.14 cardinal, isolated (no case, gender or context)"


def main():
    out = Path(sys.argv[1]).resolve()
    inside = subprocess.run(["git", "-C", str(out.parent if not out.exists() else out), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    if inside.returncode == 0:
        sys.exit(f"{out} is inside a git repository; stage the payload outside any repository")
    out.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(TEXTS.open(encoding="utf-8"), delimiter="\t"))
    width = {True: 25, False: 60}
    payload, langs = [], {}
    for r in rows:
        lang, tid, text = r["Language"], r["Text"], r["text"].replace("\n", " ")
        for a, b in tokens(lang, text):
            w = width[lang in UNSPACED]
            card, card_src = cardinals(lang, text[a:b]) if re.search(rf"[{DIGIT}]", text[a:b]) else ("", "")
            payload.append({"id": f"{lang}-{tid}-{a}", "language": lang, "text": tid, "token": text[a:b],
                            "left": text[max(0, a - w):a], "right": text[b:b + w],
                            "library_cardinals": card, "library_note": card_src})
            langs[lang] = langs.get(lang, 0) + 1
    with (out / "payload.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(payload[0]), delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        w.writeheader(); w.writerows(payload)
    with (out / "languages.tsv").open("w", encoding="utf-8") as f:
        f.write("language\ttokens\n" + "".join(f"{k}\t{v}\n" for k, v in sorted(langs.items())))
    print(f"{len(payload)} tokens in {len(langs)} languages -> {out}")


if __name__ == "__main__":
    main()
