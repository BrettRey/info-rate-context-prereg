"""Filter the Wiktextract extract of English Wiktionary (data/raw/wiktionary/raw-wiktextract-data.jsonl.gz,
2026-10-03; DECISIONS 2026-10-10) to the counter languages, keeping only the fields the counters can use:
word, lang, lang_code, pos, sounds, hyphenation(s), categories (entry and sense level) and forms.
Read as a stream; writes data/interim/wiktionary/<lang_code>.jsonl.gz and a count per language.
Content: CC BY-SA 4.0 and GFDL (Wiktionary); extraction by Wiktextract (Ylonen).
Usage: python -I src/stage3_wiktionary_filter.py
"""
import gzip, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "raw", "wiktionary", "raw-wiktextract-data.jsonl.gz")
OUT = os.path.join(ROOT, "data", "interim", "wiktionary")
LANGS = {"Spanish", "Catalan", "Italian", "German", "English", "French", "Serbo-Croatian", "Turkish", "Finnish",
         "Hungarian", "Basque", "Korean", "Chinese", "Vietnamese"}
KEEP = ("word", "lang", "lang_code", "pos", "sounds", "hyphenation", "hyphenations", "forms")

def main():
    os.makedirs(OUT, exist_ok=True); outs, counts = {}, {}
    with gzip.open(SRC, "rt", encoding="utf-8") as f:
        for n, line in enumerate(f):
            if n % 2_000_000 == 0:
                print(n, sum(counts.values()), flush=True)
            d = json.loads(line); lang = d.get("lang")
            if lang not in LANGS or "word" not in d:
                continue
            rec = {k: d[k] for k in KEEP if k in d}
            cats = set(d.get("categories", []))
            for s in d.get("senses", []):
                cats.update(s.get("categories", []))
            if cats:
                rec["categories"] = sorted(cats)
            code = d.get("lang_code", lang)
            if code not in outs:
                outs[code] = gzip.open(os.path.join(OUT, f"{code}.jsonl.gz"), "wt", encoding="utf-8")
            outs[code].write(json.dumps(rec, ensure_ascii=False) + "\n"); counts[code] = counts.get(code, 0) + 1
    for o in outs.values():
        o.close()
    json.dump(counts, open(os.path.join(OUT, "counts.json"), "w"), indent=1)
    print("done", counts, flush=True)

if __name__ == "__main__":
    main()
