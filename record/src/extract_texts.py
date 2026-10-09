"""Extract the 15 read texts in 17 languages from SM Text S3 (Coupé et al. 2019).

Input: the PyMuPDF markdown companion of the supplement in literature/.
Output: data/ref/texts.tsv (Language, Text, text), gitignored with the rest of data/ref.

Repairs applied, both artefacts of PDF extraction rather than of the texts:
- CMN, YUE, JPN: spaces left by line wraps are removed (these scripts don't use them).
- THA: every sara am (U+0E33) comes out as a space plus sara aa (U+0E32), with the
  nikhahit dropped ("น ้า" for "น้ำ"). Since no Thai syllable can begin with sara aa,
  a consonant + space + optional tone mark + sara aa is rewritten as consonant +
  tone mark + sara am.
"""
import csv
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SM = ROOT.parents[2] / "literature/coupe_etal_2019_comparable_information_rates_SM.md"
OUT = ROOT / "data/ref/texts.tsv"

LANGS = ["CAT", "CMN", "DEU", "ENG", "EUS", "FIN", "FRA", "HUN", "ITA",
         "JPN", "KOR", "SPA", "SRP", "THA", "TUR", "VIE", "YUE"]
TEXTS = ["O1", "O2", "O3", "O4", "O6", "O8", "O9",
         "P0", "P1", "P2", "P3", "P8", "P9", "Q0", "Q1"]
CJK = re.compile(r"(?<=[　-ヿ㐀-鿿＀-￯]) +|"
                 r" +(?=[　-ヿ㐀-鿿＀-￯])")
THAI_AM = re.compile(r"(?<=[ก-ฮ]) ([่-๋]?)า")

sm = SM.read_text(encoding="utf-8")
start = sm.index("Passage O1 CAT:")
end = sm.index("Data file S1.", start)
region = sm[start:end]

rows = []
passages = re.split(r"Passage ([OPQ][0-9])\b", region)[1:]
for code, body in zip(passages[::2], passages[1::2]):
    parts = re.split(r"\b(" + "|".join(LANGS) + r"): ", body)[1:]
    for lang, text in zip(parts[::2], parts[1::2]):
        text = re.sub(r"\s+", " ", text).strip()
        if lang in ("CMN", "YUE", "JPN"):
            text = CJK.sub("", text)
        if lang == "THA":
            text = THAI_AM.sub(lambda m: m.group(1) + "ำ", text)
        rows.append((lang, code, text))

found = {(l, c) for l, c, _ in rows}
expected = {(l, c) for l in LANGS for c in TEXTS}
assert len(rows) == len(found), "duplicate language-text pairs"
assert found == expected, f"missing {sorted(expected - found)}, extra {sorted(found - expected)}"

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["Language", "Text", "text"])
    w.writerows(sorted(rows))
print(f"{len(rows)} texts -> {OUT.relative_to(ROOT)}")
