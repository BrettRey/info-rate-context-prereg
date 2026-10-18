"""Prepare linguistic resources and estimator inputs from explicit split files.

No discovery: documents is {id: path}, splits names train/validation/test IDs.
Onsets are counted on isolated TRAINING word types, with token frequencies;
syllable vocabularies come only from retained TRAINING lines. Held-out OOVs
are refused until an analytical OOV policy is approved. No fitting occurs.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import argparse
from array import array
import collections
from collections import Counter
import gzip
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unicodedata
import zlib

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('linguistic_pipeline', Path(__file__).with_name('pipeline.py'))
P = importlib.util.module_from_spec(_spec); sys.modules[_spec.name] = P; _spec.loader.exec_module(P)


# Brett, 2026-10-15: onsets are learned from word types the language's Wiktionary
# lists; every training type ('all-types', the inventory as first built) is a
# one-at-a-time sensitivity check (src/stage3/multiverse.py PREPARATION_CHECKS).
ONSET_SOURCES = ('lexicon', 'all-types')
ONSET_LEXICON_ROOT = ROOT / 'data/interim/onset-lexicons'
# Resource hashes this module read, checked by the freeze lock (src/stage3/freeze.py).
__freeze_resources__ = {}


def _onset_lexicon_provenance():
    raw = (ROOT / 'resources/onset-lexicons-provenance.json').read_bytes()
    __freeze_resources__['resources/onset-lexicons-provenance.json'] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8'))


ONSET_LEXICON_PROVENANCE = _onset_lexicon_provenance()


def onset_lexicon_listed(language, keys):
    """The keys the language's onset lexicon lists, and the list's identity.

    The lists aren't committed (src/stage3/build_onset_lexicons.py writes them to
    data/interim/onset-lexicons/); each is checked against the SHA-256 the committed
    provenance records before it is read, and streamed against the keys rather than
    held, since Finnish lists 25 million forms.
    """
    entry = ONSET_LEXICON_PROVENANCE['lists'].get(language)
    if entry is None:
        raise ValueError('No onset lexicon is declared for ' + language)
    path = ONSET_LEXICON_ROOT / f'{language}.txt.gz'
    if not path.is_file():
        raise ValueError(f'Onset lexicon missing: {path}; rebuild it with src/stage3/build_onset_lexicons.py')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError('Onset lexicon checksum mismatch: ' + language)
    wanted = set(keys)
    with gzip.open(io.BytesIO(data), 'rt', encoding='utf-8') as stream:
        found = {word for word in (line.rstrip('\n') for line in stream) if word in wanted}
    return found, dict(kind='frozen', sha256=entry['sha256'], words=entry['words'],
                       provenance='resources/onset-lexicons-provenance.json')


def supplied_onset_lexicon(words):
    """A caller-supplied list (simulated runs only), keyed as `onsets.collect` keys types."""
    if isinstance(words, str) or any(not isinstance(w, str) or not w for w in words):
        raise ValueError('A supplied onset lexicon is a collection of nonempty words')
    keyed = sorted({unicodedata.normalize('NFC', w).lower() for w in words})
    return frozenset(keyed), dict(kind='caller-supplied', sha256=P.digest(P.canonical(keyed).encode()),
                                  words=len(keyed))


def read_documents(documents, splits):
    splits = {s: tuple(ids) for s, ids in splits.items()}
    if set(splits) != {'train', 'validation', 'test'} or any(not ids for ids in splits.values()):
        raise ValueError('Supply three nonempty document splits')
    ids = tuple(d for split in splits.values() for d in split)
    if len(set(ids)) != len(ids) or set(ids) != set(documents):
        raise ValueError('Split manifest must partition every supplied document exactly once')
    texts, hashes, paths = {}, {}, {}
    for document in ids:
        if not isinstance(document, str) or not document:
            raise ValueError('Document IDs must be nonempty strings')
        path = Path(documents[document]).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Corpus input must be inside the supplied project checkout')
        raw = path.read_bytes()
        texts[document] = tuple(raw.decode('utf-8').splitlines())
        hashes[document] = hashlib.sha256(raw).hexdigest()
        paths[document] = path
    # Distinct IDs aren't distinct sources: one file, or two identical ones,
    # under two IDs would put the same text in two splits.
    if len(set(paths.values())) != len(paths) or len(set(hashes.values())) != len(hashes):
        raise ValueError('Two documents share a source file or identical content; deduplicate before splitting')
    return texts, splits, hashes


def configuration_id(declaration):
    return P.digest(P.canonical(declaration).encode())


def training_onsets(texts, splits, declaration, output, *, g2p=None, floor=3, gap_treatment,
                    excluded_lines=None, scope=None, onset_source='lexicon', onset_lexicon=None, cache_dir=None):
    """Use isolated counter readings from training only, never held-out types.

    scope (Brett, 2026-10-13): None for the whole training split, or a B₀
    prefix {document: leading lines}, the same size in every language, so the
    floor doesn't admit more rare clusters in larger corpora.

    onset_source (Brett, 2026-10-15): 'lexicon', a type counts toward an onset's
    type and token counts only if the language's onset lexicon lists it (the frozen
    list, or onset_lexicon, a caller-supplied collection, in simulations);
    'all-types' counts every training type, the one-at-a-time check. The source
    metadata records which, the list's identity and its coverage of training.

    cache_dir: the G2P cache folder, by default `g2p-cache` inside `output`.

    Bootstrap with an empty inventory solely to obtain the effective word trace;
    these provisional cuts are discarded. Native/non-onset routes carry an
    explicit not-applicable resource record.
    """
    M = P.registry(); O = M.S.O
    language, option = declaration['language'], declaration['option']
    if onset_source not in ONSET_SOURCES:
        raise ValueError('onset_source must be lexicon (Brett, 2026-10-15) or all-types')
    if onset_lexicon is not None and onset_source != 'lexicon':
        raise ValueError('A supplied onset lexicon needs onset_source=lexicon')
    if language in M.NO_ONSET_INVENTORY:
        value = dict(applicable=False, reason='fixed character/block/written-syllable/native-reader units',
                     declaration=declaration, training_documents=list(splits['train']),
                     gap_treatment=gap_treatment)
        path = Path(output) / 'onsets-not-applicable.json'
        P.atomic(path, (P.canonical(value)+'\n').encode())
        return None, dict(value, path=str(path.resolve()), sha256=P.digest(path.read_bytes()))
    frequencies, prons = Counter(), {}
    g2p_descriptor = None
    kwargs = P.registry_configuration(declaration, inventory=frozenset(), g2p=g2p)
    learned = list(scope) if scope is not None else list(splits['train'])
    for document in learned:
        report = P.process_document(document, texts[document], language, option,
            Path(output) / 'bootstrap', cache_dir=Path(cache_dir) if cache_dir is not None else Path(output) / 'g2p-cache',
            declaration=declaration, _scan_only=True, gap_treatment=gap_treatment, **kwargs)
        g2p_descriptor = report['config']['g2p']
        for i, line in enumerate(report['lines']):
            if (line['status'] != 'complete' or i in (excluded_lines or {}).get(document, ())
                    or (scope is not None and i >= scope[document])):
                continue
            for word in line.get('words', ()):
                if not word['g2p']:
                    continue
                value = word['g2p']['pronunciation']
                key = word['text']
                if key in prons and prons[key] != value:
                    raise ValueError('Training word type has conflicting contextual pronunciations')
                prons[key] = value; frequencies[key] += 1
    opts = dict(declaration['counter_options'])
    if language == 'CAT' and option == 'B':
        opts['i_attachment'] = declaration['settings']['i_attachment']
    # One record per type (NFC, lowercased, as `collect` keys types). The spellings of
    # one type can read differently (an odd-cased form spelled out letter by letter, a
    # cased name), so the type takes its most frequent spelling's reading and every
    # spelling's tokens; a tie goes to the first spelling in code-point order.
    spellings = {}
    for word in sorted(frequencies):
        spellings.setdefault(unicodedata.normalize('NFC', word).lower(), []).append(word)
    tokens = {key: sum(frequencies[w] for w in spellings[key]) for key in spellings}
    if onset_source == 'all-types':
        listed, lexicon = set(spellings), None
    elif onset_lexicon is None:
        listed, lexicon = onset_lexicon_listed(language, spellings)
    else:
        supplied, lexicon = supplied_onset_lexicon(onset_lexicon)
        listed = set(spellings) & supplied
    records = []
    for key in sorted(listed):
        word = max(spellings[key], key=frequencies.__getitem__)
        counted = O.C.COUNTERS[language][option](word, pronunciations={word: prons[word]}, **opts)
        records.append({'word': word, 'counter_result': counted, 'tokens': tokens[key]})
    coverage = dict(training_types=len(spellings), listed_types=len(listed),
                    training_tokens=sum(tokens.values()), listed_tokens=sum(tokens[k] for k in listed))
    source = {'kind': 'training-split-only' if scope is None else 'training-B0-prefix', 'documents': learned,
              'onset_source': onset_source, 'onset_lexicon': lexicon, 'onset_coverage': coverage,
              'input_sha256': {d: P.digest(P.canonical(texts[d]).encode()) for d in learned},
              'declaration': declaration, 'gap_treatment': gap_treatment, 'g2p': g2p_descriptor,
              'onset_scope': None if scope is None else [[d, n] for d, n in scope.items()],
              'excluded_training_lines': {d: list((excluded_lines or {}).get(d, ())) for d in learned}}
    inventory = O.collect(records, language, option, floor=floor, counter_options=opts, source=source)
    path = Path(output) / 'onsets.tsv'
    O.write(inventory, path)
    descriptor = inventory.descriptor()
    descriptor['inventory_sha256'] = descriptor.pop('sha256')
    return inventory, dict(applicable=True, path=str(path.resolve()),
        sha256=P.digest(path.read_bytes()), onset_source=onset_source, onset_lexicon=lexicon,
        onset_coverage=coverage, **descriptor)


def check_prefix(pairs, splits, texts):
    """[[document, n], ...]: a prefix of the training documents in split order, whole
    documents except the last, which keeps its first n source lines. Returns a dict."""
    if not isinstance(pairs, (list, tuple)) or any(not isinstance(x, (list, tuple)) or len(x) != 2 for x in pairs):
        raise ValueError('A budget cut is an ordered list of [document, leading lines]')
    order = [d for d, _ in pairs]
    if not order or order != list(splits['train'][:len(order)]):
        raise ValueError('A budget cut must be a prefix of the training documents in split order')
    for i, (d, n) in enumerate(pairs):
        total = len(texts[d])
        if type(n) is not int or not 0 < n <= total or (i < len(order) - 1 and n != total):
            raise ValueError('A budget cut keeps whole documents except the last, by leading lines')
    return {d: n for d, n in pairs}


def cut_training(reports, splits, budget, *, texts=None):
    """Training reports cut to a budget's prefix; validation and test untouched.

    The prefix must follow the split's training order: every document before the
    last kept in full, the last one by its leading source lines. With `texts`,
    line counts come from the source, so reports are needed only for the
    documents the cut keeps.
    """
    if budget is None:
        return reports, dict(splits)
    lines = check_prefix(budget['lines'], splits, texts if texts is not None
                         else {d: reports[d]['lines'] for d in splits['train']})
    order = list(lines)
    cut = dict(reports)
    for d in order:
        kept = reports[d]['lines'][:lines[d]]
        cut[d] = dict(reports[d], lines=kept, encoded_syllables=sum(len(line['syllables']) for line in kept))
    return cut, dict(splits, train=tuple(order))


def named_shared(declared, job_shared, language, SHARED):
    """A named universe's shared settings as they apply to one language's jobs (shared_settings.restrict)."""
    return SHARED.restrict(declared, job_shared, language)


def flag_pairs(lines):
    """(word-initial flag, label) for every retained syllable, as the flagged rungs see them."""
    pairs = set()
    for line in lines:
        group = line['syllables'] if line.get('status') != 'masked' else []
        for i, syllable in enumerate(group):
            pairs.add((int(i == 0 or syllable['owner'] != group[i-1]['owner']), syllable['label']))
    return pairs


POOLED = '<rare>'
POOLED_TARGET = 'p'  # a flagged rung's pooled target is b<flag>sp, outside the vocabulary (Codex review)


class PoolingUnsupported(ValueError):
    """Held-out text needs the pooled symbol but training has nothing rare enough to support it."""


def pool_rare(cut, used, heldout):
    """The pooled unknown symbol (Brett, 2026-10-15: "hapax is fine").

    A syllable seen once in this budget's training text, and a held-out syllable
    outside what is left, are relabelled `POOLED`, an ordinary vocabulary item, so
    the models learn its probability from rare syllables' contexts. On the flagged
    rungs the same holds for (word-initial flag, syllable) pairs: the pairs returned
    are those seen at least twice with an unpooled syllable, and `encode` gives any
    other pair's target its own token (`POOLED_TARGET`), so the vocabulary the plain
    rungs and the neural models use keeps only what training supports.
    Lines are copied (budgets share the scan reports). The record keeps each pooled
    held-out token's original label, so escape coding can be added when scoring.
    """
    counts = collections.Counter(s['label'] for d in used['train'] for line in cut[d]['lines'] for s in line['syllables'])
    if POOLED in counts:
        raise ValueError('A syllable label collides with the pooled symbol')
    kept = {label for label, n in counts.items() if n > 1}
    relabelled, record = dict(cut), dict(schema='pooled-v1', training_hapax=sorted(set(counts) - kept),
                                         heldout_syllables={}, heldout_pairs={})
    for d in (*used['train'], *heldout):
        lines, changed = [], []
        for i, line in enumerate(cut[d]['lines']):
            syllables = []
            for j, s in enumerate(line['syllables']):
                if s['label'] in kept:
                    syllables.append(s)
                else:
                    syllables.append(dict(s, label=POOLED))
                    if d in heldout:
                        changed.append([i, j, s['label']])
            lines.append(dict(line, syllables=syllables))
        relabelled[d] = dict(cut[d], lines=lines)
        if changed:
            record['heldout_syllables'][d] = changed
    if record['heldout_syllables'] and not record['training_hapax']:
        raise PoolingUnsupported('A held-out syllable needs the pooled symbol, but no training syllable '
                         'was rare enough to give it support')
    pair_counts = collections.Counter()
    for d in used['train']:
        for line in relabelled[d]['lines']:
            group = line['syllables'] if line.get('status') != 'masked' else []
            for i, s in enumerate(group):
                pair_counts[(int(i == 0 or s['owner'] != group[i-1]['owner']), s['label'])] += 1
    allowed = {pair for pair, n in pair_counts.items() if n > 1 and pair[1] != POOLED}
    supported = {f for (f, label), n in pair_counts.items() if n == 1 or label == POOLED}
    for d in heldout:
        changed = []
        for i, line in enumerate(relabelled[d]['lines']):
            group = line['syllables'] if line.get('status') != 'masked' else []
            for j, s in enumerate(group):
                f = int(j == 0 or s['owner'] != group[j-1]['owner'])
                if (f, s['label']) not in allowed:
                    if f not in supported:
                        raise PoolingUnsupported('A held-out flag+syllable pair needs the pooled symbol, but no '
                                         'training pair with that flag was rare enough to give it support')
                    if s['label'] != POOLED:
                        changed.append([i, j, f, s['label']])
        if changed:
            record['heldout_pairs'][d] = changed
    record['pooled_flags'] = sorted(supported)
    return relabelled, record, allowed


def oov_counts(cut, heldout, vocabulary, trained):
    """How much held-out text is unseen in training, as counts only (no labels kept).

    Over retained lines, as the rungs see them: syllable tokens whose label is
    outside the training vocabulary, tokens whose label is in it but whose
    (word-initial flag, label) pair training never saw, and the lines either
    touches. Unseen targets for the flagged rungs are the two token counts summed.
    """
    tokens = lines = touched = unseen = unseen_pairs = 0
    types, pair_types = set(), set()
    for d in heldout:
        for line in cut[d]['lines']:
            group = line['syllables'] if line.get('status') != 'masked' else []
            if not group:
                continue
            lines += 1; hit = False
            for i, syllable in enumerate(group):
                tokens += 1
                pair = (int(i == 0 or syllable['owner'] != group[i-1]['owner']), syllable['label'])
                if syllable['label'] not in vocabulary:
                    unseen += 1; types.add(syllable['label']); hit = True
                elif pair not in trained:
                    unseen_pairs += 1; pair_types.add(pair); hit = True
            touched += hit
    return dict(heldout_syllable_tokens=tokens, heldout_lines=lines, lines_touched=touched,
                unseen_syllable_types=len(types), unseen_syllable_tokens=unseen,
                unseen_pair_types=len(pair_types), unseen_pair_tokens=unseen_pairs)


def corpus_vectors(lines, vocabulary, treatment):
    syllables, initial, starts, resets = [], [], [], []
    reset = True
    for line in lines:
        if line.get('status') == 'masked':
            reset = True
            continue
        group = line['syllables']
        if not group:
            continue
        offset = len(syllables)
        if reset:
            resets.append(offset)
        if treatment == 'line-bounded' or reset:
            starts.append(offset)
        for i, syllable in enumerate(group):
            syllables.append(vocabulary[syllable['label']])
            initial.append(int(i == 0 or syllable['owner'] != group[i-1]['owner']))
        reset = False
    if not syllables:
        raise ValueError('Document has no retained syllables; revise the explicit split manifest')
    return dict(syllables=syllables, initial=initial, starts=starts, reset_starts=resets)


RECORD_SCHEMA = 'syllable-record-v1'
_STATUSES = ('complete', 'masked', 'blocked')


def write_record(path, reports, order):
    """The scanned syllables a declaration's token files are built from (P9, Brett 2026-10-15).

    Written once per declaration, since every budget label is a cut of it, so that
    `prepare` can record each token file's digest without keeping the file and
    `materialise` can rebuild the file just before a job reads it. A syllable is an
    index into the record's label table and a word-initial bit: the encoders read an
    owner only to ask whether a syllable starts a word. zlib over a JSON header and
    little-endian integer arrays. Returns the record's digest.
    """
    labels = sorted({s['label'] for d in order for line in reports[d]['lines'] for s in line['syllables']})
    index = {label: i for i, label in enumerate(labels)}
    statuses, lengths, ids, initial = array('B'), array('I'), array('I'), bytearray()
    for d in order:
        for line in reports[d]['lines']:
            statuses.append(_STATUSES.index(line['status']))
            group = line['syllables']; lengths.append(len(group))
            for i, s in enumerate(group):
                ids.append(index[s['label']]); initial.append(int(i == 0 or s['owner'] != group[i-1]['owner']))
    if sys.byteorder != 'little':
        lengths.byteswap(); ids.byteswap()
    header = P.canonical(dict(schema=RECORD_SCHEMA, documents=list(order), labels=labels,
                              line_counts=[len(reports[d]['lines']) for d in order],
                              encoded_syllables=[reports[d]['encoded_syllables'] for d in order])).encode()
    data = zlib.compress(struct.pack('<I', len(header)) + header + statuses.tobytes() + lengths.tobytes()
                         + ids.tobytes() + bytes(initial), 6)
    P.atomic(path, data)
    return P.digest(data)


_RECORD = {}  # the last record read, by path and digest: jobs of one declaration come together


def read_record(path, sha256):
    """The compact scan reports a record holds, checked against its digest; owners are word counters."""
    key = (str(path), sha256)
    if key in _RECORD:
        return _RECORD[key]
    data = Path(path).read_bytes()
    if P.digest(data) != sha256:
        raise ValueError(f'Syllable record differs from its recorded digest: {path}')
    raw = zlib.decompress(data)
    (size,) = struct.unpack('<I', raw[:4])
    header = json.loads(raw[4:4 + size])
    if header.get('schema') != RECORD_SCHEMA:
        raise ValueError(f'Not a syllable record: {path}')
    n_lines = sum(header['line_counts'])
    offset = 4 + size
    statuses = array('B', raw[offset:offset + n_lines]); offset += n_lines
    lengths = array('I'); lengths.frombytes(raw[offset:offset + 4 * n_lines]); offset += 4 * n_lines
    if sys.byteorder != 'little':
        lengths.byteswap()
    n = sum(lengths)
    ids = array('I'); ids.frombytes(raw[offset:offset + 4 * n]); offset += 4 * n
    if sys.byteorder != 'little':
        ids.byteswap()
    initial = raw[offset:offset + n]
    if offset + n != len(raw) or len(initial) != n:
        raise ValueError(f'Syllable record is truncated or has trailing bytes: {path}')
    labels, reports, line, k = header['labels'], {}, 0, 0
    for d, count, encoded in zip(header['documents'], header['line_counts'], header['encoded_syllables']):
        lines = []
        for _ in range(count):
            group, owner = [], -1
            for _ in range(lengths[line]):
                owner += initial[k]
                group.append(dict(label=labels[ids[k]], owner=owner)); k += 1
            lines.append(dict(status=_STATUSES[statuses[line]], syllables=group)); line += 1
        reports[d] = dict(lines=lines, encoded_syllables=encoded)
    _RECORD.clear(); _RECORD[key] = reports
    return reports


SCHEMA = 'linguistic-inputs-v2'
# Job fields shared with the preparation: stored once in its manifest and rebuilt on
# reading (P9 at real size; DECISIONS.md, 2026-10-16).
BY_REFERENCE = ('documents', 'source_hashes', 'realised_syllables', 'word_corpora')


def token_path(base, treatment, rung, document):
    return base / treatment / rung / (P.digest(document.encode()) + '.txt')


def split_path(base, treatment, rung, split):
    return base / treatment / rung / (split + '.txt')


def corpus_path(base, treatment, document):
    return base / treatment / 'word-corpora' / (P.digest(document.encode()) + '.json')


def word_corpus(document, lines, vocabulary, treatment, provenance):
    """A neural job's per-document input, as `prepare` hashes it and `materialise` writes it."""
    value = dict(schema='word-corpus-v1', document=document, **corpus_vectors(lines, vocabulary, treatment),
                 provenance=provenance)
    return (P.canonical(value)+'\n').encode()


