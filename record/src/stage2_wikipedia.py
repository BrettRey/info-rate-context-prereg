"""Stage 2: sample and clean Hugging Face wikimedia/wikipedia 20231101, one language at a time.

Implements DECISIONS.md: "Stage 2: Wikipedia source" and the approved stub rule
(notes/wikipedia-stub-rule-proposal.md). Row groups (1,000 page-id-ordered articles) are
sampled at random across a language's shards and read by HTTP range request; the row group
is the split group for Stage 5.

Pass 1 keeps each article's prose lines (ending in sentence-final punctuation), splits them
into sentences and cleans them. Tokens with a digit or with letters outside the language's
inventory are replaced by the gap marker GAP, so both treatments can be built later:
drop every sentence containing GAP (as the subtitles were cleaned), or split sentences at
GAP. Pass 2 computes each article's template share and drops articles at 0.5 or more; the
share is stored, so the 0.3 arm is a filter on the output.

Usage: .venv/bin/python -I src/stage2_wikipedia.py YUE [EUS ...]
Outputs:
  data/raw/wikipedia/<LANG>.tsv.gz             group, article, sentence, share, text (gitignored)
  results/stage2/manifest/wikipedia_<LANG>.tsv.gz one row per sampled article (tracked)
  results/stage2/manifest/wikipedia_shards.tsv shard URL, ETag, size, row groups
"""
import collections
import csv
import gzip
import io
import json
import pathlib
import random
import re
import sys
import time
import unicodedata
import urllib.request
import zlib

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import stage2_opensubtitles as os2  # noqa: E402  (letter inventories, LID, HTTP, guard)

ROOT = os2.ROOT
OUT_DIR = ROOT / "data/raw/wikipedia"
CACHE_DIR = ROOT / "data/interim/wiki_cache"
MANIFEST_DIR = ROOT / "results/stage2/manifest"
HF = "https://huggingface.co/datasets/wikimedia/wikipedia"
SNAPSHOT = "20231101"
CODE = {"VIE": "vi", "EUS": "eu", "CAT": "ca", "DEU": "de", "ENG": "en", "FRA": "fr",
        "ITA": "it", "SPA": "es", "SRP": "sr", "JPN": "ja", "KOR": "ko", "CMN": "zh",
        "YUE": "zh-yue", "THA": "th", "TUR": "tr", "FIN": "fi", "HUN": "hu"}
CJK = {"CMN", "YUE", "JPN"}
SEED = 20261008
CAP_BYTES = 200_000_000      # pass-1 prose (gap markers excluded) per language
NGRAM, SUBSAMPLE, DF_FLOOR = 8, 4, 20
# Window length (Brett, 2026-10-08): 8 characters where a character is roughly a syllable,
# 24 elsewhere. The first rule (8 everywhere) dropped 97.5% of Basque articles.
SHORT_WINDOW = {"CMN", "YUE", "JPN", "KOR"}

def window(lang):
    return NGRAM if lang in SHORT_WINDOW else 24
SHARE_DROP = 0.5             # main threshold; 0.3 arm is a filter on the stored share
GAP = "⟂"
THAI_CHAR = re.compile(r"[\u0e01-\u0e5b]")
THAI_MIN = 80                # Thai prose line: at least 80 Thai characters (Brett, 2026-10-08)
THAI_MIN_ARM = 150           # sensitivity row

