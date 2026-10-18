"""Candidate document plumbing, with no corpus discovery or implicit downloads.

`process_document` accepts text already supplied by its caller. A main G2P is
cached independently of the counter option (Japanese contextual source chunks,
otherwise word types). Counters with no full segmentation
block estimator inputs by default; `segment_mode='nuclei'` is an explicit proxy
for fake-data plumbing, or a versioned segmenter may supply full syllables.

Boundary models use isolated bigram windows. Their context tokens are auxiliary:
score only the target token, normalising over S outcomes (or J outcomes for the
charged model), excluding context tokens, EOS and UNK. Ordinary rung files use
orders k+1. Metadata is stored alongside text, never inside KenLM's vocabulary.
"""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import MappingProxyType
import unicodedata as U
import regex
from dataclasses import asdict, dataclass, replace

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("stage4_candidate_counters", ROOT / "src/stage3/counters.py")
C = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = C
_spec.loader.exec_module(C)
RUNGS = ("0", "1w", "1", "2", "3", "4", "1b-free", "1b-charged",
         "2-free", "2-charged", "3-free", "3-charged", "4-free", "4-charged")
TREATMENTS = ("line-bounded", "cross-line")
GIB = 1024 ** 3


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


_FILE_DIGESTS = {}
_DISTRIBUTION_VERSIONS = {}


def _stamp(stat):
    """A file's identity for reuse: size, modification and change times, inode.

    Writing a file's contents always moves its change time (which `touch` can't
    set back), and copying another file in gives a new inode, so size and
    modification time alone are not enough (P8 fixes review, 2026-10-14).
    """
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_dev)


def _file_digest(path):
    """A source file's digest, reread only when its stamp changes.

    `version()` runs on every pronunciation-cache lookup (through the G2P
    descriptor); rehashing every source file each time was most of the cost of
    cutting real text (P8 profile, 2026-10-14).
    """
    name = os.fspath(path)
    key = (name, *_stamp(os.stat(name)))
    if key not in _FILE_DIGESTS:
        with open(name, 'rb') as stream:
            _FILE_DIGESTS[key] = digest(stream.read())
    return _FILE_DIGESTS[key]


_VERSION_FILES = {}


def _version_files():
    root = os.fspath(ROOT)
    if root not in _VERSION_FILES:
        _VERSION_FILES[root] = (__file__, os.fspath(ROOT / "src/stage3/counters.py"),
                                os.fspath(ROOT / "src/stage3/french_lexicon.py"),
                                *(os.fspath(ROOT / 'src/stage3' / n) for n in (
                                    'native_units.py', 'japanese.py', 'thai.py', 'multiverse.py', 'segment.py',
                                    'onsets.py', 'tones.py', 'word_segmenters.py')))
    return _VERSION_FILES[root]


def version_fingerprint():
    """A cheap stand-in for `version()`: it changes whenever any file `version()` hashes does."""
    return tuple((name, *_stamp(os.stat(name))) for name in _version_files())


def _distribution_version(name):
    if name not in _DISTRIBUTION_VERSIONS:
        _DISTRIBUTION_VERSIONS[name] = importlib.metadata.version(name)
    return _DISTRIBUTION_VERSIONS[name]


def version():
    """Fingerprint both the pipeline and the actual candidate counter source."""
    return {"pipeline": _file_digest(Path(__file__)),
            "counter": _file_digest(ROOT / "src/stage3/counters.py"),
            "french_helpers": _file_digest(ROOT / "src/stage3/french_lexicon.py"),
            "native_counters": {name: _file_digest(ROOT / 'src/stage3' / name)
                                for name in ('native_units.py', 'japanese.py', 'thai.py')},
            "segmentation_registry": {name: _file_digest(ROOT / 'src/stage3' / name)
                                      for name in ('multiverse.py', 'segment.py', 'onsets.py', 'tones.py', 'word_segmenters.py')},
            "lexicons": C.LEXICON_PROVENANCE,
            "python": sys.version.split()[0], "regex": _distribution_version("regex")}


def preflight(path, reserve):
    """Keep 42 GiB free after the planned writes, with 1 GiB extra headroom."""
    parent = Path(path).absolute()
    while not parent.exists():
        parent = parent.parent
    if reserve > 100 * 1024 ** 2:
        subprocess.run(["df", "-g", "/"], check=True)
    free = shutil.disk_usage(parent).free
    if free - reserve - GIB < 42 * GIB:
        raise RuntimeError(f"disk guard: {free} free bytes, {reserve} reserved; 42 GiB plus margin required")


def atomic(path, data):
    path = Path(path)
    preflight(path.parent, len(data) + 16384)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".stage4-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass(frozen=True)
class G2P:
    tool: str
    version: str
    voice: str
    settings: dict
    transcribe: object

    def descriptor(self):
        if not all(isinstance(x, str) and x for x in (self.tool, self.version, self.voice)):
            raise ValueError("G2P tool, version and voice must be explicit nonempty strings")
        if not isinstance(self.settings, dict) or not callable(self.transcribe):
            raise ValueError("G2P requires dictionary settings and a transcribe callable")
        return json.loads(canonical({"tool": self.tool, "version": self.version,
                                     "voice": self.voice, "settings": self.settings, "adapter_code": version()}))


class PronunciationFailure(ValueError):
    """Explicit unreadable input, never a resource/configuration failure."""


DATA_MESSAGES = frozenset({
    'Word segmentation does not align with fixed syllable units',
    'Diacritic/length mark without a preceding phone', 'Tie bar without a second phone',
    'Tie bar without a second phone in the word',
    'Chained tie bars are not a pair (only vowel chains can be accepted)',
    'CAT vowel loss has no neighbouring syllable host',
    'Italian qu repair does not align with the reading',
    'A written Vietnamese syllable must have at most one tone mark',
    'Word has no counted nucleus or attachment', 'Words without counted nuclei must not be silently dropped',
    'Unhandled non-Han characters', 'Unhandled non-Hangul G2P output',
    'No Mandarin tonal reading for a character', 'Ambiguous Mandarin tonal alignment',
    'Missing Cantonese tonal reading or character alignment',
    'Cantonese syllables do not align to characters',
    'Expected one explicitly toned label per Han character',
    'Tonal labels do not align to the counted characters', 'Unsupported multi-character tonal unit',
    'Supply one tonal label per counted Han unit, with erhua already joined',
    'Invalid tonal syllable label', 'A Han syllable label must retain an explicit tone',
    'Lexique syllables disagree with effective phones',
})
SOFTWARE_MESSAGES = frozenset({
    'Pinned Thai model missing; downloads disabled', 'Only the pinned local Thai model may be read',
    'Thai neural adapter requires CPU', 'Offline attacut worker exited',
    'Installed OpenJTalk dictionary required; downloads disabled',
    'Japanese chunk cache must retain every contextual token pronunciation',
    'One source per Japanese word required', 'One character span per Thai syllable required',
    'Invalid/nonmonotonic Thai syllable span',
})


def exception_chain(error):
    """The error and every exception behind it, explicit or implicit.

    Both __cause__ and __context__ are followed, whatever __suppress_context__
    says: `raise ... from None` hides a fault from tracebacks, not from here.
    An exception reached only as implicit context whose exact type is KeyError,
    IndexError or StopIteration is a handled lookup or iteration miss (control
    flow), not a fault, and is left out. As an explicit cause (`from e`), or as
    any other type (LookupError itself included: missing nltk data raises it),
    it is kept.
    """
    # Visit everything once, but remember whether any path reached an exception
    # explicitly (the error itself or a __cause__): one that is also an explicit
    # cause somewhere is kept even if it was met first as implicit context.
    reached, pending = {}, [(error, True)]
    while pending:
        current, explicit = pending.pop(0)
        if current is None:
            continue
        if id(current) in reached:
            reached[id(current)][1] |= explicit
            continue
        reached[id(current)] = [current, explicit]
        pending.append((current.__cause__, True))
        if current.__context__ is not current.__cause__:
            pending.append((current.__context__, False))
    chain = [current for current, explicit in reached.values()
             if explicit or type(current) not in (KeyError, IndexError, StopIteration)]
    return chain


def data_failure(error):
    """Fixed invalid-reading/alignment messages only; software faults stop runs."""
    messages = set(DATA_MESSAGES)
    for name in ('stage3_japanese', 'stage3_thai'):
        messages.update(getattr(sys.modules.get(name), 'FAILURE_MESSAGES', ()))
    for current in exception_chain(error):
        if (not isinstance(current, ValueError) or str(current) in SOFTWARE_MESSAGES
                or str(current).startswith('Unknown ')
                or (current is not error and str(current) not in messages
                    and not isinstance(current, PronunciationFailure)
                    and not getattr(current, 'alignment_sentinel', False))):
            raise current
    if isinstance(error, PronunciationFailure) or str(error) in messages:
        return True
    raise error


# Subtitle mojibake is removed in Stage 2, before its script and letter filters
# (src/stage2_mojibake.py). Stage 4 receives Stage 2's output lines and only
# normalises them; it applies no second mojibake rule.
STAGE2_FILTER = 'Stage 2 mojibake-v2 (src/stage2_mojibake.py), applied before Stage 4'
# A line holding only this private-use character stands where Stage 2 dropped
# lines (src/stage7/corpora.py writes it). It is masked in every option, so
# cross-line context resets there (Brett, 2026-10-13). Stage 2 removes
# private-use characters from text, so no real line can be this.
STAGE2_GAP = '\ue000'


# In CMN and YUE the name dots and the bullet separate words (Brett, 2026-10-14):
# transliterated names are written with them between their parts, and as
# characters without a reading they would otherwise drop the line. Catalan keeps
# · inside words (col·legi), so this is for these two languages only.
NAME_DOTS = {ord(c): ' ' for c in '\u00b7\u30fb\u2027\u2022'}


# Strings a G2P or segmenter can't read, mapped to their spoken or standard form
# before any option counts, every firing counted (Brett, 2026-10-15; found by the
# read-text pass/fail check): an explicit list, not a general cleaner. VIE: Đ/đ
# written with the look-alike eth, which underthesea silently replaces, breaking
# alignment. CMN, YUE: the small form variants of punctuation (﹖), which aren't
# phrase ends, to the full-width forms that are. HUN: the abbreviation Dr (dr), read
# doktor; a period after it then ends no phrase.
SMALL_FORMS = {'\ufe50': '\uff0c', '\ufe51': '\u3001', '\ufe52': '\uff0e', '\ufe54': '\uff1b',
               '\ufe55': '\uff1a', '\ufe56': '\uff1f', '\ufe57': '\uff01'}
