"""Candidate syllable counts on invented words or supplied pronunciations.

Rules follow notes/stage3-candidate-conventions.md. IPA results expose nucleus
groups, not a choice of consonant boundaries for Stage 5. Full segmentation is
returned for spelling/block/character rules. Frozen public Wiktionary-derived
lists and installed G2P resources are read; adapters never download resources.
"""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import csv, hashlib, importlib.util, inspect, json, re, subprocess, sys, unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from functools import lru_cache, wraps
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch
import regex

VOWELS = set("iyɨʉɯuɪʏʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒɚɝ")
LINE_END = set("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")  # str.splitlines() boundaries
# Full-width/CJK equivalents are pending the project lead's confirmation.
WIDE_PHRASE_END = set('，．。、；：？！＂「」『』（）［］【】《》〈〉〔〕｢｣')
PHRASE_END = set('.,;:?!…«»"„“”()[]–—') | LINE_END | WIDE_PHRASE_END | {"⟂"}
ESPEAK_LABEL = re.compile(r"\(([a-zA-Z0-9_\-\u200d]+)\)")
HAN = regex.compile(r"\p{Han}")
GLIDES = set("jwɥ")
FIN_VOWELS = set("aeiouyäö")
FIN_DIPHTHONGS = set("ei yi öi äi ai oi ui iu eu au ou ey iy öy äy ie yö uo".split())
FIN_EXTRA = set("ia iä ae äe eo eö".split())
RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources"
CHAINED_TIES = ("reject", "one_nucleus", "disjoint_pairs")
DEFAULT_CHAINED_TIES = "one_nucleus"   # Brett, 2026-10-10 (row 44)
_CHAINED_TIES = ContextVar("chained_ties", default=DEFAULT_CHAINED_TIES)
# Immutable, enumerable declarations; option names match COUNTERS (including C′).
FORKS = MappingProxyType({
    row: MappingProxyType(dict(row=row, setting=setting, values=values, options=options))
    for row, setting, values, options in (
        (16, "spanish_pairing", ("code", "historical_maximal_pairing", "non_close_pairs_only"), (("SPA", "B"),)),
        (17, "italian_terminal", ("code", "protect_all_terminal_run", "protect_terminal_nuclei"),
         tuple(("ITA", o) for o in ("A", "B", "C"))),
        (5, "identical_vowels", ("code", "all_identical_first"),
         tuple(("FIN", o) for o in ("A", "B", "C", "C′", "D")) +
         tuple(("ITA", o) for o in ("A", "B", "C")) + (("SPA", "B"), ("EUS", "B"))),
        (12, "catalan_stress", ("code", "isolation_stress"), (("CAT", "B"),)),
        (26, "basque_r0", ("code", "preserve_shared_R0"), (("EUS", "B"),)),
    )
})
_FORK_BY_SETTING = {fork["setting"]: fork for fork in FORKS.values()}
_FORK_SETTINGS = ContextVar("counter_forks", default=None)

def _setting(name):
    return (_FORK_SETTINGS.get() or {}).get(name, "code")

def _resolved_settings():
    return dict(chained_ties=_CHAINED_TIES.get(), **{name: _setting(name) for name in _FORK_BY_SETTING})

@contextmanager
def counter_settings(*, chained_ties=None, **forks):
    """Scope validated settings; language/option applicability is checked on calls.

    Omitted values inherit the enclosing scope. Explicit code values still count
    as selected forks, so applying them to an unrelated counter is an error.
    """
    chained_ties = _CHAINED_TIES.get() if chained_ties is None else chained_ties
    if chained_ties not in CHAINED_TIES:
        raise ValueError("Unknown chained-tie policy")
    for name, value in forks.items():
        if name not in _FORK_BY_SETTING or value not in _FORK_BY_SETTING[name]["values"]:
            raise ValueError(f"Unknown counter fork setting/value: {name}={value}")
    token = _CHAINED_TIES.set(chained_ties)
    fork_token = _FORK_SETTINGS.set(dict(_FORK_SETTINGS.get() or {}, **forks))
    try:
        yield
    finally:
        _FORK_SETTINGS.reset(fork_token)
        _CHAINED_TIES.reset(token)

# Hashes of the resource bytes this module read into memory, checked by the freeze lock
# against the listed files (a lexicon revised and stamped without a restart).
__freeze_resources__ = {}


def _frozen_lexicons():
    raw = (RESOURCE_ROOT / "lexicons-provenance.json").read_bytes()
    __freeze_resources__["resources/lexicons-provenance.json"] = hashlib.sha256(raw).hexdigest()
    metadata = json.loads(raw.decode("utf-8"))
    italian, mandarin, catalan = {}, {}, set()
    ita_variable, cmn_variable = set(), set()
    descriptors = {}
    for name in ("ita_hiatus.tsv", "cmn_erhua.tsv", "cat_function_words.tsv"):
        data = (RESOURCE_ROOT / name).read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        __freeze_resources__["resources/" + name] = checksum
        if checksum != metadata["resources"][name]["sha256"]:
            raise ValueError(f"Frozen lexicon checksum mismatch: {name}")
        resource = metadata['resources'][name]
        descriptors[name] = (dict(resource['provenance']) if 'provenance' in resource else
                             {k: metadata[k] for k in ("source", "dump_date", "extract_date", "license", "citation", "citation_url")})
        descriptors[name].update(sha256=checksum, index_base=metadata["index_base"],
                                 policy=metadata["resources"][name]["policy"])
        if name == "ita_hiatus.tsv" and "main_g2p" in metadata["resources"][name]:
            descriptors[name].update(main_g2p=metadata["resources"][name]["main_g2p"],
                                     alignment_policy=metadata["resources"][name]["alignment_policy"])
        for row in csv.DictReader(data.decode("utf-8").splitlines(), delimiter="\t"):
            if name == "ita_hiatus.tsv":
                word = unicodedata.normalize("NFC", row["word"]).lower()
                # one set per pronunciation; a pair is protected only if every pronunciation of the spelling
                # has it (homographs such as piano /ˈpja.no/ beside a rare /piˈa.no/; Claude, 2026-10-10)
                italian.setdefault(word, []).append({tuple(p) for p in json.loads(row["protected_pairs"])})
                if row["variable"] == "1":
                    ita_variable.add(word)
            elif name == 'cat_function_words.tsv':
                catalan.add(unicodedata.normalize('NFC', row['word']).lower())
            else:
                word = unicodedata.normalize("NFC", row["form"]).replace("兒", "儿")
                mandarin.setdefault(word, set()).add(tuple(json.loads(row["erhua_positions"])))
                if row["variable"] == "1":
                    cmn_variable.add(word)
    agreed = {w: set.intersection(*ps) for w, ps in italian.items()}
    return (MappingProxyType({w: tuple(sorted(ps)) for w, ps in agreed.items() if ps}),
            MappingProxyType({w: sorted(ps, key=lambda p: (-len(p), p))[0] for w, ps in mandarin.items()}),
            frozenset(ita_variable), frozenset(cmn_variable), descriptors, frozenset(catalan))

ITA_HIATUS, CMN_ERHUA, ITA_VARIABLE, CMN_VARIABLE, LEXICON_PROVENANCE, CAT_FUNCTION_WORDS = _frozen_lexicons()
def _italian_evidence():
    evidence = {}
    data = (RESOURCE_ROOT / 'ita_hiatus.tsv').read_bytes()
    if hashlib.sha256(data).hexdigest() != __freeze_resources__['resources/ita_hiatus.tsv']:
        raise ValueError('ita_hiatus.tsv changed while the counters loaded')
    for row in csv.DictReader(data.decode('utf-8').splitlines(), delimiter='\t'):
        evidence.setdefault(unicodedata.normalize('NFC', row['word']).lower(), []).append(
            (row['ipa'], tuple(tuple(p) for p in json.loads(row['protected_pairs']))))
    return MappingProxyType({w: tuple(rs) for w, rs in evidence.items()})