END = re.compile(r"[。！？.!?…][」』”\"’'）)\]]*\s*$")
SPLIT_CJK = re.compile(r"(?<=[。！？!?])[」』”\"）)]*")
SPLIT_SPACE = re.compile(r"(?<=[.!?…])(?<![0-9]\.)[”\"’')\]]*\s+")   # no split after an ordinal "1300."
PAREN = re.compile(r"[(（][^)）]*[)）]|\[[^\]]*\]")
DIGITS = re.compile(r"\d+(?:[.,:/\-]\d+)*")
LATIN_RUN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ɏ][A-Za-zÀ-ÖØ-öø-ɏ'’\-]*")
WS = re.compile(r"\s+")
GAPS = re.compile(GAP + r"(?:\s*" + GAP + r")*")

def wiki_clean(t, lang):
    """Like the subtitle base_clean, without the subtitle code-page repairs."""
    t = unicodedata.normalize("NFKC", t)
    if lang == "THA":
        t = os2.THAI_AM.sub("\\1\u0e33", t)
    t = "".join(c for c in t if unicodedata.category(c) not in ("Cf", "Cc", "Co"))
    if lang == "SRP":
        t = t.translate(os2.SR_TABLE)
    if lang == "VIE":
        t = t.translate(os2.REPAIRS["VIE"])
    return WS.sub(" ", t).strip()

def gap_tokens(s, lang, letter_ok):
    """Replace digit tokens and out-of-inventory letter runs with GAP."""
    if lang in CJK or lang in ("KOR", "THA"):
        s = DIGITS.sub(GAP, s)
        s = LATIN_RUN.sub(GAP, s)
        s = "".join(c if (unicodedata.category(c)[0] not in "LM" or letter_ok(c)) else GAP for c in s)
    else:
        out = []
        for tok in s.split(" "):
            letters = [c for c in tok if unicodedata.category(c)[0] in "LM"]
            if any(unicodedata.category(c) == "Nd" for c in tok) or not all(letter_ok(c) for c in letters):
                out.append(GAP)
            else:
                out.append(tok)
        s = " ".join(out)
    return GAPS.sub(GAP, s)

# A piece ending in an ordinal or an initial ("1300.", "XIX.", "II.", "J.") did not end a
# sentence: rejoin it to what follows. Python look-behinds can't express a Roman numeral.
NOT_AN_END = re.compile(r"(?:^|\s)(?:[0-9]+|[IVXLCDM]+|[A-ZÀ-ÖØ-Þ])\.[”\"’')\]]*$")

def sentences(para, lang):
    if lang == "THA":            # Thai marks sentence and clause breaks with spaces
        return [p for p in para.split(" ") if p]
    if lang in CJK:
        parts = [p.strip() for p in SPLIT_CJK.split(para) if p and p.strip()]
        return parts
    parts = [p.strip() for p in SPLIT_SPACE.split(para) if p and p.strip()]
    out = []
    for p in parts:
        if out and NOT_AN_END.search(out[-1]):
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out

def letters_left(s):
    return any(unicodedata.category(c)[0] == "L" for c in s.replace(GAP, ""))

# ---------------------------------------------------------------- access

def shard_list(code):
    url = f"https://huggingface.co/api/datasets/wikimedia/wikipedia/tree/main/{SNAPSHOT}.{code}"
    _, body = os2.http(url)
    return sorted(x["path"] for x in json.loads(body) if x["path"].endswith(".parquet"))

def open_shard(path):
    url = f"{HF}/resolve/main/{path}"
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=120) as r:
        size, final = int(r.headers["Content-Length"]), r.geturl()
        etag = r.headers.get("X-Linked-Etag") or r.headers.get("ETag", "")
    # Read through the stable resolve URL: each range request is redirected afresh, so a
    # signed CDN link expiring mid-run doesn't matter (urllib keeps the Range header).
    f = io.BufferedReader(os2.HTTPFile(url, size), buffer_size=1 << 20)
    return pq.ParquetFile(f), url, size, etag.strip('"')

# ---------------------------------------------------------------- pass 1

def pass1(lang):
    code = CODE[lang]
    cache = CACHE_DIR / f"{lang}.jsonl.gz"
    if cache.exists():
        print(f"{lang}: pass-1 cache exists", flush=True)
        return cache
    os2.guard()
    norm = os2.Normaliser(lang)
    shards = shard_list(code)
    units, files = [], {}
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    sh = MANIFEST_DIR / "wikipedia_shards.tsv"
    new = not sh.exists()
    with open(sh, "a", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        if new:
            w.writerow(["lang", "shard", "url", "etag", "bytes", "rows", "row_groups", "read"])
        for p in shards:
            pf, url, size, etag = open_shard(p)
            files[p] = pf
            units += [(p, g) for g in range(pf.metadata.num_row_groups)]
            w.writerow([lang, p, url, etag, size, pf.metadata.num_rows, pf.metadata.num_row_groups,
                        time.strftime("%Y-%m-%d %H:%M:%S")])
    random.Random(SEED).shuffle(units)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".part")
    total, t0, read = 0, time.time(), 0
    counts = collections.Counter()
    with gzip.open(tmp, "wt", encoding="utf-8") as g:
        for k, (p, rg) in enumerate(units):
            if total >= CAP_BYTES:
                break
            if k % 20 == 0:
                os2.guard()
            tab = files[p].read_row_group(rg, columns=["id", "title", "text"]).to_pylist()
            read += 1
            group = f"{pathlib.PurePosixPath(p).stem}:{rg}"
            for art in tab:
                counts["articles"] += 1
                prose, sents, pthai, sent_para = [], [], [], []
                for para in art["text"].split("\n"):
                    para = wiki_clean(para, lang)
                    if not para:
                        continue
                    if lang == "THA":
                        nth = len(THAI_CHAR.findall(para))
                        if nth < THAI_MIN or para[0] in "|{}":
                            continue
                    elif not END.search(para):
                        continue
                    prose.append(para)
                    if lang == "THA":
                        pthai.append(nth)
                    for s in sentences(PAREN.sub(" ", para), lang):
                        s = WS.sub(" ", os2.STRAY.sub(" ", s)).strip()
                        if os2.URL.search(s):
                            counts["url"] += 1
                            continue
                        s = gap_tokens(s, lang, norm.letter_ok)
                        if not letters_left(s):
                            counts["no_letters"] += 1
                            continue
                        sents.append(s)
                        sent_para.append(len(prose) - 1)
                if not prose:
                    counts["no_prose"] += 1
                eng = norm.english_flags([s.replace(GAP, " ") for s in sents])
                kept = [s for s, e in zip(sents, eng) if not e]
                kept_para = [q for q, e in zip(sent_para, eng) if not e]
                counts["english"] += len(sents) - len(kept)
                rec = {"group": group, "id": art["id"], "title": art["title"],
                       "prose": prose, "sents": kept}
                if lang == "THA":
                    rec["pthai"], rec["sent_para"] = pthai, kept_para
                g.write(json.dumps(rec, ensure_ascii=False) + "\n")
                total += sum(len(s.replace(GAP, "").encode()) for s in kept)
            if k % 10 == 0:
                print(f"{lang}: {k+1}/{len(units)} row groups, {counts['articles']} articles, "
                      f"{total/1e6:.1f} MB, {time.time()-t0:.0f}s", flush=True)
    tmp.rename(cache)
    print(f"{lang}: pass 1 done, {read} of {len(units)} row groups; "
          f"{dict(counts)}; {total/1e6:.1f} MB", flush=True)
    return cache

