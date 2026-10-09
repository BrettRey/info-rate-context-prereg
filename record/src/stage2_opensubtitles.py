"""Stage 2: sample and normalise OPUS OpenSubtitles v2024 documents, one language at a time.

Implements the rules logged in DECISIONS.md ("Stage 2: OpenSubtitles sampling and
normalisation", 2026-10-08). Members of each raw zip are fetched singly by HTTP range
request and checked against the zip's CRC32; no zip is downloaded whole and no raw XML
is kept.

Usage: .venv/bin/python -I src/stage2_opensubtitles.py EUS [CAT ...]

Outputs (per language):
  data/raw/opensubtitles/<LANG>.tsv.gz            group, folder, file, line, text (gitignored);
                                                  line = 0-based position of the OPUS <s> in its
                                                  document, so gaps mark dropped sentences
  results/stage2/manifest/opensubtitles_<LANG>.tsv  one row per folder tried (tracked)
  results/stage2/manifest/opensubtitles_zips.tsv    zip URL, ETag, Last-Modified, size
  data/interim/stage2_rejects/<LANG>.tsv          sample of rejected lines per filter
"""
import collections
import concurrent.futures as cf
import csv
import gzip
import hashlib
import html
import io
import pathlib
import random
import re
import shutil
import struct
import sys
import time
import unicodedata
import pickle
import urllib.error
import urllib.request
from http.client import HTTPException
import xml.etree.ElementTree as ET
import zipfile
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/raw/opensubtitles"
MANIFEST_DIR = ROOT / "results/stage2/manifest"
REJECT_DIR = ROOT / "data/interim/stage2_rejects"
CKPT_DIR = ROOT / "data/interim/stage2_ckpt"
BASE = "https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/raw/{code}.zip"

SEED = 20261008
CAP_BYTES = 200_000_000      # normalised UTF-8 text per language
MIN_FILE_BYTES = 10_000      # eligibility of a subtitle file, from the zip directory
NO_FILM_ID = "4294967295"    # 2**32 - 1: OPUS's placeholder when a file has no IMDb id
MAX_TRIES = 3                # files tried per folder
MIN_LINES = 50               # kept lines for a document to count
MAX_LETTER_FAIL = 0.20       # Latin scripts: share of lines failing the letter check
MIN_OPUS_CONF = 0.9
NO_OPUS_CONF = {"SRP"}         # OPUS gives sr files 0.5: a tie with hr/bs, not another language
EDGE_LINES = 20              # credit-word filter applies to the first and last 20 lines
ENGLISH_DROP = 0.9
DATA_CEILING = 10 * 1024**3  # bytes under data/
FREE_FLOOR = 40 * 1024**3    # bytes free on the volume
WORKERS = 8
MAX_NET_WAIT = 2 * 3600    # seconds to wait out a lost connection
CHUNK = 64                 # folders per checkpoint
REJECT_SAMPLE = 300

OPUS_CODE = {"VIE": "vi", "EUS": "eu", "CAT": "ca", "DEU": "de", "ENG": "en", "FRA": "fr",
             "ITA": "it", "SPA": "es", "SRP": "sr", "JPN": "ja", "KOR": "ko", "CMN": "zh_CN",
             "THA": "th", "TUR": "tr", "FIN": "fi", "HUN": "hu"}
LATIN = {"VIE", "EUS", "CAT", "DEU", "ENG", "FRA", "ITA", "SPA", "SRP", "TUR", "FIN", "HUN"}

# ---------------------------------------------------------------- letter inventories

def _vietnamese():
    vowels = "aăâeêioôơuưy"
    tones = ["", "\u0300", "\u0301", "\u0309", "\u0303", "\u0323"]
    out = set("bcdđghklmnpqrstvx" + "fjwz")
    for v in vowels:
        for t in tones:
            out.add(unicodedata.normalize("NFC", v + t))
    return out

