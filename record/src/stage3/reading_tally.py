"""Offline count-reading diagnostics, using only an explicitly supplied UTF-8 file.

python -I -B src/stage3/reading_tally.py SPA sample.txt --output results/tally
Optional: --rows 3,16 --cache results/pronunciations.json

One process, one transcription per NFC type and versioned adapter. No persistent
cache is required: without --cache the same per-type reuse happens in memory.
The five declared counter forks use production settings; other comparisons
remain diagnostics of proposals.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import csv
import hashlib
import importlib.util
import importlib.metadata
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata as U
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


E = load("tally_examples", ROOT / "src/stage3/reading_examples.py")
C = E.C
P = load("tally_pipeline", ROOT / "src/stage4/pipeline.py")
P.C = C
IPA = (set(C.VOICES) | set(C.EPITRAN)) - {"FIN"}  # FIN counts spelling, not its IPA trace.
PAIR = {"SPA": ("B",), "ITA": ("A", "B", "C"), "EUS": ("B",)}
ALL = {lang: tuple(options) for lang, options in C.COUNTERS.items()}
CODE_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Cache:
    """A checksummed JSON cache, namespaced by language/tool/version/voice/settings.

    Failures are remembered for this run but never persisted. --cache reads only
    that cache; it never searches for prior files or other inputs.
    """
    def __init__(self, language, path=None, backend=None):
        self.language, self.path = language, Path(path) if path else None
        self.backend = backend
        self.records, self.failures, self.adapters, self.signatures = {}, {}, {}, {}
        self.memory = {}
        self.transcriptions = 0
        if self.path and self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if saved.get("schema") != "reading-tally-cache-v1":
                raise ValueError("Unsupported pronunciation cache schema")
            self.records = saved["records"]
            if saved.get("sha256") != hashlib.sha256(canon(self.records).encode()).hexdigest():
                raise ValueError("Pronunciation cache checksum mismatch")

    def adapter(self, route):
        if route in self.adapters:
            return self.adapters[route]
        lang = self.language
        if self.backend is not None:
            if route != "main":
                raise RuntimeError("Injected backend has no contrasting G2P route")
            backend = self.backend
        elif lang in {'JPN', 'THA'}:
            native = sys.modules['stage3_japanese' if lang == 'JPN' else 'stage3_thai']
            tool = ('pyopenjtalk' if route == 'second' else 'fugashi') if lang == 'JPN' else ('thaig2p' if route == 'second' else 'tltk')
            desc = native.route_descriptor(tool)
            def transcribe(word):
                if lang == 'JPN':
                    pairs = native.resolved_chunk(word, tool)
                    return {'pronunciation': [p for _, p, _ in pairs], 'tokens': [w for w, _, _ in pairs],
                            'word_sources': [s for _, _, s in pairs], 'source': tool, 'languages': []}
                pronunciation, source = native.resolved_word(word, tool)
                return {'pronunciation': list(pronunciation), 'source': source, 'languages': []}
            backend = P.G2P(tool, canon(desc['version']), desc['voice'], desc, transcribe)
        elif lang in {"CMN", "YUE"}:
            backend = P.G2P("orthography", U.unidata_version, lang,
                            {"normalization": "NFC", "Han": "regex-Script=Han"},
                            lambda word: {"pronunciation": word, "source": "characters", "languages": []})
        else:
            backend = P.main_g2p(lang)
        settings = dict(backend.settings, tally_code=CODE_HASH, route=route)
        transcribe = backend.transcribe
        if self.backend is None and lang in C.VOICES and lang != "FRA":
            voice = C.VOICES[lang]
            def transcribe(word):
                raw = subprocess.run([C.ESPEAK, "-q", "--ipa=3", "-v", voice, "--", word],
                                     capture_output=True, text=True, check=True).stdout.strip()
                labels = [x.replace("\u200d", "") for x in C.ESPEAK_LABEL.findall(raw)]
                clean = C.ESPEAK_LABEL.sub("", raw).replace("\u200d", "\u0361")
                return {"pronunciation": clean, "source": "espeak", "languages": sorted(set(labels) - {voice}),
                        "raw": raw.replace("\u200d", "\u0361")}
        if self.backend is None and lang == 'FRA':
            lexical_transcribe = transcribe
            def transcribe(word):
                entry = C.FRA_LEXICON.get(word.lower())
                if entry is not None:
                    value = lexical_transcribe(word)
                    value['raw'] = C.decode_lexique(entry['phon'], legacy=True)
                    return value
                raw = subprocess.run([C.ESPEAK, '-q', '--ipa=3', '-v', 'fr', '--', word],
                                     capture_output=True, text=True, check=True).stdout.strip()
                labels = [x.replace('\u200d', '') for x in C.ESPEAK_LABEL.findall(raw)]
                clean = C.ESPEAK_LABEL.sub('', raw).replace('\u200d', '\u0361')
                return {'pronunciation': clean, 'source': 'espeak-fallback',
                        'languages': sorted(set(labels) - {'fr'}), 'raw': raw.replace('\u200d', '\u0361')}
        if route == "raw-case":
            transcribe = lambda word: {"pronunciation": C._epitran("tur-Latn").transliterate(word),
                                       "source": "epitran-raw-case", "languages": []}
        elif route in {"raw-predictor", "normalized-relookup"}:
            def transcribe(word):
                normalized = word.lower().replace("’", "'")
                found = C._cmu().get(normalized)
                if found:
                    phones = found[0]
                elif route == "raw-predictor":
                    phones = C._english_predictor().predict(normalized)
                else:
                    plain = "".join(c for c in U.normalize("NFKD", normalized) if not U.category(c).startswith("M"))
                    phones = C.english_word(plain)[0]
                return {"pronunciation": list(phones), "source": route, "languages": []}
        backend = P.G2P(backend.tool, backend.version, backend.voice, settings, transcribe)
        self.adapters[route] = backend
        self.signatures[route] = {"language": lang, **backend.descriptor()}
        return backend

    def get(self, word, route="main"):
        word = U.normalize("NFC", word)
        if (route, word) in self.memory:
            return self.memory[route, word]
        backend = self.adapter(route)
        key = canon({**self.signatures[route], "word": word})
        if key in self.failures:
            raise self.failures[key]
        if key not in self.records:
            try:
                value = backend.transcribe(word)
                P.validate_pronunciation({k: value[k] for k in ("pronunciation", "source", "languages")})
            except (RuntimeError, LookupError, ValueError, ImportError, OSError, subprocess.CalledProcessError) as e:
                self.failures[key] = e
                raise
            self.records[key] = json.loads(canon(value))
            self.transcriptions += 1
        value = self.records[key]
        P.validate_pronunciation({k: value[k] for k in ("pronunciation", "source", "languages")})
        self.memory[route, word] = value
        return value

    def save(self):
        if self.path:
            P.atomic(self.path, (canon({"schema": "reading-tally-cache-v1", "records": self.records,
                                      "sha256": hashlib.sha256(canon(self.records).encode()).hexdigest()}) + "\n").encode())


def table():
    """Read row identities without executing the fixed-example generator."""
    text = (ROOT / "notes-draft/counter-readings.md").read_text(encoding="utf-8")
    rows = {}
    for line in text.splitlines():
        match = re.match(r"\| (\d+)\. \*\*(.*?)\*\*", line)
        if match:
            rows[int(match[1])] = match[2]
    identity = json.dumps([(r, title) for r, title in rows.items() if r <= 53], ensure_ascii=False, separators=(",", ":"))
    if hashlib.sha256(identity.encode()).hexdigest() != "89182936f390fd0d0a2a40a0aa3f17e760e97120a071020e9788fcac03948646":
        raise ValueError("Readings table changed; update the tally's row registry")
    native = load('t8_native_tally', ROOT / 'src/stage3/native_tally.py')
    if {r: title for r, title in rows.items() if r > 53} != native.TITLES:
        raise ValueError('T8 readings table changed; update its row registry')
    return rows, hashlib.sha256(text.encode()).hexdigest()


def options(row, lang):
    """Options affected by each proposal; no new production reading is selected."""
    if lang in {'JPN', 'THA'} or row > 53:
        return ({54: {'JPN': ('G1',)}, 55: {'JPN': ('G1', 'G2')},
                 56: {'THA': ('A',)}, 57: {'THA': ('A',)}}.get(row, {}).get(lang, ()))
    if row in C.FORKS:
        return tuple(option for language, option in C.FORKS[row]['options'] if language == lang)
    if row in {1, 2, 9, 34, 38, 49}:
        return ALL[lang]
    if row in {3}:
        return {"SPA": ("B",), "ITA": ("B",)}.get(lang, ())
    if row == 4:
        return ALL[lang] if lang == "EUS" else PAIR.get(lang, ())
    if row == 6:
        return ALL[lang] if lang == "FIN" else PAIR.get(lang, ())
    if row in {7, 43, 44, 51}:
        return ALL[lang] if lang in IPA else ()
    if row == 8:
        return ALL[lang] if lang in C.VOICES else ()
    if row in {10, 11, 12, 41, 45}:
        return ("B",) if lang == "CAT" else ()
    if row in {13, 14, 40, 47, 48}:
        return ALL[lang] if lang == "FRA" else ()
    if row == 15:
        return ALL[lang] if lang == "ENG" else ()
    if row == 16:
        return ("B",) if lang == "SPA" else ()
    if row in {17, 18, 19}:
        return ALL[lang] if lang == "ITA" else ()
    if row == 20:
        return ("B", "D") if lang == "FIN" else ()
    if row in {21, 28}:
        return ("A", "C") if lang == "EUS" else ()
    if row in {22, 53}:
        return ALL[lang] if lang == "TUR" else ()
    if row in {23, 24}:
        return ("B",) if lang == "TUR" else ()
    if row == 25:
        return ("A",) if lang == "FIN" else ()
    if row == 26:
        return ("B",) if lang == "EUS" else ()
    if row == 27:
        return ("C",) if lang == "EUS" else ()
    if row in {29, 37, 46}:
        return ("A",) if lang == "VIE" else ()
    if row in {30, 31, 32, 33}:
        return ("A",) if lang == "CMN" else ()
    if row == 35:
        return ("A",) if lang in {"CMN", "YUE"} else ()
    if row == 36:
        return ("A",) if lang in {"CMN", "YUE", "KOR"} else ()
    if row == 39:
        return ("C",) if lang == "FIN" else ()
    if row == 42:
        return ("A",) if lang == "SRP" else ()
    if row == 50:
        return ALL[lang] if lang == "FIN" else ()
    if row == 52:
        return ("A",) if lang == "KOR" else ()
    return ()


SKIP = {
    18: "No alternative frozen Italian exception list or productive prefix rule.",
    25: "The alternative 20-pair inventory is unknown; C′ is a different, already named option.",
    28: "No lexical/context rule distinguishes recoverable vowels from genuine glides.",
    30: "The Wiktionary default is frozen; no competing dictionary or contextual reading policy is supplied.",
    31: "No alternative frozen Mandarin word segmenter is supplied for comparison with longest match.",
    32: "Input validation rejects the alternative; no numeric code count for bridging tokens.",
    33: "The frozen default aligns both scripts; no competing script-conversion policy is supplied.",
    38: "No frozen per-language spoken digit/letter convention; dropping tokens would not estimate it.",
    40: "No general intended-word/letter pronunciation policy; fixture overrides do not generalize.",
    41: "Passage-specific loss has no general phrase-final deletion rule.",
    **{r: "This row concerns segmentation, ownership, spelling or phones, not a defined count alternative."
       for r in range(45, 54)},
}
ALTERNATIVES = {
    54: ('G2',), 55: ('pyopenjtalk',), 56: ('thaig2p',), 57: ('attacut',),
    1: ("narrow_marks_only",), 2: ("LF_CR_only",), 3: ("word_first",),
    4: ("consonants_only_between",), 5: ("all_identical_first",), 6: ("entire_run",),
    7: ("every_tie_nuclear",), 8: ("labels_as_phones",), 9: ("strip_outer_quotes", "outer_quotes_end_phrases", "retain_curly_quotes"),
    10: ("printed_order", "que_first"), 11: ("reverse_token_traversal",),
    12: ("isolation_stress",),
    13: ("lowest_frequency_entry",), 14: ("source_IPA_column", "undecoded_legacy_symbols"),
    15: ("raw_predictor", "normalized_CMU_relookup"), 16: ("stressed_close_hiatus_kept", "non_close_pairs_only", "historical_maximal_pairing"),
    17: ("protect_edge_only", "protect_all_terminal_run", "protect_terminal_nuclei"), 19: ("exception_edge_only",), 20: ("first_vowel_run",),
    21: ("pair_first", "sequential_triples"), 22: ("Epitran_case_handling",),
    23: ("disjoint_fusion",), 24: ("full_symbol_identity",), 26: ("preserve_shared_R0",),
    27: ("include_lax_ui",), 29: ("whitespace_units",), 34: ("broader_word_hyphens",),
    35: ("ideographs_only",), 36: ("NFKC",), 37: ("every_whitespace_token",),
    39: ("case_sensitive_exact",), 42: ("isolated_syllabic_r",), 43: ("syllabic_mark_wins",),
    44: ("disjoint_pairs",),
}
PARTIAL_SKIP = {
    10: {"simultaneous_contexts": "No frozen simultaneous-context/orphan-host policy."},
    11: {"simultaneous_contexts": "No frozen simultaneous-context/orphan-host policy."},
    20: {"independent_syllabifier": "No independent Finnish syllabifier/resource was supplied."},
    23: {"morpheme_hiatus": "No morpheme parser or boundary policy was supplied."},
    43: {"reject_contradictory_marks": "Rejection has no numeric alternative count to compare."},
}


def spans(text, tokens):
    out, start = [], 0
    for t in tokens:
        at = text.index(t.word, start)
        out.append((at, at + len(t.word)))
        start = at + len(t.word)
    return out


def tokenize_variant(text, row):
    marks = C.PHRASE_END
    if row == 1:
        marks = marks - C.WIDE_PHRASE_END
    if row == 2:
        marks = marks - (C.LINE_END - set("\n\r"))
    tokens, word = [], []
    def flush():
        if word:
            value = ''.join(word)
            if row != 9:
                value = value.strip('‘’')
            if value:
                tokens.append(C.Token(value, False))
            word.clear()
    for c in text:
        if c in marks:
            flush()
            if tokens:
                tokens[-1] = C.Token(tokens[-1].word, True)
        elif c.isspace() or c in ("-‐‑－‒\u00ad" if row == 34 else "-‐‑"):
            flush()
        else:
            word.append(c)
    flush()
    if tokens:
        tokens[-1] = C.Token(tokens[-1].word, True)
    return tuple(tokens)


def pair_rule(mode):
    original = C._pair
    def run(groups, phones, tokens, cross=False, blocked=(), forbidden=()):
        if mode == "all_identical_first":
            with C.counter_settings(identical_vowels=mode):
                return original(groups, phones, tokens, cross, blocked, forbidden)
        blocked = set(blocked)
        groups = [list(g) for g in groups]
        if mode == "word_first":
            slot = {p: i for i, g in enumerate(groups) for p in g}
            local = original(groups, phones, tokens, False, blocked, forbidden)
            out, i = [], 0
            while i < len(local):
                a = local[i]
                if (i + 1 < len(local) and len({slot[p] for p in a + local[i + 1]}) <= 2
                        and not blocked.intersection(a + local[i + 1])
                        and (a[-1], local[i + 1][0]) not in forbidden
                        and C._adjacent(a, local[i + 1], phones, tokens, cross)):
                    out.append(a + local[i + 1]); i += 2
                else:
                    out.append(a); i += 1
            return out
        out = []
        for g in groups:
            if (out and mode == "entire_run" and not blocked.intersection(out[-1] + g)
                    and (out[-1][-1], g[0]) not in forbidden
                    and C._adjacent(out[-1], g, phones, tokens, cross)):
                out[-1].extend(g)
            else:
                out.append(g)
        return out if mode == "entire_run" else original(out, phones, tokens, cross, blocked, forbidden)
    return run


def italian_edge_variant(text, prons, option, row, alternative="protect_edge_only"):
    """Change just terminal protection (17) or exception protection (19)."""
    if row == 17:
        return C.COUNTERS['ITA'][option](text, prons,
                    italian_terminal='code' if alternative == 'protect_edge_only' else alternative)
    tokens, prons, sources = C._input(text, "ITA", prons)
    phones = [p for w, pron in enumerate(prons) for p in C._phones(pron, w)]
    groups, blocked, forbidden = C._r0(phones), set(), set()
    for w, token in enumerate(tokens):
        local = [g for g in groups if phones[g[0]].word == w]
        for a, b in C.italian_exception_pairs(token.word, prons[w])[0]:
            if row == 19:
                forbidden.add((local[a][-1], local[b][0]))
            else:
                blocked.update(local[a] + local[b])
        last = max((i for i, p in enumerate(phones) if p.word == w), default=-1)
        if ((option == "C" or token.phrase_end) and len(local) >= 2 and local[-1][-1] == last
                and C._adjacent(local[-2], local[-1], phones, tokens, False)):
            forbidden.add((local[-2][-1], local[-1][0]))
    out, i = [], 0
    while i < len(groups):
        a = groups[i]
        if (i + 1 < len(groups) and (a[-1], groups[i + 1][0]) not in forbidden
                and not blocked.intersection(a + groups[i + 1])
                and C._adjacent(a, groups[i + 1], phones, tokens, option == "B")):
            out.append(a + groups[i + 1]); i += 2
        else:
            out.append(a); i += 1
    return C._result(out, phones, tokens, prons, sources)


def finnish_first_run(word, option):
    word = U.normalize("NFC", word.lower())
    first = next((i for i, c in enumerate(word) if c in C.FIN_VOWELS), len(word))
    count, i = 0, 0
    while i < len(word):
        if word[i] not in C.FIN_VOWELS:
            i += 1; continue
        pair = word[i:i + 2]
        join = len(pair) == 2 and pair[1] in C.FIN_VOWELS and (
            pair[0] == pair[1] or pair in C.FIN_DIPHTHONGS or (option == "D" and pair in C.FIN_EXTRA))
        if pair in {"eu", "ou"} and any(c not in C.FIN_VOWELS for c in word[first:i]):
            join = False
        count += 1; i += 2 if join else 1
    return count


def strict_turkish(word, ipa):
    """Cumulative TUR-B fusion with full current-symbol identity, not disjoint fusion."""
    phones, out, i = C._phones(ipa), [], 0
    while i < len(phones):
        p = phones[i]
        if p.base == "ɰ" and out and i + 1 < len(phones) and out[-1].vowel and phones[i + 1].vowel:
            left, right = out[-1], phones[i + 1]
            if left.base not in set("ieɛyœøɪʏæ") or right.base not in set("ieɛyœøɪʏæ"):
                if left.text == right.text:
                    left.text = left.text.rstrip(":ːˑ") + "ː"; i += 2
                else:
                    i += 1
                continue
        out.append(p); i += 1
    return len(C._r0(out))


class Evaluation(tuple):
    """Source-token counts; a positive unattributed total adds an explicit final slot."""
    def __new__(cls, counts, unattributed=0):
        out = tuple.__new__(cls, (*counts, unattributed) if unattributed else counts)
        out._unattributed = unattributed
        return out

    @property
    def unattributed(self):
        return self._unattributed


def _evaluate(text, lang, option, cache, row=None, alternative=None):
    """Return counts owned by original shared tokens, preserving total syllables.

    A changed tokenizer assigns a merged token to its leftmost overlapping source
    token; split tokens sum back to their source token. This is explicit accounting,
    not a claim that every participating word independently lost a syllable.
    """
    text = U.normalize("NFC", text)
    original = C.tokenize(text)
    original_tokenize = C.tokenize
    original_spans = spans(text, original)
    tokens, mapping = original, list(range(len(original)))
    if row in {1, 2, 34} or row == 9 and alternative == 'retain_curly_quotes':
        variant = tokenize_variant(text, row)
        owners = [next((i for i, (x, y) in enumerate(original_spans) if a < y and b > x), None)
                  for a, b in spans(text, variant)]
        tokens, mapping = variant, owners
    if row == 9 and alternative != 'retain_curly_quotes':
        mutable = list(tokens)
        for i, t in enumerate(tokens):
            ends = alternative == "outer_quotes_end_phrases"
            stripped = t.word.strip("'‘’")
            mutable[i] = C.Token(stripped, t.phrase_end or ends and t.word[-1:] in "'‘’")
            if ends and t.word[:1] in "'‘’" and i:
                mutable[i - 1] = C.Token(mutable[i - 1].word, True)
        tokens = tuple(mutable)
    if row in {29, 37}:
        counts = [0] * len(original)
        for m in re.finditer(r"\S+", text.replace('⟂', ' ')):
            i = next((i for i, (a, b) in enumerate(original_spans) if m.start() < b and m.end() > a), None)
            if i is None:
                raise ValueError("Whitespace unit has no shared token for count attribution")
            counts[i] += 1
        return Evaluation(counts)
    route = {22: "raw-case"}.get(row, "main")
    if row == 15:
        route = "raw-predictor" if alternative == "raw_predictor" else "normalized-relookup"
    values = [cache.get(t.word, route) if t.word else {"pronunciation": "", "languages": []} for t in tokens]
    prons = [v["pronunciation"] for v in values]
    if row == 8:
        if any("raw" not in v for v in values):
            raise RuntimeError("Raw espeak control labels unavailable in this adapter")
        prons = [v["raw"] for v in values]
    if row == 27:
        prons = [p.replace("ʊ", "u").replace("ɪ", "i") for p in prons]
    counts = None
    with ExitStack() as stack:
        # Local to this single-process evaluation; never changes counter source.
        stack.enter_context(patch.object(C, "tokenize", lambda value: tokens if value == text else original_tokenize(value)))
        if row in {3, 6} and lang != "FIN":
            stack.enter_context(patch.object(C, "_pair", pair_rule(alternative)))
        if row == 4:
            def adjacent(a, b, phones, ts, cross):
                p, q = phones[a[-1]], phones[b[0]]
                return (all(p.vowel for p in phones[a[-1] + 1:b[0]]) and
                        (p.word == q.word or cross and all(not ts[w].phrase_end for w in range(p.word, q.word))))
            stack.enter_context(patch.object(C, "_adjacent", adjacent))
        if row == 7:
            old_r0 = C._r0
            def tied(phones):
                groups = old_r0(phones)
                present = {i for g in groups for i in g}
                groups += [[i, i + 1] for i, p in enumerate(phones) if "\u0361" in p.text and i not in present]
                return sorted(groups, key=lambda g: g[0])
            stack.enter_context(patch.object(C, "_r0", tied))
        if row == 8:
            def legacy_r0(phones):
                groups, i = [], 0
                while i < len(phones):
                    p = phones[i]
                    if p.nucleus:
                        group = [i]
                        if p.vowel and "\u0361" in p.text and i + 1 < len(phones) and phones[i + 1].vowel:
                            group.append(i + 1); i += 1
                        groups.append(group)
                    i += 1
                return groups
            stack.enter_context(patch.object(C, "_r0", legacy_r0))
        if row == 43:
            old_nucleus = C._Phone.nucleus
            stack.enter_context(patch.object(C._Phone, "nucleus", property(lambda p: "\u0329" in p.text or old_nucleus.fget(p))))
        if row in C.FORKS:
            fork = C.FORKS[row]
            # Historical tally labels for the approved default remain aliases.
            value = {'protect_edge_only': 'code', 'stressed_close_hiatus_kept': 'code'}.get(alternative, alternative)
            result = C.COUNTERS[lang][option](text, pronunciations=prons, **{fork['setting']: value})
        elif row in {10, 11}:
            order = ("el/es", "que", "i", "final") if alternative == "printed_order" else (
                ("que", "el/es", "i", "final") if alternative == "que_first" else ("i", "el/es", "que", "final"))
            result = E.cat_order(text, prons, order, reverse=row == 11)
        elif row == 13:
            lexicon = {t.word.lower(): dict(C._french_module.lowest_entry(C.FRA_ENTRIES[t.word.lower()]))
                       for t in tokens if t.word.lower() in C.FRA_ENTRIES}
            result = C.COUNTERS[lang][option](text, lexicon=lexicon,
                        pronunciations={t.word: p for t, p in zip(tokens, prons)})
        elif row == 14:
            contrast = {}
            for t, p in zip(tokens, prons):
                entry = C.FRA_LEXICON.get(t.word.lower())
                if entry is None:
                    contrast[t.word] = p
                else:
                    contrast[t.word] = entry['ipa'].replace('ə', '') if option == 'B' else entry['ipa']
                    if alternative == 'undecoded_legacy_symbols':
                        contrast[t.word] = entry['phon'].replace('°', '') if option == 'B' else entry['phon']
            counts = [C.r0(contrast[t.word]).count for t in tokens]
        elif row == 19:
            result = italian_edge_variant(text, prons, option, row, alternative)
        elif row == 21:
            counts = [E.basque_precedence(t.word, p, "sequential" if alternative == "sequential_triples" else "pair-first", option=option).count
                      for t, p in zip(tokens, prons)]
        elif row == 23:
            counts = [E.turkish_pair_fusion(t.word, p).count for t, p in zip(tokens, prons)]
        elif row == 24:
            counts = [strict_turkish(t.word, p) for t, p in zip(tokens, prons)]
        elif row == 20:
            counts = [finnish_first_run(t.word, option) for t in tokens]
        elif row == 6 and lang == "FIN":
            counts = [len(re.findall("[aeiouyäö]+", t.word.lower())) for t in tokens]
        elif row == 35:
            counts = [sum("\u3400" <= c <= "\u9fff" or "\U00020000" <= c <= "\U000323af" for c in t.word) for t in tokens]
        elif row == 36:
            counts = [sum("가" <= c <= "힣" for c in U.normalize("NFKC", p)) if lang == "KOR" else
                      sum(C._han(c) for c in U.normalize("NFKC", t.word)) for t, p in zip(tokens, prons)]
        elif row == 39:
            counts = [len(C._finnish_word(t.word, "C" if t.word in {"pian", "tae", "teos"} else "A")[0]) for t in tokens]
        elif row == 42:
            counts = [1 if re.fullmatch("r[\u0329]*", p) else C.srp_a(t.word, [p]).count for t, p in zip(tokens, prons)]
        else:
            kwargs = {"pronunciations": prons} if lang not in {"CMN", "YUE", "VIE"} else {}
            if lang == "FRA":
                kwargs["pronunciations"] = {t.word: p for t, p in zip(tokens, prons)}
            result = C.COUNTERS[lang][option](text, **kwargs)
        if counts is None:
            counts = [0] * len(tokens)
            for host in result.hosts:
                counts[host] += 1
            if sum(counts) != result.count:
                raise ValueError("Counter ownership does not preserve its count")
    out = [0] * len(original)
    unattributed = 0
    for i, count in zip(mapping, counts):
        if i is None:
            unattributed += count
        else:
            out[i] += count
    return Evaluation(out, unattributed)


FAILURES = (RuntimeError, LookupError, ValueError, ImportError, OSError, subprocess.CalledProcessError)


class LineFailure(ValueError):
    """Safe diagnostics: word types and error class, never tool error strings."""
    def __init__(self, kind, words):
        super().__init__(kind)
        self.kind, self.words = kind, words


def evaluate(text, lang, option, cache, row=None, alternative=None, *, chained_ties=C.DEFAULT_CHAINED_TIES):
    setting = alternative if row == 44 else chained_ties
    with C.counter_settings(chained_ties=setting):
        try:
            return _evaluate(text, lang, option, cache, row, alternative)
        except FAILURES as error:
            # Identify independently failing variant tokens without retranscribing
            # any type. Context-only failures have no falsely blamed word type.
            tokens = (tokenize_variant(text, row) if row in {1, 2, 34} or
                      row == 9 and alternative == 'retain_curly_quotes' else C.tokenize(text))
            failures = Counter()
            for word, frequency in Counter(t.word for t in tokens).items():
                try:
                    _evaluate(word, lang, option, cache, row, alternative)
                except FAILURES:
                    failures[word] += frequency
            raise LineFailure(type(error).__name__, failures) from None


def tally(lines, language, selected=None, *, cache=None, chained_ties=C.DEFAULT_CHAINED_TIES):
    """Aggregate matched successful lines; failures are local to each comparison.

    Input lines are separated at LF/CR by the file reader. Other Unicode line
    controls remain inside a physical line so row 2 can test their phrase role.
    """
    if language in {'JPN', 'THA'}:
        native = load('t8_native_tally', ROOT / 'src/stage3/native_tally.py')
        return native.tally(sys.modules[__name__], lines, language, selected, cache, chained_ties)
    titles, table_hash = table()
    if chained_ties not in C.CHAINED_TIES:
        raise ValueError("Unknown chained-tie policy")
    if language not in ALL:
        raise ValueError("Unknown language")
    selected = sorted(set(selected)) if selected is not None else [r for r in titles if options(r, language)]
    if any(r not in titles for r in selected):
        raise ValueError("Row numbers must be between 1 and 53")
    cache = cache if cache is not None else Cache(language)
    if cache.language != language:
        raise ValueError("Cache language does not match tally language")
    # Input is retained only in memory; outputs never contain lines/sentences.
    lines = [U.normalize("NFC", line) for line in lines]
    token_lines = [C.tokenize(line) for line in lines]
    word_tokens = sum(map(len, token_lines))
    provenance = {"counter_sha256": P.version()["counter"], "tally_sha256": CODE_HASH,
                  "lexicons": C.LEXICON_PROVENANCE,
                  "variants_sha256": hashlib.sha256(Path(E.__file__).read_bytes()).hexdigest(),
                  "table_sha256": table_hash, "unicode": U.unidata_version,
                  "python": sys.version.split()[0], "regex_version": importlib.metadata.version("regex"),
                  "French_scope": "frozen Lexique 4.1 maximum-frequency entries; espeak fallback" if language == "FRA" else "",
                  "token_accounting": "owned nuclei; merged tokens mapped leftmost; split tokens summed",
                  "difference": "alternative minus code",
                  "chained_ties": chained_ties,
                  "counter_settings": dict(C._resolved_settings(), chained_ties=chained_ties),
                  "row44_reference": "one_nucleus versus disjoint_pairs; reject has no numeric count",
                  "failure_accounting": "whole failed line excluded on both sides; shares use successful lines/tokens"}
    results, baselines = [], {}
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        for row in selected:
            opts = options(row, language)
            reason = SKIP.get(row, "") if opts else "Row does not apply to this language."
            if reason:
                results.append(dict(row=row, title=titles[row], language=language, option=",".join(opts),
                                    alternative="", status="skipped", reason=reason, lines=len(lines), word_tokens=word_tokens))
                continue
            for option in opts:
                for alternative in ALTERNATIVES[row]:
                    record = dict(row=row, title=titles[row], language=language, option=option,
                                  alternative=alternative, lines=len(lines), word_tokens=word_tokens)
                    baseline_setting = "one_nucleus" if row == 44 else chained_ties
                    alternative_setting = alternative if row == 44 else chained_ties
                    record.update(baseline_chained_ties=baseline_setting, alternative_chained_ties=alternative_setting)
                    baseline_forks = dict(C._resolved_settings(), chained_ties=baseline_setting)
                    alternative_forks = dict(baseline_forks, chained_ties=alternative_setting)
                    if row in C.FORKS:
                        alternative_forks[C.FORKS[row]['setting']] = {
                            'protect_edge_only': 'code', 'stressed_close_hiatus_kept': 'code'
                        }.get(alternative, alternative)
                    record.update(baseline_counter_settings=baseline_forks, alternative_counter_settings=alternative_forks)
                    changed, successful_frequencies, failing_types, failure_kinds = Counter(), Counter(), Counter(), Counter()
                    code_total = alt_total = changed_tokens = changed_lines = lines_with_changed_tokens = 0
                    code_unattributed = alt_unattributed = successful_lines = successful_tokens = failed_lines = failed_tokens = 0
                    unattributed_failed_lines = 0
                    for index, (line, tokens) in enumerate(zip(lines, token_lines)):
                        key = (option, baseline_setting, index)
                        if key not in baselines:
                            try:
                                baselines[key] = evaluate(line, language, option, cache, chained_ties=baseline_setting)
                            except FAILURES as error:
                                baselines[key] = error
                        code = baselines[key]
                        try:
                            if isinstance(code, Exception):
                                raise code
                            alt = evaluate(line, language, option, cache, row, alternative,
                                           chained_ties=alternative_setting)
                        except FAILURES as error:
                            failed_lines += 1
                            failed_tokens += len(tokens)  # all excluded source tokens, not just offending types
                            failure_kinds[getattr(error, "kind", type(error).__name__)] += 1
                            words = getattr(error, "words", {})
                            failing_types.update(words)
                            unattributed_failed_lines += not bool(words)
                            continue
                        successful_lines += 1; successful_tokens += len(tokens)
                        successful_frequencies.update(t.word for t in tokens)
                        code_total += sum(code); alt_total += sum(alt)
                        code_unattributed += code.unattributed; alt_unattributed += alt.unattributed
                        different = False
                        for t, a, b in zip(tokens, code, alt):
                            if a != b:
                                changed[(t.word, a, b)] += 1
                                changed_tokens += 1; different = True
                        lines_with_changed_tokens += different
                        changed_lines += sum(code) != sum(alt)
                    affected_freq = Counter()
                    for (word, a, b), n in changed.items():
                        affected_freq[word] += n
                    top = sorted(affected_freq, key=lambda w: (-affected_freq[w], w))[:20]
                    top_types = [{"word": w, "affected_frequency": affected_freq[w], "frequency": successful_frequencies[w],
                                  "count_pairs": [{"code": a, "alternative": b, "frequency": n}
                                                  for (word, a, b), n in sorted(changed.items()) if word == w]} for w in top]
                    record.update(successful_lines=successful_lines, successful_word_tokens=successful_tokens,
                                  failed_lines=failed_lines, failed_tokens=failed_tokens,
                                  failing_types=[{"word": w, "frequency": n} for w, n in
                                                 sorted(failing_types.items(), key=lambda item: (-item[1], item[0]))[:20]],
                                  failure_kinds=dict(sorted(failure_kinds.items())), unattributed_failed_lines=unattributed_failed_lines)
                    if failed_lines and not successful_lines:
                        record.update(status="skipped", reason="No successful lines; G2P/counter/attribution failure.")
                    else:
                        record.update(status="partial" if failed_lines else "covered", reason="",
                                      code_syllables=code_total, alternative_syllables=alt_total, difference=alt_total-code_total,
                                      code_unattributed_syllables=code_unattributed, alternative_unattributed_syllables=alt_unattributed,
                                      changed_word_tokens=changed_tokens, changed_token_share=changed_tokens/successful_tokens if successful_tokens else 0.,
                                      changed_lines=changed_lines, changed_line_share=changed_lines/successful_lines if successful_lines else 0.,
                                      lines_with_changed_tokens=lines_with_changed_tokens, top_types=top_types)
                    results.append(record)
                for alternative, reason in PARTIAL_SKIP.get(row, {}).items():
                    results.append(dict(row=row, title=titles[row], language=language, option=option,
                                        alternative=alternative, status="skipped", reason=reason,
                                        lines=len(lines), word_tokens=word_tokens))
        descriptors = {route: backend.descriptor() for route, backend in sorted(cache.adapters.items())}
        cache.save()
    fallback_share = None
    if language == 'FRA':
        fallback_share = sum(t.word.lower() not in C.FRA_LEXICON for ts in token_lines for t in ts) / word_tokens if word_tokens else 0.
    return {"fallback_share": fallback_share, "schema": "reading-tally-v2", "language": language, "lines": len(lines), "word_tokens": word_tokens,
            "provenance": dict(provenance, adapters=descriptors), "rows": results}


FIELDS = ("row", "title", "language", "option", "alternative", "status", "reason", "lines", "word_tokens",
          "code_syllables", "alternative_syllables", "code_unattributed_syllables", "alternative_unattributed_syllables", "difference", "changed_word_tokens", "changed_token_share",
          "changed_lines", "changed_line_share", "lines_with_changed_tokens", "top_types",
          "baseline_chained_ties", "alternative_chained_ties", "successful_lines", "successful_word_tokens",
          "baseline_counter_settings", "alternative_counter_settings",
          "failed_lines", "failed_tokens", "failing_types", "failure_kinds", "unattributed_failed_lines",
          "failure_messages", "code_non_syllabic_word_tokens", "alternative_non_syllabic_word_tokens",
          "baseline_split_unit_alignment", "alternative_split_unit_alignment", "provenance")


def write_outputs(report, prefix):
    prefix = Path(prefix)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    ordered = sorted(report["rows"], key=lambda r: (r["status"] not in {"covered", "partial"}, -r.get("changed_token_share", 0),
                                                    r["row"], r["option"], r["alternative"]))
    for row in ordered:
        value = dict(row, provenance=canon(report["provenance"]))
        for key in ("top_types", "failing_types", "failure_kinds", "baseline_counter_settings", "alternative_counter_settings",
                    "failure_messages", "baseline_split_unit_alignment", "alternative_split_unit_alignment"):
            if key in value:
                value[key] = canon(value[key])
        writer.writerow(value)
    md = ["# Counter-reading tally", "", f"Language: {report['language']}. Lines: {report['lines']}. Word tokens: {report['word_tokens']}. Fallback share: {report.get('fallback_share')}. Non-syllabic word tokens: {report.get('non_syllabic_word_tokens', 0)}.", "",
          "Difference = alternative minus code. Token changes use owned nuclei, so an ownership shift can change tokens without changing a line's total. "
          "Merged alternative tokens belong to the leftmost overlapping source token; split counts sum to their source token. "
          "Unattributed syllables are included in line totals and reported separately in TSV; full variant adjacency is retained. "
          "Failed lines are excluded from both sides of their comparison; shares use successful lines/tokens. "
          "Row 44 uses one_nucleus as its numeric reference, comparing disjoint_pairs; other comparisons use the production default, one_nucleus. "
          "Top types and their context-dependent count pairs are in the TSV. No line text is emitted.", "",
          "| Row | Option | Alternative | Code | Alternative | Difference | Tokens changed | Line totals changed | Lines with token changes |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in ordered:
        if r["status"] in {"covered", "partial"}:
            md.append(f"| {r['row']} | {r['option']} | {r['alternative']} | {r['code_syllables']} | {r['alternative_syllables']} | "
                      f"{r['difference']} | {r['changed_word_tokens']} ({r['changed_token_share']:.2%}) | "
                      f"{r['changed_lines']} ({r['changed_line_share']:.2%}) | {r['lines_with_changed_tokens']} |")
    md.extend(["", "Failed lines per comparison:", "",
               "| Row | Option | Alternative | Successful lines / tokens | Failed lines | Failed tokens | Commonest failing types (frequency) | Context-only failures |",
               "|---|---|---|---:|---:|---:|---|---:|"])
    def md_word(word):
        return word.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "&#124;")
    for r in ordered:
        if "failed_lines" in r:
            types = ", ".join(md_word(t['word']) + " (" + str(t['frequency']) + ")" for t in r['failing_types'])
            md.append(f"| {r['row']} | {r['option']} | {r['alternative']} | "
                      f"{r['successful_lines']} / {r['successful_word_tokens']} | {r['failed_lines']} | "
                      f"{r['failed_tokens']} | {types} | {r['unattributed_failed_lines']} |")
    if report.get('fallback_by_option'):
        md.extend(['', 'Native route accounting:', '',
                   '| Option | Word tokens | Fallback words | Fallback share | Non-syllabic words |',
                   '|---|---:|---:|---:|---:|'])
        for option, counts in sorted(report['fallback_by_option'].items()):
            md.append(f"| {option} | {counts['word_tokens']} | {counts['fallback_word_tokens']} | "
                      f"{counts['share']:.2%} | {counts['non_syllabic_word_tokens']} |")
    if report.get('split_unit_alignment_by_option'):
        md.extend(['', 'Thai split-unit placement (successful matched lines):', '',
                   '| Option | Route | Fragment readings | Spelling pieces | Inside-piece cuts | Units with inside-piece cuts | Failed lines |',
                   '|---|---|---:|---:|---:|---:|---:|'])
        for option, routes in sorted(report['split_unit_alignment_by_option'].items()):
            for route, counts in sorted(routes.items()):
                md.append(f"| {option} | {route} | {counts['fragment_readings']} | {counts['spelling_pieces']} | "
                          f"{counts['cuts_inside_pieces']} | {counts['units_with_cut_inside_piece']} | {counts['failed_lines']} |")
    if any(r.get('failure_messages') for r in ordered):
        md.extend(['', 'Fixed native error messages (reader errors and text are redacted):', '',
                   '| Row | Option | Alternative | Message | Failed lines |',
                   '|---|---|---|---|---:|'])
        for r in ordered:
            for message, frequency in sorted(r.get('failure_messages', {}).items()):
                md.append(f"| {r['row']} | {r['option']} | {r['alternative']} | {md_word(message)} | {frequency} |")
    md.extend(["", "Skipped comparisons:", ""])
    for r in ordered:
        if r["status"] == "skipped":
            md.append(f"- Row {r['row']} ({r['option']}; {r['alternative'] or 'all alternatives'}): {r['reason']}")
    md.extend(["", "Row 6's whole-run rule is an excluded historical rule, not a candidate fork. "
               "French counts use frozen Lexique 4.1 and espeak fallback. Mandarin uses the frozen Wiktionary erhua default. "
               "Unrelated language rows are omitted unless explicitly selected. Comparisons with no successful lines contain no numeric totals.", "",
               "Provenance: `" + canon(report["provenance"]) + "`", ""])
    tsv, summary = Path(str(prefix) + ".tsv"), Path(str(prefix) + ".md")
    P.atomic(tsv, stream.getvalue().encode())
    P.atomic(summary, "\n".join(md).encode())
    return tsv, summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("language", type=str.upper, choices=sorted(ALL))
    p.add_argument("input", type=Path, help="Only this UTF-8 running-text file is read; no discovery")
    p.add_argument("--rows", nargs="+", help="Optional row numbers, space/comma separated")
    p.add_argument("--output", required=True, type=Path, help="Output prefix; writes PREFIX.tsv and PREFIX.md")
    p.add_argument("--cache", type=Path, help="Optional explicit persistent pronunciation cache")
    p.add_argument("--chained-ties", choices=C.CHAINED_TIES, default=C.DEFAULT_CHAINED_TIES)
    args = p.parse_args()
    try:
        selected = [int(n) for item in args.rows for n in item.split(",")] if args.rows else None
        outputs = [Path(str(args.output) + ext).resolve() for ext in (".tsv", ".md")]
        paths = [args.input.resolve(), *outputs] + ([args.cache.resolve()] if args.cache else [])
        if len(set(paths)) != len(paths):
            raise ValueError("Input, cache and output paths must be distinct")
        # Never on the read texts: those are counted only by the production command.
        GUARD = importlib.util.spec_from_file_location('reading_tally_read_text_guard', Path(__file__).with_name('read_text_guard.py'))
        guard = importlib.util.module_from_spec(GUARD); GUARD.loader.exec_module(guard)
        try:
            guard.check(args.input)
        except guard.ReadTextRefused as refused:
            p.exit(2, f"Tally refused: {refused}\n")
        # Universal-newline file iteration preserves non-CR/LF line controls.
        with args.input.open(encoding="utf-8", newline=None) as f:
            lines = [line.rstrip("\n") for line in f]
        cache = Cache(args.language, args.cache)
        report = tally(lines, args.language, selected, cache=cache, chained_ties=args.chained_ties)
        tsv, summary = write_outputs(report, args.output)
    except (ValueError, OSError, KeyError) as e:
        p.exit(2, "Tally failed: " + type(e).__name__ + "; check arguments, UTF-8 input and cache.\n")
    print(f"Wrote {tsv.name} and {summary.name}; {sum(r['status'] == 'covered' for r in report['rows'])} covered comparisons; "
          f"{sum(r['status'] == 'partial' for r in report['rows'])} partial; "
          f"{sum(r['status'] == 'skipped' for r in report['rows'])} skipped.")


if __name__ == "__main__":
    main()
