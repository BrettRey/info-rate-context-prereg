"""Shared trace/token validation for the Japanese and Thai native segmenters."""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
from dataclasses import replace
import hashlib
import importlib.metadata as metadata
from pathlib import Path
import sys
import unicodedata as U


class AlignmentMiss(ValueError):
    """Raised only by this project's own parsing/alignment checks.

    It marks "this alignment proof failed", which is a property of the data.
    External code can't raise it, so a bare ValueError() from a converter or
    reader is never mistaken for one.
    """
    alignment_sentinel = True


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


SOFTWARE = frozenset({'Japanese chunk cache must retain every contextual token pronunciation',
                      'One source per Japanese word required',
                      'Pinned Thai model missing; downloads disabled',
                      'Only the pinned local Thai model may be read',
                      'Thai neural adapter requires CPU', 'Offline attacut worker exited',
                      'Installed OpenJTalk dictionary required; downloads disabled',
                      'One character span per Thai syllable required',
                      'Invalid/nonmonotonic Thai syllable span'})


def reader_data_error(error):
    """Only invalid readings may trigger another reader; software faults escape.

    Every exception in the chain must be a declared reading failure or an
    internal AlignmentMiss. Unknown policy/reader and cache/shape errors are
    configuration faults.
    """
    declared = set()
    for name in ('stage3_japanese', 'stage3_thai'):
        declared.update(getattr(sys.modules.get(name), 'FAILURE_MESSAGES', ()))
    for current in exception_chain(error):
        if type(current) is AlignmentMiss:
            continue
        if (not isinstance(current, ValueError) or str(current).startswith('Unknown ')
                or str(current) not in declared or str(current) in SOFTWARE):
            raise current


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def versions(*names):
    return {name: metadata.version(name) for name in names}


def partition(core, text, splitter, word_tokens=None):
    """Never allow an engine token across a source space, gap or phrase boundary."""
    chunks = core.tokenize(text)
    supplied = iter(word_tokens) if word_tokens is not None else None
    tokens = []
    for chunk in chunks:
        if supplied is None:
            pieces = tuple(splitter(chunk.word))
        else:
            pieces, consumed = [], ''
            while len(consumed) < len(chunk.word):
                try:
                    piece = next(supplied)
                except StopIteration:
                    raise ValueError('Supplied word tokens do not cover the source') from None
                if not isinstance(piece, str) or not piece or not chunk.word.startswith(consumed + piece):
                    raise ValueError('Supplied word token crosses a separator or changes source spelling')
                pieces.append(piece); consumed += piece
        if not pieces or ''.join(pieces) != chunk.word or any(not p or p.isspace() for p in pieces):
            raise ValueError('Word segmenter must preserve every source character')
        tokens.extend(core.Token(p, False) for p in pieces)
        tokens[-1] = replace(tokens[-1], phrase_end=chunk.phrase_end)
    if supplied is not None:
        try:
            next(supplied)
        except StopIteration:
            pass
        else:
            raise ValueError('Extra supplied word tokens')
    return tuple(tokens)


def pronunciation_values(tokens, supplied, transcribe):
    if supplied is None:
        return tuple(transcribe(t.word) for t in tokens)
    if hasattr(supplied, 'keys'):
        try:
            return tuple(supplied[t.word] for t in tokens)
        except KeyError:
            raise ValueError('A native word is missing its supplied pronunciation') from None
    values = tuple(supplied)
    if len(values) != len(tokens):
        raise ValueError('Supply one pronunciation per reader/segmenter word token')
    return values


def source_spans(text, tokens):
    text = U.normalize('NFC', text)
    cursor, spans = 0, []
    for token in tokens:
        begin = text.find(token.word, cursor)
        if begin < 0:
            raise ValueError('Native token cannot be aligned to source text')
        cursor = begin + len(token.word); spans.append((begin, cursor))
    return tuple(spans)


def result(core, tokens, prons, units, nuclei, source, provenance):
    syllables = tuple(s for word in units for s in word)
    hosts = tuple(w for w, word in enumerate(units) for _ in word)
    if any(not word for word in units):
        raise ValueError('A native word has no syllables')
    return core.Count(len(syllables), syllables, tuple(n for word in nuclei for n in word),
                      hosts, tuple((w,) for w in hosts), tokens, tuple(prons),
                      (source,) * len(tokens), resource_provenance=provenance)
