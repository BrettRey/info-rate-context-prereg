"""Offline pronunciation-form readers and G1/G2 Japanese syllables.

Kana strings are type labels; pitch accent is omitted. No kana spelling to
pronunciation heuristic is applied to reader output. Dictionary comparison
normalization is separate in compare_jpn_tha.py.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
from functools import lru_cache
import importlib.util
from pathlib import Path
import sys
import unicodedata as U


def _helper():
    name = 'stage3_native_units'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name('native_units.py'))
        m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
    return sys.modules[name]


N = _helper()
# Main reader selected by the project lead on 2026-10-10; second is diagnostic.
READERS = ('fugashi', 'pyopenjtalk')
# The last kana of a contracted/loan mora supplies its vowel.
VOWEL_ROWS = ('アカガサザタダナハバパマヤラワァャヵ',
              'イキギシジチヂニヒビピミリヰィ',
              'ウクグスズツヅヌフブプムユルヴゥュ',
              'エケゲセゼテデネヘベペメレヱェヶ',
              'オコゴソゾトドノホボポモヨロヲォョ')
VOWEL = {c: v for row, v in zip(VOWEL_ROWS, 'aiueo') for c in row}
SMALL = frozenset('ァィゥェォャュョ')
EXTENSIONS = frozenset('ーンッ')
# Only these fixed counter messages may enter aggregate diagnostic reports.
FAILURE_MESSAGES = frozenset({
    'Missing Japanese pronunciation', 'Orphan/repeated Japanese devoicing annotation',
    'Orphan/repeated small kana', 'Unhandled Japanese pronunciation character',
    'Unknown Japanese grouping/extension policy', 'Orphan Japanese extension mora',
    'Stacked Japanese extension mora', 'Unknown Japanese reader',
    'Japanese reader changed source spelling', 'Japanese word failed the selected reader',
    'Japanese word failed both readers', 'Japanese word has no pronunciation from either reader',
    'Japanese chunk cache must retain every contextual token pronunciation',
    'One source per Japanese word required',
    'Installed OpenJTalk dictionary required; downloads disabled',
})


def katakana(value):
    value = U.normalize('NFC', U.normalize('NFKC', value))
    return ''.join(chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c for c in value)


def non_syllabic(word):
    value = U.normalize('NFKC', word)
    return bool(value) and all(U.category(c)[0] in 'PS' for c in value)


def clean_reading(reading):
    return katakana(reading).replace('、', '').replace('。', '')


def morae(reading):
    if not isinstance(reading, str) or not reading:
        raise ValueError('Missing Japanese pronunciation')
    out = []
    for c in clean_reading(reading):
        if c == '’':
            # OpenJTalk appends this annotation to a devoiced vowel mora.
            if not out or out[-1][-1] not in VOWEL:
                raise ValueError('Orphan/repeated Japanese devoicing annotation')
            out[-1] += c
        elif c in SMALL:
            if not out or out[-1][-1] in EXTENSIONS or out[-1][-1] in SMALL:
                raise ValueError('Orphan/repeated small kana')
            out[-1] += c
        elif c in VOWEL or c in EXTENSIONS:
            out.append(c)
        else:
            raise ValueError('Unhandled Japanese pronunciation character')
    return tuple(m.replace('’', '') for m in out)


def syllables(reading, option='G1', stacked='attach'):
    """Greedy within-word grouping; /ai oi ui/ need an onsetless second mora.

    A stack such as ターン attaches both length and nasal to its vowel by default;
    stacked='reject' implements the literal at-most-one extension reading.
    """
    if option not in ('G1', 'G2') or stacked not in ('attach', 'reject'):
        raise ValueError('Unknown Japanese grouping/extension policy')
    out, nuclei, previous_vowel = [], [], None
    for mora in morae(reading):
        if mora in EXTENSIONS:
            if not out:
                raise ValueError('Orphan Japanese extension mora')
            if stacked == 'reject' and out[-1][-1] in EXTENSIONS:
                raise ValueError('Stacked Japanese extension mora')
            out[-1] += mora; nuclei[-1] += mora; previous_vowel = None
            continue
        v = VOWEL[mora[-1]]
        if (option == 'G2' and out and mora == 'イ' and previous_vowel in {'a', 'o', 'u'}
                and len(nuclei[-1]) == 1):
            out[-1] += mora; nuclei[-1] += v; previous_vowel = None
        else:
            out.append(mora); nuclei.append(v); previous_vowel = v
    return tuple(out), tuple(nuclei)


@lru_cache(maxsize=1)
def tagger():
    import fugashi, unidic_lite
    return fugashi.Tagger('-d "' + unidic_lite.DICDIR + '"')


@lru_cache(maxsize=32768)
def read_chunk(text, reader='fugashi'):
    if reader == 'pyopenjtalk':
        import pyopenjtalk
        # Verify the pinned installed dictionary before an API that could fetch it.
        dictionary = Path(pyopenjtalk.OPEN_JTALK_DICT_DIR.decode())
        if not (dictionary / 'sys.dic').is_file():
            raise FileNotFoundError('Installed OpenJTalk dictionary required; downloads disabled')
        values = tuple((w['string'], w['pron']) for w in pyopenjtalk.run_frontend(text))
    elif reader == 'fugashi':
        values = tuple((w.surface, w.feature.pron or '') for w in tagger()(text))
    else:
        raise ValueError('Unknown Japanese reader')
    if ''.join(w for w, _ in values) != text:
        raise ValueError('Japanese reader changed source spelling')
    return values


def resolved_chunk(text, reader='fugashi'):
    """Keep main-reader boundaries/context; retry only missing word readings."""
    if reader not in READERS:
        raise ValueError('Unknown Japanese reader')
    if non_syllabic(text):
        return ((text, '', 'non-syllabic'),)
    source = reader
    try:
        pairs = read_chunk(text, reader)
    except Exception as error:
        N.reader_data_error(error)
        if reader != 'fugashi':
            raise ValueError('Japanese word failed the selected reader') from error
        try:
            pairs = read_chunk(text, 'pyopenjtalk')
            source = 'pyopenjtalk-fallback'
        except Exception as fallback_error:
            N.reader_data_error(fallback_error)
            raise ValueError('Japanese word failed both readers') from fallback_error
    resolved = []
    for word, pron in pairs:
        if non_syllabic(word):
            resolved.append((word, '', 'non-syllabic'))
            continue
        word_source = source
        if reader == 'fugashi' and (not pron or pron == '*'):
            try:
                pron = ''.join(p for _, p in read_chunk(word, 'pyopenjtalk'))
            except Exception as fallback_error:
                N.reader_data_error(fallback_error)
                raise ValueError('Japanese word failed both readers') from fallback_error
            word_source = 'pyopenjtalk-fallback'
        if not pron or pron == '*':
            raise ValueError('Japanese word has no pronunciation from either reader')
        resolved.append((word, pron, word_source))
    return tuple(resolved)


def route_descriptor(reader='fugashi'):
    value = dict(descriptor(reader))
    if reader == 'fugashi':
        value['fallback'] = descriptor('pyopenjtalk')
        value['fallback_policy'] = 'missing word pronunciation or reader error; keep fugashi boundaries when available'
    value['orphan_length'] = 'attach across word boundary; drop at line start'
    value['orphan_extensions'] = 'ー, ン, ッ attach across word boundary; drop at line start'
    value['non_syllabic_tokens'] = 'NFKC Unicode P*/S* tokens; no reader or fallback'
    value['reader_pause_marks'] = 'strip 、 and 。 before mora parsing'
    return value


def tokens(core, text, reader='fugashi', word_tokens=None):
    def split(s):
        if non_syllabic(s):
            return [s]
        try:
            return [w for w, _ in read_chunk(s, reader)]
        except Exception as error:
            # Only an invalid reading may switch tokenizer; faults stop the run.
            N.reader_data_error(error)
            if reader != 'fugashi':
                raise
            return [w for w, _ in read_chunk(s, 'pyopenjtalk')]
    return N.partition(core, text, split, word_tokens)


def pronunciations(core, text, reader='fugashi', word_tokens=None):
    if word_tokens is not None:
        ts = tokens(core, text, reader, word_tokens)
        return ts, tuple(''.join(p for _, p, _ in resolved_chunk(t.word, reader)) for t in ts)
    ts, ps = [], []
    for chunk in core.tokenize(text):
        pairs = resolved_chunk(chunk.word, reader)
        ts.extend(core.Token(w, False) for w, _, _ in pairs); ps.extend(p for _, p, _ in pairs)
        if pairs:
            ts[-1] = core.Token(ts[-1].word, chunk.phrase_end)
    return tuple(ts), tuple(ps)


def cached_pronunciations(core, text, reader, get):
    """Cache source chunks, then keep contextual pronunciations by occurrence.

    A lexical type can have different pronunciations within the same chunk.
    The getter returns one pronunciation per reader token, in reader order.
    """
    ts, ps = [], []
    for chunk in core.tokenize(text):
        if non_syllabic(chunk.word):
            pairs = ((chunk.word, ''),)
        else:
            try:
                pairs = read_chunk(chunk.word, reader)
            except Exception as error:
                N.reader_data_error(error)
                if reader != 'fugashi':
                    raise
                pairs = read_chunk(chunk.word, 'pyopenjtalk')
        values = get(chunk.word)
        if not isinstance(values, (list, tuple)) or len(values) != len(pairs):
            raise ValueError('Japanese chunk cache must retain every contextual token pronunciation')
        ts.extend(core.Token(w, False) for w, _ in pairs); ps.extend(values)
        if pairs:
            ts[-1] = core.Token(ts[-1].word, chunk.phrase_end)
    return tuple(ts), tuple(ps)


@lru_cache(maxsize=2)
def descriptor(reader='fugashi'):
    if reader not in READERS:
        raise ValueError('Unknown Japanese reader')
    if reader == 'pyopenjtalk':
        import pyopenjtalk
        path = Path(pyopenjtalk.OPEN_JTALK_DICT_DIR.decode())
        package_versions = N.versions('pyopenjtalk')
    else:
        import unidic_lite
        path = Path(unidic_lite.DICDIR)
        package_versions = N.versions('fugashi', 'unidic-lite')
    return {'tool': reader, 'version': package_versions, 'voice': 'ja',
            'dictionary_sha256': N.sha256(path / 'sys.dic'), 'pronunciation_field': 'pron',
            'pitch_accent': 'unmarked', 'code_sha256': N.sha256(__file__)}


def count(core, text, option, pronunciations=None, reader='fugashi', word_tokens=None, stacked='attach',
          pronunciation_sources=None):
    if reader not in READERS:
        raise ValueError('Unknown Japanese reader')
    if option not in ('G1', 'G2') or stacked not in ('attach', 'reject'):
        raise ValueError('Unknown Japanese grouping/extension policy')
    if pronunciations is None:
        ts = tokens(core, text, reader, word_tokens)
        if word_tokens is None:
            readings = [r for chunk in core.tokenize(text) for r in resolved_chunk(chunk.word, reader)]
            ps = tuple(p for _, p, _ in readings)
            sources = tuple(s for _, _, s in readings)
        else:
            readings = [resolved_chunk(t.word, reader) for t in ts]
            ps = tuple(''.join(p for _, p, _ in rows) for rows in readings)
            sources = tuple('pyopenjtalk-fallback' if any(s.endswith('-fallback') for _, _, s in rows)
                            else reader for rows in readings)
    else:
        ts = tokens(core, text, reader, word_tokens)
        ps = N.pronunciation_values(ts, pronunciations, None)
        sources = tuple(pronunciation_sources) if pronunciation_sources is not None else ('supplied',) * len(ts)
    if len(sources) != len(ts):
        raise ValueError('One source per Japanese word required')
    labels, nuclei, hosts, members, dropped, symbols = [], [], [], [], [], []
    ps, sources = list(ps), list(sources)
    for w, p in enumerate(ps):
        if non_syllabic(ts[w].word):
            ps[w] = ''; sources[w] = 'non-syllabic'; symbols.append(w)
            continue
        if not isinstance(p, str) or not p:
            raise ValueError('Missing Japanese pronunciation')
        p = clean_reading(p)
        if not p:
            raise ValueError('Missing Japanese pronunciation')
        while p and p[0] in EXTENSIONS:
            if labels:
                labels[-1] += p[0]; nuclei[-1] += p[0]
                members[-1] = tuple(sorted(set(members[-1]) | {w}))
            else:
                dropped.append(w)
            p = p[1:]
        if p:
            ss, ns = syllables(p, option, stacked)
            labels.extend(ss); nuclei.extend(ns); hosts.extend([w] * len(ss)); members.extend([(w,)] * len(ss))
    provenance = dict(route_descriptor(reader), stacked_extensions=stacked, dropped_length_words=sorted(set(dropped)),
                      dropped_extension_words=sorted(set(dropped)), non_syllabic_words=symbols,
                      word_reading='supplied pronunciations' if pronunciations is not None else
                      'contextual reader pronunciation' if word_tokens is None else 'isolated supplied tokens')
    return core.Count(len(labels), tuple(labels), tuple(nuclei), tuple(hosts), tuple(members),
                      ts, tuple(ps), tuple(sources), resource_provenance=provenance)


def register(core):
    def jpn_g1(text, pronunciations=None, reader='fugashi', word_tokens=None, stacked='attach', pronunciation_sources=None):
        return count(core, text, 'G1', pronunciations, reader, word_tokens, stacked, pronunciation_sources)
    def jpn_g2(text, pronunciations=None, reader='fugashi', word_tokens=None, stacked='attach', pronunciation_sources=None):
        return count(core, text, 'G2', pronunciations, reader, word_tokens, stacked, pronunciation_sources)
    return {'G1': jpn_g1, 'G2': jpn_g2}