def compact(report):
    """The parts of a scan report the cut, the vocabulary, the checks and the encoders read.

    The full report (counter trace, configuration, provenance) is about 19 KB a
    line; keeping every document's for a declaration doesn't fit real corpora.
    """
    return dict(lines=[dict(status=line['status'], syllables=[dict(label=s['label'], owner=s['owner'])
                                                               for s in line['syllables']])
                       for line in report['lines']],
                encoded_syllables=report['encoded_syllables'])


def _check_label(language, shared, budget, gap_treatment, SHARED):
    if shared is not None and 'line' in shared:
        raise ValueError('The line label is set per treatment by prepare; do not supply it in shared')
    if shared is not None and 'gap' in shared and shared['gap'] != gap_treatment:
        raise ValueError('shared gap label differs from the gap_treatment the files are built with')
    if shared is not None:
        SHARED.check(shared, language)
    if budget is not None and (not isinstance(budget, dict)
                               or set(budget) != {'label', 'target', 'B0', 'units_sha256', 'lines', 'onset_lines'}
                               or budget['label'] not in SHARED.FORKS['budget']):
        raise ValueError('budget must come from budgets.budget_argument, with a registry budget label')
    if (budget is None) != ((shared or {}).get('budget') is None) or (
            budget is not None and shared['budget'] != budget['label']):
        raise ValueError('shared budget label must be supplied exactly when a budget cut is, and equal its label')