# ---------------------------------------------------------------- pass 2

def gram_hashes(prose, n):
    x = re.sub(r"\d", "9", " ".join(prose))
    hs = set()
    for i in range(len(x) - n + 1):
        b = x[i:i + n].encode()
        lo = zlib.crc32(b)
        if lo % SUBSAMPLE == 0:              # stable 1-in-4 subsample
            hs.add((zlib.crc32(b[::-1]) << 32) | lo)   # stable 64-bit key
    return np.fromiter(hs, dtype=np.uint64, count=len(hs))

def thai_subset(a, floor):
    """Keep only paragraphs with at least `floor` Thai characters, and their sentences."""
    keep = {i for i, n in enumerate(a["pthai"]) if n >= floor}
    a = dict(a)
    a["prose"] = [p for i, p in enumerate(a["prose"]) if i in keep]
    a["sents"] = [x for x, q in zip(a["sents"], a["sent_para"]) if q in keep]
    return a

def pass2(lang, cache, thai_floor=None):
    arts = [json.loads(l) for l in gzip.open(cache, "rt", encoding="utf-8")]
    name = lang
    if thai_floor:
        arts = [thai_subset(a, thai_floor) for a in arts]
        name = f"{lang}-p{thai_floor}"
    H = [gram_hashes(a["prose"], window(lang)) for a in arts]
    allh = np.concatenate([h for h in H if len(h)]) if any(len(h) for h in H) else np.zeros(0, np.uint64)
    uniq, df = np.unique(allh, return_counts=True)
    shared = set(uniq[df >= DF_FLOOR].tolist())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.tsv.gz"
    rows = []
    with gzip.open(out.with_suffix(".part"), "wt", encoding="utf-8") as g:
        g.write("group\tarticle\tsentence\tshare\ttext\n")
        for a, h in zip(arts, H):
            share = (sum(1 for x in h.tolist() if x in shared) / len(h)) if len(h) else 1.0
            status = "no_prose" if not a["prose"] else ("drop:template" if share >= SHARE_DROP else "kept")
            if status == "kept":
                for j, s in enumerate(a["sents"]):
                    g.write(f"{a['group']}\t{a['id']}\t{j}\t{share:.3f}\t{s}\n")
            rows.append({"group": a["group"], "article": a["id"], "status": status,
                         "share": f"{share:.3f}", "n_sent": len(a["sents"]),
                         "bytes": sum(len(s.replace(GAP, "").encode()) for s in a["sents"])})
    out.with_suffix(".part").rename(out)
    with gzip.open(MANIFEST_DIR / f"wikipedia_{name}.tsv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    st = collections.Counter(r["status"] for r in rows)
    kept = [r for r in rows if r["status"] == "kept"]
    kb = sum(r["bytes"] for r in kept)
    k3 = sum(r["bytes"] for r in kept if float(r["share"]) < 0.3)
    print(f"{name}: pass 2 done. articles {len(rows)} {dict(st)}; kept {kb/1e6:.1f} MB "
          f"(share < 0.3 arm {k3/1e6:.1f} MB)", flush=True)

def run(lang, pass1_only=False):
    out = OUT_DIR / f"{lang}.tsv.gz"
    if out.exists():
        print(f"{lang}: {out} exists, skipping")
        return
    cache = pass1(lang)
    if pass1_only:
        print(f"{lang}: pass 2 not run (pass1_only)", flush=True)
        return
    pass2(lang, cache)
    if lang == "THA":
        pass2(lang, cache, thai_floor=THAI_MIN_ARM)

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for lang in args:
        run(lang, pass1_only="--pass1-only" in sys.argv)