NORMALISATIONS = (
    ('vie-eth-as-d-stroke', frozenset({'VIE'}), re.compile('[\u00d0\u00f0]'),
     lambda m: {'\u00d0': '\u0110', '\u00f0': '\u0111'}[m.group()]),
    ('han-small-form-punctuation', frozenset({'CMN', 'YUE'}), re.compile('[' + ''.join(SMALL_FORMS) + ']'),
     lambda m: SMALL_FORMS[m.group()]),
    ('hun-dr-doktor', frozenset({'HUN'}), re.compile(r'(?<!\w)[Dd]r(?!\w)(?:\.(?!\w))?'), lambda m: 'doktor'),
)


def _normalise(line, language):
    line = U.normalize('NFC', line)
    fired = {}
    for rule, languages, pattern, replacement in NORMALISATIONS:
        if language in languages:
            line, n = pattern.subn(replacement, line)
            if n:
                fired[rule] = n
    return (line.translate(NAME_DOTS) if language in {'CMN', 'YUE'} else line), fired


def normalise_line(line, language):
    """NFC; the explicit normalisations; in CMN and YUE the name dots and bullet as word separators."""
    return _normalise(line, language)[0]


def normalisation_firings(line, language):
    """How often each normalisation fires on this line: {rule: n}, empty if none."""
    return _normalise(line, language)[1]


def corpus_filter(lines, language):
    """Caller supplies exactly Stage 2's surviving lines; normalised, source indices kept."""
    return {'lines': tuple(normalise_line(line, language) for line in lines)}


def main_g2p(language, *, lexicon=None, fallback_required=True, _fallback_only=False,
             reader='fugashi', tool='tltk', japanese_context=True):
    """Installed main adapters only. Unavailable main routes must be supplied."""
    if language == "FRA" and not _fallback_only:
        lexicon = C.FRA_LEXICON if lexicon is None else lexicon
    if language == "FRA" and lexicon is not None and not _fallback_only:
        entries = lexicon
        lexicon_checksum = (C.LEXICON_PROVENANCE["fra_lexique.tsv"]["sha256"] if entries is C.FRA_LEXICON else
                            digest(canonical({word: dict(entry) if hasattr(entry, "keys") else entry for word, entry in entries.items()}).encode()))
        fallback = main_g2p("FRA", _fallback_only=True) if fallback_required else None
        def transcribe(word):
            entry = entries.get(word.lower())
            if entry is not None:
                return {"pronunciation": entry if isinstance(entry, str) else entry["phon"],
                        "source": "lexique", "languages": []}
            if fallback is None:
                raise LookupError("Word absent from the declared Lexique-only route")
            return fallback.transcribe(word)
        return G2P("lexique+espeak-ng" if fallback else "lexique",
                   canonical({"lexicon_sha256": lexicon_checksum,
                              "fallback_version": fallback.version if fallback else None}), "fr",
                   {"fallback": fallback.descriptor() if fallback else None}, transcribe)
    if language in C.VOICES:
        v = subprocess.run([C.ESPEAK, "--version"], check=True, capture_output=True, text=True).stdout.strip()
        voice = C.VOICES[language]
        def transcribe(word):
            # The disk cache owns reuse under a versioned descriptor. The
            # counter's (word, voice) memory cache cannot establish tool version.
            p = C.espeak.__wrapped__(word, voice)
            return {"pronunciation": str(p), "source": "espeak", "languages": list(p.languages)}
        return G2P("espeak-ng", v, voice, {"ipa": 3, "isolated_word": True}, transcribe)
    if language in C.EPITRAN:
        code = C.EPITRAN[language]
        def transcribe(word):
            pronunciation, source = C.epitran_reading(word, code)
            return {"pronunciation": pronunciation, "source": source, "languages": []}
        return G2P("epitran", importlib.metadata.version("epitran"), code,
                   {"repairs": list(C.ITALIAN_REPAIRS)} if code == "ita-Latn" else {}, transcribe)
    if language == "ENG":
        v = canonical({p: importlib.metadata.version(p) for p in ("cmudict", "g2p-en")})
        def transcribe(word):
            p, source = C.english_word(word)
            return {"pronunciation": list(p), "source": source, "languages": []}
        return G2P("cmudict+g2p-en", v, "en", {"cmu_variant": 0, "isolated_word": True,
                   "oov_normalization": "NFKD-drop-M", "normalized_cmu_relookup": True}, transcribe)
    if language == "KOR":
        def transcribe(word):
            with C._offline_nltk():
                p = C._korean()(word)
            return {"pronunciation": p, "source": "g2pk2", "languages": []}
        return G2P("g2pk2", importlib.metadata.version("g2pk2"), "ko", {}, transcribe)
    if language == "VIE":
        # The candidate note explicitly uses orthography, with no main G2P.
        return G2P("orthography", version()["counter"], "vi", {"counter_normalizes_tone": True},
                   lambda word: {"pronunciation": word, "source": "orthography", "languages": []})
    if language in {'CMN', 'YUE'}:
        tones = registry().S._load('stage3_tones', ROOT / 'src/stage3/tones.py').Tones(language)
        desc = tones.descriptor()
        return G2P(desc['tool'], desc['version'], language, desc,
                   lambda word: {'pronunciation': list(tones.transcribe(word)),
                                 'source': desc['tool'], 'languages': []})
    if language in {'JPN', 'THA'}:
        native = sys.modules['stage3_japanese' if language == 'JPN' else 'stage3_thai']
        desc = native.route_descriptor(reader) if language == 'JPN' else native.route_descriptor(tool)
        if language == 'JPN':
            desc = dict(desc, pronunciation_units='source chunks' if japanese_context else 'isolated supplied tokens')
        def transcribe(word):
            if language == 'JPN':
                rows = native.resolved_chunk(word, reader)
                if japanese_context:
                    return {'pronunciation': [p for _, p, _ in rows], 'source': reader, 'languages': [],
                            'word_sources': [s for _, _, s in rows]}
                value = ''.join(p for _, p, _ in rows)
                source = 'pyopenjtalk-fallback' if any(s.endswith('-fallback') for _, _, s in rows) else reader
            else:
                value, source = native.resolved_word(word, tool)
                value = list(value)
            return {'pronunciation': value, 'source': source, 'languages': []}
        return G2P(desc['tool'], canonical(desc['version']), desc['voice'], desc, transcribe)
    raise ValueError(f"No implemented main G2P for {language}; supply a versioned G2P explicitly")


def validate_pronunciation(value):
    if not isinstance(value, dict) or set(value) - {"pronunciation", "source", "languages", "word_sources"} or not {
            "pronunciation", "source", "languages"}.issubset(value):
        raise ValueError("G2P must return pronunciation, source and languages")
    p = value["pronunciation"]
    if not (isinstance(p, str) or isinstance(p, list) and all(isinstance(x, str) for x in p)):
        raise ValueError("pronunciation must be a string or phone-string list")
    if not isinstance(value["source"], str) or not value["source"]:
        raise ValueError("G2P source must be explicit")
    if not isinstance(value["languages"], list) or not all(isinstance(x, str) for x in value["languages"]):
        raise ValueError("G2P languages must be a string list")
    if 'word_sources' in value and (not isinstance(p, list) or not isinstance(value['word_sources'], list)
            or len(p) != len(value['word_sources']) or any(not isinstance(s, str) or not s for s in value['word_sources'])):
        raise ValueError('One source per contextual Japanese pronunciation required')
    return json.loads(canonical(value))


