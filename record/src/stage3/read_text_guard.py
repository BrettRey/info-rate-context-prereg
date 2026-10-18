"""Refuse to count the read texts outside the production command (the NS hold).

Before the freeze is stamped, no syllable count may be taken on a read text
(`DECISIONS.md`). The ad hoc tools (`segment_entropy.py`, `reading_tally.py`)
count any file they are given, so they call `check` first. It refuses:
  - a file under `data/ref/`;
  - a file byte-identical to the texts table or a readings table;
  - a file holding a whole read text, or at least half of the sentences of
    any one read text (at least two, unless it has only one of 12 characters
    or more) (after NFC, case folding, whitespace collapsing and
    stripping punctuation), found line by line or in the joined text, so a
    reflowed or rewrapped copy is caught too.
One read-text sentence turning up in a subtitle corpus doesn't refuse it.
The production command reads the texts by its own gated route, which passes
an entropy authorization from the anchored freeze. Like the freeze lock this
catches mistakes, not deliberate circumvention.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import csv
import hashlib
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
TEXTS = ROOT / 'data/ref/texts.tsv'
READINGS = (ROOT / 'resources/digit-readings/readings.tsv', ROOT / 'results/stage3/digit-readings/readings.tsv')
SENTENCE_END = re.compile(r'(?<=[.!?。！？…])\s+|(?<=[。！？])')
MIN_CHARS = 12


class ReadTextRefused(ValueError):
    pass


def normal(text):
    text = unicodedata.normalize('NFC', text).casefold()
    text = ''.join(c for c in text if not unicodedata.category(c).startswith('P'))
    return ' '.join(text.split())


def read_text_units(texts_table=TEXTS):
    """Normalized sentences and whole texts of the read texts (empty if the table is absent)."""
    path = Path(texts_table)
    if not path.is_file():
        return [], set()
    per_text, wholes = [], set()
    with path.open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            text = row.get('text') or ''
            wholes.add(normal(text))
            per_text.append({normal(p) for p in SENTENCE_END.split(text) if len(normal(p)) >= MIN_CHARS})
    return per_text, wholes


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(path, *, authorized=False, texts_table=None, readings=None, root=None):
    """Raise ReadTextRefused unless this file is clearly not the read texts (or the run is authorized)."""
    if authorized:
        return
    texts_table = TEXTS if texts_table is None else texts_table
    readings = READINGS if readings is None else readings
    root = ROOT if root is None else root
    path = Path(path).resolve()
    if path.is_relative_to((Path(root) / 'data/ref').resolve()):
        raise ReadTextRefused(f'{path} is under data/ref/: the read texts are counted only by the production command')
    digest = _sha(path)
    for protected in (Path(texts_table), *map(Path, readings)):
        if protected.is_file() and _sha(protected) == digest:
            raise ReadTextRefused(f'{path} is a copy of {protected}')
    per_text, wholes = read_text_units(texts_table)
    if not per_text and not wholes:
        return
    raw = path.read_text(encoding='utf-8', errors='replace')
    # Line breaks are ignored, so a reflowed or rewrapped copy is still seen.
    joined = ' '.join(raw.split())
    flat = normal(joined)
    if any(whole and whole in flat for whole in wholes):
        raise ReadTextRefused(f'{path} holds a whole read text')
    # Sentences found line by line and in the joined text, so neither a
    # reflowed nor a rewrapped copy hides them.
    found = {normal(p) for line in raw.splitlines() for p in SENTENCE_END.split(line)}
    found |= {normal(p) for p in SENTENCE_END.split(joined)}
    for sentences in per_text:
        matched = len(sentences & found)
        if matched >= min(2, len(sentences)) and 2 * matched >= len(sentences) > 0:
            raise ReadTextRefused(f'{path} holds half or more of the sentences of a read text')