EXTRA = {
    "EUS": "ñçüáéíóú",
    "CAT": "àèéíïòóúüçñ",
    "DEU": "äöüßé",
    "ENG": "éèïëç",
    "FRA": "àâæçéèêëîïôœùûüÿ",
    "ITA": "àèéìíòóùúî",
    "SPA": "áéíóúüñ",
    "SRP": "čćđšž",
    "TUR": "çğıöşüâîû",
    "FIN": "äöåšž",
    "HUN": "áéíóöőúüű",
}

def latin_inventory(lang):
    letters = _vietnamese() | set("aeiouy") if lang == "VIE" else set("abcdefghijklmnopqrstuvwxyz") | set(EXTRA[lang])
    allowed = set(letters)
    for l in letters:
        u = l.upper()
        if len(u) == 1:
            allowed.add(u)
    allowed |= {"İ", "ẞ"}
    return allowed

def in_ranges(c, ranges):
    o = ord(c)
    return any(a <= o <= b for a, b in ranges)

HAN = [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FFFF), (0x3005, 0x3007)]
KANA = [(0x3040, 0x309F), (0x30A0, 0x30FF), (0x31F0, 0x31FF)]
HANGUL = [(0xAC00, 0xD7A3)]
THAI = [(0x0E01, 0x0E5B)]

def letter_ok_fn(lang):
    if lang in LATIN:
        inv = latin_inventory(lang)
        return lambda c: c in inv
    ranges = {"JPN": HAN + KANA, "CMN": HAN, "YUE": HAN, "KOR": HANGUL, "THA": THAI}[lang]
    return lambda c: in_ranges(c, ranges)

# ---------------------------------------------------------------- repairs and markup

REPAIRS = {
    "SRP": str.maketrans({"è": "č", "æ": "ć", "ð": "đ", "È": "Č", "Æ": "Ć", "Ð": "Đ"}),
    "TUR": str.maketrans({"ý": "ı", "þ": "ş", "ð": "ğ", "Ý": "İ", "Þ": "Ş", "Ð": "Ğ"}),
    "HUN": str.maketrans({"õ": "ő", "û": "ű", "Õ": "Ő", "Û": "Ű", "ô": "ő", "Ô": "Ő"}),   # ô: a second stand-in for ő
    "VIE": str.maketrans({"Ð": "Đ", "ð": "đ"}),   # eth look-alike for d-bar; Vietnamese has no eth
}
SR_CYR = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџш",
                  ["a", "b", "v", "g", "d", "đ", "e", "ž", "z", "i", "j", "k", "l", "lj", "m", "n",
                   "nj", "o", "p", "r", "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š"]))
SR_CYR.update({k.upper(): (v[0].upper() + v[1:]) for k, v in list(SR_CYR.items())})
SR_TABLE = str.maketrans(SR_CYR)

MARKUP = [re.compile(p) for p in (r"<[^>]*>", r"\{[^}]*\}", r"\\[A-Za-z]+[0-9&H]*\}?",
                                   r"\[[^\]]*\]", r"\([^)]*\)")]
STRAY = re.compile(r"[\[\]{}<>()\\]")
MUSIC = re.compile(r"[♪♫♬#¶]")
LEAD_DASH = re.compile(r"^\s*[-–—‐]+\s*")
TURN_DASH = re.compile(r"(?<=\s)[-–—‐]+(?=\S)|\s[-–—‐]+\s")
LABEL = re.compile(r"^([^:：]{2,25})[:：]\s+")
URL = re.compile(r"https?://|www\.|\S@\S+\.\w{2,}|\w\.(com|org|net|tv|info|biz)\b"
                 r"|\w\.(ru|ro|hu|br|es|fr|de|it|tr|vn|cn|jp|kr|th)(/|$)", re.I)
CREDIT = ["subtit", "opensub", "sync", "ripped", "translat", "tradu", "übersetz", "untertitel",
          "sous-titr", "sottotitol", "subtítol", "subtítul", "azpititul", "itzulpen", "tekstity",
          "suomennos", "felirat", "fordítás", "fordította", "altyazı", "çeviri", "çeviren",
          "prevod", "titlov", "phụ đề", "biên dịch", "dịch bởi", "字幕", "翻译", "翻譯", "校对",
          "时间轴", "翻訳", "자막", "번역", "คำบรรยาย", "แปลโดย", "ซับไทย"]
