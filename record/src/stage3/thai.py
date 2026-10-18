"""Offline tone-bearing Thai G2P and independently selectable word boundaries.

G2P is performed on fixed newmm pronunciation units for either word segmenter.
Thus switching word boundaries cannot change the unflagged syllable sequence.
When a word boundary splits a pronunciation unit, fragment transcriptions or
TLTK spelling pieces must reproduce its fixed syllable sequence exactly.
Alignment establishes ownership, never replaces labels or word boundaries.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
from functools import lru_cache
import importlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch
import unicodedata as U

name = 'stage3_native_units'
if name not in sys.modules:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name('native_units.py'))
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
N = sys.modules[name]
TOOLS = ('tltk', 'thaig2p')
SEGMENTERS = ('newmm', 'attacut')
# Machine paths (DECISIONS.md, 2026-10-17); the defaults are this laptop's.
ATTACUT_PYTHON = Path(__import__('os').environ.get('INFO_RATE_ATTACUT_VENV', '/Users/brettreynolds/projects/LLM-CLI-projects/papers/development/info-rate-context/.venv-attacut')) / 'bin/python'
MODEL = Path(__import__('os').environ.get('INFO_RATE_THAI_MODEL', '/Users/brettreynolds/pythainlp-data/thaig2p-0.1.tar'))
if not (ATTACUT_PYTHON.is_absolute() and MODEL.is_absolute()):
    raise ValueError('INFO_RATE_ATTACUT_VENV and INFO_RATE_THAI_MODEL must be absolute paths')
TLTK_TONES = {'1': '˧', '2': '˨˩', '3': '˥˩', '4': '˦˥', '5': '˩˩˦'}
# Phonemic tone categories; explicit supported phonetic realizations only.
TONE_CANON = {'˧': '˧', '˨˩': '˨˩', '˩': '˨˩', '˥˩': '˥˩', '˦˥': '˦˥',
              '˥': '˦˥', '˩˩˦': '˩˩˦', '˩˦': '˩˩˦', '˩˧': '˩˩˦',
              '˧˩': '˨˩', '˨˦': '˩˩˦', '˦˩': '˥˩'}
FAILURE_MESSAGES = frozenset({
    'A Thai syllable must have a body and explicit tone', 'Unhandled Thai tone or syllable body',
    'Missing/empty Thai syllable', 'Pinned Thai model missing; downloads disabled',
    'Only the pinned local Thai model may be read', 'Thai neural adapter requires CPU',
    'Thai G2P requires Thai-script word units', 'Unknown Thai G2P',
    'Thai word failed the selected reader', 'Thai word failed both G2P tools',
    'Thai repeat mark has no preceding word', 'Unknown Thai word segmenter',
    'Offline attacut worker exited', 'Thai word segmenter changed source spelling',
    'Unknown Thai tool or segmenter', 'Thai spelling pieces unavailable',
    'Thai spelling piece has no source word',
    'Thai fragment readings differ from the pronunciation unit; supply exact syllable_spans',
    'One character span per Thai syllable required', 'Invalid/nonmonotonic Thai syllable span',
    'Thai word boundary splits a pronunciation unit; supply exact syllable_spans',
    'Thai word has no aligned syllable',
})


def normalize_syllable(value):
    """Canonical tool labels; retain length, consonants and lexical tone.

    Cross-tool phonemic notation mapping belongs only to the comparator.
    """
    value = U.normalize('NFC', ''.join(value.split())).replace(':', 'ː').replace('g', 'ɡ')
    value = value.replace('\u031a', '').replace('\u032f', '').replace('͡', '').replace('͜', '').replace('ᴐ', 'ɔ')
    match = re.fullmatch(r'([^˥˦˧˨˩0-9]+)([˥˦˧˨˩]+|[1-5])', value)
    if not match:
        raise ValueError('A Thai syllable must have a body and explicit tone')
    body, tone = match.groups()
    if tone.isdigit():
        tone = TLTK_TONES[tone]
    if (tone not in TONE_CANON or not re.search('[aiueoɛɔɯɤə]', body)
            or not re.fullmatch(r'[a-zɡŋɲʔʰɕɛɔɯɤəɨɪʊːʲ]+', body)):
        raise ValueError('Unhandled Thai tone or syllable body')
    return body + TONE_CANON[tone]


def parse(value):
    if isinstance(value, str):
        values = re.split(r'\s*\.\s*', value.strip())
        # TLTK IPA can have spaces separating its own words.
        values = [s for v in values for s in (v.split() if re.search(r'[1-5]', v) else [v])]
    else:
        values = tuple(value)
    if not values or any(not s for s in values):
        raise ValueError('Missing/empty Thai syllable')
    return tuple(normalize_syllable(s) for s in values)


@lru_cache(maxsize=1)
def neural():
    if not MODEL.is_file():
        raise FileNotFoundError('Pinned Thai model missing; downloads disabled')
    import torch
    torch.set_num_threads(1)
    import pythainlp.corpus
    # The import constructs its singleton. Pin the local model before that import.
    def local_model(model_name, *args, **kwargs):
        if model_name != 'thai-g2p':
            raise FileNotFoundError('Only the pinned local Thai model may be read')
        return str(MODEL)
    with patch.object(torch.cuda, 'is_available', return_value=False), \
         patch.object(pythainlp.corpus, 'get_corpus_path', local_model), torch.random.fork_rng(devices=[]):
        torch.manual_seed(0)
        module = importlib.import_module('pythainlp.transliterate.thaig2p')
    if module.device.type != 'cpu':
        raise RuntimeError('Thai neural adapter requires CPU')
    return module


@lru_cache(maxsize=32768)
def transcribe(word, tool='tltk'):
    if not word or any(not ('\u0e01' <= c <= '\u0e5b') for c in word):
        raise ValueError('Thai G2P requires Thai-script word units')
    if tool == 'tltk':
        from pythainlp.transliterate.tltk import tltk_ipa
        value = tltk_ipa(word)
    elif tool == 'thaig2p':
        import torch
        with torch.inference_mode():
            value = neural().transliterate(word)
    else:
        raise ValueError('Unknown Thai G2P')
    return parse(value)


def resolved_word(word, tool='tltk'):
    """A failed/empty/toneless main reading is retried by the CPU neural tool."""
    if tool not in TOOLS:
        raise ValueError('Unknown Thai G2P')
    try:
        return parse(transcribe(word, tool)), tool
    except Exception as main_error:
        N.reader_data_error(main_error)
        if tool != 'tltk':
            raise ValueError('Thai word failed the selected reader') from main_error
        try:
            return parse(transcribe(word, 'thaig2p')), 'thaig2p-fallback'
        except Exception as fallback_error:
            N.reader_data_error(fallback_error)
            raise ValueError('Thai word failed both G2P tools') from fallback_error


def route_descriptor(tool='tltk', segmenter='newmm'):
    value = dict(descriptor(tool, segmenter))
    if tool == 'tltk':
        value['fallback'] = descriptor('thaig2p', segmenter)
        value['fallback_policy'] = 'error, empty or invalid tone-bearing syllable'
    value['split_alignment'] = 'exact fragment readings, then exact TLTK spelling-piece readings; first-character ownership'
    value['repeat_fragment'] = 'ๆ repeats the preceding target word during split-unit alignment'
    return value


@lru_cache(maxsize=32768)
def split_chunk(text, segmenter='newmm'):
    if segmenter == 'newmm':
        from pythainlp.tokenize import word_tokenize
        result = tuple(word_tokenize(text, engine='newmm', keep_whitespace=False))
    elif segmenter == 'attacut':
        worker = attacut_worker()
        worker.stdin.write(json.dumps(text) + '\n'); worker.stdin.flush()
        reply = worker.stdout.readline()
        if not reply:
            raise RuntimeError('Offline attacut worker exited')
        result = tuple(json.loads(reply))
    else:
        raise ValueError('Unknown Thai word segmenter')
    if not result or ''.join(result) != text:
        raise ValueError('Thai word segmenter changed source spelling')
    return result


@lru_cache(maxsize=1)
def attacut_worker():
    """One synchronous, idle-between-requests subprocess in the pinned environment."""
    import atexit
    from os import environ
    env = dict(environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               VECLIB_MAXIMUM_THREADS='1', CUDA_VISIBLE_DEVICES='')
    code = ('import sys,json,torch; torch.set_num_threads(1); torch.set_num_interop_threads(1)\n'
            'from attacut import tokenize\n'
            'for line in sys.stdin:\n'
            ' print(json.dumps(tokenize(json.loads(line)),ensure_ascii=False),flush=True)\n')
    worker = subprocess.Popen([str(ATTACUT_PYTHON), '-I', '-B', '-c', code], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    def close():
        worker.stdin.close()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.terminate(); worker.wait(timeout=5)
        worker.stdout.close()
    atexit.register(close)
    return worker


def tokens(core, text, segmenter='newmm', word_tokens=None):
    return N.partition(core, text, lambda s: split_chunk(s, segmenter), word_tokens)


@lru_cache(maxsize=4)
def descriptor(tool='tltk', segmenter='newmm'):
    if tool not in TOOLS or segmenter not in SEGMENTERS:
        raise ValueError('Unknown Thai tool or segmenter')
    versions = N.versions('pythainlp', 'tltk') if tool == 'tltk' else N.versions('pythainlp', 'torch')
    model = {'version': '0.1', 'sha256': N.sha256(MODEL)} if tool == 'thaig2p' else None
    if segmenter == 'attacut':
        proc = subprocess.run([str(ATTACUT_PYTHON), '-I', '-B', '-c',
                               'import importlib.metadata as m; print(m.version("attacut"))'],
                              capture_output=True, text=True, check=True)
        versions['attacut'] = proc.stdout.strip()
    return {'tool': tool, 'version': versions, 'voice': 'th', 'model': model,
            'segmenter': segmenter, 'pronunciation_units': 'newmm', 'device': 'cpu', 'threads': 1,
            'tone': 'five canonical IPA contours', 'code_sha256': N.sha256(__file__)}


@lru_cache(maxsize=32768)
def spelling_pieces(word):
    """Read TLTK's source pieces and convert their contextual romanization to IPA.

    Use the installed th2ipa conversion on the saved g2p output, so no fragment
    is re-transcribed and its tone/length normalization matches transcribe().
    Malformed output and changed spelling never establish alignment.
    """
    # Reader/import faults must escape; only our parsing/alignment proof below
    # establishes that this word's spelling pieces are unavailable.
    import tltk.nlp as nlp
    raw = nlp.g2p(word.replace('ฅ', 'ค'))
    try:
        halves = raw.removesuffix('|<s/>').split('<tr/>')
        if len(halves) != 2:
            raise N.AlignmentMiss
        spelling, reading = halves
        spelling_groups, reading_groups = spelling.split('|'), reading.split('|')
        if len(spelling_groups) != len(reading_groups):
            raise N.AlignmentMiss
        out = []
        for source, phones in zip(spelling_groups, reading_groups):
            pieces = source.split('~')
            # A single spelling piece may have several syllables, including a
            # repeated multi-syllable word. Keep all its phone separators.
            readings = phones.split('~') if len(pieces) > 1 else [phones]
            if len(pieces) != len(readings) or any(not p for p in pieces):
                raise N.AlignmentMiss
            for piece, roman in zip(pieces, readings):
                saved = piece + '<tr/>' + roman + '|<s/>'
                with patch.object(nlp, 'g2p', return_value=saved):
                    ipa = nlp.th2ipa('').removesuffix(' <s/>')
                out.append((piece, parse(ipa)))
        if ''.join(piece for piece, _ in out) != word:
            raise N.AlignmentMiss
        return tuple(out)
    except Exception as error:
        N.reader_data_error(error)
        raise ValueError('Thai spelling pieces unavailable') from error


def alignment_counts():
    return dict(fragment_readings=0, spelling_pieces=0, cuts_inside_pieces=0,
                units_with_cut_inside_piece=0)


def aligned_spans(text, base_spans, target_spans, grouped, tool, stats=None, piece_words=None):
    """Keep fixed labels; prefer fragments, then verified contextual pieces."""
    stats = stats if stats is not None else alignment_counts()
    piece_words = piece_words if piece_words is not None else set()
    spans, placed = [], {}
    for (a, b), labels in zip(base_spans, grouped):
        whole = next((i for i, (x, y) in enumerate(target_spans) if x <= a and b <= y), None)
        if whole is not None:
            spans.extend([(a, b)] * len(labels))
            placed.setdefault(whole, []).extend(labels)
            continue
        fragments = [(i, max(a, x), min(b, y)) for i, (x, y) in enumerate(target_spans) if a < y and b > x]
        predicted, proposed = [], []
        try:
            tentative = {i: list(ss) for i, ss in placed.items()}
            for i, x, y in fragments:
                fragment = text[x:y].strip()
                if fragment == 'ๆ':
                    if not tentative.get(i - 1):
                        raise ValueError('Thai repeat mark has no preceding word')
                    syllables = tuple(tentative[i - 1])
                else:
                    syllables, _ = resolved_word(fragment, tool)
                tentative.setdefault(i, []).extend(syllables)
                predicted.extend(syllables); proposed.extend([(x, y)] * len(syllables))
        except Exception as error:
            N.reader_data_error(error)
            predicted = []
        if tuple(predicted) == labels:
            stats['fragment_readings'] += 1
            spans.extend(proposed); placed = tentative
            continue
        try:
            pieces = spelling_pieces(text[a:b])
            if (''.join(piece for piece, _ in pieces) != text[a:b] or
                    tuple(s for _, ss in pieces for s in ss) != labels):
                raise N.AlignmentMiss
        except Exception as error:
            N.reader_data_error(error)
            raise ValueError('Thai fragment readings differ from the pronunciation unit; supply exact syllable_spans') from error
        cursor, cuts = a, set()
        for piece, ss in pieces:
            end = cursor + len(piece)
            owners = [i for i, (x, y) in enumerate(target_spans) if x <= cursor < y]
            if len(owners) != 1:
                raise ValueError('Thai spelling piece has no source word')
            # A one-character span encodes the requested first-character host,
            # including when the piece extends across a target word boundary.
            spans.extend([(cursor, cursor + 1)] * len(ss))
            placed.setdefault(owners[0], []).extend(ss)
            piece_words.update(i for i, (x, y) in enumerate(target_spans) if x < end and y > cursor)
            cuts.update(x for x, _ in target_spans if cursor < x < end)
            cursor = end
        if cursor != b:
            raise ValueError('Thai fragment readings differ from the pronunciation unit; supply exact syllable_spans')
        stats['spelling_pieces'] += 1
        stats['cuts_inside_pieces'] += len(cuts)
        stats['units_with_cut_inside_piece'] += bool(cuts)
    return tuple(spans)


def count(core, text, pronunciations=None, tool='tltk', segmenter='newmm', word_tokens=None,
          syllable_spans=None, pronunciation_sources=None):
    if tool not in TOOLS or segmenter not in SEGMENTERS:
        raise ValueError('Unknown Thai tool or segmenter')
    ts = tokens(core, text, segmenter, word_tokens)
    base = tokens(core, text, 'newmm')
    if pronunciations is None:
        readings = [resolved_word(t.word, tool) for t in base]
        ps = tuple(p for p, _ in readings)
        sources = tuple(s for _, s in readings)
    else:
        ps = N.pronunciation_values(base, pronunciations, None)
        sources = (N.pronunciation_values(base, pronunciation_sources, None) if pronunciation_sources is not None
                   else ('supplied',) * len(base))
    grouped = [parse(p) for p in ps]
    labels = tuple(s for ss in grouped for s in ss)
    base_spans, target_spans = N.source_spans(text, base), N.source_spans(text, ts)
    stats, piece_words = alignment_counts(), set()
    if syllable_spans is None:
        spans = aligned_spans(U.normalize('NFC', text), base_spans, target_spans, grouped, tool, stats, piece_words)
    else:
        spans = tuple(tuple(s) for s in syllable_spans)
        if len(spans) != len(labels):
            raise ValueError('One character span per Thai syllable required')
        previous = 0
        for (a, b), parent in zip(spans, (span for span, ss in zip(base_spans, grouped) for _ in ss)):
            if not isinstance(a, int) or not isinstance(b, int) or not parent[0] <= a < b <= parent[1] or a < previous:
                raise ValueError('Invalid/nonmonotonic Thai syllable span')
            previous = a
    hosts = []
    for a, b in spans:
        matches = [i for i, (x, y) in enumerate(target_spans) if x <= a and b <= y]
        if len(matches) != 1:
            raise ValueError('Thai word boundary splits a pronunciation unit; supply exact syllable_spans')
        hosts.append(matches[0])
    unowned = set(range(len(ts))) - set(hosts)
    if unowned - piece_words:
        raise ValueError('Thai word has no aligned syllable')
    word_prons = tuple('.'.join(s for s, h in zip(labels, hosts) if h == w) for w in range(len(ts)))
    syllable_sources = tuple(source for source, ss in zip(sources, grouped) for _ in ss)
    word_sources = tuple('+'.join(dict.fromkeys(s for s, h in zip(syllable_sources, hosts) if h == w))
                         for w in range(len(ts)))
    # A continuation fragment without owned syllables retains the fixed unit's
    # source; its empty pronunciation is an explicit alignment consequence.
    word_sources = tuple(source or '+'.join(dict.fromkeys(s for s, (a, b) in zip(sources, base_spans)
                         if a < target_spans[w][1] and b > target_spans[w][0]))
                         for w, source in enumerate(word_sources))
    nuclei = tuple(re.search(r'[aiueoɛɔɯɤə].*', s).group() for s in labels)
    return core.Count(len(labels), labels, nuclei, tuple(hosts), tuple((h,) for h in hosts), ts,
                      word_prons, word_sources, resource_provenance=dict(route_descriptor(tool, segmenter),
                      split_unit_alignment=stats, spelling_piece_unowned_words=sorted(unowned),
                      alignment='explicit syllable spans' if syllable_spans is not None else
                      'whole newmm units, exact fragment readings or verified contextual spelling pieces'))


def register(core):
    def tha_a(text, pronunciations=None, tool='tltk', segmenter='newmm', word_tokens=None, syllable_spans=None, pronunciation_sources=None):
        return count(core, text, pronunciations, tool, segmenter, word_tokens, syllable_spans, pronunciation_sources)
    return {'A': tha_a}