def prepare(documents, splits, language, output=None, *, backends=None, floor=3,
            gap_treatment, simulated=False, shared=None, named_inputs=None,
            neural_settings=None, oov_policy='pooled-hapax', include_calibration=False, kenlm_peak_bytes=None,
            budget=None, labels=None, provisional_mask=None, onset_source='lexicon', onset_lexicon=None,
            g2p_cache=None, check=None):
    """Return a hashed preparation manifest and runnable ordered job specs.

    Production neural jobs are restricted to ready authoritative named
    declarations. With no named_inputs, neural files are prepared but the job
    list is pending. simulated=True emits small-scale neural jobs for all
    declarations, using caller settings; it never authorizes corpus discovery.

    budget (Brett, 2026-10-13): None, or {'label': 'B' | 'B/2' | '3B', 'lines':
    [[document, n], ...], 'onset_lines': [[document, n], ...], 'target', 'B0',
    'units_sha256'} from src/stage4/budgets.py: prefixes of the training
    documents in split order, each with its leading source lines, checked against
    a recomputation from this preparation's own training units. onset_lines is the B₀ prefix for every label: the onset
    inventories, and so the mask, are learned from it and stay the same across
    budgets; `lines` cuts only the training text behind vocabularies, files and
    jobs. Without a budget (the counts pass) onsets come from the whole split.

    onset_source (Brett, 2026-10-15): 'lexicon' (the default) learns onsets only
    from training types the language's Wiktionary lists; 'all-types' and floors 1
    and 10 are one-at-a-time sensitivity checks. onset_lexicon: a caller-supplied
    word collection in place of the frozen list, simulated runs only.

    labels (P8, result-neutral): a list of {'output', 'shared', 'budget'} for the
    budget labels of one text variant, which share the B₀ onset prefix; the scan
    (masks, onsets, per-document reports) is made once and each label is cut,
    encoded and written as a single call would; returns the manifests in label
    order. provisional_mask: the counts phase's mask for these documents (empty
    onset inventories), used in place of rebuilding it and checked document by
    document. The first-listed declaration covers every document (its per-line
    counts are the training units the budgets are verified against; documents no
    cut uses are counted as the counts phase counts them); the others only the
    held-out documents and the training prefix the largest cut uses.

    g2p_cache (P9, item 8a, result-neutral): one G2P cache folder for every scan
    here (the provisional and removal masks, the onset inventories and the
    per-declaration scans). Entries are keyed by G2P signature and word, so
    declarations share them; the default keeps a folder per use, as before.

    check: a check view's id (`multiverse.check_views`; design in DECISIONS.md,
    2026-10-16). The preparation then covers that view's declarations, its masks
    record the view, and its manifest and marker name it; without one it covers the
    universes, as before.
    """
    # No default gap treatment: both are forks, and drop is the first-listed one
    # (notes/multiverse-spec.md, Brett 2026-10-10). Labels must describe the build.
    if gap_treatment not in ('drop', 'split'):
        raise ValueError('Declare gap_treatment: drop or split (drop is first-listed)')
    single = labels is None
    labels = [dict(output=output, shared=shared, budget=budget)] if single else [dict(l) for l in labels]
    if not labels or any(set(l) != {'output', 'shared', 'budget'} for l in labels):
        raise ValueError('labels must be a list of {output, shared, budget}')
    SHARED = P.registry().S._load('linguistic_shared_settings', ROOT / 'src/stage3/shared_settings.py')
    for label in labels:
        _check_label(language, label['shared'], label['budget'], gap_treatment, SHARED)
    if named_inputs is not None and not simulated:
        SHARED.check_order(named_inputs.get('shared_settings', {}))
    budgets = [l['budget'] for l in labels]
    if len(labels) > 1 and (any(b is None for b in budgets) or len({P.canonical(
            [b['onset_lines'], b['units_sha256'], b['B0']]) for b in budgets}) != 1):
        raise ValueError('Labels prepared together must be budget cuts of one plan with one onset prefix')
    if oov_policy not in ('pooled-hapax', 'error'):
        raise ValueError('OOV policy must be pooled-hapax (Brett, 2026-10-15) or error')
    if type(floor) is not int or floor < 1:
        raise ValueError('Onset floor must be a positive integer')
    if onset_source not in ONSET_SOURCES:
        raise ValueError('onset_source must be lexicon (Brett, 2026-10-15) or all-types')
    if onset_lexicon is not None and (not simulated or onset_source != 'lexicon'):
        raise ValueError('A supplied onset lexicon is for simulated runs with onset_source=lexicon')
    lexicon_identity = None if onset_lexicon is None else supplied_onset_lexicon(onset_lexicon)[1]
    # The marker binds the list the inventories will read, so an interrupted
    # preparation can't resume against a rebuilt list (review-p9integrate-20261015).
    if lexicon_identity is None and onset_source == 'lexicon' and language not in P.registry().NO_ONSET_INVENTORY:
        entry = ONSET_LEXICON_PROVENANCE['lists'].get(language)
        if entry is None:
            raise ValueError('No onset lexicon is declared for ' + language)
        lexicon_identity = dict(kind='frozen', sha256=entry['sha256'], words=entry['words'],
                                provenance='resources/onset-lexicons-provenance.json')
    if kenlm_peak_bytes is not None and (type(kenlm_peak_bytes) is not int or kenlm_peak_bytes < 1):
        raise ValueError('KenLM disk reservation must be a positive integer')
    texts, splits, hashes = read_documents(documents, splits)
    # Production inputs come only from the registry routes: no supplied G2P
    # backends, full segmentation, real counters, under the common mask.
    production = not simulated and not backends
    outputs = [Path(l['output']).resolve() for l in labels]
    if any(not o.is_relative_to(ROOT) for o in outputs) or len(set(outputs)) != len(outputs):
        raise ValueError('Preparation outputs must be distinct folders inside the supplied project checkout')
    first_output = outputs[0]
    backends = dict(backends or {})
    declarations = P.registry().declarations(language, include_calibration=include_calibration, check=check)
    if check is not None and dict(onset_source=onset_source, floor=floor) != \
            P.registry().check_view(language, check)['preparation']:
        raise ValueError('A check preparation must use its view\'s onset source and floor')
    markers = []
    for label, out in zip(labels, outputs):
        preparation = dict(language=language, splits=splits, source_sha256=hashes, floor=floor,
            onset_source=onset_source, onset_lexicon=lexicon_identity, gap_treatment=gap_treatment, simulated=simulated, shared=label['shared'], named_inputs=named_inputs,
            neural_settings=neural_settings, oov_policy=oov_policy, include_calibration=include_calibration,
            kenlm_peak_bytes=kenlm_peak_bytes, budget=label['budget'],
            backends={k: v.descriptor() for k, v in backends.items()}, versions=P.version(),
            builder_sha256=P.digest(Path(__file__).read_bytes()))
        if check is not None:
            preparation['check'] = check
        preparation = json.loads(P.canonical(preparation))
        marker = out / 'preparation.json'
        if marker.exists():
            if json.loads(marker.read_text()) != preparation:
                raise ValueError('Refusing preparation resume with changed source/configuration/splits')
        else:
            P.atomic(marker, (P.canonical(preparation)+'\n').encode())
        markers.append(marker)
    def bootstrap(declaration):
        key = configuration_id(declaration)
        return dict(P.registry_configuration(declaration, inventory=frozenset(),
                    g2p=backends.get(key, backends.get(language))), gap_treatment=gap_treatment)
    if provisional_mask is not None:
        provisional = P.read_mask(provisional_mask)
        # It covers the whole corpus; these documents are the split's, which leaves out
        # documents with no retained syllable, so their part of it is taken.
        if (provisional['language'] != language or provisional['include_calibration'] != include_calibration
                or provisional.get('check') != check
                or provisional['declarations'] != json.loads(P.canonical(declarations))
                or not set(texts) <= set(provisional['documents'])
                or any(provisional['documents'][d]['input_sha256'] != P.digest(P.canonical(texts[d]).encode())
                       or provisional['documents'][d]['n_lines'] != len(texts[d]) for d in texts)):
            raise ValueError('The supplied provisional mask does not cover these documents and declarations')
        provisional = P.restrict_mask(provisional, texts)
        for out in outputs:
            P.atomic(out / 'bootstrap-mask.json', (P.canonical(provisional)+'\n').encode())
    else:
        # Without supplied G2P the mask's declarations can be scanned in parallel (P.mask_adapter rebuilds bootstrap).
        provisional = P.build_language_mask(texts, language, first_output / 'bootstrap-mask.json',
                                            include_calibration=include_calibration, cache_dir=g2p_cache, check=check,
                                            **(dict(adapter_spec=dict(gap_treatment=gap_treatment, inventories={}))
                                               if not backends else dict(prepare=bootstrap)))
        for out in outputs[1:]:
            P.atomic(out / 'bootstrap-mask.json', (first_output / 'bootstrap-mask.json').read_bytes())
    excluded = {d: tuple(sorted(map(int, row['masked_lines']))) for d, row in provisional['documents'].items()}
    scope = None if budgets[0] is None else check_prefix(budgets[0]['onset_lines'], splits, texts)
    inventories, scanned = {}, {}
    for declaration in declarations:
        key = configuration_id(declaration)
        backend = backends.get(key, backends.get(language))
        inventories[key], scanned[key] = training_onsets(texts, splits, declaration,
            first_output / key / 'resources', g2p=backend, floor=floor, gap_treatment=gap_treatment,
            excluded_lines=excluded, scope=scope, onset_source=onset_source, onset_lexicon=onset_lexicon,
            cache_dir=g2p_cache)
    # Each label keeps its own copy of the onset resources, as a single call writes them.
    resources_by_label = []
    for out in outputs:
        resources = {}
        for key, row in scanned.items():
            source = Path(row['path']); target = out / key / 'resources' / source.name
            if target != source:
                P.atomic(target, source.read_bytes())
            resources[key] = dict(row, path=str(target))
        resources_by_label.append(resources)
    def adapter(declaration):
        key = configuration_id(declaration)
        return dict(P.registry_configuration(declaration, inventory=inventories[key],
                    g2p=backends.get(key, backends.get(language))), gap_treatment=gap_treatment)
    # Documents any label uses: held-out, and the training prefix of the largest cut.
    if any(b is None for b in budgets):
        needed_training = list(splits['train'])
    else:
        longest = max(budgets, key=lambda b: len(b['lines']))
        needed_training = [d for d, _ in longest['lines']]
    needed = [d for d in texts if d in set(needed_training) | set(splits['validation']) | set(splits['test'])]
    # Without supplied G2P, P.mask_adapter rebuilds `adapter` from each inventory's file, so the
    # declarations can be scanned in parallel (P9 at real size).
    spec = dict(gap_treatment=gap_treatment, inventories={
        P.declaration_key(d): None if inventories[configuration_id(d)] is None else scanned[configuration_id(d)]['path']
        for d in declarations})
    mask = P.build_language_mask({d: texts[d] for d in needed}, language, first_output / 'removal-mask.json',
                                 include_calibration=include_calibration, cache_dir=g2p_cache, check=check,
                                 **(dict(adapter_spec=spec) if not backends else dict(prepare=adapter)))
    for out in outputs[1:]:
        P.atomic(out / 'removal-mask.json', (first_output / 'removal-mask.json').read_bytes())
    if any(set(row['masked_lines']) != set(provisional['documents'][d]['masked_lines'])
           for d, row in mask['documents'].items()):
        raise ValueError('Line eligibility changed after learning training onsets; lead decision required')
    named = []
    if named_inputs is not None:
        if set(named_inputs) - {'languages', 'shared_settings', 'ns_lens'} or set(
                named_inputs.get('languages', ())) != set(P.registry().REGISTRY):
            raise ValueError('Production named inputs must supply the full authoritative language panel')
        N = P.registry().S._load('linguistic_named', ROOT / 'src/stage6/named_universes.py')
        named = N.consume(N.build(named_inputs['languages'], named_inputs['shared_settings'],
                                 ns_lens=named_inputs.get('ns_lens')))['neural']
    jobs = [[] for _ in labels]; counts = [{} for _ in labels]; used_by_label = [None] * len(labels)
    sizes = [{} for _ in labels]; records = {}; tables = [{} for _ in labels]
    artifacts = []
    for marker, out, resources in zip(markers, outputs, resources_by_label):
        row = {str(marker): P.digest(marker.read_bytes()),
               str(out / 'bootstrap-mask.json'): P.digest((out / 'bootstrap-mask.json').read_bytes()),
               str(out / 'removal-mask.json'): P.digest((out / 'removal-mask.json').read_bytes())}
        row.update({r['path']: r['sha256'] for r in resources.values()})
        artifacts.append(row)
    training_units = None
    oov = []
    scan_cache = Path(g2p_cache) if g2p_cache is not None else first_output / 'mask-g2p-cache'
    # Each mask is validated once here, not once per document scanned against it.
    validated = P.validated_mask(mask)
    validated_provisional = None
    # Without supplied G2P, the declarations' scans can run that many at a time
    # (INFO_RATE_SCAN_WORKERS), each writing its record; the loop then reads each back,
    # as materialisation and escape coding do (P9 at real size).
    scanned_records = (_records_in_workers(texts, needed, language, declarations, spec, first_output / 'removal-mask.json',
                                           first_output, scan_cache, P.scan_workers())
                       if not backends and P.scan_workers() > 1 and len(declarations) > 1 else {})
    for declaration in declarations:
        key = configuration_id(declaration)
        record_path = first_output / key / 'syllables.rec'
        if key in scanned_records:
            record_sha256 = scanned_records[key]
            reports = read_record(record_path, record_sha256)
        else:
            reports = {}
            for document in needed:
                # Scan with the final inventory and common mask; encoding IDs are
                # learned later, so provisional document-local files aren't written.
                reports[document] = compact(P.process_document(document, texts[document], language, declaration['option'],
                    first_output / key / 'scan', cache_dir=scan_cache, removal_mask=validated,
                    declaration=declaration, _scan_only=True, **adapter(declaration)))
            # Token files are hashed, not kept; `materialise` rebuilds them from this record (P9).
            record_sha256 = write_record(record_path, reports, needed)
        records[key] = str(record_path)
        for row in artifacts:
            row[str(record_path)] = record_sha256
        if declaration is declarations[0]:
            # First-listed per-line syllables in split order, from which the
            # budgets are planned (src/stage4/budgets.py). Budget-independent.
            # Documents no cut uses are counted as the counts phase counts them
            # (empty inventories, the provisional mask): counts don't depend on
            # the inventory, and the two masks agree wherever both exist.
            units = {}
            for d in splits['train']:
                if d in reports:
                    units[d] = [len(line['syllables']) for line in reports[d]['lines']]
                else:
                    if validated_provisional is None:
                        validated_provisional = P.validated_mask(provisional)
                    report = P.process_document(d, texts[d], language, declaration['option'],
                        first_output / key / 'scan', cache_dir=scan_cache,
                        removal_mask=validated_provisional, declaration=declaration, _scan_only=True,
                        **bootstrap(declaration))
                    units[d] = [len(line['syllables']) for line in report['lines']]
            training_units = [[d, units[d]] for d in splits['train']]
            # A check preparation's budget is the main preparation's, verified there against the
            # first-listed units under the main mask; its own mask and declarations count other
            # units, so the counts phase checks it equals main's instead (Codex review, 2026-10-16).
            if check is None and any(b is not None for b in budgets):
                BUDGETS = P.registry().S._load('linguistic_budgets', ROOT / 'src/stage4/budgets.py')
                for b in budgets:
                    if b is not None:
                        BUDGETS.verify(b, training_units)
        options = {'convention': declaration['option']}
        for fork in P.registry().REGISTRY[language][declaration['option']]['forks']:
            options[fork['setting']] = declaration[fork['target']][fork['setting']]
        for l, (label, out) in enumerate(zip(labels, outputs)):
            shared_l, budget_l, base = label['shared'], label['budget'], out / key
            cut, used = cut_training(reports, splits, budget_l, texts=texts)
            used_by_label[l] = used
            heldout = (*splits['validation'], *splits['test'])
            seen = {s['label'] for d in used['train'] for line in cut[d]['lines'] for s in line['syllables']}
            if not seen:
                raise ValueError('No retained training syllables')
            unknown = {d: sorted({s['label'] for line in cut[d]['lines'] for s in line['syllables']} - seen)
                       for d in heldout}
            # Flagged rungs predict (word-initial flag, syllable) pairs, so a pair
            # unseen in training is an OOV target too.
            trained = set().union(*(flag_pairs(cut[d]['lines']) for d in used['train']))
            unknown_pairs = {d: sorted([f, label] for f, label in flag_pairs(cut[d]['lines']) - trained
                                       if label in seen) for d in heldout}
            unseen = any(unknown.values()) or any(unknown_pairs.values())
            if unseen:
                P.atomic(base / 'oov-report.json', (P.canonical(dict(syllables=unknown, flag_syllable_pairs=unknown_pairs))+'\n').encode())
            # Every declaration and budget is counted, zeros included, on the labels as
            # scanned (Brett, 2026-10-15: count first, then a pre-stated rule).
            oov.append(dict(declaration=key, shared=shared_l, budget=None if budget_l is None else
                            dict(label=budget_l['label'], target=budget_l['target']), unseen=unseen, unsupported=None,
                            **oov_counts(cut, heldout, seen, trained)))
            pairs = None
            if oov_policy == 'pooled-hapax':
                try:
                    cut, pooled, pairs = pool_rare(cut, used, heldout)
                except PoolingUnsupported as error:
                    # Counted everywhere first, then stopped (Codex review).
                    oov[-1]['unsupported'] = str(error)
                if any(row['unsupported'] for row in oov):
                    continue
                P.atomic(base / 'pooled.json', (P.canonical(pooled)+'\n').encode())
            vocabulary = {label: i for i, label in enumerate(sorted({s['label']
                for d in used['train'] for line in cut[d]['lines'] for s in line['syllables']}))}
            vocab_record = dict(schema='training-vocabulary-v1', vocabulary=vocabulary,
                training_documents=list(used['train']), declaration=declaration, budget=budget_l,
                source_sha256={d: hashes[d] for d in used['train']}, oov_policy=oov_policy)
            vocab_path = base / 'vocabulary.json'
            P.atomic(vocab_path, (P.canonical(vocab_record)+'\n').encode())
            artifacts[l][str(vocab_path)] = P.digest(vocab_path.read_bytes())
            pair_policy = None if pairs is None else dict(
                allowed={(f, vocabulary[label]) for f, label in pairs}, pooled=POOLED_TARGET)
            if oov_policy == 'error' and any(row['unseen'] for row in oov):
                continue
            counts[l][key] = {split: {d: cut[d]['encoded_syllables'] for d in ids}
                              for split, ids in used.items()}
            for treatment in P.TREATMENTS:
                current_shared = dict(shared_l or {}, line='bounded' if treatment == 'line-bounded' else 'running')
                selected = ([dict(name=None)] if simulated else
                            [n for n in named if n['status'] == 'ready' and not n.get('alias_of')
                             and named_shared(n['shared'], current_shared, language, SHARED) == current_shared
                             and n['options'].get(language) == options])
                rungs, word_corpora = {}, {s: [] for s in used}
                table = tables[l].setdefault(key, {}).setdefault(treatment, dict(test={}))
                # Each file's digest and size are recorded; the file itself is written by
                # `materialise` just before a job reads it (P9). Word corpora only where a
                # neural job reads them. Training and validation documents are read only
                # through their split files, so of the per-document token files only the
                # test documents' are recorded; those and the word corpora go in compact
                # tables in document order (P9 at real size).
                for split, ids in (used.items() if selected else ()):
                    rows = []
                    for d in ids:
                        data = word_corpus(d, cut[d]['lines'], vocabulary, treatment, dict(
                            declaration=declaration, vocabulary_sha256=artifacts[l][str(vocab_path)],
                            mask_sha256=mask['sha256'], input_sha256=hashes[d]))
                        rows.append([P.digest(data), len(data)])
                        word_corpora[split].append(dict(document=d, path=str(corpus_path(base, treatment, d))))
                    table.setdefault('word_corpora', {})[split] = rows
                for rung in P.RUNGS:
                    specification = {}
                    for split, ids in used.items():
                        joined, size, per_document, rows = hashlib.sha256(), 0, [], []
                        for d in ids:
                            data, meta = P.encode(cut[d]['lines'], rung, treatment, vocabulary=vocabulary,
                                                  pooled_pairs=pair_policy)
                            joined.update(data); size += len(data)
                            if split == 'test':
                                rows.append([P.digest(data), len(data)])
                                per_document.append(dict(document=d, path=str(token_path(base, treatment, rung, d))))
                        path = split_path(base, treatment, rung, split)
                        artifacts[l][str(path)] = joined.hexdigest(); sizes[l][str(path)] = size
                        specification[split] = str(path)
                        if split == 'test':
                            specification['test_documents'] = per_document
                            table['test'][rung] = rows
                    specification.update(order=meta['order'], encoding=meta['encoding'],
                                         score_mode='normalised')
                    if meta['encoding'] == 'candidate-a-window-v1':
                        specification['target_prefix'] = meta['target_prefix']
                    rungs[rung] = specification
                # Measured on invented text at B and B/2 (results/p9/kenlm-peak/): a fit's model with
                # its binary or its zero-backoff rewrite peaked at 26 to 28 times the largest training
                # rung file; 40 leaves room over that (Codex review).
                estimated_peak = 64*1024**2 + 40*max(sizes[l][r['train']] for r in rungs.values())
                common = dict(simulated=simulated, language=language, documents={s: list(ids) for s, ids in used.items()},
                    shared=current_shared, options=options, tokenisation=dict(format='candidate-a-v1',
                        vocabulary_sha256=artifacts[l][str(vocab_path)],
                        onset_resource={k: v for k, v in resources_by_label[l][key].items() if k != 'path'},
                        mask_sha256=mask['sha256'], declaration=declaration,
                        production_ready=production), source_hashes=hashes,
                    realised_syllables=counts[l][key], peak_bytes=kenlm_peak_bytes or estimated_peak,
                    peak_source='declared', peak_basis='caller-declared' if kenlm_peak_bytes else
                                'measured: 64 MiB + 40 times the largest training rung file (26 to 28 times on '
                                'invented text at B and B/2, results/p9/kenlm-peak/)')
                jobs[l].append(dict(common, estimator=dict(name='kenlm'), rungs=rungs))
                for name in selected:
                    settings = neural_settings
                    if settings is None:
                        prod = P.registry().S._load('linguistic_production', ROOT / 'src/stage5/production.py')
                        settings = prod.neural_settings()
                    job = dict(common, estimator=dict(name='neural', settings=settings,
                        vocab=len(vocabulary), line_treatment=current_shared['line'], device='cpu'),
                        device='cpu', word_corpora=word_corpora,
                        rungs={r: rungs[r] for r in ('1w', '1', '4')}, peak_bytes=64*1024**2,
                        peak_basis='in-memory neural model; declared 64 MiB for score bookkeeping')
                    if not simulated:
                        job.update(named_universe=name['name'], named_universe_inputs=named_inputs)
                        prod = P.registry().S._load('linguistic_production', ROOT / 'src/stage5/production.py')
                        prod.validate_neural(job, {'settings': settings})
                    jobs[l].append(job)
    P.atomic(first_output / 'oov-summary.json',
             (P.canonical(dict(schema='oov-summary-v2', language=language, oov_policy=oov_policy, rows=oov))+'\n').encode())
    if oov_policy == 'error' and any(row['unseen'] for row in oov):
        raise ValueError('Held-out syllables or flag+syllable pairs absent from training; '
                         'see oov-summary.json and each oov-report.json')
    unsupported = [row['unsupported'] for row in oov if row['unsupported']]
    if unsupported:
        raise PoolingUnsupported(unsupported[0] + '; see oov-summary.json')
    manifests = []
    for l, (label, out) in enumerate(zip(labels, outputs)):
        if named_inputs is not None and not simulated:
            # A ready named universe that includes this language must get a job;
            # labels or options that match nothing would otherwise drop it silently.
            # A universe is expected here when its applicable settings all match this
            # preparation's labels, or when one of them is missing from the labels
            # (a mislabelled preparation would otherwise lose its neural jobs silently).
            base = dict(label['shared'] or {})
            run = base.get('run', SHARED.FIRST_LISTED['run'])
            def expects(n):
                relevant = {k: v for k, v in n['shared'].items()
                            if k != 'line' and (k in base or SHARED.applicable(k, language, run))}
                return any(k not in base for k in relevant) or all(base[k] == v for k, v in relevant.items())
            # An alias (dictionary of first-listed) reuses its target's estimates.
            expected = {n['name'] for n in named if n['status'] == 'ready' and not n.get('alias_of')
                        and language in n['options'] and expects(n)}
            produced = {j.get('named_universe') for j in jobs[l] if j['estimator']['name'] == 'neural'}
            if expected - produced:
                raise ValueError(f'Named universes selected no neural job: {sorted(expected - produced)}; '
                                 'check the shared labels and options against the named inputs')
        # Each job names this manifest; Stage 5 checks a real job against it.
        label_jobs = [dict(job, preparation=str(out / 'inputs.json')) for job in jobs[l]]
        manifest = dict(schema=SCHEMA, language=language, production=production,
            splits={s: list(ids) for s, ids in splits.items()}, budget=label['budget'], training_units=training_units,
            budget_splits={s: list(ids) for s, ids in used_by_label[l].items()},
            source_sha256=hashes, declarations=declarations, resources=resources_by_label[l], counts=counts[l],
            removal_mask_sha256=mask['sha256'], oov_policy=oov_policy, artifacts=artifacts[l],
            artifact_bytes=sizes[l], document_files=tables[l], syllable_records=records,
            neural_jobs_pending=named_inputs is None and not simulated,
            jobs=[_by_reference(job) for job in label_jobs], versions=P.version(),
            named_universes=named,
            builder_sha256=P.digest(Path(__file__).read_bytes()))
        if check is not None:
            manifest['check'] = check
        manifest['sha256'] = P.digest(P.canonical(manifest).encode())
        written = json.loads(P.canonical(manifest))
        # The jobs as read back are the jobs built here (each checked against its digest).
        for stored in written['jobs']:
            _rebuilt(written, stored)
        P.atomic(out / 'inputs.json', (P.canonical(manifest)+'\n').encode())
        manifests.append(written)
    return manifests[0] if single else manifests