class PronunciationCache:
    """Atomic per-type records; options deliberately do not invalidate main G2P.

    Validated values are shared by every cache on the same directory with the
    same backend signature (one is made per document and option, and each would
    otherwise reread every word from disk), as immutable strings each cache parses
    for itself, and only while the word's disk record keeps the stamp it had when
    read (`_stamp`: size, modification and change times, inode), so a rewritten
    record is validated again. The backend is checked on every lookup against a
    cheap fingerprint (its tool, version, voice and settings, and the stamp of
    every file `version()` hashes); the full descriptor is rebuilt only when that
    changes (P8 profile, 2026-10-14).

    An entry names its G2P descriptor and its producer by digest (schema v3).
    Each distinct descriptor, and each producer less its document and input
    digest, is stored once in the folder (`g2p/`, `producers/`) as a file named
    by the digest of its bytes; the entry carries the document's own two fields.
    In v2 every entry repeated both, and a declaration's segmenter (with its
    learned onset inventory, 403 KB on Catalan) made each entry 417 KB (P9,
    2026-10-15).
    """
    _SHARED = {}
    _STORED = {}  # stored record -> its stamp when its bytes last matched its name

    def __init__(self, directory, language, backend, *, producer):
        self.directory = Path(directory)
        self.backend = backend
        self.signature = dict(language=language, **backend.descriptor())
        self.producer = json.loads(canonical(producer))
        self.memory = {}
        self.failures = {}
        # Shared values are reused only while their disk record is unchanged.
        self.shared = self._SHARED.setdefault((str(self.directory.resolve()), canonical(self.signature)), {})
        self._checked = self._fingerprint()
        self._signature_sha256 = digest((canonical(self.signature) + "\n").encode())
        self._producer_ref = None

    def _store(self, folder, text):
        """Write `text` once as folder/<sha256 of its bytes>.json; return the digest."""
        data = (text + "\n").encode()
        name = digest(data)
        if not (self.directory / folder / (name + ".json")).exists():
            atomic(self.directory / folder / (name + ".json"), data)
        self._check_stored(folder, name)
        return name

    def _check_stored(self, folder, name):
        if not (isinstance(name, str) and re.fullmatch(r"[0-9a-f]{64}", name)):
            raise ValueError(f"invalid G2P cache {folder} reference")
        path = self.directory / folder / (name + ".json")
        try:
            stamp = _stamp(os.stat(path))
        except OSError:
            raise ValueError(f"missing G2P cache {folder} record: {name}") from None
        if self._STORED.get(os.fspath(path)) == stamp:
            return
        data = path.read_bytes()
        if digest(data) != name or not isinstance(json.loads(data), dict):
            raise ValueError(f"invalid G2P cache {folder} record: {name}")
        self._STORED[os.fspath(path)] = stamp

    def _producer_entry(self):
        # Stored once per cache; the document's own fields ride in each entry.
        if self._producer_ref is None:
            shared = {k: v for k, v in self.producer.items() if k not in PER_DOCUMENT}
            own = {k: self.producer[k] for k in PER_DOCUMENT if k in self.producer}
            self._store("g2p", canonical(self.signature))  # named self._signature_sha256
            self._producer_ref = dict(own, shared_sha256=self._store("producers", canonical(shared)))
        return self._producer_ref

    def _fingerprint(self):
        return (self.backend.tool, self.backend.version, self.backend.voice, canonical(self.backend.settings),
                version_fingerprint())

    def get(self, word):
        self.check_backend()
        if word in self.failures:
            raise self.failures[word]
        if word in self.memory:
            return self.memory[word]
        if word in self.shared:
            text, path, stamp, shared_sha256 = self.shared[word]
            try:
                current = _stamp(os.stat(path))
            except OSError:
                current = None
            if current == stamp:
                # The records the entry names are checked as a cold read checks them (Codex review).
                self._check_stored("g2p", self._signature_sha256)
                self._check_stored("producers", shared_sha256)
                # Each cache gets its own copy; the shared form is an immutable string.
                value = json.loads(text)
                self.memory[word] = value
                return value
        path = self.directory / (digest(canonical({"g2p": self.signature, "word": word}).encode()) + ".json")
        key = {"g2p_sha256": self._signature_sha256, "word": word}
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("schema") == "g2p-cache-v2":
                raise ValueError(f"G2P cache entry {path.name} has the old schema v2; use a new cache folder")
            producer = record.get("producer")
            if (record.get("schema") != "g2p-cache-v3" or record.get("key") != key or not isinstance(producer, dict)
                    or set(producer) - {"shared_sha256", *PER_DOCUMENT}):
                raise ValueError(f"invalid G2P cache key: {path.name}")
            shared_sha256 = producer.get("shared_sha256")
            self._check_stored("g2p", self._signature_sha256)
            self._check_stored("producers", shared_sha256)
            value = validate_pronunciation(record.get("value"))
            if record.get("value_sha256") != digest(canonical(value).encode()):
                raise ValueError(f"invalid G2P cache checksum: {path.name}")
        else:
            try:
                raw = self.backend.transcribe(word)
                value = validate_pronunciation(raw)
            except Exception as e:
                data_failure(e)
                self.failures[word] = e
                raise
            self.check_backend()
            entry = self._producer_entry()
            shared_sha256 = entry["shared_sha256"]
            # Checked again before each write, so no entry names a record that has gone (Codex review).
            self._check_stored("g2p", self._signature_sha256)
            self._check_stored("producers", shared_sha256)
            atomic(path, (canonical({"schema": "g2p-cache-v3", "key": key, "producer": entry,
                                     "value": value, "value_sha256": digest(canonical(value).encode())}) + "\n").encode())
        self.memory[word] = value
        self.shared[word] = (canonical(value), os.fspath(path), _stamp(os.stat(path)), shared_sha256)
        return value

    def check_backend(self):
        # The full descriptor is rebuilt only when the backend or a hashed source file changed.
        fingerprint = self._fingerprint()
        if fingerprint == self._checked:
            return
        current = dict(language=self.signature["language"], **self.backend.descriptor())
        if current != self.signature:
            raise ValueError("G2P descriptor changed after cache creation; create a new cache")
        self._checked = fingerprint


def _counter_input(language, values):
    prons = {}
    for word, value in values.items():
        p = value["pronunciation"]
        if isinstance(p, str) and value["languages"]:
            p = C._EspeakIPA(p, tuple(value["languages"]))
        prons[word] = p
    return prons


_SEGMENTER_DIGESTS = {}


def _segmenter_basis(segmenter_version):
    # Each syllable names its segmenter by digest: the version string carries the
    # learned onset inventory (403 KB on Catalan), and a copy per syllable held 24 GB
    # for one long document (P9, Codex review, 2026-10-15). The report's
    # configuration keeps the full string.
    if segmenter_version not in _SEGMENTER_DIGESTS:
        if len(_SEGMENTER_DIGESTS) >= 64:
            _SEGMENTER_DIGESTS.clear()
        _SEGMENTER_DIGESTS[segmenter_version] = "supplied-segmenter:sha256:" + digest(segmenter_version.encode())
    return _SEGMENTER_DIGESTS[segmenter_version]


def segment_line(text, language, option, cache, *, counter_options, segment_mode,
                 ownership, segmenter, segmenter_version, counter):
    # The read-text lens calls this directly with raw lines; corpus lines are already
    # normalised (process_document counts their firings), so only raw lines record any.
    fired = normalisation_firings(text, language) if isinstance(text, str) else {}
    text = normalise_line(text, language) if isinstance(text, str) else text
    record = _segment_line(text, language, option, cache, counter_options=counter_options,
                           segment_mode=segment_mode, ownership=ownership, segmenter=segmenter,
                           segmenter_version=segmenter_version, counter=counter)
    if fired:
        record['normalizations'] = fired
    return record


def g2p_repairs(records):
    """Word tokens whose G2P reading carries a named repair: {repair: n}, empty if none."""
    repairs = {}
    for record in records:
        for word in record.get('words', ()):
            for part in ((word.get('g2p') or {}).get('source') or '').split('+')[1:]:
                if part in C.ITALIAN_REPAIRS:
                    repairs[part] = repairs.get(part, 0) + 1
    return repairs