WS = re.compile(r"\s+")
# English test only for lines of >= 4 words containing one of these (words that are not
# also common in the 16 languages: no he, so, was, will, on, me, i, to, do, a, no).
EN_WORDS = set("the you and of is it that what my your we are this with for she they why how "
               "when there here not don't i'm it's you're can't know love want have just like "
               "get all be".split())
TOKEN = re.compile(r"[\w']+")

ENTITY_LEFT = re.compile(r"\b(lrm|rlm|nbsp|zwnj|zwj);", re.I)   # entity remnants that lost their "&"
THAI_AM = re.compile("\u0e4d([\u0e48-\u0e4b]?)\u0e32")        # NFKC splits sara am; recompose

def base_clean(raw, lang):
    t = html.unescape(raw)
    t = ENTITY_LEFT.sub(" ", t)
    t = unicodedata.normalize("NFKC", t)
    if lang == "THA":
        t = THAI_AM.sub("\\1\u0e33", t)
    t = "".join(c for c in t if unicodedata.category(c) not in ("Cf", "Cc"))
    t = WS.sub(" ", t).strip()
    if lang in REPAIRS:
        t = t.translate(REPAIRS[lang])
    if lang == "SRP":
        t = t.translate(SR_TABLE)
    return t

class Normaliser:
    FILTERS = ["empty_raw", "music", "url", "credit", "digit", "letters", "english", "no_letters"]

    def __init__(self, lang):
        self.lang = lang
        self.letter_ok = letter_ok_fn(lang)
        self.lid = None
        if lang in LATIN and lang != "ENG":
            from lingua import Language, LanguageDetectorBuilder
            target = {"VIE": Language.VIETNAMESE, "EUS": Language.BASQUE, "CAT": Language.CATALAN,
                      "DEU": Language.GERMAN, "FRA": Language.FRENCH, "ITA": Language.ITALIAN,
                      "SPA": Language.SPANISH, "SRP": Language.CROATIAN, "TUR": Language.TURKISH,
                      "FIN": Language.FINNISH, "HUN": Language.HUNGARIAN}[lang]
            self.lid = LanguageDetectorBuilder.from_languages(target, Language.ENGLISH).build()
            self.english = Language.ENGLISH

    def line(self, raw, pos, n):
        """Return (text, None) if kept, or (original, filter_name) if dropped."""
        t = base_clean(raw, self.lang)
        if not t:
            return raw, "empty_raw"
        if MUSIC.search(t):
            return t, "music"
        for rx in MARKUP:
            t = rx.sub(" ", t)
        t = STRAY.sub(" ", t)
        if self.lang in LATIN:
            m = LABEL.match(t)
            if m and m.group(1).isupper():
                t = t[m.end():]
        t = LEAD_DASH.sub("", t)
        t = TURN_DASH.sub(" ", t)
        t = WS.sub(" ", t).strip()
        if URL.search(t):
            return t, "url"
        if pos < EDGE_LINES or pos >= n - EDGE_LINES:
            low = t.lower()
            if any(w in low for w in CREDIT):
                return t, "credit"
        if any(unicodedata.category(c) == "Nd" for c in t):
            return t, "digit"
        letters = [c for c in t if unicodedata.category(c)[0] in "LM"]
        if not letters:
            return t, "no_letters"
        if ("\ufffd" in t or any(unicodedata.category(c) == "Co" for c in t)
                or not all(self.letter_ok(c) for c in letters)):
            return t, "letters"
        return t, None

    def english_flags(self, texts):
        out = [False] * len(texts)
        if self.lid is None or not texts:
            return out
        cand = [j for j, t in enumerate(texts)
                if len(t.split()) >= 4 and any(w in EN_WORDS for w in TOKEN.findall(t.lower()))]
        if not cand:
            return out
        vals = self.lid.compute_language_confidence_values_in_parallel([texts[j] for j in cand])
        for j, cv in zip(cand, vals):
            eng = next((c.value for c in cv if c.language == self.english), 0.0)
            out[j] = eng >= ENGLISH_DROP
        return out