def _treatment(job):
    return 'line-bounded' if job['shared']['line'] == 'bounded' else 'cross-line'


def _by_reference(job):
    """A job as its manifest stores it: without the fields it shares with the preparation
    (`BY_REFERENCE`, and each rung's test-document files), with its full form's digest."""
    stored = {k: v for k, v in job.items() if k not in BY_REFERENCE}
    stored['rungs'] = {r: {k: v for k, v in spec.items() if k != 'test_documents'} for r, spec in job['rungs'].items()}
    stored['job_sha256'] = P.digest(P.canonical(job).encode())
    return stored


def _rebuilt(manifest, stored):
    """A stored job with its preparation's fields restored, the same objects as the manifest's;
    refused unless it hashes to the digest recorded for the job as prepared."""
    key = configuration_id(stored['tokenisation']['declaration'])
    base, treatment, documents = Path(stored['preparation']).parent / key, _treatment(stored), manifest['budget_splits']
    job = {k: v for k, v in stored.items() if k != 'job_sha256'}
    job.update(documents=documents, source_hashes=manifest['source_sha256'], realised_syllables=manifest['counts'][key])
    job['rungs'] = {r: dict(spec, test_documents=[dict(document=d, path=str(token_path(base, treatment, r, d)))
                                                  for d in documents['test']])
                    for r, spec in stored['rungs'].items()}
    if stored['estimator']['name'] == 'neural':
        job['word_corpora'] = {s: [dict(document=d, path=str(corpus_path(base, treatment, d))) for d in ids]
                               for s, ids in documents.items()}
    if P.digest(P.canonical(job).encode()) != stored['job_sha256']:
        raise ValueError(f"A job rebuilt from its manifest differs from the job prepared: {stored['preparation']}")
    return job


