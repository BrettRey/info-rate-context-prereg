"""Derive the word lists that onset inventories are learned from, offline.

Brett, 2026-10-15: a training word type counts toward an onset's type and token
counts only if the language's Wiktionary lists it, as a headword or a form, so
names and loanwords read with the language's rules (English *st* in Catalan)
don't define its onsets. One list per onset language: every headword and every
`forms[].form` of the language's Wiktextract extract, NFC-normalised and
lowercased as `onsets.collect` keys types, without strings that contain
whitespace or no letter (multiword forms never match a token) and without the
table and template rows Wiktextract stores among the forms. Serbo-Croatian forms
carry tone and length marks that running text never has (*jȅste*, *bȉo*), so for
SRP the combining marks on vowels and syllabic r are removed; č, ć, š, ž and đ
are letters and stay. Nothing is generated or inferred.

The lists are written gzipped (mtime 0, so a rebuild is byte-identical) to
data/interim/onset-lexicons/ by default, which is not committed (they are large;
Claude's choice, 2026-10-15). resources/onset-lexicons-provenance.json, which is
committed and bound by the freeze, records each list's SHA-256, and the onset
code checks a list against it before use.

    python -I -B src/stage3/build_onset_lexicons.py [--source DIR] [--out DIR]
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
# Onset languages (training_onsets: every language but CMN, YUE, VIE, KOR, JPN, THA)
# and their Wiktextract language codes; Serbian is under Serbo-Croatian.
CODES = {'CAT': 'ca', 'DEU': 'de', 'ENG': 'en', 'EUS': 'eu', 'FIN': 'fi', 'FRA': 'fr',
         'HUN': 'hu', 'ITA': 'it', 'SPA': 'es', 'SRP': 'sh', 'TUR': 'tr'}
TEMPLATE_TAGS = {'table-tags', 'inflection-template', 'class'}
SOURCE = {"source": "English Wiktionary, Wiktextract language extracts",
          "raw_extract": "https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz",
          "raw_extract_bytes": 2981058381,
          "raw_extract_sha256": "3dac8a09e57827bef493e2e6b552fe917bf3b1fc55dee05c4e4a3702aff5dbdb",
          "dump_date": "2026-09-02", "extract_date": "2026-10-03",
          "filter": "src/stage3_wiktionary_filter.py (main repository), DECISIONS.md 2026-10-10",
          "license": "CC BY-SA 4.0 and GFDL",
          "citation": "Ylonen, Tatu (2022). Wiktextract: Wiktionary as Machine-Readable Structured Data. LREC 2022, pp. 1317–1325.",
          "citation_url": "https://aclanthology.org/2022.lrec-1.140/",
          "lists_committed": False,
          "lists_location": "data/interim/onset-lexicons/<LANG>.txt.gz (gitignored; rebuild with this script)"}
PROSODIC_MARKS = {'̀', '́', '̂', '̄', '̆', '̏', '̑'}
PROSODIC_BEARERS = set('aeiouAEIOUrRаеиоуАЕИОУрР')


def strip_prosody(text):
    """Serbo-Croatian: drop tone/length marks on vowels and syllabic r only."""
    out = []
    for c in unicodedata.normalize('NFD', text):
        if c in PROSODIC_MARKS and out and out[-1] in PROSODIC_BEARERS:
            continue
        out.append(c)
    return unicodedata.normalize('NFC', ''.join(out))


def key(text, language):
    text = unicodedata.normalize('NFC', text)
    if language == 'SRP':
        text = strip_prosody(text)
    return unicodedata.normalize('NFC', text).lower()


def usable(text):
    return bool(text) and not any(c.isspace() for c in text) and any(c.isalpha() for c in text)


def derive(stream, language):
    words, summary = set(), dict(entries=0, headwords=0, forms=0, template_rows=0, unusable=0)
    for line in stream:
        entry = json.loads(line)
        summary['entries'] += 1
        candidates = [(entry.get('word') or '', 'headwords')]
        for form in entry.get('forms') or ():
            if not isinstance(form, dict):
                continue
            if TEMPLATE_TAGS & set(form.get('tags') or ()):
                summary['template_rows'] += 1
                continue
            candidates.append((form.get('form') or '', 'forms'))
        for text, kind in candidates:
            if not usable(text):
                summary['unusable'] += 1
                continue
            summary[kind] += 1
            words.add(key(text, language))
    summary['words'] = len(words)
    return sorted(words), summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/interim/wiktionary')
    parser.add_argument('--out', type=Path, default=ROOT / 'data/interim/onset-lexicons')
    parser.add_argument('--provenance', type=Path, default=ROOT / 'resources/onset-lexicons-provenance.json')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    meta = dict(SOURCE, builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                policy='a training word type counts toward onset counts only if its NFC-lowercased key is a listed '
                       'headword or form (Brett, 2026-10-15); SRP keys without tone/length marks',
                lists={})
    for language, code in sorted(CODES.items()):
        source = args.source / f'{code}.jsonl.gz'
        with source.open('rb') as f:
            input_sha256 = hashlib.file_digest(f, 'sha256').hexdigest()
        with gzip.open(source, 'rt', encoding='utf-8') as stream:
            words, summary = derive(stream, language)
        data = gzip.compress(('\n'.join(words) + '\n').encode('utf-8'), compresslevel=9, mtime=0)
        (args.out / f'{language}.txt.gz').write_bytes(data)
        meta['lists'][language] = dict(summary, wiktionary_code=code, input=f'data/interim/wiktionary/{code}.jsonl.gz',
                                       input_sha256=input_sha256, sha256=hashlib.sha256(data).hexdigest(),
                                       bytes=len(data), prosody_stripped=language == 'SRP')
        print(language, json.dumps(meta['lists'][language], sort_keys=True), flush=True)
    args.provenance.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