# ---------------------------------------------------------------- HTTP and zip access

class NetworkDown(BaseException):
    """Raised after MAX_NET_WAIT without a connection; not caught as a per-folder error."""

def http(url, headers=None, method="GET"):
    """GET or HEAD. Server errors retry briefly; a lost connection is waited out, then aborts."""
    attempt, waited, warned = 0, 0, False
    while True:
        try:
            req = urllib.request.Request(url, headers=headers or {}, method=method)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.headers, (r.read() if method == "GET" else b"")
        except urllib.error.HTTPError as e:
            if e.code in (408, 429, 500, 502, 503, 504) and attempt < 8:
                attempt += 1
                time.sleep(min(60, 2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, HTTPException, OSError) as e:
            if waited >= MAX_NET_WAIT:
                raise NetworkDown(f"no connection for {waited}s: {e}")
            if not warned:
                print(f"network error ({e}); waiting for the connection", flush=True)
                warned = True
            time.sleep(30)
            waited += 30

class HTTPFile(io.RawIOBase):
    def __init__(self, url, size):
        self.url, self.size, self.pos = url, size, 0
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos
    def readinto(self, b):
        if self.pos >= self.size or len(b) == 0:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        _, data = http(self.url, {"Range": f"bytes={self.pos}-{end}"})
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)

def fetch_member(url, info):
    off = info.header_offset
    want = 30 + len(info.filename.encode()) + 1024 + info.compress_size
    _, blob = http(url, {"Range": f"bytes={off}-{off + want - 1}"})
    sig, *_ = struct.unpack("<I", blob[:4])
    assert sig == 0x04034B50, f"bad local header at {off}"
    fnlen, extralen = struct.unpack("<HH", blob[26:30])
    start = 30 + fnlen + extralen
    data = blob[start:start + info.compress_size]
    if len(data) < info.compress_size:
        a = off + start + len(data)
        _, rest = http(url, {"Range": f"bytes={a}-{off + start + info.compress_size - 1}"})
        data += rest
    if info.compress_type == zipfile.ZIP_DEFLATED:
        raw = zlib.decompressobj(-15).decompress(data)
    elif info.compress_type == zipfile.ZIP_STORED:
        raw = data
    else:
        raise ValueError(f"compression {info.compress_type}")
    if zlib.crc32(raw) & 0xFFFFFFFF != info.CRC:
        raise ValueError("CRC mismatch")
    return raw

# ---------------------------------------------------------------- documents

def parse_doc(raw):
    root = ET.fromstring(raw)
    meta = {}
    m = root.find("meta")
    if m is not None:
        for el in m.iter():
            if el.text and el.text.strip() and len(el) == 0:
                meta[el.tag] = el.text.strip()
    sents = [" ".join(s.itertext()) for s in root.iter("s")]
    return meta, sents

def process_folder(url, files, norm):
    """Try up to MAX_TRIES files of one folder; return a result dict."""
    res = {"tried": 0, "status": "no_eligible_file"}
    for info in files[:MAX_TRIES]:
        res["tried"] += 1
        try:
            raw = fetch_member(url, info)
            meta, sents = parse_doc(raw)
        except Exception as e:
            res.update(status=f"error:{type(e).__name__}", file=info.filename)
            continue
        counts = collections.Counter()
        rejects = []
        kept = []
        n = len(sents)
        for i, s in enumerate(sents):
            t, why = norm.line(s, i, n)
            if why:
                counts[why] += 1
                rejects.append((why, t))
            else:
                kept.append((i, t))
        flags = norm.english_flags([t for _, t in kept])
        final = []
        for (i, t), f in zip(kept, flags):
            if f:
                counts["english"] += 1
                rejects.append(("english", t))
            else:
                final.append((i, t))
        status = "kept"
        if meta.get("machine_translated") == "1":
            status = "drop:machine_translated"
        elif norm.lang not in NO_OPUS_CONF and "confidence" in meta and float(meta["confidence"]) < MIN_OPUS_CONF:
            status = "drop:opus_confidence"
        elif norm.lang in LATIN and n and counts["letters"] / n > MAX_LETTER_FAIL:
            status = "drop:letter_rate"
        elif len(final) < MIN_LINES:
            status = "drop:too_few_lines"
        res = {"tried": res["tried"], "status": status, "file": info.filename,
               "sha256": hashlib.sha256(raw).hexdigest(), "n_sent": n, "n_kept": len(final),
               "bytes_kept": sum(len(t.encode()) for _, t in final), "counts": counts,
               "rejects": rejects, "lines": final, "mt": meta.get("machine_translated", ""),
               "conf": meta.get("confidence", "")}
        if status == "kept":
            return res
    return res