_PREPARATION = {}


def _manifest_digest(manifest):
    return P.digest(P.canonical({k: v for k, v in manifest.items() if k != 'sha256'}).encode())


def read_preparation(inputs, *, verify=False):
    """A preparation manifest, checked against its own digest. The last one read is kept,
    since the runner, materialisation and escape coding each read a job's preparation
    (P9 at real size); callers must not change it. A kept manifest is read again when the
    file's size, times or inode change; verify=True (the runner's provenance check) also
    checks the kept one against its digest again and rebuilds its file tables, so a
    change made to it in memory is refused (Codex review, 2026-10-16)."""
    path = Path(inputs).resolve()
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_dev)
    entry = _PREPARATION.get('entry')
    if entry is None or entry['key'] != key:
        manifest = json.loads(path.read_text())
        if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA or \
                manifest.get('sha256') != _manifest_digest(manifest):
            raise ValueError(f'invalid preparation manifest: {inputs}')
        entry = _PREPARATION['entry'] = dict(key=key, manifest=manifest, files={})
    elif verify:
        if entry['manifest'].get('sha256') != _manifest_digest(entry['manifest']):
            _PREPARATION.clear()
            raise ValueError(f'invalid preparation manifest: {inputs} (changed in memory)')
        entry['files'] = {}
    return entry['manifest']