ITA_EVIDENCE = _italian_evidence()
CMN_ERHUA_ENTRIES = tuple(sorted(CMN_ERHUA.items()))
ESPEAK = __import__("os").environ.get("INFO_RATE_ESPEAK", "/opt/homebrew/bin/espeak-ng")  # machine path (DECISIONS.md, 2026-10-17)
if not ESPEAK.startswith("/"):
    raise ValueError(f"INFO_RATE_ESPEAK must be an absolute path: {ESPEAK}")
VOICES = dict(SPA="es", CAT="ca", DEU="de", EUS="eu", FRA="fr")
EPITRAN = dict(ITA="ita-Latn", SRP="srp-Latn", TUR="tur-Latn", FIN="fin-Latn", HUN="hun-Latn")

@dataclass(frozen=True)
class Token:
    word: str
    phrase_end: bool

@dataclass(frozen=True)
class Attachment:
    word: int
    host: int
    nucleus: int
    segments: str
    side: str

@dataclass(frozen=True)
class LanguageSwitch:
    word: int
    text: str
    languages: tuple

@dataclass(frozen=True)
class Count:
    """Count and trace; segmentation is None when consonant boundaries are unfixed.

    Nuclei retain grouped source symbols. Hosts/members index tokens; attachments
    assign a vowel-less Catalan word to a host nucleus. All indices start at zero.
    """
    count: int
    segmentation: tuple | None
    nuclei: tuple
    hosts: tuple
    members: tuple
    tokens: tuple
    pronunciations: tuple
    sources: tuple
    attachments: tuple = ()
    switched_words: tuple = ()
    resource_provenance: dict | None = None
    chained_ties: str = DEFAULT_CHAINED_TIES
    # Effective phones after language-specific mutations, and exact nucleus
    # indices. Segmenters must not reconstruct them from the original G2P.
    phone_texts: tuple = ()
    phone_words: tuple = ()
    phone_stress: tuple = ()
    group_indices: tuple = ()
    counter_settings: dict = field(default_factory=_resolved_settings)
    # Native option defaults and fingerprints of overrides, without word lists.
    counter_options: dict = field(default_factory=dict)

    @property
    def switched_word_count(self):
        """Number of word tokens read using a switched espeak language, including repeats."""
        return len(self.switched_words)

    @property
    def fallback_share(self):
        """Fraction of word tokens using a fallback, including mixed Thai words."""
        return (sum(any(part.endswith('-fallback') for part in s.split('+')) for s in self.sources)
                / len(self.sources) if self.sources else 0.0)

def tokenize(text):
    """Split words at spaces/hyphens; retain internal apostrophes and phrase ends."""
    tokens, word = [], []
    def flush():
        if word:
            stripped = ''.join(word).strip('‘’')
            if stripped:
                tokens.append(Token(stripped, False))
            word.clear()
    for c in unicodedata.normalize("NFC", text):
        if c in PHRASE_END:
            flush()
            if tokens:
                tokens[-1] = Token(tokens[-1].word, True)
        elif c.isspace() or c in "-‐‑":
            flush()
        else:
            word.append(c)
    flush()
    if tokens:
        tokens[-1] = Token(tokens[-1].word, True)
    return tuple(tokens)

@contextmanager
def _offline_nltk():
    """Restrict NLTK to interpreter resources and block implicit downloads."""
    import nltk
    paths = [str(Path(sys.prefix) / "nltk_data"), str(Path(nltk.__file__).parent / "nltk_data")]
    # g2p-en probes an obsolete tagger during import. A false download result
    # permits import; actually missing resources still raise LookupError on use.
    with patch.object(nltk.data, "path", paths), patch.object(nltk, "download", return_value=False):
        yield

class _EspeakIPA(str):
    """Clean IPA carrying language switches without putting control labels in phones."""
    def __new__(cls, ipa, languages=()):
        out = super().__new__(cls, ipa)
        out.languages = languages
        return out

@lru_cache(maxsize=8192)
def espeak(word, voice):
    """Transcribe one isolated word so phrase rules are applied by our counter."""
    # espeak 1.52 uses ZWJ in --ipa=3 output for tied segments. Translate it
    # to the note's U+0361; default --ipa omits these ties entirely.
    raw = subprocess.run([ESPEAK, "-q", "--ipa=3", "-v", voice, "--", word],
                         capture_output=True, text=True, check=True).stdout.strip()
    labels = [label.replace("\u200d", "") for label in ESPEAK_LABEL.findall(raw)]
    languages = tuple(dict.fromkeys(label for label in labels if label != voice))
    # Strip labels before translating joiners; joiners inside labels aren't ties.
    return _EspeakIPA(ESPEAK_LABEL.sub("", raw).replace("\u200d", "\u0361"), languages)

@lru_cache(maxsize=None)
def _epitran(code):
    import epitran
    return epitran.Epitran(code)

@lru_cache(maxsize=8192)
def _epitran_word(word, code):
    if code == "tur-Latn":
        word = unicodedata.normalize("NFC", word).translate(str.maketrans("İI", "iı")).lower()
    return _epitran(code).transliterate(word)

# Two Epitran vowel repairs for Italian (Brett, 2026-10-15), each named in the
# reading's source so every firing is counted; the 2026-10-10 drop of the Epitran
# vowel repair stands for the other cases (sciare).
# Epitran reads the u after q as a vowel (qui /kui/, acqua /akkua/), and at word end
# every Italian option keeps it as a nucleus. Spelled q+u+vowel, the u is the glide
# w: the word is read again with that u written w, which must give the first reading
# with exactly those u turned w (true of every such Italian Wiktionary form, 12,794).
# Word-internal cases (quando, questo) keep their count; only their labels change.
ITALIAN_QU_GLIDE = "ita-qu-glide"
ITALIAN_QU_UNALIGNED = "Italian qu repair does not align with the reading"
_ITALIAN_QU = re.compile(r"([qQ])([uU])(?=[aeiouàáèéìíîòóùúAEIOUÀÁÈÉÌÍÎÒÓÙÚ])")
# Epitran reads word-final gli as /ʎ/ with no vowel (gli, figli, degli), so a
# standalone gli had no syllable and other -gli words lost their last; the i is
# the nucleus there, and its /i/ is restored.
ITALIAN_FINAL_GLI = "ita-final-gli"
ITALIAN_REPAIRS = (ITALIAN_FINAL_GLI, ITALIAN_QU_GLIDE)

def epitran_reading(word, code):
    """Epitran's reading and its source, with the Italian repairs tagged."""
    pron = _epitran_word(word, code)
    repairs = []
    if code == "ita-Latn":
        sites = len(_ITALIAN_QU.findall(word))
        if sites:
            glided = _epitran_word(_ITALIAN_QU.sub(lambda m: m.group(1) + ("w" if m.group(2) == "u" else "W"), word), code)
            changed = [(a, b) for a, b in zip(pron, glided) if a != b]
            if len(glided) != len(pron) or len(changed) != sites or any(c != ("u", "w") for c in changed):
                raise ValueError(ITALIAN_QU_UNALIGNED)
            pron = glided; repairs.append(ITALIAN_QU_GLIDE)
        if unicodedata.normalize("NFC", word).lower().endswith("gli") and pron.endswith("ʎ"):
            pron += "i"; repairs.append(ITALIAN_FINAL_GLI)
    return pron, "+".join(["epitran", *repairs])

