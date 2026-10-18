"""Frozen Lexique 4.1 decoding, selection and integrity; no file discovery."""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import csv, hashlib, io, json, unicodedata
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
ROOT = Path(__file__).resolve().parents[2]
LEXIQUE_IPA = dict(zip('E O 9 2 @ 5 1 § 8 S Z N R G °'.split(),
                      'ɛ ɔ œ ø ɑ̃ ɛ̃ œ̃ ɔ̃ ɥ ʃ ʒ ɲ ʁ ŋ ə'.split()))
# Source uses literal "3" once (relish), also unconverted in its IPA column.
LEXIQUE_IPA['3'] = '3'
LEGACY_IPA = dict(LEXIQUE_IPA, **{'3': 'ə'})
FIELDS = ('word','phon','ipa','pos','lemma','frequency','syll','syll_nb')
TIE_RULE = 'descending Decimal frequency; ascending (POS, phon, ipa, lemma, syllabification, syllable-number string, original spelling, original frequency string)'

def decode_lexique(form, *, legacy=False):
    mapping = LEGACY_IPA if legacy else LEXIQUE_IPA
    return unicodedata.normalize('NFC', ''.join(mapping.get(c,c) for c in form))

def key(entry):
    frequency = Decimal(entry['frequency'])
    if not frequency.is_finite() or frequency < 0:
        raise ValueError('Invalid Lexique frequency')
    return (-frequency, *(entry[k] for k in ('pos','phon','ipa','lemma','syll','syll_nb','word','frequency')))

def group_entries(rows):
    grouped = {}
    for row in rows:
        word = unicodedata.normalize('NFC', row['word']).lower()
        grouped.setdefault(word, []).append(dict(row))
    return {w: tuple(sorted(rs, key=key)) for w,rs in sorted(grouped.items())}

def select_entries(rows):
    return {w: rs[0] for w,rs in group_entries(rows).items()}

def lowest_entry(entries):
    """Tally diagnostic: smallest frequency with the production ascending tie rule."""
    return min(entries, key=lambda r: (Decimal(r['frequency']), *key(r)[1:]))

# Hashes of the resource bytes read into memory, checked by the freeze lock.
__freeze_resources__ = {}


@lru_cache(maxsize=1)
def frozen():
    root = ROOT / 'resources'
    raw = (root/'fra-lexique-provenance.json').read_bytes()
    __freeze_resources__['resources/fra-lexique-provenance.json'] = hashlib.sha256(raw).hexdigest()
    meta = json.loads(raw.decode('utf-8'))
    data = (root/'fra_lexique.tsv').read_bytes()
    checksum=hashlib.sha256(data).hexdigest()
    __freeze_resources__['resources/fra_lexique.tsv'] = checksum
    if checksum != meta['sha256']:
        raise ValueError('Frozen lexicon checksum mismatch: fra_lexique.tsv')
    grouped = group_entries(csv.DictReader(io.StringIO(data.decode('utf-8')),delimiter='\t'))
    entries = MappingProxyType({w: tuple(MappingProxyType(r) for r in rs) for w,rs in grouped.items()})
    selected = MappingProxyType({w:rs[0] for w,rs in entries.items()})
    descriptor={k:meta[k] for k in ('source','release','license','citation','source_sha256','sha256','selection_policy','schwa_policy','nonstandard_3_policy')}
    return selected, entries, descriptor