def _segment_line(text, language, option, cache, *, counter_options, segment_mode,
                  ownership, segmenter, segmenter_version, counter):
    counter_options = dict(counter_options)
    word_adapter = None
    if language in {'CMN', 'YUE', 'VIE'} and 'segmenter' in counter_options:
        name = counter_options.pop('segmenter')
        word_adapter = word_segmenter(language, name)
    contextual = (language == 'JPN' and 'word_tokens' not in counter_options and
                  cache.backend.settings.get('pronunciation_units') == 'source chunks')
    contextual_prons = None
    contextual_sources = None
    tokens = (C.cmn_a(text, word_tokens=counter_options["word_tokens"]).tokens
              if language == "CMN" and "word_tokens" in counter_options else C.tokenize(text))
    if language in {'JPN', 'THA'}:
        native = sys.modules['stage3_japanese' if language == 'JPN' else 'stage3_thai']
        native_options = ({'reader': counter_options.get('reader', 'fugashi')} if language == 'JPN'
                          else {'segmenter': counter_options.get('segmenter', 'newmm')})
        try:
            tokens = native.tokens(C, text, **native_options, word_tokens=counter_options.get('word_tokens'))
        except Exception as e:
            data_failure(e)
            return {'text': text, 'words': [], 'syllables': [], 'counter_count': None,
                    'status': 'blocked', 'counter_trace': None,
                    'problems': [{'reason': 'g2p-or-tokenizer-failed', 'detail': str(e)}]}
        # Thai pronunciation units stay newmm even when word boundaries vary.
        input_tokens = native.tokens(C, text) if language == 'THA' else tokens
    else:
        input_tokens = tokens
    values, problems = {}, []
    if contextual:
        chunk_values = {}
        def chunk_pronunciation(chunk):
            chunk_values[chunk] = cache.get(chunk)
            return chunk_values[chunk]['pronunciation']
        try:
            tokens, contextual_prons = native.cached_pronunciations(
                C, text, counter_options.get('reader', 'fugashi'),
                chunk_pronunciation)
            contextual_sources = tuple(s for chunk in C.tokenize(text)
                                       for s in chunk_values[chunk.word].get('word_sources',
                                           [chunk_values[chunk.word]['source']] * len(chunk_values[chunk.word]['pronunciation'])))
        except Exception as e:
            data_failure(e)
            problems.append({'reason': 'g2p-failed', 'detail': str(e)})
        input_tokens = ()
    for w, token in enumerate(input_tokens):
        try:
            entry = (counter_options.get("lexicon") or {}).get(token.word.lower()) if language == "FRA" else None
            if entry is not None:
                # Explicit overrides need not use the injected main backend.
                values[token.word] = {"pronunciation": entry if isinstance(entry, str) else entry["phon"],
                                      "source": "lexique", "languages": []}
            else:
                values[token.word] = cache.get(token.word)
        except Exception as e:
            data_failure(e)
            problems.append({"word": w, "text": token.word, "reason": "g2p-failed", "detail": str(e)})
    words = [{"index": w, "text": t.word, "phrase_end": t.phrase_end,
              "g2p": ({'pronunciation': contextual_prons[w], 'source': contextual_sources[w], 'languages': []}
                      if contextual_prons is not None else values.get(t.word)), "owned_syllables": [], "participating_syllables": []}
             for w, t in enumerate(tokens)]
    base = {"text": text, "words": words, "syllables": [], "counter_count": None,
            "problems": problems, "status": "blocked", "counter_trace": None}
    if problems:
        return base
    kwargs = dict(counter_options)
    if language not in {"CMN", "YUE", "VIE"}:
        kwargs["pronunciations"] = contextual_prons if contextual else _counter_input(language, values)
    if language in {'JPN', 'THA'}:
        if contextual:
            kwargs['pronunciation_sources'] = contextual_sources
        elif language == 'THA':
            kwargs['pronunciation_sources'] = {w: v['source'] for w, v in values.items()}
        else:
            kwargs['pronunciation_sources'] = [values[t.word]['source'] for t in tokens]
    try:
        result = counter(text, **kwargs)
    except Exception as e:
        data_failure(e)
        base["problems"].append({"reason": "counter-failed", "detail": str(e), "words": list(range(len(words)))})
        return base
    if tuple(t.word for t in result.tokens) != tuple(t.word for t in tokens):
        raise ValueError("Counter tokenization differs from pipeline words; supply a matching tokenizer before use")
    if language == 'THA':
        # Word-aware ownership may split/merge fixed newmm G2P units. Describe
        # each selected word using its owned original syllables, not a new G2P.
        for word, pronunciation, source in zip(words, result.pronunciations, result.sources):
            word['g2p'] = {'pronunciation': pronunciation,
                           'source': cache.backend.tool if source == 'supplied' else source, 'languages': []}
    if language in {"CMN", "YUE"}:
        # These counters count characters; downstream segmentation must see
        # the main pronunciation, including tone, rather than the characters.
        result = replace(result, pronunciations=tuple(values[t.word]["pronunciation"] for t in tokens),
                         sources=tuple(values[t.word]["source"] for t in tokens))
        for w, token in enumerate(tokens):
            unhandled = "".join(c for c in token.word if not C._han(c))
            if unhandled:
                base["problems"].append({"word": w, "text": token.word,
                                         "reason": "unhandled-characters", "unhandled": unhandled})
    base["counter_count"] = result.count
    base['fallback_share'] = result.fallback_share
    base["counter_trace"] = asdict(result)
    if segmenter is None and language == 'FRA' and option == 'B' and result.count:
        # Counted without full segmentation (the read-text lens): schwa-only clitics are
        # placed by the same rule, with no onset inventory. Where one attaches can't change
        # a count, only whether every word is covered (Brett, 2026-10-14).
        placed = registry().S._french_clitic_attachments(result, frozenset())
        added = placed.attachments[len(result.attachments):]
        if added:
            base['segmentation_attachments'] = [asdict(a) for a in added]
            result = placed
    segments = result.segmentation if result.count else ()
    basis = "counter-segmentation"
    if result.count and language in {"FIN", "CMN", "YUE"}:
        # Counter spelling/character cuts establish counts and ownership only.
        segments = None
    if result.count and segmenter is not None:
        try:
            output = segmenter(result); basis = _segmenter_basis(segmenter_version)
            if hasattr(output, 'syllables'):
                segments = tuple(output.syllables)
                added = output.counter.attachments[len(result.attachments):]
                if added:
                    base['segmentation_attachments'] = [asdict(a) for a in added]
                    result = replace(result, attachments=output.counter.attachments, members=output.counter.members)
            else:
                segments = tuple(output)
        except Exception as e:
            data_failure(e)
            base['problems'].append({'reason': 'segmentation-failed', 'detail': str(e)})
            return base
    if segments is None and segment_mode == "nuclei":
        segments = result.nuclei; basis = "nucleus-proxy"
    if segments is None:
        base["problems"].append({"reason": "full-segmentation-unfixed", "words": list(range(len(words)))})
    else:
        if len(segments) != result.count or any(not isinstance(s, str) or not s for s in segments):
            raise ValueError("Segmenter must return exactly one nonempty string per counted syllable")
        if not (len(result.hosts) == len(result.members) == result.count):
            raise ValueError("Counter ownership length disagrees with count")
        owners = []
        for i, (label, host, members) in enumerate(zip(segments, result.hosts, result.members)):
            if not members or host not in members or any(not 0 <= w < len(words) for w in members):
                raise ValueError("Invalid counter syllable ownership")
            owner = host if ownership == "counter" else min(members) if ownership == "first-member" else max(members)
            owners.append(owner)
            base["syllables"].append({"index": i, "label": label, "nucleus": result.nuclei[i],
                                      "owner": owner, "counter_host": host, "members": list(members), "basis": basis})
            words[owner]["owned_syllables"].append(i)
            for w in members:
                words[w]["participating_syllables"].append(i)
        if owners != sorted(owners):
            raise ValueError("Selected ownership interleaves word syllables; word-aware encoding is undefined")
    covered = {w for members in result.members for w in members}
    if language == 'JPN':
        covered.update((result.resource_provenance or {}).get('dropped_length_words', []))
        covered.update((result.resource_provenance or {}).get('non_syllabic_words', []))
    if language == 'THA':
        covered.update((result.resource_provenance or {}).get('spelling_piece_unowned_words', []))
    for w, word in enumerate(words):
        if w not in covered:
            base["problems"].append({"word": w, "text": word["text"], "reason": "no-syllable-or-attachment"})
    base["status"] = "blocked" if base["problems"] else "complete"
    if word_adapter is not None and not base['problems']:
        try:
            selected, owners = word_segmenters().align(result, language, word_adapter, C)
        except Exception as e:
            data_failure(e)
            base['problems'].append({'reason': 'word-segmentation-failed', 'detail': str(e)})
            base['status'] = 'blocked'
            return base
        base['counter_words'] = words
        base['words'] = [{'index': w, 'text': t.word, 'phrase_end': t.phrase_end,
                          'g2p': None, 'owned_syllables': [], 'participating_syllables': []}
                         for w, t in enumerate(selected)]
        for s, owner in zip(base['syllables'], owners):
            s['counter_owner'] = s['owner']
            s['owner'] = owner
            s['counter_members'] = s['members']
            s['members'] = [owner]
            base['words'][owner]['owned_syllables'].append(s['index'])
            base['words'][owner]['participating_syllables'].append(s['index'])
        for word in base['words']:
            owned = [base['syllables'][i] for i in word['owned_syllables']]
            original = sorted({s['counter_owner'] for s in owned})
            word['g2p'] = {'pronunciation': [s['label'] for s in owned],
                           'source': '+'.join(dict.fromkeys(result.sources[w] for w in original)),
                           'languages': [], 'basis': 'assembled-fixed-unit-readings',
                           'counter_words': original}
        base['word_segmenter'] = word_adapter.descriptor()
    return base


def word_segmenters():
    return registry().S._load('stage3_word_segmenters', ROOT / 'src/stage3/word_segmenters.py')


_WORD_SEGMENTERS = {}


def word_segmenter(language, name):
    key = (language, name)
    if key not in _WORD_SEGMENTERS:
        _WORD_SEGMENTERS[key] = word_segmenters().Segmenter(language, name)
    return _WORD_SEGMENTERS[key]


def encode(lines, rung, treatment, *, vocabulary=None, higher_rungs="plain", pooled_pairs=None):
    """Candidate/A tokens/windows; plain higher rungs retain the spec's streams.

    Pass a common, training-declared label-to-integer mapping across documents
    and splits. The local sorted mapping is for standalone document preparation.
    Free rungs condition the scorer's outcome mass on the current flag; they
    never put that flag in the history. Explicit higher variants are supported.
    With `pooled_pairs` ({allowed: {(flag, id)}, pooled: token}), a flagged target whose
    pair is not allowed is b<flag>s<token> (P9, Brett 2026-10-15); histories and plain
    rungs are unchanged.
    """
    lines = tuple(lines)
    if treatment not in TREATMENTS or higher_rungs not in {"plain", "free", "charged"}:
        raise ValueError("Unknown line treatment or higher-rung convention")
    labels = {s["label"] for line in lines for s in line["syllables"]}
    vocabulary = ({label: i for i, label in enumerate(sorted(labels))}
                  if vocabulary is None else dict(vocabulary))
    if (any(type(i) is not int or i < 0 for i in vocabulary.values())
            or len(set(vocabulary.values())) != len(vocabulary) or not labels.issubset(vocabulary)):
        raise ValueError("Vocabulary must assign distinct nonnegative integers to every syllable label")
    effective = rung + "-" + higher_rungs if rung in {"2", "3", "4"} and higher_rungs != "plain" else rung
    valid = set(RUNGS) | {str(k) + "-" + policy for k in (2, 3, 4) for policy in ("free", "charged")}
    if effective not in valid:
        raise ValueError("Unknown rung")
    k = 0 if effective == "0" else int(effective[0])
    flagged = effective not in {"0", "1w", "1", "2", "3", "4"}
    groups = []
    for line in lines:
        syll = line["syllables"]
        groups.append([(vocabulary[s["label"]], int(i == 0 or s["owner"] != syll[i - 1]["owner"]))
                       for i, s in enumerate(syll)])
    if treatment == "cross-line":
        joined = [[]]
        for line, group in zip(lines, groups):
            if line.get('status') == 'masked':
                joined.append([])
            else:
                joined[-1].extend(group)
        groups = joined
    text = []
    for group in groups:
        if not group:
            continue
        if not flagged and effective != "1w":
            text.append(" ".join(f"s{s}" for s, _ in group))
        else:
            for i, (s, b) in enumerate(group):
                if effective == "1w":
                    history = ("<w>",) if b else ((f"c{group[i-1][0]}",) if i else ())
                else:
                    history = tuple(f"s{x}" for x, _ in group[max(0, i-k):i])
                if flagged and pooled_pairs is not None and (b, s) not in pooled_pairs["allowed"]:
                    s = pooled_pairs["pooled"]
                target = f"b{b}s{s}" if flagged else f"s{s}"
                text.append(" ".join((*history, target)))
    metadata = {"rung": rung, "scorer_rung": effective, "line_treatment": treatment, "order": k + 1,
                "target_prefix": "b" if flagged else "s", "n_syllables": sum(map(len, groups)),
                "encoding": "candidate-a-window-v1" if flagged or effective == "1w" else "candidate-a-stream-v1",
                "vocabulary": vocabulary,
                "score": "target only; current-flag class mass for free, joint class mass for charged, syllable mass for plain",
                "model_format": "unigram ARPA (binary requires order >= 2)" if rung == "0" else "ARPA or binary",
                "document_reset": True, "higher_rungs": higher_rungs,
                "masked_line_reset": True,
                "masked_source_lines": [i for i, line in enumerate(lines) if line.get('status') == 'masked'],
                "boundary_history": "plain previous syllables; no previous flags"}
    return ("\n".join(text) + ("\n" if text else "")).encode(), metadata