def _document_files(inputs, key):
    """{path: (sha256, bytes)} of one declaration's per-document files, from the manifest's tables."""
    manifest = read_preparation(inputs)
    entry = _PREPARATION['entry']
    if key not in entry['files']:
        base, documents, files = Path(inputs).resolve().parent / key, manifest['budget_splits'], {}
        for treatment, table in manifest['document_files'].get(key, {}).items():
            for rung, rows in table['test'].items():
                files.update((str(token_path(base, treatment, rung, d)), tuple(row))
                             for d, row in zip(documents['test'], rows, strict=True))
            for split, rows in table.get('word_corpora', {}).items():
                files.update((str(corpus_path(base, treatment, d)), tuple(row))
                             for d, row in zip(documents[split], rows, strict=True))
        entry['files'] = {key: files}
    return entry['files'][key]


def recorded(inputs, path):
    """(sha256, bytes) that `prepare` recorded for one of a preparation's files, or None.
    Bytes are None for files whose size isn't recorded (markers, masks, resources, records,
    vocabularies)."""
    manifest = read_preparation(inputs)
    path = str(path)
    if path in manifest['artifacts']:
        return manifest['artifacts'][path], manifest['artifact_bytes'].get(path)
    out = Path(inputs).resolve().parent
    if not Path(path).is_relative_to(out) or len(Path(path).relative_to(out).parts) < 2:
        return None
    return _document_files(inputs, Path(path).relative_to(out).parts[0]).get(path)