def epitran_word(word, code):
    return epitran_reading(word, code)[0]

@lru_cache(maxsize=1)
def _cmu():
    import cmudict
    return cmudict.dict()

@lru_cache(maxsize=1)
def _english_predictor():
    with _offline_nltk():
        from g2p_en import G2p
        return G2p()

def english_word(word):
    """CMU, accent-stripped CMU, then isolated g2p-en predictor without POS context."""
    word = word.lower().replace("’", "'")
    pron = _cmu().get(word)
    if pron:
        return tuple(pron[0]), "cmudict"
    word = "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.category(c).startswith("M"))
    pron = _cmu().get(word)
    if pron:
        return tuple(pron[0]), "cmudict"
    try:
        return tuple(_english_predictor().predict(word)), "g2p-en"
    except (ImportError, LookupError) as e:
        raise RuntimeError("g2p-en needs local installed resources; downloads are disabled") from e

@lru_cache(maxsize=1)
def _korean():
    with _offline_nltk():
        from g2pk2 import G2p
        return G2p()

def g2pk2_available():
    return importlib.util.find_spec("g2pk2") is not None

def _input(text, lang, pronunciations=None):
    tokens = tokenize(text)
    if pronunciations is not None:
        if hasattr(pronunciations, "keys"):
            prons = tuple(pronunciations[t.word] for t in tokens)
        else:
            prons = tuple(pronunciations)
        if len(prons) != len(tokens):
            raise ValueError("Supply one pronunciation per word token")
        return tokens, prons, ("supplied",) * len(tokens)
    if lang in VOICES:
        return tokens, tuple(espeak(t.word, VOICES[lang]) for t in tokens), ("espeak",) * len(tokens)
    if lang in EPITRAN:
        readings = [epitran_reading(t.word, EPITRAN[lang]) for t in tokens]
        return tokens, tuple(p for p, _ in readings), tuple(s for _, s in readings)
    raise ValueError(f"No IPA adapter for {lang}")

@dataclass
class _Phone:
    text: str
    base: str
    word: int
    stressed: bool = False
    stress: str = ""

    @property
    def vowel(self):
        return self.base in VOWELS

    @property
    def nucleus(self):
        if self.base in GLIDES or "\u032f" in self.text:
            return False
        return self.vowel or "\u0329" in self.text

def _phones(ipa, word=0, srp=False):
    """Attach length/diacritics to phones and stress to the next vowel nucleus."""
    out, stress_positions = [], {}
    for c in unicodedata.normalize("NFD", ipa):
        if c in "ˈˌ":
            stress_positions[len(out)] = c
        elif c in "ːˑ:" or unicodedata.combining(c):
            if srp and c == "\u0329":
                continue
            if not out:
                raise ValueError("Diacritic/length mark without a preceding phone")
            out[-1].text += c
        elif not c.isspace() and c not in "'’":
            out.append(_Phone(c, c, word))
    if out and any(t in out[-1].text for t in "͜͡"):
        raise ValueError("Tie bar without a second phone")
    pending, tie_position = "", 0
    for i, p in enumerate(out):
        if i in stress_positions:
            pending = stress_positions[i]
        tied_second = i > 0 and any(t in out[i - 1].text for t in "͜͡")
        tie_position = tie_position + 1 if tied_second else 0
        if _CHAINED_TIES.get() == "disjoint_pairs":
            tied_second = bool(tie_position % 2)
        if p.nucleus and not tied_second:
            p.stressed = bool(pending)
            p.stress = pending
            pending = ""
    return out

def _unstressed_final_vowel_start(phones):
    """Start of a deletable final nucleus, including its tie/glide tail."""
    if not phones or not phones[-1].vowel:
        return None
    groups = _r0(phones)
    if not groups:
        return None
    start = groups[-1][0]
    if not all(p.vowel for p in phones[start:]) or phones[start].stressed:
        return None
    return start

def _r0(phones):
    groups, i = [], 0
    while i < len(phones):
        p = phones[i]
        g = [i]
        if any(t in p.text for t in "͜͡"):
            end = i
            while any(t in phones[end].text for t in "͜͡"):
                if end + 1 >= len(phones) or phones[end + 1].word != p.word:
                    raise ValueError("Tie bar without a second phone in the word")
                end += 1
            if end > i + 1:
                policy = _CHAINED_TIES.get()
                if policy == "reject" or not all(q.vowel for q in phones[i:end + 1]):
                    raise ValueError("Chained tie bars are not a pair (only vowel chains can be accepted)")
                if policy == "disjoint_pairs":
                    for start in range(i, end + 1, 2):
                        if phones[start].nucleus:
                            groups.append(list(range(start, min(start + 2, end + 1))))
                    i = end + 1
                    continue
            g = list(range(i, end + 1)); i = end
        if p.nucleus:
            groups.append(g)
        i += 1
    return groups

def _adjacent(a, b, phones, tokens, cross):
    p, q = phones[a[-1]], phones[b[0]]
    if not all(phones[i].vowel for i in range(a[-1], b[0] + 1)):
        return False
    if p.word == q.word:
        return True
    return cross and all(not tokens[w].phrase_end for w in range(p.word, q.word))

def _pair(groups, phones, tokens, cross=False, blocked=(), forbidden=()):
    """Greedy R0 pairs with whole-nucleus and boundary-only protection."""
    out, i = [], 0
    blocked = set(blocked)
    if _setting("identical_vowels") == "all_identical_first":
        # Keep every source phone and its word, collapsing R0 slots only. The
        # same boundaries and protected nuclei constrain fusion and pairing.
        fused = []
        for group in groups:
            same = fused and all(phones[p].base == phones[fused[-1][0]].base for p in fused[-1] + group)
            if (same and not blocked.intersection(fused[-1] + group)
                    and (fused[-1][-1], group[0]) not in forbidden
                    and _adjacent(fused[-1], group, phones, tokens, cross)):
                fused[-1].extend(group)
            else:
                fused.append(list(group))
        groups = fused
    while i < len(groups):
        a = groups[i]
        if (i + 1 < len(groups) and not blocked.intersection(a + groups[i + 1])
                and (a[-1], groups[i + 1][0]) not in forbidden
                and _adjacent(a, groups[i + 1], phones, tokens, cross)):
            out.append(a + groups[i + 1]); i += 2
        else:
            out.append(a); i += 1
    return out

def _result(groups, phones, tokens, prons, sources, segmentation=None, attachments=()):
    members = tuple(tuple(dict.fromkeys(phones[i].word for i in g)) for g in groups)
    switches = tuple(LanguageSwitch(w, tokens[w].word, pron.languages) for w, pron in enumerate(prons)
                     if getattr(pron, "languages", ()))
    return Count(len(groups), segmentation, tuple("".join(phones[i].text for i in g) for g in groups),
                 tuple(m[0] for m in members), members, tokens, prons, sources, tuple(attachments), switches,
                 chained_ties=_CHAINED_TIES.get(),
                 phone_texts=tuple(p.text for p in phones),
                 phone_words=tuple(p.word for p in phones),
                 phone_stress=tuple(p.stress for p in phones),
                 group_indices=tuple(tuple(g) for g in groups))

def r0(ipa):
    """Count transcribed nuclei, including tied vowels and syllabic consonants."""
    phones = _phones(ipa)
    return _result(_r0(phones), phones, (Token(ipa, True),), (ipa,), ("supplied",))

def pairing(ipa):
    phones = _phones(ipa); tokens = (Token(ipa, True),)
    return _result(_pair(_r0(phones), phones, tokens), phones, tokens, (ipa,), ("supplied",))

def cross_word_pairing(text, pronunciations):
    return _ipa(text, "SPA", "pair-cross", pronunciations)