def score_candidate(candidate, model, arpa, corpus, rung, treatment, *, check=False):
    """Use candidate/A's scorer, extending its plain contexts to spec rungs 2–4.

    Unigrams retain candidate/A's direct-ARPA route (no order-one KenLM model).
    The caller maps the file's line treatment and uses metadata.scorer_rung.
    """
    if rung == "0":
        if treatment not in {"bounded", "running"}:
            raise ValueError("treatment must be bounded or running")
        probabilities = {}
        order = 0
        with candidate.open_arpa(arpa) as source:
            for line in source:
                match = re.match(r"\\(\d+)-grams:", line)
                if match:
                    order = int(match[1])
                    continue
                parts = line.split()
                if order == 1 and len(parts) >= 2 and re.fullmatch(r"s\d+", parts[1]):
                    probabilities[parts[1]] = float(parts[0])
        targets = [f"s{s}" for s in corpus.s]
        if any(word not in probabilities for word in targets):
            raise ValueError("OOV syllable in unigram test set")
        z = math.fsum(10 ** lp for lp in probabilities.values())
        if not math.isfinite(z) or z <= 0:
            raise ValueError("Invalid unigram syllable outcome mass")
        loss = -math.log2(10) * math.fsum(probabilities[word] for word in targets) / len(targets)
        return {"raw_bits": loss, "test_bits": loss + math.log2(z),
                "n_scored": len(targets), "oov": 0, "n_histories": 1}
    if rung not in {"2", "3", "4"}:
        return candidate.score(model, arpa, corpus, rung, treatment, check=check)
    if treatment not in {"bounded", "running"}:
        raise ValueError("treatment must be bounded or running")
    starts = set(map(int, corpus.starts)) if treatment == "bounded" else {0}
    histories, start = [], 0
    for i in range(len(corpus.s)):
        if i in starts:
            start = i
        history = tuple(f"s{x}" for x in corpus.s[max(start, i-int(rung)):i])
        if len(history) < int(rung):
            history = ("<s>",) + history
        histories.append(history)
    masses = candidate.ClassMass(arpa, model, histories, False)
    if check:
        for history in set(histories):
            if not math.isclose(masses.normalizer(history), masses.brute(history), rel_tol=2e-5, abs_tol=2e-7):
                raise AssertionError(f"class sum disagrees for {history}")
    raw = norm = 0.0
    tmp = candidate.kenlm.State()
    for s, history in zip(corpus.s, histories):
        word = f"s{s}"
        if word not in masses.vocabulary:
            raise ValueError(f"OOV target {word}")
        lp = model.BaseScore(candidate.state_for(model, history), word, tmp)
        raw += lp; norm += lp - math.log10(masses.normalizer(history))
    scale = -math.log2(10) / len(corpus.s)
    return {"raw_bits": raw*scale, "test_bits": norm*scale, "n_scored": len(corpus.s),
            "oov": 0, "n_histories": len(set(histories))}


def mandarin_partitions(lines, options, supplied):
    """Validate document subdivisions, then assign them to original lines.

    Flat tokens retain the counter's document-wide contract. An explicit list
    per line is also accepted, including empty lists for blank lines. Neither
    input may bridge the counter's mandatory separators.
    """
    flat = options.get("word_tokens")
    if supplied is not None:
        if "word_tokens" in options:
            raise ValueError("Supply flat word_tokens or word_tokens_by_line, not both")
        if not isinstance(supplied, (list, tuple)) or len(supplied) != len(lines):
            raise ValueError("word_tokens_by_line must contain one token sequence per source line")
        partitions = []
        for text, words in zip(lines, supplied):
            if not isinstance(words, (list, tuple)) or any(not isinstance(w, str) for w in words):
                raise ValueError("Each word_tokens_by_line entry must be a sequence of text tokens")
            partitions.append([t.word for t in C.cmn_a(text, word_tokens=words).tokens])
        return partitions
    if "word_tokens" not in options:
        return None
    if not isinstance(flat, (list, tuple)) or any(not isinstance(w, str) for w in flat):
        raise ValueError("word_tokens must be a sequence of text tokens")
    words = iter(C.cmn_a("\n".join(lines), word_tokens=flat).tokens)
    partitions = []
    for text in lines:
        remaining = sum(len(t.word) for t in C.tokenize(text))
        part = []
        while remaining:
            word = next(words).word
            part.append(word)
            remaining -= len(word)
        partitions.append(part)
    return partitions


def treat_gaps(text, policy):
    """Sentence ends: .?! and their full-width forms; source line is a final end.

    Other phrase punctuation is retained and does not end a sentence. Dropped
    spans retain their closing punctuation so retained neighbours cannot pair.
    """
    if policy == 'split':
        return text, 0
    pieces = re.findall(r'[^.?!。．？！]*[.?!。．？！]+|[^.?!。．？！]+$', text)
    kept, dropped = [], 0
    for piece in pieces:
        if '⟂' in piece:
            dropped += 1
            ending = re.search(r'[.?!。．？！]+$', piece)
            suffix = ending.group() if ending else ''
            kept.append(' ' * (len(piece) - len(suffix)) + suffix)
        else:
            kept.append(piece)
    return ''.join(kept), dropped


