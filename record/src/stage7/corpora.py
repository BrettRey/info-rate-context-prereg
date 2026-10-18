"""Read Stage 2 outputs into documents for the production command.

A corpus manifest names every Stage 2 file the command may read; nothing is
discovered. Entries:
    {"run": "main" | "wikipedia", "language": "SPA", "kind": "subtitles" | "wikipedia",
     "path": "data/raw/opensubtitles/SPA.tsv.gz", "sha256": "...",
     "thai_prose_lines": "80"}            # Thai Wikipedia entries only

Subtitles (columns group, folder, file, line, text): a document is one
subtitle file (`folder/file`), its group the Stage 2 group (a series for TV
episodes, the folder for a film), its lines in their original order. Where
Stage 2 dropped lines (the `line` positions jump), one gap line
(`GAP_LINE`, which the pipeline masks) stands in for them, so cross-line
context resets there (Brett, 2026-10-13).
Wikipedia (columns group, article, sentence, share, text): a document is one
article; its group is the Stage 2 row group of 1,000 page-id-ordered articles,
which `stage2_wikipedia.py` declares the split group. The stub setting drops
articles whose templated share is at or above the threshold; where articles
repeat one text, the first by ID represents them and its share decides (Brett,
2026-10-13), and what letting the smallest share decide would keep is reported
as `stub_rule_alternative`. Sentence numbers
there count kept sentences only, so the non-prose lines Stage 2 dropped leave
no gap to reset at (they would need the pass-1 cache's paragraph structure).

Two documents with identical lines are one source: the first by ID is kept
and the others listed, so the split can't put the same text on both sides.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

SCHEMA = 'production-corpora-v1'
GAP_LINE = '\ue000'  # the same as stage4/pipeline.py STAGE2_GAP
KINDS = ('subtitles', 'wikipedia')


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path, root):
    """Validate a corpus manifest; every file must exist and match its recorded hash."""
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA or not manifest.get('entries'):
        raise ValueError('Invalid corpus manifest')
    seen = set()
    for entry in manifest['entries']:
        keys = {'run', 'language', 'kind', 'path', 'sha256'} | ({'thai_prose_lines'} if 'thai_prose_lines' in entry else set())
        if set(entry) != keys or entry['kind'] not in KINDS or entry['run'] not in ('main', 'wikipedia'):
            raise ValueError(f'Invalid corpus manifest entry: {entry}')
        key = (entry['run'], entry['language'], entry.get('thai_prose_lines'))
        if key in seen:
            raise ValueError(f'Duplicate corpus entry: {key}')
        seen.add(key)
        path = (Path(root) / entry['path']).resolve()
        if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
            raise ValueError(f'Corpus file missing or outside the project: {entry["path"]}')
        if sha256_file(path) != entry['sha256']:
            raise ValueError(f'Corpus file changed since the manifest was written: {entry["path"]}')
    return manifest


def _rows(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE)


def read_subtitles(path):
    documents, groups = {}, {}
    for row in _rows(path):
        document = f"{row['folder']}/{row['file']}"
        if groups.setdefault(document, row['group']) != row['group']:
            raise ValueError(f'One subtitle file in two groups: {document}')
        documents.setdefault(document, []).append((int(row['line']), row['text']))
    return _finish(documents, groups)


def read_wikipedia(path, stub):
    threshold = float(stub)
    documents, shares, groups = {}, {}, {}
    for row in _rows(path):
        article = row['article']
        if shares.setdefault(article, row['share']) != row['share']:
            raise ValueError(f'One article with two templated shares: {article}')
        if groups.setdefault(article, row['group']) != row['group']:
            raise ValueError(f'One article in two row groups: {article}')
        documents.setdefault(article, []).append((int(row['sentence']), row['text']))
    # Duplicates are resolved before the stub filter, so every stub setting keeps
    # the same copy of a repeated text and the one split stays valid for all.
    corpus = _finish(documents, groups, gaps=False)
    kept = {a: t for a, t in corpus['texts'].items() if float(shares[a]) < threshold}
    # Reported, not used (Brett, 2026-10-13): the texts a rule letting the
    # smallest share in a duplicate group decide would keep in addition.
    smallest = {a: float(shares[a]) for a in corpus['texts']}
    for duplicate, representative in corpus['duplicates']:
        smallest[representative] = min(smallest[representative], float(shares[duplicate]))
    extra = sorted(a for a in corpus['texts'] if a not in kept and smallest[a] < threshold)
    alternative = dict(rule='smallest share in a duplicate group decides', documents=extra,
                       characters=sum(len(line) for a in extra for line in corpus['texts'][a]))
    return dict(texts=kept, groups={a: groups[a] for a in kept}, duplicates=corpus['duplicates'],
                dropped_stubs=sorted(set(corpus['texts']) - set(kept)), stub_rule_alternative=alternative)


def _finish(documents, groups, dropped_stubs=(), gaps=True):
    texts = {}
    for document, lines in documents.items():
        positions = [p for p, _ in lines]
        if positions != sorted(positions) or len(set(positions)) != len(positions):
            raise ValueError(f'Lines out of order or repeated in {document}')
        if any('\n' in t or '\r' in t or t == GAP_LINE for _, t in lines):
            raise ValueError(f'Embedded line break or gap marker in {document}')
        out = []
        for i, (position, text) in enumerate(lines):
            if gaps and i and position > lines[i - 1][0] + 1:
                out.append(GAP_LINE)  # Stage 2 dropped the lines between
            out.append(text)
        texts[document] = tuple(out)
    kept, duplicates, seen = {}, [], {}
    for document in sorted(texts):
        digest = hashlib.sha256('\n'.join(texts[document]).encode()).hexdigest()
        if digest in seen:
            duplicates.append([document, seen[digest]])
            continue
        seen[digest] = document
        kept[document] = texts[document]
    return dict(texts=kept, groups={d: groups[d] for d in kept}, duplicates=duplicates,
                dropped_stubs=list(dropped_stubs))


def read_entry(entry, root, stub):
    path = Path(root) / entry['path']
    return read_subtitles(path) if entry['kind'] == 'subtitles' else read_wikipedia(path, stub)


def write_documents(texts, directory):
    """One file per document under `directory`; returns {document: path}. Files are reused only if identical."""
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for document, lines in texts.items():
        data = ('\n'.join(lines) + '\n').encode('utf-8')
        path = directory / (hashlib.sha256(document.encode()).hexdigest() + '.txt')
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
        paths[document] = str(path)
    return paths