def _ipa(text, lang, rule="r0", pronunciations=None):
    tokens, prons, sources = _input(text, lang, pronunciations)
    phones = [p for w, pron in enumerate(prons) for p in _phones(pron, w, lang == "SRP")]
    if lang == "SRP":
        for i, p in enumerate(phones):
            if p.base == "r":
                prev = phones[i - 1] if i and phones[i - 1].word == p.word else None
                nxt = phones[i + 1] if i + 1 < len(phones) and phones[i + 1].word == p.word else None
                if (prev is None or not prev.vowel) and (nxt is None or not nxt.vowel) and (prev or nxt):
                    p.text += "\u0329"
    groups = _r0(phones)
    if rule.startswith("pair"):
        forbidden = set()
        if rule == 'pair-cross-stressed-hiatus':
            policy = _setting("spanish_pairing")
            for a, b in zip(groups, groups[1:]):
                if (policy != "historical_maximal_pairing" and phones[a[0]].word == phones[b[0]].word
                        and any(phones[g[0]].base in 'iuɪʊ' and
                                (policy == "non_close_pairs_only" or phones[g[0]].stressed) for g in (a, b))):
                    forbidden.add((a[-1], b[0]))
        groups = _pair(groups, phones, tokens, rule != 'pair', forbidden=forbidden)
    return _result(groups, phones, tokens, prons, sources)

def spa_a(text, pronunciations=None):
    return _ipa(text, "SPA", pronunciations=pronunciations)

def spa_b(text, pronunciations=None):
    return _ipa(text, "SPA", "pair-cross-stressed-hiatus", pronunciations)

def cat_a(text, pronunciations=None):
    return _ipa(text, "CAT", pronunciations=pronunciations)

def cat_b(text, pronunciations=None, i_attachment="code"):
    """Apply passage elisions using glide, then function-word, then final-vowel rules."""
    if i_attachment not in {"code", "backward"}:
        raise ValueError("Unknown Catalan i attachment")
    tokens, prons, sources = _input(text, "CAT", pronunciations)
    words = [_phones(pron, w) for w, pron in enumerate(prons)]
    function_words = []
    for w, t in enumerate(tokens):
        spelling = unicodedata.normalize('NFC', t.word).lower()
        if _setting("catalan_stress") == "code" and spelling in CAT_FUNCTION_WORDS:
            function_words.append(spelling)
            for p in words[w]:
                p.stressed = False
    def linked(w):
        return w + 1 < len(words) and not tokens[w].phrase_end
    def final(w):
        return bool(words[w]) and words[w][-1].vowel
    def initial(w):
        return bool(words[w]) and words[w][0].vowel
    attach = {}
    # The passage's i becomes j first: in 'tramuntana i el' this keeps el.
    for w, t in enumerate(tokens):
        if t.word.lower() == "i" and ((w and linked(w - 1) and final(w - 1)) or (linked(w) and initial(w + 1))):
            for p in words[w]:
                if p.vowel:
                    p.text, p.base = "j", "j"
            attach[w] = (w + 1, "before") if linked(w) and initial(w + 1) else (w - 1, "after")
            if (i_attachment == "backward" and w and linked(w - 1)
                    and any(p.nucleus for p in words[w - 1])):
                attach[w] = (w - 1, "after")
    deleted = set()
    # A reduced el/es blocks que's look-ahead in 'que el qui'.
    for w, t in enumerate(tokens):
        if t.word.lower() in ("el", "es") and w and linked(w - 1) and final(w - 1):
            words[w] = [p for p in words[w] if not p.vowel]
            attach[w] = (w - 1, "after"); deleted.add(w)
    for w, t in enumerate(tokens):
        if t.word.lower() == "que" and linked(w) and initial(w + 1):
            words[w] = [p for p in words[w] if not p.vowel]
            attach[w] = (w + 1, "before"); deleted.add(w)
    for w in range(len(words)):
        if w in deleted or not linked(w) or not final(w) or not initial(w + 1):
            continue
        start = _unstressed_final_vowel_start(words[w])
        if start is not None:
            del words[w][start:]
            if not any(p.nucleus for p in words[w]):
                attach[w] = (w + 1, "before")
    phones = [p for word in words for p in word]
    groups = _r0(phones)
    attachments = []
    for w, (host, side) in sorted(attach.items()):
        seen = {w}
        while host in attach and host not in seen:
            seen.add(host); host = attach[host][0]
        matches = [i for i, g in enumerate(groups) if phones[g[0]].word == host]
        if not matches:
            raise ValueError("CAT vowel loss has no neighbouring syllable host")
        nucleus = matches[0] if side == "before" else matches[-1]
        attachments.append(Attachment(w, host, nucleus, "".join(p.text for p in words[w]), side))
    result = _result(groups, phones, tokens, prons, sources, attachments=attachments)
    members = [set(m) for m in result.members]
    for a in attachments:
        members[a.nucleus].add(a.word)
    # Full syllables need no consonant-boundary choice when each host has one
    # nucleus. This covers the passage's que/el and cada/u illustrations.
    owners = {a.word: a.host for a in attachments}
    single = all(result.hosts.count(h) == 1 for h in result.hosts)
    assigned = all(owners.get(p.word, p.word) in result.hosts for p in phones)
    segmentation = None
    if single and assigned:
        segmentation = tuple("".join(p.text for p in phones if owners.get(p.word, p.word) == h) for h in result.hosts)
    return replace(result, members=tuple(tuple(sorted(m)) for m in members), segmentation=segmentation,
                   resource_provenance={'resource': LEXICON_PROVENANCE['cat_function_words.tsv'],
                                        'i_attachment': i_attachment,
                                        'function_word_matching': 'NFC-lowercase-spelling',
                                        'homograph_policy': 'function-word reading for every matching spelling',
                                        'function_words_unstressed': sorted(set(function_words))})

def align_italian_pairs(reference, pronunciation, pairs):
    """Locate protected vowels in every minimum-edit phone alignment.

    Consonants anchor the mapping when a main-G2P vowel is missing. Compare
    base phones (e/ɛ and o/ɔ neutralized); keep tied phones as one unit and
    protect only uniquely aligned, adjacent nuclei with matching vowel bases.
    Never synthesize a missing vowel or guess between equal-cost alignments.
    """
    def units(ipa):
        phones = _phones(ipa.strip('/[]'))
        nuclei = {g[0]: ordinal for ordinal, g in enumerate(_r0(phones))}
        out, i = [], 0
        while i < len(phones):
            p = phones[i]
            group = [p]
            if any(t in p.text for t in '͜͡'):
                group.append(phones[i + 1])
            if not p.base.isspace() and p.base != '.':
                label = ''.join(q.base.translate(str.maketrans('ɛɔ', 'eo')) for q in group)
                out.append((label, nuclei.get(i, -1)))
            i += len(group)
        return out
    ref, main = units(reference), units(pronunciation)
    needed = {n for pair in pairs for n in pair}
    @lru_cache(None)
    def visit(a, b):
        if a == len(ref):
            return len(main) - b, ((),)
        if b == len(main):
            return len(ref) - a, (tuple((n, -1) for _, n in ref[a:] if n in needed),)
        choices = []
        cost, maps = visit(a + 1, b)
        head = ((ref[a][1], -1),) if ref[a][1] in needed else ()
        choices.append((cost + 1, tuple(head + tail for tail in maps)))
        cost, maps = visit(a, b + 1)
        choices.append((cost + 1, maps))
        cost, maps = visit(a + 1, b + 1)
        equal = ref[a][0] == main[b][0]
        head = ((ref[a][1], main[b][1] if equal else -1),) if ref[a][1] in needed else ()
        choices.append((cost + int(not equal), tuple(head + tail for tail in maps)))
        best = min(c for c, _ in choices)
        projections = set(m for c, maps in choices if c == best for m in maps)
        return best, tuple(sorted(projections)[:2])
    _, matches = visit(0, 0)
    if len(matches) != 1:
        return (), 'ambiguous-phone-alignment'
    mapping = dict(matches[0])
    if any(mapping[n] < 0 for n in needed):
        return (), 'missing-or-different-protected-vowel'
    aligned = tuple((mapping[a], mapping[b]) for a, b in pairs)
    if any(b != a + 1 for a, b in aligned):
        return (), 'protected-nuclei-not-adjacent'
    return aligned, 'aligned'