def process_document(document, lines, language, option, output, *, g2p=None, cache_dir=None,
                     counter_options=None, segment_mode="require", ownership="counter",
                     segmenter=None, segmenter_version=None, counter=None, counter_version=None,
                     vocabulary=None, higher_rungs="plain", word_tokens_by_line=None, gap_treatment="split",
                     removal_mask=None, declaration=None, onset_inventory=None, _scan_only=False):
    """Publish a resumable single-document bundle. A blocked report has no LM files.

    Use distinct output directories for documents/configurations. Manifest is the
    final commit marker; interrupted artifacts are rebuilt using the type cache.
    Source/config/input changes or corrupted committed files refuse reuse.
    Production callers supply a frozen language mask. Without one this is the
    historical single-option diagnostic API, not a common-text production run.
    """
    if not isinstance(document, str) or not document:
        raise ValueError("document requires a nonempty identifier")
    if isinstance(lines, str):
        raise ValueError("Supply a sequence of document lines, not one string")
    lines = list(lines)
    if any(not isinstance(t, str) or any(c in C.LINE_END for c in t) for t in lines):
        raise ValueError("Each line must be text without embedded line separators")
    if language not in C.COUNTERS or option not in C.COUNTERS[language]:
        raise ValueError("Unknown candidate language/option")
    if counter is not None and (not callable(counter) or not isinstance(counter_version, str) or not counter_version):
        raise ValueError("A supplied counter requires an explicit version")
    supplied_g2p, supplied_counter = g2p is not None, counter is not None
    counter = counter or C.COUNTERS[language][option]
    if segment_mode not in {"require", "nuclei"} or ownership not in {"counter", "first-member", "last-member"}:
        raise ValueError("Unknown segmentation/ownership convention")
    if segmenter is not None and (not isinstance(segmenter_version, str) or not segmenter_version):
        raise ValueError("A supplied segmenter requires an explicit version")
    if higher_rungs != 'plain':
        raise ValueError('Production plain rungs must stay plain; free and charged rungs are explicit')
    if gap_treatment not in {'split', 'drop'}:
        raise ValueError('gap_treatment must be split or drop')
    source_lines = list(lines)
    normalised = list(corpus_filter(source_lines, language)['lines'])
    masked = {i: [{'reason': 'stage2-dropped-line'}] for i, line in enumerate(source_lines) if line == STAGE2_GAP}
    treated = [treat_gaps(line, gap_treatment) for line in normalised]
    lines = [text for text, _ in treated]
    if declaration is not None and (declaration['language'], declaration['option']) != (language, option):
        raise ValueError('Declaration does not match language/option')
    if declaration is not None:
        # A declaration fixes its counter settings and ownership. Callers supply
        # resources (G2P, inventories, segmenters, lexicons such as erhua_words)
        # but can neither omit nor override a declared setting.
        bound = registry_bound(declaration)
        supplied = json.loads(canonical(counter_options)) if counter_options is not None else {}
        if any(key in supplied and supplied[key] != value for key, value in bound['counter_options'].items()):
            raise ValueError('Counter options contradict the registry declaration')
        if ownership not in {'counter', bound['ownership']}:
            raise ValueError('Ownership contradicts the registry declaration')
        opts, ownership = dict(supplied, **bound['counter_options']), bound['ownership']
    else:
        opts = json.loads(canonical(counter_options if counter_options is not None else {}))
    # A declaration's full segmentation is built here from that declaration;
    # only the historical diagnostic API (no declaration) takes a callback.
    if declaration is not None and (segmenter is not None or segmenter_version is not None):
        raise ValueError("A declaration's segmenter is built from the registry; supply onset_inventory instead")
    if declaration is not None and segment_mode == 'require':
        segmenter, segmenter_version = registry_segmenter_for(declaration, onset_inventory)
    if word_tokens_by_line is not None and language != "CMN":
        raise ValueError("word_tokens_by_line is supported only by the Mandarin counter")
    if word_tokens_by_line is not None and isinstance(word_tokens_by_line, (list, tuple)):
        word_tokens_by_line = [[U.normalize('NFC', w) if isinstance(w, str) else w for w in words]
                               if isinstance(words, (list, tuple)) else words for words in word_tokens_by_line]
    if language == "CMN" and isinstance(opts.get("word_tokens"), (list, tuple)):
        opts["word_tokens"] = [U.normalize('NFC', w) if isinstance(w, str) else w for w in opts["word_tokens"]]
    # Partitions are taken on the NFC lines the counter sees, before gap removal.
    partitions = mandarin_partitions(normalised, opts, word_tokens_by_line) if language == "CMN" else None
    if partitions is not None and gap_treatment == 'drop':
        retained = []
        for source, text, words in zip(normalised, lines, partitions):
            part, start = [], 0
            for word in words:
                at = source.index(word, start)
                start = at + len(word)
                if text[at:start] == word:
                    part.append(word)
            retained.append(part)
        partitions = retained
    lexicon = opts.get("lexicon")
    if language == "FRA" and lexicon is None:
        lexicon = C.FRA_LEXICON
    fallback_required = not (language == "FRA" and lexicon and all(
        token.word.lower() in lexicon for line in lines for token in C.tokenize(line)))
    g2p = g2p or main_g2p(language, lexicon=lexicon, fallback_required=fallback_required,
                           reader=opts.get('reader', 'fugashi'), tool=opts.get('tool', 'tltk'),
                           japanese_context='word_tokens' not in opts)
    output = Path(output)
    cfg = {"document": document, "language": language, "option": option, "versions": version(),
           "counter": {"name": getattr(counter, "__qualname__", type(counter).__qualname__),
                       "version": counter_version or version()["counter"]},
           "g2p": g2p.descriptor(), "counter_options": opts, "word_tokens_by_line": partitions,
           "segment_mode": segment_mode,
           "ownership": ownership, "segmenter_version": segmenter_version,
           "vocabulary": vocabulary, "higher_rungs": higher_rungs, "encoding": "candidate-a-v1",
           "tokenizer": "candidate-counter-tokenize", "rungs": list(RUNGS), "treatments": list(TREATMENTS),
           "input_sha256": digest(canonical(source_lines).encode()), "gap_treatment": gap_treatment,
           "sentence_boundaries": ".?!。．？！; source-line end", "schema": "stage4-document-v2",
           "declaration": json.loads(canonical(declaration)), "corpus_filter": STAGE2_FILTER,
           "registry_production": bool(declaration is not None and not supplied_g2p and not supplied_counter
                                       and segment_mode == 'require'
                                       and registry_segmenter(declaration, segmenter_version))}
    if language in {'JPN', 'THA'}:
        native = sys.modules['stage3_japanese' if language == 'JPN' else 'stage3_thai']
        cfg['native_tools'] = (native.route_descriptor(opts.get('reader', 'fugashi')) if language == 'JPN' else
                               native.route_descriptor(opts.get('tool', 'tltk'), opts.get('segmenter', 'newmm')))
    if language in {'CMN', 'YUE', 'VIE'} and 'segmenter' in opts:
        cfg['word_segmenter'] = word_segmenter(language, opts['segmenter']).descriptor()
    if removal_mask is not None:
        if not isinstance(removal_mask, ValidatedMask):
            removal_mask = validated_mask(removal_mask)
        removal_mask.check_code()
        if removal_mask.language != language or document not in removal_mask.documents:
            raise ValueError('Removal mask does not cover this language/document')
        covered = removal_mask.document(document)
        if (covered['input_sha256'] != cfg['input_sha256'] or covered['n_lines'] != len(source_lines)
                or not removal_mask.covers(cfg, covered)):
            raise ValueError('Removal mask does not cover this source/configuration; rebuild and freeze it')
        masked = {int(i): reasons for i, reasons in covered['masked_lines'].items()}
        cfg['removal_mask_sha256'] = removal_mask.full_sha256
    marker = output / "manifest.json"
    if marker.exists() and not _scan_only:
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if saved.get("config") != cfg:
            raise ValueError("Refusing resume with changed source/configuration/input")
        if saved.get("status") not in {"complete", "blocked"}:
            raise ValueError("Invalid committed status")
        expected = {"document.json"} if saved.get("status") == 'blocked' else {
            "document.json", *(f"{t}/{r}{suffix}" for t in TREATMENTS for r in RUNGS for suffix in (".txt", ".meta.json"))}
        if set(saved.get("artifacts", {})) != expected:
            raise ValueError("Incomplete or unrecognised committed artifact inventory")
        for name, metadata in saved["artifacts"].items():
            path = output / name
            if not path.is_file() or digest(path.read_bytes()) != metadata.get("sha256") or metadata.get("provenance") != cfg:
                raise ValueError(f"Corrupt committed artifact: {name}")
        return json.loads((output / "document.json").read_text(encoding="utf-8"))
    pending = output / "pending.json"
    if _scan_only:
        pass
    elif pending.exists():
        if json.loads(pending.read_text(encoding="utf-8")) != cfg:
            raise ValueError("Refusing interrupted resume with changed source/configuration/input")
    else:
        if output.exists() and any(p.name != "g2p-cache" for p in output.iterdir()):
            raise ValueError("Refusing unmarked existing output files")
        atomic(pending, (canonical(cfg) + "\n").encode())
    cache = PronunciationCache(cache_dir or output / "g2p-cache", language, g2p, producer=cfg)
    records = [({'text': t, 'source_line': i, 'words': [], 'syllables': [], 'counter_count': 0,
                 'counter_trace': None, 'status': 'masked', 'problems': [], 'removal_reasons': masked[i]}
                if i in masked else segment_line(t, language, option, cache,
                            counter_options=opts if partitions is None else dict(opts, word_tokens=partitions[i]),
                            segment_mode=segment_mode,
                            ownership=ownership, segmenter=segmenter, segmenter_version=segmenter_version,
                            counter=counter))
               for i, t in enumerate(lines)]
    problems = [dict(line=i, **p) for i, r in enumerate(records) for p in r["problems"]]
    if removal_mask is not None and problems:
        raise ValueError('Unmasked data failure after frozen first pass; rebuild and freeze the removal mask')
    if _scan_only and any(p['reason'] == 'full-segmentation-unfixed' for p in problems):
        raise ValueError('Full segmentation must be configured before building a removal mask')
    for i, record in enumerate(records):
        record['source_line'] = i
    report = {"config": cfg, "document": document,
              "status": 'blocked' if problems else 'complete',
              # Only registry production routes under a frozen mask may be scored.
              "production_ready": removal_mask is not None and not _scan_only and cfg['registry_production'],
              "lines": records, "problems": problems,
              "masked_lines": sorted(masked),
              "dropped_sentences": sum(n for _, n in treated),
              "gap_occurrences": sum(line.count("⟂") for line in source_lines),
              "counter_syllables": sum(r["counter_count"] or 0 for r in records),
              "count_complete": all(r["counter_count"] is not None for r in records),
              "nucleus_proxy": any(s["basis"] == "nucleus-proxy" for r in records for s in r["syllables"]),
              "encoded_syllables": sum(len(r["syllables"]) for r in records)}
    # Every firing of the explicit normalisations and named G2P repairs is counted;
    # the fields appear only where one fired, so other reports are unchanged.
    normalizations = {}
    for line in source_lines:
        for rule, n in normalisation_firings(line, language).items():
            normalizations[rule] = normalizations.get(rule, 0) + n
    if normalizations:
        report['normalizations'] = dict(sorted(normalizations.items()))
    repairs = g2p_repairs(records)
    if repairs:
        report['g2p_repairs'] = repairs
    report = json.loads(canonical(report))  # Identical API values before and after disk resume.
    if language in {'JPN', 'THA', 'FRA'}:
        successful = [r for r in records if r['counter_trace'] is not None]
        total = sum(len(r['words']) for r in successful)
        fallback_count = sum(sum(any(s.endswith('-fallback') for s in source.split('+'))
                                 for source in r['counter_trace']['sources']) for r in successful)
        report['fallback_share'] = fallback_count / total if total else 0.
        report['fallback_word_tokens'] = fallback_count
        report['fallback_total_word_tokens'] = total
        report['non_syllabic_word_tokens'] = sum(len(
            (r['counter_trace'].get('resource_provenance') or {}).get('non_syllabic_words', []))
            for r in successful)
        if language == 'THA':
            native = sys.modules['stage3_thai']
            report['split_unit_alignment'] = {k: sum(
                (r['counter_trace'].get('resource_provenance') or {}).get('split_unit_alignment', {}).get(k, 0)
                for r in successful) for k in native.alignment_counts()}
            report['failed_lines'] = sum(r['status'] == 'blocked' for r in records)
    if _scan_only:
        return report
    payloads = {"document.json": (canonical(report) + "\n").encode()}
    if report['status'] == 'complete':
        for t in TREATMENTS:
            for r in RUNGS:
                data, meta = encode(records, r, t, vocabulary=vocabulary, higher_rungs=higher_rungs)
                payloads[f"{t}/{r}.txt"] = data
                payloads[f"{t}/{r}.meta.json"] = (canonical(dict(provenance=cfg, **meta)) + "\n").encode()
    manifest = {"config": cfg, "status": report["status"],
                "artifacts": {name: {"sha256": digest(data), "bytes": len(data), "provenance": cfg}
                              for name, data in payloads.items()}}
    payloads["manifest.json"] = (canonical(manifest) + "\n").encode()
    preflight(output, sum(map(len, payloads.values())) + 32768 * len(payloads))
    if report['status'] != 'complete':
        # Only remove this pipeline's known artifacts. An interrupted complete
        # attempt may have published windows before reaching its commit marker.
        for treatment in TREATMENTS:
            directory = output / treatment
            for rung in RUNGS:
                for suffix in (".txt", ".meta.json"):
                    (directory / (rung + suffix)).unlink(missing_ok=True)
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
    for name, data in payloads.items():
        atomic(output / name, data)
    pending.unlink(missing_ok=True)
    return report


def registry():
    name = 'stage4_mask_multiverse'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / 'src/stage3/multiverse.py')
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def mask_configuration(cfg):
    """Vocabulary IDs belong to later training/encoding, not line eligibility."""
    return {name: value for name, value in cfg.items() if name != 'vocabulary'}


def registry_configuration(declaration, *, inventory=None, g2p=None):
    """Adapt a complete registry declaration to process_document's arguments.

    Returns resources and settings only. The segmenter is never handed to the
    caller: process_document builds it from the declaration it is given and the
    onset inventory, so a segmenter for other settings can't be substituted.
    """
    language, option = declaration['language'], declaration['option']
    settings = declaration['settings']
    opts = dict(declaration['counter_options'])
    if language == 'CAT' and option == 'B':
        opts['i_attachment'] = settings['i_attachment']
    return {'g2p': g2p, 'counter_options': opts, 'onset_inventory': inventory,
            'ownership': 'counter' if language == 'CAT' else
                         'first-member' if settings['ownership'] == 'left' else 'last-member'}


def registry_segmenter_for(declaration, inventory):
    """The full-segmentation callback and version a declaration's settings define."""
    M = registry()
    language, option = declaration['language'], declaration['option']
    settings = declaration['settings']
    def segmenter(result):
        tonal = None
        if language in {'CMN', 'YUE'}:
            T = M.S._load('stage3_tones', ROOT / 'src/stage3/tones.py')
            adapter = T.Tones(language)
            tonal = {t.word: adapter.join(result, w, p)
                     for w, (t, p) in enumerate(zip(result.tokens, result.pronunciations))}
        # The full segmentation: its syllables, and the counter result as segmentation
        # completed it (FRA-B attaches schwa-only clitics to a neighbouring syllable).
        return M.S.segment_result(result, language, option, inventory, settings=settings,
                                  tonal_pronunciations=tonal)
    inventory_identity = ({'metadata': inventory.metadata, 'legal': sorted(inventory.legal)}
                          if isinstance(inventory, M.S.O.Inventory) else
                          sorted(inventory) if inventory is not None else None)
    return segmenter, canonical({'segment': version()['segmentation_registry'], 'settings': settings,
                                 'inventory': inventory_identity})


_BOUND = {}


def registry_bound(declaration):
    """The settings a declaration fixes, whatever resources are supplied."""
    key = canonical(declaration)
    if key not in _BOUND:
        adapted = registry_configuration(json.loads(key))
        _BOUND[key] = canonical({'counter_options': adapted['counter_options'],
                                 'ownership': adapted['ownership']})
    return json.loads(_BOUND[key])


