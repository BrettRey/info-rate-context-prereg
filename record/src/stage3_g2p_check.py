"""Stage 3: agreement between candidate G2P tools on syllable counts (DECISIONS.md, 2026-10-09).

For each Latin-script language: 100 word tokens sampled (seed 20261009) from its subtitle
sample; syllables counted from Epitran (not ENG, EUS), espeak-ng, CMUdict (ENG) and pyphen
(where a dictionary exists). A G2P syllable is a maximal run of vowel symbols; for SRP an r
between consonants (or a word edge and a consonant) also counts. Touches no NS value.

Usage: .venv/bin/python -I src/stage3_g2p_check.py
Writes results/stage3/g2p_check_words.tsv (every word and count) and g2p_check_summary.tsv.
"""
import csv, gzip, itertools, pathlib, random, re, subprocess, sys, unicodedata, warnings

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/stage3"
SEED, N_LINES, N_WORDS = 20261009, 2000, 100
LANGS = {  # lang: (epitran code or None, espeak voice, pyphen dict or None)
    "EUS": (None, "eu", "eu"), "CAT": ("cat-Latn", "ca", "ca"), "DEU": ("deu-Latn", "de", "de"),
    "ENG": (None, "en-gb", "en"), "FRA": ("fra-Latn", "fr", "fr"), "ITA": ("ita-Latn", "it", "it"),
    "SPA": ("spa-Latn", "es", "es"), "SRP": ("srp-Latn", "sr", "sr_Latn"),
    "TUR": ("tur-Latn", "tr", None), "FIN": ("fin-Latn", "fi", None), "HUN": ("hun-Latn", "hu", "hu"),
}
VOWELS = set("iyɨʉɯuɪʏʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒɚɝ")
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")

def nuclei(ipa, lang):
    """Count maximal runs of vowel symbols; combining marks, length and stress don't break a run."""
    ipa = unicodedata.normalize("NFD", ipa)
    count, in_v, prev = 0, False, " "
    chars = [c for c in ipa if c not in "ˈˌ"]
    for i, c in enumerate(chars):
        # Epitran's srp-Latn map (lines 31-32) writes every l and n with U+0329, apparently meant
        # as the dental mark U+032A; in SRP the mark is ignored and syllabic r has its own rule.
        if c == "\u0329" and lang == "SRP":
            continue
        if c == "\u0329" and not in_v:      # syllabic mark under a consonant: a nucleus
            count += 1
            continue
        if unicodedata.category(c) == "Mn" or c in "ː:ˑ":
            continue
        base = c
        if base in VOWELS:
            if not in_v:
                count += 1
            in_v = True
        else:
            if lang == "SRP" and base == "r":
                nxt = next((d for d in chars[i + 1:] if unicodedata.category(d) != "Mn"), " ")
                if (prev not in VOWELS) and (nxt not in VOWELS):
                    count += 1
            in_v = False
        prev = base
    return count

def sample_words(lang):
    rng = random.Random(SEED)
    keep = []
    with gzip.open(ROOT / f"data/raw/opensubtitles/{lang}.tsv.gz", "rt", encoding="utf-8") as f:
        next(f)
        for i, row in enumerate(f):
            t = row.rstrip("\n").split("\t", 4)[4]
            if len(keep) < N_LINES:
                keep.append(t)
            else:
                j = rng.randrange(i + 1)
                if j < N_LINES:
                    keep[j] = t
    tokens = [w.lower() for t in keep for w in WORD.findall(t)]
    return random.Random(SEED + 1).sample(tokens, N_WORDS)

def espeak(words, voice):
    out = subprocess.run(["espeak-ng", "-q", "--ipa", "-v", voice], input="\n".join(words),
                         capture_output=True, text=True, check=True).stdout.splitlines()
    out = [l.strip() for l in out if l.strip()]
    if len(out) != len(words):      # one line per input line expected; fall back to word by word
        out = [subprocess.run(["espeak-ng", "-q", "--ipa", "-v", voice, w], capture_output=True,
                              text=True).stdout.strip() for w in words]
    return out

def main():
    import epitran, pyphen, cmudict
    OUT.mkdir(parents=True, exist_ok=True)
    cmu = cmudict.dict()
    rows, summary = [], []
    for lang, (epi_code, voice, pyph) in LANGS.items():
        words = sample_words(lang)
        epi = epitran.Epitran(epi_code) if epi_code else None
        hyph = pyphen.Pyphen(lang=pyph, left=1, right=1) if pyph else None   # no typesetting minimums
        esp = espeak(words, voice)
        for w, e in zip(words, esp):
            r = {"lang": lang, "word": w, "espeak_ipa": e, "espeak": nuclei(e, lang)}
            if epi:
                ipa = epi.transliterate(w)
                r.update(epitran_ipa=ipa, epitran=nuclei(ipa, lang))
            if lang == "ENG":
                pron = cmu.get(w)
                r["cmudict"] = sum(1 for ph in pron[0] if ph[-1].isdigit()) if pron else ""
            if hyph:
                r["pyphen"] = len(hyph.inserted(w).split("-"))
            rows.append(r)
        methods = [m for m in ("epitran", "espeak", "cmudict", "pyphen") if any(m in r and r[m] != "" for r in rows if r["lang"] == lang)]
        for a, b in itertools.combinations(methods, 2):
            pairs = [(r[a], r[b]) for r in rows if r["lang"] == lang and r.get(a, "") != "" and r.get(b, "") != ""]
            agree = sum(1 for x, y in pairs if x == y)
            summary.append({"lang": lang, "pair": f"{a}-{b}", "n": len(pairs), "agree": agree,
                            "rate": round(agree / len(pairs), 2) if pairs else ""})
        print(lang, " ".join(f"{s['pair']} {s['agree']}/{s['n']}" for s in summary if s["lang"] == lang), flush=True)
    fields = ["lang", "word", "epitran_ipa", "epitran", "espeak_ipa", "espeak", "cmudict", "pyphen"]
    with open(OUT / "g2p_check_words.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    with open(OUT / "g2p_check_summary.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]), delimiter="\t"); w.writeheader(); w.writerows(summary)

if __name__ == "__main__":
    main()