@lru_cache(maxsize=8192)
def italian_exception_pairs(word, pronunciation):
    """Intersect aligned evidence; negative readings veto protection as before."""
    evidence = ITA_EVIDENCE.get(unicodedata.normalize('NFC', word).lower(), ())
    if not evidence or not all(pairs for _, pairs in evidence):
        return (), 'no-unanimous-exception'
    aligned = [align_italian_pairs(ipa, pronunciation, pairs) for ipa, pairs in evidence]
    failed = next((status for _, status in aligned if status != 'aligned'), None)
    if failed:
        return (), failed
    return tuple(sorted(set.intersection(*(set(ps) for ps, _ in aligned)))), 'aligned'


def _italian(text, option, pronunciations=None, exceptions=None):
    tokens, prons, sources = _input(text, "ITA", pronunciations)
    phones = [p for w, pron in enumerate(prons) for p in _phones(pron, w)]
    groups = _r0(phones); blocked, forbidden = set(), set()
    unaligned = {}
    default_resource = exceptions is None
    exceptions = ITA_HIATUS if default_resource else exceptions
    for w, t in enumerate(tokens):
        local = [g for g in groups if phones[g[0]].word == w]
        if default_resource:
            pairs, status = italian_exception_pairs(t.word, prons[w])
            if status not in {'aligned', 'no-unanimous-exception'}:
                unaligned[t.word.lower()] = status
        else:
            pairs = exceptions.get(t.word.lower(), ())
        for a, b in pairs:
            if b >= len(local) or a < 0 or b != a + 1:
                raise ValueError("Italian exception must name adjacent nucleus ordinals")
            blocked.update(local[a] + local[b])
        last = next((i for i in range(len(phones) - 1, -1, -1) if phones[i].word == w), None)
        if (option == "C" or t.phrase_end) and len(local) >= 2 and local[-1][-1] == last:
            if _adjacent(local[-2], local[-1], phones, tokens, False):
                policy = _setting("italian_terminal")
                if policy == "protect_terminal_nuclei":
                    blocked.update(local[-2] + local[-1])
                elif policy == "protect_all_terminal_run":
                    blocked.update(local[-1])
                    for a, b in reversed(list(zip(local, local[1:]))):
                        if not _adjacent(a, b, phones, tokens, False):
                            break
                        blocked.update(a)
                else:
                    forbidden.add((local[-2][-1], local[-1][0]))
    result = _result(_pair(groups, phones, tokens, option == "B", blocked, forbidden), phones, tokens, prons, sources)
    provenance = {"resource": LEXICON_PROVENANCE["ita_hiatus.tsv"] if default_resource else "caller-supplied",
                  "variable_default": "intersection-protected-pairs",
                  "alignment": "unique-minimum-edit-phone-alignment-e-o-neutralized",
                  "unaligned_words": unaligned,
                  "variable_words": sorted({t.word.lower() for t in tokens if default_resource and t.word.lower() in ITA_VARIABLE})}
    return replace(result, resource_provenance=provenance)

def ita_a(text, pronunciations=None, exceptions=None):
    return _italian(text, "A", pronunciations, exceptions)

def ita_b(text, pronunciations=None, exceptions=None):
    return _italian(text, "B", pronunciations, exceptions)

def ita_c(text, pronunciations=None, exceptions=None):
    return _italian(text, "C", pronunciations, exceptions)

def deu_a(text, pronunciations=None):
    return _ipa(text, "DEU", pronunciations=pronunciations)

def _english(text, option, pronunciations=None):
    tokens = tokenize(text)
    if pronunciations is None:
        pairs = [english_word(t.word) for t in tokens]
        prons, sources = tuple(p[0] for p in pairs), tuple(p[1] for p in pairs)
    else:
        tokens, prons, sources = _input(text, "ENG", pronunciations)
    nuclei, hosts, phones, groups = [], [], [], []
    for w, pron in enumerate(prons):
        pron = pron.split() if isinstance(pron, str) else pron
        start = len(phones)
        phones.extend(_Phone(p, p.rstrip("012"), w) for p in pron)
        i = 0
        while i < len(pron):
            p = pron[i]
            if re.fullmatch(r"[A-Z]+[012]", p):
                g = [start + i]
                group = p
                if option == "B" and p[:-1] in {"AY", "AW", "EY", "OW", "OY"} and i + 1 < len(pron) and pron[i + 1] in {"ER0", "AH0"}:
                    group += " " + pron[i + 1]; g.append(start + i + 1); i += 1
                nuclei.append(group); hosts.append(w)
                groups.append(tuple(g))
            i += 1
    return Count(len(nuclei), None, tuple(nuclei), tuple(hosts), tuple((w,) for w in hosts), tokens, prons, sources,
                 phone_texts=tuple(p.text for p in phones), phone_words=tuple(p.word for p in phones),
                 phone_stress=("",) * len(phones), group_indices=tuple(groups))

def eng_a(text, pronunciations=None):
    return _english(text, "A", pronunciations)

def eng_b(text, pronunciations=None):
    return _english(text, "B", pronunciations)

# Share one immutable Lexique table across independently loaded counter modules.
_french_name = 'frozen_french_helpers'
_french_module = sys.modules.get(_french_name)
if _french_module is None:
    _french_spec = importlib.util.spec_from_file_location(_french_name, Path(__file__).with_name('french_lexicon.py'))
    _french_module = importlib.util.module_from_spec(_french_spec)
    sys.modules[_french_name] = _french_module
    _french_spec.loader.exec_module(_french_module)
LEXIQUE_IPA = _french_module.LEXIQUE_IPA
decode_lexique = _french_module.decode_lexique
FRA_LEXICON, FRA_ENTRIES, _fra_provenance = _french_module.frozen()
LEXICON_PROVENANCE['fra_lexique.tsv'] = _fra_provenance