def recorded_files(inputs):
    """Every file a preparation recorded, {path: (sha256, bytes or None)}."""
    manifest = read_preparation(inputs)
    files = {p: (sha, manifest['artifact_bytes'].get(p)) for p, sha in manifest['artifacts'].items()}
    for key in manifest['document_files']:
        files.update(_document_files(inputs, key))
    return files


def preparation_entries(inputs, *, key=None, estimator=None):
    """(digest, job) for a preparation's jobs as prepared, rebuilt from its manifest: one
    declaration's (`key`, a configuration id) or all, one estimator's or all."""
    manifest = read_preparation(inputs)
    return [(stored['job_sha256'], _rebuilt(manifest, stored)) for stored in manifest['jobs']
            if (key is None or configuration_id(stored['tokenisation']['declaration']) == key)
            and (estimator is None or stored['estimator']['name'] == estimator)]


def preparation_jobs(inputs, **select):
    """A preparation's jobs as prepared (`preparation_entries` without the digests)."""
    return [job for _, job in preparation_entries(inputs, **select)]


def rebuilt_jobs(manifest):
    """The jobs of a manifest already in hand (as `prepare` returns it), rebuilt and checked."""
    return [_rebuilt(manifest, stored) for stored in manifest['jobs']]


def job_paths(job):
    """The token files and word corpora a job may read: its rungs' files (the joined test
    file too, which a callback estimator's identity hashes) and a neural job's word corpora."""
    paths = []
    for r in job['rungs'].values():
        paths += [r['train'], r['validation'], r['test'], *(row['path'] for row in r.get('test_documents', ()))]
    paths += [e['path'] for entries in job.get('word_corpora', {}).values() for e in entries]
    return list(dict.fromkeys(paths))


def _write_checked(path, chunks, size, sha256, linked):
    """Write `chunks` to `path` atomically if they hash to `sha256`; a file whose bytes are
    already on disk this round is a hard link to it, so identical rungs take the space once."""
    path = Path(path)
    if sha256 in linked and Path(linked[sha256]).exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        name = path.with_name('.stage4-link-' + path.name)
        name.unlink(missing_ok=True)
        os.link(linked[sha256], name); os.replace(name, path)
        return
    P.preflight(path.parent, size + 16384)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.stage4-', dir=path.parent)
    try:
        h = hashlib.sha256()
        with os.fdopen(fd, 'wb') as f:
            for c in chunks:
                f.write(c); h.update(c)
            f.flush(); os.fsync(f.fileno())
        if h.hexdigest() != sha256:
            raise ValueError(f'Materialised file differs from its recorded digest: {path}')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    linked[sha256] = str(path)


