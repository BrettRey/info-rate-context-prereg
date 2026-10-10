"""Exposure counts for readings the tally can't compute (DECISIONS 2026-10-10): how often a rough proxy
for each row's triggering environment occurs in the tally sample. Proxy frequencies, not bounds and not
changes in counts: the word lists are rough, written for this count only, and are not candidate rules; the
Italian prefix proxy misses unprefixed hiatus such as *biologia*. Revised 2026-10-10 after review: adjacency
is checked within phrases only, and the Han denominator is Script=Han, as in the counters.
Usage: python -I src/stage3_tally_exposure.py
"""
import json, os, re, unicodedata
import regex
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "data", "interim", "tally-sample")
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.U)
CAT_FUNCTION = {"a", "i", "o", "u", "la", "de", "que", "se", "me", "te", "ne", "ho", "hi", "ja", "ni", "si", "li"}
VOWEL0 = re.compile(r"^[aeiouàèéíïòóúüh]", re.I)

def lines(lang):
    with open(os.path.join(S, f"{lang}.txt"), encoding="utf-8") as f:
        return [unicodedata.normalize("NFC", l.rstrip("\n")) for l in f]

def words(line):
    return [w.lower() for w in WORD.findall(line)]

out = {}
PHRASE = re.compile(r"[.,;:?!…«»\"“”„()\[\]–—⟂]")
ls = lines("CAT"); n = hit = 0
for l in ls:
    for ph in PHRASE.split(l):
        ws = words(ph); n += len(ws)
        hit += sum(1 for a, b in zip(ws, ws[1:]) if a in CAT_FUNCTION and VOWEL0.match(b))
out["12 CAT function word before a vowel"] = {"tokens": n, "environments": hit, "share": hit / n}
ws = [w for l in lines("FRA") for w in words(l)]
e = sum(1 for w in ws if w.endswith("ent") and len(w) > 4)
out["13 FRA tokens ending in -ent"] = {"tokens": len(ws), "environments": e, "share": e / len(ws)}
ws = [w for l in lines("ITA") for w in words(l)]
e = sum(1 for w in ws if re.match(r"^(ri|re|pre|de|pro)[aeiou]", w))
out["18 ITA prefix-like ri/re/pre/de/pro + vowel"] = {"tokens": len(ws), "environments": e, "share": e / len(ws)}
for lang in ("CMN", "YUE"):
    chars = [c for l in lines(lang) for c in l if regex.match(r"\p{Han}", c)]
    e = sum(1 for c in chars if c in "儿兒")
    out[f"30-33 {lang} share of Han characters that are 儿/兒"] = {"characters": len(chars), "environments": e, "share": e / len(chars) if chars else 0}
for lang in sorted(f[:-4] for f in os.listdir(S) if f.endswith(".txt")):
    ls = lines(lang); d = sum(1 for l in ls if re.search(r"\d", l))
    out[f"38 {lang} lines with a digit"] = {"lines": len(ls), "environments": d, "share": d / len(ls)}
json.dump(out, open(os.path.join(ROOT, "data", "interim", "tally-results", "exposure.json"), "w"), indent=1, ensure_ascii=False)
for k, v in out.items():
    print(f"{k}: {v['environments']} of {v.get('tokens', v.get('characters', v.get('lines')))} ({100 * v['share']:.1f}%)")