def _french(text, option, lexicon=None, pronunciations=None, nonstandard_3="retain-as-schwa"):
    """Frozen max-frequency Lexique defaults; B drops only elidable °.

    Preserve 25_SyllPhono only when deleting ° leaves nonempty one-nucleus
    syllables that concatenate to the retained pronunciation; no new cuts.
    """
    default_resource = lexicon is None
    lexicon = FRA_LEXICON if default_resource else lexicon
    if nonstandard_3 not in {"retain-as-schwa", "literal-IPA-column"}:
        raise ValueError("Unknown nonstandard Lexique 3 policy")
    retain_3 = nonstandard_3 == "retain-as-schwa"
    tokens = tokenize(text); prons, sources, phones, segments = [], [], [], []
    complete = True
    word_segments = []
    for w, t in enumerate(tokens):
        entry = lexicon.get(t.word.lower())
        retained_segments = None
        if entry is not None:
            if isinstance(entry, str):
                form, syll = entry, None
            else:
                form, syll = entry["phon"], entry.get("syll")
            raw = form.replace("°", "") if option == "B" else form
            ipa = decode_lexique(raw.replace(".", "").replace("-", ""), legacy=retain_3)
            sources.append("lexique"); prons.append(form)
            # Use syll only when it segments exactly the retained form, including
            # B forms whose final ° has already been omitted by Lexique.
            supplied = re.split(r"[.-]", syll.replace("°", "") if option == "B" else syll) if syll else []
            if supplied and "".join(supplied) == raw.replace(".", "").replace("-", ""):
                if len(supplied) == len(_r0(_phones(ipa))) and all(
                        len(_r0(_phones(decode_lexique(part, legacy=retain_3)))) == 1 for part in supplied):
                    segments.extend(supplied)
                    retained_segments = tuple(supplied)
                else:
                    complete = False
            else:
                complete = False
        else:
            ipa = pronunciations[t.word] if pronunciations is not None else espeak(t.word, "fr")
            sources.append("espeak-fallback"); prons.append(ipa); complete = False
        phones.extend(_phones(ipa, w))
        # Keep valid local Lexique cuts even if another word needs resyllabification.
        word_segments.append(retained_segments)
    result = _result(_r0(phones), phones, tokens, tuple(prons), tuple(sources), tuple(segments) if complete else None)
    return replace(result, resource_provenance={
        'resource': LEXICON_PROVENANCE['fra_lexique.tsv'] if default_resource else 'caller-supplied',
        'selection_policy': _french_module.TIE_RULE if default_resource else 'caller-supplied',
        'schwa_policy': 'B deletes only °; A keeps all vowels; 2 retained',
        'nonstandard_3_policy': nonstandard_3,
        'word_segments': word_segments,
        'nonstandard_3_words': [t.word for t, p, source in zip(tokens, prons, sources) if source == 'lexique' and '3' in p]})

def fra_a(text, lexicon=None, pronunciations=None, nonstandard_3="retain-as-schwa"):
    return _french(text, "A", lexicon, pronunciations, nonstandard_3)

def fra_b(text, lexicon=None, pronunciations=None, nonstandard_3="retain-as-schwa"):
    return _french(text, "B", lexicon, pronunciations, nonstandard_3)

# The vowelless prepositions s and k have no nucleus of their own; they are spoken
# with the next word (s njim), so they attach to the first syllable of the following
# word in the line, or at line or phrase end to the last syllable of the preceding
# word. Count unchanged. A declared fallback for the convention (Brett, 2026-10-15).
SRP_PROCLITICS = frozenset({"s", "k"})
SRP_PROCLITIC_POLICY = {"words": sorted(SRP_PROCLITICS), "matching": "NFC-lowercase whole token",
                        "host": "first syllable of the following word unless a phrase ends; "
                                "otherwise the last syllable of the preceding word"}

def srp_a(text, pronunciations=None):
    result = _ipa(text, "SRP", pronunciations=pronunciations)
    voiced = set(result.hosts)
    members = [set(m) for m in result.members]
    attachments = []
    for w, token in enumerate(result.tokens):
        if unicodedata.normalize("NFC", token.word).lower() not in SRP_PROCLITICS or w in voiced:
            continue
        following = [s for s, h in enumerate(result.hosts) if h > w]
        preceding = [s for s, h in enumerate(result.hosts) if h < w]
        if following and not token.phrase_end:
            nucleus, side = following[0], "before"
        elif preceding:
            nucleus, side = preceding[-1], "after"
        else:
            continue  # a line of proclitics alone has no host and stays unattached
        segments = "".join(t for t, owner in zip(result.phone_texts, result.phone_words) if owner == w)
        attachments.append(Attachment(w, result.hosts[nucleus], nucleus, segments, side))
        members[nucleus].add(w)
    return replace(result, attachments=tuple(attachments), members=tuple(tuple(sorted(m)) for m in members),
                   resource_provenance={"proclitic_attachment": SRP_PROCLITIC_POLICY})

def tur_a(text, pronunciations=None):
    return _ipa(text, "TUR", pronunciations=pronunciations)

def tur_b(text, pronunciations=None):
    """Delete non-front intervocalic ɰ and fuse identical flanking vowels."""
    tokens, prons, sources = _input(text, "TUR", pronunciations)
    phones = []
    for w, pron in enumerate(prons):
        word = _phones(pron, w); out, i = [], 0
        while i < len(word):
            p = word[i]
            if p.base == "ɰ" and out and i + 1 < len(word) and out[-1].vowel and word[i + 1].vowel:
                left, right = out[-1], word[i + 1]
                if left.base not in set("ieɛyœøɪʏæ") or right.base not in set("ieɛyœøɪʏæ"):
                    if left.base == right.base:
                        # The surviving vowel inherits the removed vowel's
                        # outgoing tie; it still binds the following phone.
                        tie = ''.join(t for t in right.text if t in '͜͡')
                        left.text = left.text.rstrip(":ːˑ͜͡") + "ː" + tie
                        left.stressed = left.stressed or right.stressed
                        left.stress = 'ˈ' if 'ˈ' in (left.stress, right.stress) else left.stress or right.stress
                        i += 2
                    else:
                        i += 1
                    continue
            out.append(p); i += 1
        phones.extend(out)
    return _result(_r0(phones), phones, tokens, prons, sources)

def _finnish_word_code(word, option):
    word = unicodedata.normalize("NFC", word.lower())
    if option == "C" and word in {"pian", "tae", "teos"}:
        return (word,), ("".join(c for c in word if c in FIN_VOWELS),)
    nuclei, i = [], 0
    while i < len(word):
        if word[i] not in FIN_VOWELS:
            i += 1; continue
        end = i + 1
        pair = word[i:i + 2]
        if len(pair) == 2 and pair[1] in FIN_VOWELS:
            join = pair[0] == pair[1] or pair in FIN_DIPHTHONGS
            if option in ("B", "D") and nuclei and pair in {"eu", "ou"}:
                join = False
            if option in ("Cprime", "D") and pair in FIN_EXTRA:
                join = True
            if join:
                end += 1
        nuclei.append((i, end)); i = end
    if not nuclei:
        return (), ()
    # Between vowel groups, put the last consonant with the following vowel.
    cuts = [0] + [b[0] if b[0] == a[1] else b[0] - 1 for a, b in zip(nuclei, nuclei[1:])] + [len(word)]
    return tuple(word[a:b] for a, b in zip(cuts, cuts[1:])), tuple(word[a:b] for a, b in nuclei)

def _finnish_word(word, option):
    word = unicodedata.normalize("NFC", word.lower())
    # Public C′ and the helper's internal Cprime denote the same rule.
    option = "Cprime" if option == "C′" else option
    if _setting("identical_vowels") != "all_identical_first":
        return _finnish_word_code(word, option)
    starts = [i for i, c in enumerate(word)
              if not (i and c in FIN_VOWELS and c == word[i - 1])]
    if len(starts) == len(word):
        return _finnish_word_code(word, option)
    collapsed = "".join(word[i] for i in starts)
    # FIN-C's three exact-form exceptions apply to the source spelling, never
    # to a spelling accidentally created by collapsing a run (e.g. taae→tae).
    selected_option = "A" if option == "C" and word not in {"pian", "tae", "teos"} else option
    syllables, nuclei = _finnish_word_code(collapsed, selected_option)
    edges = starts + [len(word)]
    segments, restored, cursor = [], [], 0
    for syllable in syllables:
        end = cursor + len(syllable)
        segments.append(word[edges[cursor]:edges[end]])
        cursor = end
    cursor = 0
    for nucleus in nuclei:
        start = collapsed.index(nucleus, cursor)
        cursor = start + len(nucleus)
        restored.append(word[edges[start]:edges[cursor]])
    return tuple(segments), tuple(restored)