def folder_key(path):
    parts = path.split("/")          # OpenSubtitles/raw/<code>/<year>/<folder>/<file>.xml
    return parts[3], parts[4]

def group_of(folder):
    f = folder.split("_")
    return f[1] if len(f) >= 2 else f[0]

def du(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())

def guard():
    free = shutil.disk_usage(ROOT).free
    used = du(ROOT / "data")
    if free < FREE_FLOOR:
        sys.exit(f"STOP: free space {free/1e9:.1f} GB below floor")
    if used > DATA_CEILING:
        sys.exit(f"STOP: data/ at {used/1e9:.1f} GB, over ceiling")

# ---------------------------------------------------------------- per language

def save_ckpt(path, st):
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(st))
    tmp.replace(path)

def run(lang):
    code = OPUS_CODE[lang]
    url = BASE.format(code=code)
    out = OUT_DIR / f"{lang}.tsv.gz"
    if out.exists():
        print(f"{lang}: {out} exists, skipping")
        return
    guard()
    hdrs, _ = http(url, method="HEAD")
    size = int(hdrs["Content-Length"])
    etag = hdrs.get("ETag", "").strip('"')
    z = zipfile.ZipFile(io.BufferedReader(HTTPFile(url, size), buffer_size=1 << 20))
    infos = [i for i in z.infolist() if i.filename.endswith(".xml")]
    folders = collections.defaultdict(list)
    for i in infos:
        folders[folder_key(i.filename)].append(i)
    keys = sorted(folders)
    random.Random(SEED).shuffle(keys)
    eligible = {k: sorted((i for i in folders[k] if i.file_size >= MIN_FILE_BYTES),
                          key=lambda i: int(pathlib.PurePosixPath(i.filename).stem))
                for k in keys}

    # One file per film: skip the no-id placeholder (unrelated films share it) and any film id
    # already met under another year folder; the first in shuffled order wins.
    skip, seen_ids = {}, set()
    for k in keys:
        fid = k[1]
        if fid.split("_")[0] == NO_FILM_ID:
            skip[k] = "skip:no_film_id"
        elif fid in seen_ids:
            skip[k] = "skip:repeated_film_id"
        else:
            seen_ids.add(fid)

    for d in (OUT_DIR, MANIFEST_DIR, REJECT_DIR, CKPT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    ckpt = CKPT_DIR / f"opensubtitles_{lang}.pkl"
    if ckpt.exists():
        st = pickle.loads(ckpt.read_bytes())
        if st["etag"] != etag:
            sys.exit(f"STOP: {lang} zip changed since the checkpoint (ETag {st['etag']} -> {etag})")
        with open(tmp, "r+b") as fh:
            fh.truncate(st["text_bytes"])
        print(f"{lang}: resuming at folder {st['next']}, {st['total_bytes']/1e6:.1f} MB", flush=True)
    else:
        tmp.unlink(missing_ok=True)
        with gzip.open(tmp, "wt", encoding="utf-8", newline="") as g:
            g.write("group\tfolder\tfile\tline\ttext\n")
        st = {"etag": etag, "next": 0, "text_bytes": tmp.stat().st_size, "total_bytes": 0,
              "totals": collections.Counter(), "reservoir": {}, "seen": collections.Counter(),
              "rng": random.Random(SEED).getstate(), "mrows": [], "done": False}
        zips = MANIFEST_DIR / "opensubtitles_zips.tsv"
        new = not zips.exists()
        with open(zips, "a", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            if new:
                w.writerow(["lang", "url", "etag", "last_modified", "bytes", "xml_files", "folders", "fetched"])
            w.writerow([lang, url, etag, hdrs.get("Last-Modified", ""), size,
                        len(infos), len(keys), time.strftime("%Y-%m-%d %H:%M:%S")])
        save_ckpt(ckpt, st)

    norm = Normaliser(lang)
    rng = random.Random()
    rng.setstate(st["rng"])
    t0 = time.time()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        c0 = st["next"]
        while c0 < len(keys) and not st["done"]:
            guard()
            batch = keys[c0:c0 + CHUNK]
            results = list(ex.map(lambda k: {"tried": 0, "status": skip[k]} if k in skip
                                  else process_folder(url, eligible[k], norm), batch))
            with gzip.open(tmp, "at", encoding="utf-8", newline="") as g:
                for (year, folder), r in zip(batch, results):
                    if st["done"]:
                        break
                    grp = group_of(folder)
                    row = {"year": year, "folder": folder, "group": grp, "status": r["status"],
                           "tried": r["tried"], "file": pathlib.PurePosixPath(r.get("file", "")).stem,
                           "sha256": r.get("sha256", ""), "machine_translated": r.get("mt", ""),
                           "opus_confidence": r.get("conf", ""), "n_sent": r.get("n_sent", 0),
                           "n_kept": r.get("n_kept", 0), "bytes_kept": r.get("bytes_kept", 0)}
                    cnt = r.get("counts", collections.Counter())
                    for fn in Normaliser.FILTERS:
                        row[fn] = cnt.get(fn, 0)
                    st["mrows"].append(row)
                    if r["status"] != "kept":
                        continue
                    for j, t in r["lines"]:
                        g.write(f"{grp}\t{folder}\t{row['file']}\t{j}\t{t}\n")
                    st["total_bytes"] += r["bytes_kept"]
                    st["totals"].update(cnt)
                    st["totals"]["kept_lines"] += r["n_kept"]
                    st["totals"]["sentences"] += r["n_sent"]
                    for why, t in r["rejects"]:
                        st["seen"][why] += 1
                        lst = st["reservoir"].setdefault(why, [])
                        if len(lst) < REJECT_SAMPLE:
                            lst.append((folder, t))
                        else:
                            k = rng.randrange(st["seen"][why])
                            if k < REJECT_SAMPLE:
                                lst[k] = (folder, t)
                    if st["total_bytes"] >= CAP_BYTES:
                        st["done"] = True
            c0 += len(batch)
            st["next"] = c0
            st["text_bytes"] = tmp.stat().st_size
            st["rng"] = rng.getstate()
            save_ckpt(ckpt, st)
            kept_docs = sum(1 for m in st["mrows"] if m["status"] == "kept")
            print(f"{lang}: {len(st['mrows'])} folders, {kept_docs} kept, {st['total_bytes']/1e6:.1f} MB, "
                  f"{time.time()-t0:.0f}s", flush=True)

    mrows, totals = st["mrows"], st["totals"]
    with open(MANIFEST_DIR / f"opensubtitles_{lang}.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(mrows[0]), delimiter="\t")
        w.writeheader()
        w.writerows(mrows)
    with open(REJECT_DIR / f"{lang}.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["filter", "folder", "text"])
        for why in sorted(st["reservoir"]):
            for folder, t in st["reservoir"][why]:
                w.writerow([why, folder, t])
    tmp.rename(out)
    ckpt.unlink()
    status = collections.Counter(m["status"] for m in mrows)
    print(f"{lang}: done. folders {len(mrows)} {dict(status)}; kept lines {totals['kept_lines']} "
          f"of {totals['sentences']} sentences in kept docs; {st['total_bytes']/1e6:.1f} MB; drops "
          + ", ".join(f"{k} {totals[k]}" for k in Normaliser.FILTERS), flush=True)

if __name__ == "__main__":
    for lang in sys.argv[1:]:
        run(lang)