def materialise_preparation(inputs, wanted=None):
    """Write a preparation's token files and word corpora from its syllable records (P9).

    `prepare` records each file's digest and size without keeping it; this rebuilds
    the files it names (`wanted`; default every token file and word corpus it records)
    through the same cut, pooling, vocabulary and encoders, and keeps a file only if it
    hashes to its recorded digest, so the runner's own provenance check then finds what
    `prepare` recorded. Returns the paths written, for `dematerialise`.
    """
    inputs = Path(inputs).resolve()
    manifest = read_preparation(inputs)
    out = inputs.parent
    if wanted is None:
        wanted = {p for p, (_, size) in recorded_files(inputs).items() if size is not None}
    else:
        wanted = set(map(str, wanted))
        unknown = sorted(p for p in wanted if (recorded(inputs, p) or (None, None))[1] is None)
        if unknown:
            raise ValueError(f'not files this preparation recorded: {unknown[:3]}')
    # The declarations, and in each the (treatment, rung or word-corpora) folders, the files sit in.
    folders = {}
    for path in wanted:
        key, treatment, folder = Path(path).relative_to(out).parts[:3]
        folders.setdefault(key, set()).add((treatment, folder))
    splits = {s: tuple(ids) for s, ids in manifest['splits'].items()}
    heldout = (*splits['validation'], *splits['test'])
    artifacts, written, linked = manifest['artifacts'], [], {}
    for declaration in manifest['declarations']:
        key = configuration_id(declaration)
        if key not in folders:
            continue
        base, files = out / key, dict(_document_files(inputs, key))
        files.update((p, (sha, manifest['artifact_bytes'].get(p))) for p, sha in artifacts.items())
        record = manifest['syllable_records'][key]
        reports = read_record(record, artifacts[record])
        cut, used = cut_training(reports, splits, manifest['budget'],
                                 texts={d: r['lines'] for d, r in reports.items()})
        if {s: list(ids) for s, ids in used.items()} != manifest['budget_splits']:
            raise ValueError(f'Syllable record gives other budget splits than the manifest: {key}')
        pairs = None
        if manifest['oov_policy'] == 'pooled-hapax':
            cut, _, pairs = pool_rare(cut, used, heldout)
        vocabulary = {label: i for i, label in enumerate(sorted({s['label']
            for d in used['train'] for line in cut[d]['lines'] for s in line['syllables']}))}
        vocab_path = base / 'vocabulary.json'
        if P.digest(vocab_path.read_bytes()) != artifacts[str(vocab_path)] or \
                json.loads(vocab_path.read_text())['vocabulary'] != vocabulary:
            raise ValueError(f'Syllable record gives another vocabulary than the preparation: {key}')
        pair_policy = None if pairs is None else dict(
            allowed={(f, vocabulary[label]) for f, label in pairs}, pooled=POOLED_TARGET)
        for treatment in P.TREATMENTS:
            if (treatment, 'word-corpora') in folders[key]:
                for split, ids in used.items():
                    for d in ids:
                        path = str(corpus_path(base, treatment, d))
                        if path in wanted:
                            data = word_corpus(d, cut[d]['lines'], vocabulary, treatment, dict(
                                declaration=declaration, vocabulary_sha256=artifacts[str(vocab_path)],
                                mask_sha256=manifest['removal_mask_sha256'], input_sha256=manifest['source_sha256'][d]))
                            sha, size = files[path]
                            _write_checked(path, [data], size, sha, linked); written.append(path)
            for rung in P.RUNGS:
                if (treatment, rung) not in folders[key]:
                    continue
                for split, ids in used.items():
                    path = str(split_path(base, treatment, rung, split))
                    documents = [str(token_path(base, treatment, rung, d)) for d in ids] if split == 'test' else []
                    if path not in wanted and not wanted.intersection(documents):
                        continue
                    parts = [P.encode(cut[d]['lines'], rung, treatment, vocabulary=vocabulary, pooled_pairs=pair_policy)[0]
                             for d in ids]
                    for document, data in zip(documents, parts):
                        if document in wanted:
                            sha, size = files[document]
                            _write_checked(document, [data], size, sha, linked); written.append(document)
                    if path in wanted:
                        sha, size = files[path]
                        _write_checked(path, parts, size, sha, linked); written.append(path)
    if wanted - set(written):
        raise ValueError(f'files the job reads were not rebuilt: {sorted(wanted - set(written))[:3]}')
    return written


def materialise(job):
    """Write the files a job reads, just before it runs; returns them for `dematerialise`."""
    return materialise_preparation(job['preparation'], job_paths(job))


def dematerialise(paths):
    """Remove materialised files after their job (P9: token files exist only while a job runs)."""
    for path in paths:
        Path(path).unlink(missing_ok=True)


def _scan_record(texts, needed, language, declaration, spec, mask_path, scan, cache, record_path):
    """One declaration's scan of the needed documents under the removal mask, written as its record."""
    validated = P.validated_mask(P.read_mask(mask_path))
    reports = {document: compact(P.process_document(document, texts[document], language, declaration['option'],
                                                    scan, cache_dir=cache, removal_mask=validated, declaration=declaration,
                                                    _scan_only=True, **P.mask_adapter(spec, declaration)))
               for document in needed}
    return write_record(record_path, reports, needed)


def _records_in_workers(texts, needed, language, declarations, spec, mask_path, first_output, cache, n):
    """Each declaration's `_scan_record` in a fresh interpreter (`--scan-worker`), n at a time
    (P9 at real size); returns each declaration's record digest by configuration id. A worker
    holds one declaration's scanned text, as the one-process loop does."""
    import concurrent.futures, subprocess
    folder = first_output / '.scan-workers'; folder.mkdir(parents=True, exist_ok=True)
    documents = folder / 'documents.json'
    P.atomic(documents, (P.canonical([[d, list(texts[d])] for d in needed]) + '\n').encode())
    def one(declaration):
        key = configuration_id(declaration)
        spec_path, result, log = folder / f'{key}.json', folder / f'{key}-result.json', folder / f'{key}.log'
        result.unlink(missing_ok=True)
        P.atomic(spec_path, (P.canonical(dict(documents=str(documents), language=language, declaration=declaration,
            adapter=spec, mask=str(mask_path), scan=str(first_output / key / 'scan'), cache=str(cache),
            record=str(first_output / key / 'syllables.rec'), result=str(result))) + '\n').encode())
        with open(log, 'wb') as out:
            code = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--scan-worker', str(spec_path)],
                                  stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT).returncode
        if code != 0 or not result.exists():
            tail = log.read_bytes()[-2000:].decode('utf-8', 'replace')
            raise RuntimeError(f'scan worker failed (exit {code}) for {language} declaration {key[:12]}; log {log}:\n{tail}')
        return key, json.loads(result.read_text())['sha256']
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(one, d) for d in declarations]
        concurrent.futures.wait(futures)
    failed = [f.exception() for f in futures if f.exception() is not None]
    if failed:
        raise failed[0]
    import shutil
    shutil.rmtree(folder)
    return dict(f.result() for f in futures)


def _scan_worker(spec_path):
    spec = json.loads(Path(spec_path).read_text())
    pairs = json.loads(Path(spec['documents']).read_text())
    texts, needed = {d: tuple(lines) for d, lines in pairs}, [d for d, _ in pairs]
    sha = _scan_record(texts, needed, spec['language'], spec['declaration'], spec['adapter'], spec['mask'],
                       Path(spec['scan']), Path(spec['cache']), Path(spec['record']))
    P.atomic(Path(spec['result']), (P.canonical(dict(sha256=sha)) + '\n').encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('language'); parser.add_argument('documents', type=Path)
    parser.add_argument('splits', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--floor', type=int, default=3)
    parser.add_argument('--onset-source', choices=ONSET_SOURCES, default='lexicon')
    parser.add_argument('--gap-treatment', choices=('drop', 'split'), required=True)
    parser.add_argument('--named-inputs', type=Path)
    parser.add_argument('--shared', type=json.loads, default={})
    parser.add_argument('--kenlm-peak-bytes', type=int, help='Measured production scratch-disk reservation')
    args = parser.parse_args()
    value = prepare(json.loads(args.documents.read_text()), json.loads(args.splits.read_text()),
        args.language, args.output, floor=args.floor, onset_source=args.onset_source,
        gap_treatment=args.gap_treatment,
        shared=args.shared, named_inputs=json.loads(args.named_inputs.read_text()) if args.named_inputs else None,
        kenlm_peak_bytes=args.kenlm_peak_bytes)
    print(P.canonical(dict(language=value['language'], jobs=len(value['jobs']), counts=value['counts'],
                          sha256=value['sha256'], neural_jobs_pending=value['neural_jobs_pending'])))


if __name__ == '__main__':
    if sys.argv[1:2] == ['--scan-worker'] and len(sys.argv) == 3:
        _scan_worker(sys.argv[2])
    else:
        main()