def registry_segmenter(declaration, segmenter_version):
    """Whether a segmenter version names the registry segmenter for these settings."""
    if not isinstance(segmenter_version, str):
        return False
    try:
        value = json.loads(segmenter_version)
    except ValueError:
        value = None
    return (isinstance(value, dict) and value.get('segment') == version()['segmentation_registry']
            and value.get('settings') == declaration['settings'])


# v3 (P9, 2026-10-15): each declaration's distinct first-pass configurations are
# stored once, in a table, and each document names its own by index, one per
# declaration; v2 repeated every configuration in every document (97% of Catalan's
# mask; about 28 GB for one Italian Wikipedia variant). A declaration can have more
# than one: French reads with `lexique` where the lexicon covers every word and with
# `lexique+espeak-ng` otherwise (Codex review). Which lines are masked is unchanged.
MASK_SCHEMA = 'stage4-language-mask-v3'
PER_DOCUMENT = ('document', 'input_sha256')


def shared_configuration(cfg):
    """A document's first-pass configuration without the fields that name the document, as a v3 mask stores it."""
    return {name: value for name, value in mask_configuration(cfg).items() if name not in PER_DOCUMENT}


def read_mask(mask):
    """Validate a first-pass artifact before any second-pass output writes."""
    mask = json.loads(Path(mask).read_text(encoding='utf-8')) if isinstance(mask, (str, Path)) else json.loads(canonical(mask))
    if not isinstance(mask, dict) or mask.get('schema') != MASK_SCHEMA:
        raise ValueError('Invalid removal mask schema')
    recorded = mask.pop('sha256', None)
    if recorded != digest(canonical(mask).encode()):
        raise ValueError('Invalid removal mask checksum')
    mask['sha256'] = recorded
    if mask.get('versions') != version():
        raise ValueError('Removal mask code changed; rebuild and freeze it')
    # A mask without `check` covers the universes; with it, that check view's declarations.
    declared = json.loads(canonical(registry().declarations(mask['language'], include_calibration=mask['include_calibration'],
                                                              check=mask.get('check'))))
    if mask.get('declarations') != declared:
        raise ValueError('Removal mask does not cover the included registry options')
    bound = [registry_bound(d) for d in declared]
    table = mask.get('configurations')
    if (not isinstance(table, list) or len(table) != len(declared)
            or any(not isinstance(row, list) or not row for row in table)):
        raise ValueError('Incomplete removal mask configurations')
    for index, row in enumerate(table):
        for cfg in row:
            if (not isinstance(cfg, dict) or cfg.get('declaration') != declared[index] or set(cfg) & set(PER_DOCUMENT)
                    or cfg.get('language') != mask['language'] or cfg.get('option') != declared[index]['option']):
                raise ValueError('Removal mask configuration does not match its coverage')
            # Coverage means the declaration's settings were applied, not only named.
            applied = cfg.get('counter_options') if isinstance(cfg.get('counter_options'), dict) else {}
            if (any(key not in applied or applied[key] != value
                    for key, value in bound[index]['counter_options'].items())
                    or cfg.get('ownership') != bound[index]['ownership']
                    or (cfg.get('segment_mode') == 'require'
                        and not registry_segmenter(declared[index], cfg.get('segmenter_version')))):
                raise ValueError('Removal mask configuration did not apply its declared settings')
    for name, document in mask['documents'].items():
        if set(document) != {'input_sha256', 'n_lines', 'masked_lines', 'configurations'}:
            raise ValueError('Removal mask document entries hold the input digest, line count, masked lines '
                             'and configuration indices only')
        indices = document['configurations']
        if (not isinstance(indices, list) or len(indices) != len(declared)
                or any(type(k) is not int or not 0 <= k < len(table[i]) for i, k in enumerate(indices))):
            raise ValueError('Incomplete removal mask configurations')
        for line, reasons in document['masked_lines'].items():
            # Keys are written as str(line); '01' beside '1' would name one line twice.
            if (not line.isdecimal() or str(int(line)) != line or not 0 <= int(line) < document['n_lines'] or not reasons
                    or any(r.get('declaration') not in range(len(declared)) and r.get('declaration') is not None
                           for r in reasons)):
                raise ValueError('Invalid masked line/reasons')
    return mask


class ValidatedMask:
    """A removal mask validated once, for scanning many documents against it.

    `process_document` used to validate the whole mask for every document
    (a full copy, two digests and every document's configurations), which on
    real corpora cost more than the scans and grew with the square of the
    corpus (P9, 2026-10-15). Each document's entry is kept as its canonical
    JSON and parsed afresh per document, so callers get the same values the
    per-call path gave and can't change the mask through them. Only
    `validated_mask` makes one (Codex review, 2026-10-15), and it is read-only.
    """
    __slots__ = ('language', 'sha256', 'full_sha256', 'documents', 'configurations', 'versions', 'fingerprint')

    def __init__(self, *args, **kwargs):
        raise TypeError('A ValidatedMask comes from validated_mask(), which validates it')

    @classmethod
    def _from_validated(cls, **fields):
        made = object.__new__(cls)
        for name, value in fields.items():
            object.__setattr__(made, name, value)
        return made

    def __setattr__(self, name, value):
        raise AttributeError('A ValidatedMask is read-only')

    def __delattr__(self, name):
        raise AttributeError('A ValidatedMask is read-only')

    def document(self, name):
        return json.loads(self.documents[name])

    def covers(self, cfg, entry):
        """Whether a document's configuration, without the fields naming the document, is one the mask recorded
        for that document (`entry`, from `document`): the list a v2 document held, rebuilt from the table."""
        recorded = [json.loads(self.configurations[i][k]) for i, k in enumerate(entry['configurations'])]
        return shared_configuration(cfg) in recorded

    def check_code(self):
        """The per-call path compared the mask's code versions with `version()` for every document; so does this,
        recomputing `version()` only when a hashed source file's stamp has changed."""
        if version_fingerprint() != self.fingerprint and canonical(version()) != self.versions:
            raise ValueError('Removal mask code changed; rebuild and freeze it')


def validated_mask(mask):
    """`read_mask` once; the digest `process_document` records and each document's entry, kept read-only."""
    fingerprint = version_fingerprint()
    mask = read_mask(mask)
    return ValidatedMask._from_validated(
        language=mask['language'], sha256=mask['sha256'], full_sha256=digest(canonical(mask).encode()),
        documents=MappingProxyType({d: canonical(v) for d, v in mask['documents'].items()}),
        configurations=tuple(tuple(canonical(c) for c in row) for row in mask['configurations']),
        versions=canonical(mask['versions']), fingerprint=fingerprint)


def _mask_summary(documents):
    summary = {'masked_lines': 0, 'by_reason': {}, 'by_failure_message': {}}
    for covered in documents.values():
        summary['masked_lines'] += len(covered['masked_lines'])
        for line, reasons in covered['masked_lines'].items():
            for layer, key in (('by_reason', lambda r: r['reason']),
                               ('by_failure_message', lambda r: r.get('detail', r['reason']))):
                for reason in {key(r) for r in reasons}:
                    row = summary[layer].setdefault(reason, {'lines': 0, 'declarations': []})
                    row['lines'] += 1
                    row['declarations'] = sorted(set(row['declarations']) | {
                        r['declaration'] for r in reasons if key(r) == reason and r['declaration'] is not None})
    return summary


def restrict_mask(mask, documents):
    """A validated mask cut down to `documents`, as build_language_mask over just them writes it.

    The counts phase masks every document of a corpus; the split leaves out
    documents with no retained syllable, so a preparation takes the mask of
    the documents it was given (Codex review, 2026-10-14).
    """
    mask = read_mask(mask)
    missing = sorted(set(documents) - set(mask['documents']))
    if missing:
        raise ValueError(f'The mask does not cover {len(missing)} documents, first {missing[0]!r}')
    restricted = {k: v for k, v in mask.items() if k not in ('documents', 'configurations', 'summary', 'sha256')}
    # Only the configurations these documents use, numbered in order of first use, as the builder numbers them.
    table, renumber = [[] for _ in mask['configurations']], [{} for _ in mask['configurations']]
    restricted['documents'] = {}
    for d in documents:
        entry = dict(mask['documents'][d], configurations=[])
        for i, k in enumerate(mask['documents'][d]['configurations']):
            if k not in renumber[i]:
                renumber[i][k] = len(table[i]); table[i].append(mask['configurations'][i][k])
            entry['configurations'].append(renumber[i][k])
        restricted['documents'][d] = entry
    restricted['configurations'] = table
    restricted['summary'] = _mask_summary(restricted['documents'])
    restricted['sha256'] = digest(canonical(restricted).encode())
    return read_mask(restricted)


SCAN_WORKERS = 'INFO_RATE_SCAN_WORKERS'


def scan_workers():
    """Declarations a removal mask scans at once: INFO_RATE_SCAN_WORKERS, default 1 (in this process).

    Inside the counts phase these run under each text variant's worker, so the machine holds
    INFO_RATE_WORKERS times this many; a mask worker holds its documents and one declaration's
    scan of one document at a time.
    """
    value = os.environ.get(SCAN_WORKERS, '1')
    if not value.isdigit() or int(value) < 1:
        raise ValueError(f'{SCAN_WORKERS} must be a positive integer')
    return int(value)


def declaration_key(declaration):
    return digest(canonical(declaration).encode())


_INVENTORIES = {}


def mask_adapter(spec, declaration):
    """A declaration's first-pass arguments from a description another process can rebuild (no
    supplied G2P): `spec['inventories']` maps `declaration_key` to an onset file to read, to None
    for a language without onset inventories, or leaves it out for an empty inventory."""
    entries = spec['inventories']
    key = declaration_key(declaration)
    if key not in entries:
        inventory = frozenset()
    elif entries[key] is None:
        inventory = None
    else:
        if entries[key] not in _INVENTORIES:
            _INVENTORIES[entries[key]] = registry().S.O.read(entries[key])
        inventory = _INVENTORIES[entries[key]]
    return dict(registry_configuration(declaration, inventory=inventory, g2p=None), gap_treatment=spec['gap_treatment'])