def _finnish(text, option, pronunciations=None):
    tokens, prons, sources = _input(text, "FIN", pronunciations)
    segments, nuclei, hosts = [], [], []
    for w, t in enumerate(tokens):
        syll, vowel = _finnish_word(t.word, option)
        segments.extend(syll); nuclei.extend(vowel); hosts.extend([w] * len(syll))
    return Count(len(segments), tuple(segments), tuple(nuclei), tuple(hosts), tuple((w,) for w in hosts), tokens, prons, sources)

def fin_a(text, pronunciations=None):
    return _finnish(text, "A", pronunciations)

def fin_b(text, pronunciations=None):
    return _finnish(text, "B", pronunciations)

def fin_c(text, pronunciations=None):
    return _finnish(text, "C", pronunciations)

def fin_cprime(text, pronunciations=None):
    return _finnish(text, "Cprime", pronunciations)

def fin_d(text, pronunciations=None):
    return _finnish(text, "D", pronunciations)

def hun_a(text, pronunciations=None):
    return _ipa(text, "HUN", pronunciations=pronunciations)

def _basque(text, option, pronunciations=None):
    tokens, prons, sources = _input(text, "EUS", pronunciations)
    phones = [p for w, pron in enumerate(prons) for p in _phones(pron, w)]
    # The explicit Basque rule decides vowel grouping, not espeak's tie bars.
    if option != "B" or _setting("basque_r0") == "code":
        for p in phones:
            if p.vowel:
                p.text = p.text.replace("\u0361", "").replace("\u035c", "").replace("\u032f", "")
    high = set("iuɪʊ")
    if option != "B":
        glide = []
        for i in range(1, len(phones) - 1):
            a, b, c = phones[i - 1:i + 2]
            if a.word == b.word == c.word and a.vowel and b.base in high and c.vowel:
                glide.append(i)
        for i in glide:
            p = phones[i]; p.text = p.base = "j" if p.base in "iɪ" else "w"
    groups = _r0(phones)
    if option == "B":
        groups = _pair(groups, phones, tokens)
    else:
        out, i = [], 0
        while i < len(groups):
            a = groups[i]
            if i + 1 < len(groups):
                b = groups[i + 1]; left, right = phones[a[-1]].base, phones[b[0]].base
                merge = (left not in high and right in high) or (option == "C" and left == "u" and right == "i")
                if merge and _adjacent(a, b, phones, tokens, False):
                    out.append(a + b); i += 2; continue
            out.append(a); i += 1
        groups = out
    return _result(groups, phones, tokens, prons, sources)

def eus_a(text, pronunciations=None):
    return _basque(text, "A", pronunciations)

def eus_b(text, pronunciations=None):
    return _basque(text, "B", pronunciations)

def eus_c(text, pronunciations=None):
    return _basque(text, "C", pronunciations)

def _orthographic(tokens, units, prons, source):
    segments = tuple(s for word in units for s in word)
    hosts = tuple(w for w, word in enumerate(units) for s in word)
    return Count(len(segments), segments, segments, hosts, tuple((w,) for w in hosts), tokens, tuple(prons), (source,) * len(tokens))

def kor_a(text, pronunciations=None):
    """Count composed Hangul blocks after g2pk2; supplied output supports offline tests."""
    tokens = tokenize(text)
    if pronunciations is None:
        if not g2pk2_available():
            raise RuntimeError("KOR-A requires g2pk2, which is not importable")
        with _offline_nltk():
            prons = tuple(_korean()(t.word) for t in tokens)
    else:
        tokens, prons, _ = _input(text, "KOR", pronunciations)
    units = [tuple(c for c in unicodedata.normalize("NFC", pron) if "가" <= c <= "힣") for pron in prons]
    return _orthographic(tokens, units, prons, "g2pk2" if pronunciations is None else "supplied")

def _han(c):
    return HAN.fullmatch(c) is not None

@lru_cache(maxsize=16)
def _erhua_trie(entries):
    trie = {}
    for word, positions in entries:
        node = trie
        for char in word:
            node = node.setdefault(char, {})
        node[None] = (word, positions)
    return trie

def cmn_a(text, erhua_words=None, word_tokens=None):
    """Count Han, joining positional 儿/兒 by longest match within Han runs.

    None loads frozen Wiktionary defaults; a mapping supplies zero-based
    positions and uses longest match too. Legacy sequences of terminal-suffix
    words retain exact-token behavior, including an explicit empty sequence.
    No match bridges non-Han characters or tokenizer/supplied word boundaries.
    """
    text = unicodedata.normalize("NFC", text)
    tokens = tokenize(text)
    if word_tokens is not None:
        supplied = tuple(unicodedata.normalize("NFC", w) for w in word_tokens)
        out, i = [], 0
        for original in tokens:
            offset = 0
            while offset < len(original.word):
                if i >= len(supplied) or not supplied[i] or not original.word.startswith(supplied[i], offset):
                    raise ValueError("Mandarin word tokens must preserve source characters and separators")
                word = supplied[i]; offset += len(word); i += 1
                out.append(Token(word, offset == len(original.word) and original.phrase_end))
        if i != len(supplied):
            raise ValueError("Mandarin word tokens must preserve source characters and separators")
        tokens = tuple(out)
    default_resource = erhua_words is None
    mapping = CMN_ERHUA if default_resource else erhua_words
    positional = hasattr(mapping, "items")
    entries = {}
    if default_resource:
        trie = _erhua_trie(CMN_ERHUA_ENTRIES)
    elif positional:
        for word, positions in mapping.items():
            word = unicodedata.normalize("NFC", word).replace("兒", "儿")
            positions = tuple(sorted(set(positions)))
            if (not word or not all(_han(c) for c in word)
                    or any(not isinstance(i, int) or isinstance(i, bool) or not 0 < i < len(word)
                           or word[i] != "儿" or i - 1 in positions for i in positions)):
                raise ValueError("Positional erhua entries must name suffixal 儿/兒 after a host character")
            entries.setdefault(word, set()).update(positions)
        trie = _erhua_trie(tuple(sorted((w, tuple(sorted(ps))) for w, ps in entries.items())))
    else:
        entries = {unicodedata.normalize("NFC", w) for w in mapping}
        if any(len(w) < 2 or not w.endswith("儿") or not all(_han(c) for c in w) for w in entries):
            raise ValueError("Erhua entries must be exact Han words ending in suffixal 儿")
    units = []
    variable_matches = set()
    for t in tokens:
        merged, suppressed = [], set()
        if positional:
            start = 0
            normalized = t.word.replace("兒", "儿")
            while start < len(normalized):
                node, stop, match = trie, start, None
                while stop < len(normalized) and _han(normalized[stop]) and normalized[stop] in node:
                    node = node[normalized[stop]]; stop += 1
                    if None in node:
                        match = (stop, node[None])
                if match:
                    stop, (word, positions) = match
                    suppressed.update(start + i for i in positions)
                    if default_resource and word in CMN_VARIABLE:
                        variable_matches.add(word)
                    start = stop
                else:
                    start += 1
        elif t.word in entries:
            suppressed.add(len(t.word) - 1)
        for i, char in enumerate(t.word):
            if _han(char):
                if i in suppressed:
                    merged[-1] += char
                else:
                    merged.append(char)
        units.append(tuple(merged))
    result = _orthographic(tokens, units, [t.word for t in tokens], "characters")
    provenance = {"resource": LEXICON_PROVENANCE["cmn_erhua.tsv"] if default_resource else "caller-supplied",
                  "variable_default": "erhua", "variable_words": sorted(variable_matches),
                  "lookup": "longest-match-Han-runs" if positional else "legacy-exact-token"}
    return replace(result, resource_provenance=provenance)

def yue_a(text):
    tokens = tokenize(text)
    return _orthographic(tokens, [tuple(c for c in t.word if _han(c)) for t in tokens], [t.word for t in tokens], "characters")

def normalize_vietnamese(word):
    """Reposition a single tone mark within the written vowel sequence; NFC output."""
    word = "".join(c for c in word if not unicodedata.category(c).startswith("P"))
    tones = set("\u0300\u0301\u0309\u0303\u0323")
    tone = [c for c in unicodedata.normalize("NFD", word) if c in tones]
    if not tone:
        return unicodedata.normalize("NFC", word)
    if len(tone) != 1:
        raise ValueError("A written Vietnamese syllable must have at most one tone mark")
    plain = unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", word) if c not in tones))
    vowels = [i for i, c in enumerate(plain) if unicodedata.normalize("NFD", c.lower())[0] in "aeiouy"]
    if len(vowels) > 1 and plain.lower().startswith(("qu", "gi")):
        vowels = [i for i in vowels if i != 1]
    special = [i for i in vowels if plain[i].lower() in "êơ"]
    if not vowels:
        return word
    if special:
        pos = special[-1]
    elif len(vowels) == 3:
        pos = vowels[1]
    elif len(vowels) == 2:
        pos = vowels[-1] if vowels[-1] < len(plain) - 1 else vowels[0]
    else:
        pos = vowels[0]
    return unicodedata.normalize("NFC", plain[:pos + 1] + tone[0] + plain[pos + 1:])

def vie_a(text):
    tokens = tokenize(text)
    units = [tuple([normalize_vietnamese(t.word)]) if any(c.isalpha() for c in t.word) else () for t in tokens]
    return _orthographic(tokens, units, [t.word for t in tokens], "written-syllables")

COUNTERS = {
    "SPA": {"A": spa_a, "B": spa_b}, "CAT": {"A": cat_a, "B": cat_b},
    "ITA": {"A": ita_a, "B": ita_b, "C": ita_c}, "DEU": {"A": deu_a},
    "ENG": {"A": eng_a, "B": eng_b}, "FRA": {"A": fra_a, "B": fra_b},
    "SRP": {"A": srp_a}, "TUR": {"A": tur_a, "B": tur_b},
    "FIN": {"A": fin_a, "B": fin_b, "C": fin_c, "C′": fin_cprime, "D": fin_d},
    "HUN": {"A": hun_a}, "EUS": {"A": eus_a, "B": eus_b, "C": eus_c},
    "KOR": {"A": kor_a}, "CMN": {"A": cmn_a}, "YUE": {"A": yue_a}, "VIE": {"A": vie_a},
}

# T8 native counters own their adapters and grouping rules in separate modules.
for _lang, _file in (("JPN", "japanese.py"), ("THA", "thai.py")):
    _spec = importlib.util.spec_from_file_location("stage3_" + _file[:-3], Path(__file__).with_name(_file))
    _module = sys.modules.get(_spec.name)
    if _module is None:
        _module = importlib.util.module_from_spec(_spec); sys.modules[_spec.name] = _module
        _spec.loader.exec_module(_module)
    COUNTERS[_lang] = _module.register(sys.modules[__name__])

def _configuration_value(value):
    """Canonicalize accepted option containers without exposing their contents."""
    if hasattr(value, 'items'):
        return {key: _configuration_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [_configuration_value(item) for item in value]
        return {'set': sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))}
    if isinstance(value, (list, tuple)):
        return [_configuration_value(item) for item in value]
    return value

def _native_configuration(counter, arguments):
    result = {}
    for name, parameter in inspect.signature(counter).parameters.items():
        if name in {'text', 'ipa', 'pronunciations', 'pronunciation_sources'}:
            continue
        value = arguments.get(name, parameter.default)
        if value is None or isinstance(value, (str, int, float, bool)):
            result[name] = value
        else:
            encoded = json.dumps(_configuration_value(value), ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':'), allow_nan=False)
            result[name] = {'sha256': hashlib.sha256(encoded.encode()).hexdigest()}
    return result

def counter_configuration(language, option, options=None):
    """Resolve all fork/native defaults without counting text or exposing lists."""
    options = dict(options or {})
    forks = {name: options.pop(name) for name in _FORK_BY_SETTING if name in options}
    chain = options.pop('chained_ties', None)
    counter = COUNTERS[language][option]
    unknown = set(options) - set(inspect.signature(counter).parameters)
    if unknown or 'text' in options or 'pronunciations' in options:
        raise ValueError('Unknown onset counter configuration')
    with counter_settings(chained_ties=chain, **forks):
        for name in (_FORK_SETTINGS.get() or {}):
            if (language, option) not in _FORK_BY_SETTING[name]['options']:
                raise ValueError('Counter fork does not apply to this language/option')
        return {'counter_settings': _resolved_settings(),
                'counter_options': _native_configuration(counter, options)}

def default_counter_configuration(language, option):
    """Declared defaults, independent of any enclosing counter_settings scope."""
    return {'counter_settings': {
                'chained_ties': DEFAULT_CHAINED_TIES,
                **{name: fork['values'][0] for name, fork in _FORK_BY_SETTING.items()}},
            'counter_options': _native_configuration(COUNTERS[language][option], {})}

def _with_settings(counter, language_option=None):
    @wraps(counter)
    def configured(*args, chained_ties=None, **kwargs):
        forks = {name: kwargs.pop(name) for name in _FORK_BY_SETTING if name in kwargs}
        with counter_settings(chained_ties=chained_ties, **forks):
            # Generic R0/pairing helpers inherit language settings, but cannot
            # explicitly select a language fork themselves.
            selected = (_FORK_SETTINGS.get() or {}) if language_option is not None else forks
            for name in selected:
                if language_option not in _FORK_BY_SETTING[name]["options"]:
                    raise ValueError(f"Counter fork {name} does not apply to {language_option}")
            native = _native_configuration(counter, inspect.signature(counter).bind(*args, **kwargs).arguments)
            return replace(counter(*args, **kwargs), chained_ties=_CHAINED_TIES.get(),
                           counter_settings=_resolved_settings(), counter_options=native)
    return configured

for _language, _options in COUNTERS.items():
    for _option, _counter in _options.items():
        _options[_option] = globals()[_counter.__name__] = _with_settings(_counter, (_language, _option))
for _name in ("r0", "pairing", "cross_word_pairing"):
    globals()[_name] = _with_settings(globals()[_name])

def main():
    """Print counts and trace on a command-line example, without reading input files."""
    import argparse, json
    from dataclasses import asdict
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("language", choices=COUNTERS)
    p.add_argument("option", help="A/B/C/Cprime/D as listed for the language")
    p.add_argument("text", help="An invented example; use the Python API for supplied pronunciations/lexicons")
    p.add_argument("--chained-ties", choices=CHAINED_TIES, default=DEFAULT_CHAINED_TIES)
    for fork in FORKS.values():
        p.add_argument("--" + fork["setting"].replace("_", "-"), choices=fork["values"], default=None)
    args = p.parse_args()
    option = "C′" if args.option in ("Cprime", "C'") else args.option
    if option not in COUNTERS[args.language]:
        p.error(f"{args.language} options: {', '.join(COUNTERS[args.language])}")
    settings = {name: getattr(args, name) for name in _FORK_BY_SETTING if getattr(args, name) is not None}
    result = COUNTERS[args.language][option](args.text, chained_ties=args.chained_ties, **settings)
    print(json.dumps(dict(asdict(result), fallback_share=result.fallback_share,
                          switched_word_count=result.switched_word_count), ensure_ascii=False))

if __name__ == "__main__":
    main()