def _declaration_scan(documents, language, index, declaration, prepare, output, cache_dir):
    """One declaration's first pass over every document: its configuration table (in document
    order) and each document's (table position, problems)."""
    table, positions, rows = [], {}, {}
    for document, lines in documents.items():
        kwargs = dict(prepare(json.loads(canonical(declaration))))
        if set(kwargs) & {'removal_mask', 'declaration', '_scan_only'}:
            raise ValueError('First-pass adapter cannot override mask coverage')
        report = process_document(document, lines, language, declaration['option'],
                                  Path(output).parent / '.mask-scan',
                                  cache_dir=Path(cache_dir) if cache_dir is not None
                                  else Path(output).parent / 'mask-g2p-cache',
                                  declaration=declaration, _scan_only=True, **kwargs)
        key = canonical(shared_configuration(report['config']))
        if key not in positions:
            positions[key] = len(table); table.append(json.loads(key))
        rows[document] = [positions[key], report['problems']]
    return dict(table=table, documents=rows)


def _scans_in_workers(documents, language, declarations, adapter_spec, output, cache_dir, n):
    """Each declaration's `_declaration_scan` in a fresh interpreter (`--mask-worker`), n at a time."""
    import concurrent.futures
    folder = Path(output).parent / '.mask-workers' / Path(output).name
    folder.mkdir(parents=True, exist_ok=True)
    texts = folder / 'documents.json'
    # Pairs, not an object: canonical JSON sorts keys, and the tables follow document order (Codex review).
    atomic(texts, (canonical([[name, list(lines)] for name, lines in documents.items()]) + '\n').encode())
    def one(index):
        spec, result, log = folder / f'{index}.json', folder / f'{index}-result.json', folder / f'{index}.log'
        result.unlink(missing_ok=True)
        atomic(spec, (canonical(dict(documents=str(texts), language=language, index=index,
                                     declaration=declarations[index], adapter=adapter_spec, output=str(output),
                                     cache_dir=None if cache_dir is None else str(cache_dir), result=str(result)))
                      + '\n').encode())
        with open(log, 'wb') as out:
            code = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--mask-worker', str(spec)],
                                  stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT).returncode
        if code != 0 or not result.exists():
            tail = log.read_bytes()[-2000:].decode('utf-8', 'replace')
            raise RuntimeError(f'mask worker failed (exit {code}) for {language} declaration {index}; log {log}:\n{tail}')
        return json.loads(result.read_text(encoding='utf-8'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(one, index) for index in range(len(declarations))]
        concurrent.futures.wait(futures)
    failed = [f.exception() for f in futures if f.exception() is not None]
    if failed:
        raise failed[0]
    results = [f.result() for f in futures]
    shutil.rmtree(folder)
    return results


def _mask_worker(spec_path):
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    documents = {name: tuple(lines) for name, lines in json.loads(Path(spec['documents']).read_text(encoding='utf-8'))}
    value = _declaration_scan(documents, spec['language'], spec['index'], spec['declaration'],
                              lambda d: mask_adapter(spec['adapter'], d), spec['output'], spec['cache_dir'])
    atomic(Path(spec['result']), (canonical(value) + '\n').encode())


def build_language_mask(documents, language, output, *, prepare=None, include_calibration=False, cache_dir=None,
                        check=None, adapter_spec=None):
    """Separate first pass across ALL included registry options; no estimator files.

    `documents` maps stable subtitle IDs to Stage-2-output lines. `prepare` may
    provide frozen per-declaration adapters/inventories; simulations use invented
    adapters. The result stores each exact configuration, original source hash,
    per-line reasons and failing declarations. It can be archived/frozen by the
    production caller; this helper does not timestamp or fetch anything.
    cache_dir: the G2P cache folder (default `mask-g2p-cache` beside `output`); the
    counts phase passes one folder per language (P9, item 8a). check: a check view's
    id (`multiverse.check_views`); the mask then covers that view's declarations
    and records it, as one without covers the universes. adapter_spec: in place of
    `prepare`, a description `mask_adapter` rebuilds in another process (production, no
    supplied G2P); with INFO_RATE_SCAN_WORKERS above 1 the declarations are then scanned that
    many at a time and merged into the same mask (P9 at real size).
    """
    declarations = json.loads(canonical(registry().declarations(language, include_calibration=include_calibration,
                                                                  check=check)))
    if any(isinstance(lines, str) for lines in documents.values()):
        raise ValueError('Each document must supply lines, not one string')
    documents = {name: tuple(lines) for name, lines in documents.items()}
    if not documents:
        raise ValueError('A removal mask requires explicit documents')
    mask = {'schema': MASK_SCHEMA, 'language': language, 'versions': version(),
            'include_calibration': include_calibration, 'declarations': declarations, 'documents': {}}
    if check is not None:
        mask['check'] = check
    if adapter_spec is not None:
        if prepare is not None:
            raise ValueError('Give a mask either prepare or adapter_spec, not both')
        prepare = lambda declaration: mask_adapter(adapter_spec, declaration)
    prepare = prepare or registry_configuration
    # A declaration's configuration is mostly the same in every document, so each
    # distinct one is stored once and documents name theirs by index (v3).
    n = scan_workers() if adapter_spec is not None else 1
    if n > 1 and len(declarations) > 1:
        scans = _scans_in_workers(documents, language, declarations, adapter_spec, output, cache_dir, n)
        for document, lines in documents.items():
            covered = {'input_sha256': digest(canonical(lines).encode()), 'n_lines': len(lines), 'masked_lines': {},
                       'configurations': []}
            for index, scan in enumerate(scans):
                position, problems = scan['documents'][document]
                covered['configurations'].append(position)
                for problem in problems:
                    covered['masked_lines'].setdefault(str(problem['line']), []).append(dict(problem, declaration=index))
                if index == 0:
                    for line, value in enumerate(lines):
                        if value == STAGE2_GAP:
                            covered['masked_lines'].setdefault(str(line), []).append(
                                {'reason': 'stage2-dropped-line', 'declaration': None})
            mask['documents'][document] = covered
        table = [scan['table'] for scan in scans]
        documents = {}  # merged above
    else:
        table = [[] for _ in declarations]
    positions = [{} for _ in declarations]
    for document, lines in documents.items():
        covered = {'input_sha256': digest(canonical(lines).encode()), 'n_lines': len(lines), 'masked_lines': {},
                   'configurations': []}
        for index, declaration in enumerate(declarations):
            kwargs = dict(prepare(json.loads(canonical(declaration))))
            if set(kwargs) & {'removal_mask', 'declaration', '_scan_only'}:
                raise ValueError('First-pass adapter cannot override mask coverage')
            report = process_document(document, lines, language, declaration['option'],
                                      Path(output).parent / '.mask-scan',
                                      cache_dir=Path(cache_dir) if cache_dir is not None
                                      else Path(output).parent / 'mask-g2p-cache',
                                      declaration=declaration, _scan_only=True, **kwargs)
            configuration = shared_configuration(report['config'])
            key = canonical(configuration)
            if key not in positions[index]:
                positions[index][key] = len(table[index]); table[index].append(json.loads(key))
            covered['configurations'].append(positions[index][key])
            for problem in report['problems']:
                line = problem['line']
                covered['masked_lines'].setdefault(str(line), []).append(dict(problem, declaration=index))
            if index == 0:
                for line, value in enumerate(lines):
                    if value == STAGE2_GAP:
                        covered['masked_lines'].setdefault(str(line), []).append(
                            {'reason': 'stage2-dropped-line', 'declaration': None})
        mask['documents'][document] = covered
    mask['configurations'] = table
    mask['summary'] = _mask_summary(mask['documents'])
    mask['sha256'] = digest(canonical(mask).encode())
    read_mask(mask)
    output = Path(output)
    if output.exists() and json.loads(output.read_text(encoding='utf-8')) != mask:
        raise ValueError('Refusing to overwrite a different frozen removal mask; use a new path')
    atomic(output, (canonical(mask) + '\n').encode())
    return mask


def main():
    import argparse
    if len(sys.argv) > 1 and sys.argv[1] == 'mask':
        p = argparse.ArgumentParser(description='Freeze a common-text mask from explicit Stage-2-output JSON')
        p.add_argument('language', choices=C.COUNTERS)
        p.add_argument('documents', type=Path, help='JSON object: document ID -> lines; no discovery')
        p.add_argument('output', type=Path)
        p.add_argument('--onsets', type=Path, help='JSON list of atomic-phone lists, frozen for this language')
        p.add_argument('--include-calibration', action='store_true')
        p.add_argument('--gap-treatment', choices=('split', 'drop'), default='split')
        args = p.parse_args(sys.argv[2:])
        inventory = tuple(tuple(row) for row in json.loads(args.onsets.read_text())) if args.onsets else None
        result = build_language_mask(json.loads(args.documents.read_text()), args.language, args.output,
                                     prepare=lambda d: dict(registry_configuration(d, inventory=inventory),
                                                            gap_treatment=args.gap_treatment),
                                     include_calibration=args.include_calibration)
        print(canonical(dict(language=result['language'], **result['summary'])))
        return 0
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("language", choices=C.COUNTERS)
    p.add_argument("option")
    p.add_argument("document")
    p.add_argument("output", type=Path)
    p.add_argument("--line", action="append", required=True, help="Supplied invented text line; no file discovery")
    p.add_argument("--gap-treatment", choices=("split", "drop"), default="split")
    p.add_argument('--mask', type=Path, required=True, help='Frozen first-pass language mask')
    p.add_argument('--universe', type=int, required=True, help='Index into the mask registry declarations')
    p.add_argument('--onsets', type=Path, help='Same frozen onset JSON used in the first pass')
    args = p.parse_args()
    mask = read_mask(args.mask)
    if not 0 <= args.universe < len(mask['declarations']):
        p.error('Universe index is outside the frozen mask declarations')
    declaration = mask['declarations'][args.universe]
    if (declaration['language'], declaration['option']) != (args.language, args.option):
        p.error('Universe does not match language/option')
    inventory = tuple(tuple(row) for row in json.loads(args.onsets.read_text())) if args.onsets else None
    result = process_document(args.document, args.line, args.language, args.option, args.output,
                              removal_mask=mask, declaration=declaration,
                              gap_treatment=args.gap_treatment,
                              **registry_configuration(declaration, inventory=inventory))
    print(canonical({k: result[k] for k in ("document", "status", "counter_syllables", "count_complete", "problems")}))
    return 0 if result["status"] == 'complete' else 2


if __name__ == "__main__":
    if sys.argv[1:2] == ['--mask-worker'] and len(sys.argv) == 3:
        _mask_worker(sys.argv[2])
        raise SystemExit(0)
    raise SystemExit(main())
