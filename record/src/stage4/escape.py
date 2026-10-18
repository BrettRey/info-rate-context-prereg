"""Escape coding: the bits to spell a pooled syllable, added at scoring (P9).

Brett's OOV rule (DECISIONS.md, 2026-10-15): where held-out syllables unseen in
training pass 0.1% of held-out tokens in any language and budget, escape coding is
the main analysis and the pooled unknown symbol the labelled secondary. The
pooled symbol (`linguistic_inputs.pool_rare`) gives a model's probability that the
next syllable is one of the rare ones; escape coding adds what it costs to say
which, by spelling the original label from its characters.

Defaults (DECISIONS.md, 2026-10-15, logged before this was built):
- charged: every scored target the pooled symbol stands for. On every rung a
  syllable relabelled `<rare>`; on a KenLM flagged rung also a pair target
  `b<flag>sp` whose syllable is not itself pooled. Neural jobs predict the
  syllable and its flag from the word corpus, which pools syllables only, so only
  `<rare>` targets are charged there.
- the spelling model (`Spelling`): the label's code points then an end symbol;
  interpolated Witten-Bell over the two previous characters, down to add-one over
  the training alphabet plus the end symbol and one unknown-character symbol;
  fitted per declaration and budget on the budget's training hapax types, one
  count each, with the alphabet from every training label.

Nothing here changes `prepare`: each preparation's syllable record goes through
the same cut and pooling as `materialise_preparation`, and the targets are checked
against the files the job scored (their recorded digests, and the pooled tokens in
them) so the bits belong to exactly the targets the model was scored on.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
from collections import Counter, defaultdict
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'escape-v1'
PLAIN = ('0', '1w', '1', '2', '3', '4')


def _load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


L = _load('escape_linguistic_inputs', ROOT / 'src/stage4/linguistic_inputs.py')
P = L.P
BOS, END, UNKNOWN = '\x02', '\x03', '\x00'


class Spelling:
    """Interpolated Witten-Bell over the two previous characters, down to add-one.

    Trained on `types` (each counted once); `alphabet` is every character seen in
    training labels. A character outside it is the unknown-character symbol.
    """
    ORDER = 3

    def __init__(self, types, alphabet):
        types = sorted(set(types))
        self.alphabet = frozenset(alphabet)
        if any(c in self.alphabet for c in (BOS, END, UNKNOWN)):
            raise ValueError('A training label holds a reserved spelling symbol')
        self.symbols = len(self.alphabet) + 2  # the alphabet, the end symbol, the unknown character
        self.counts = [defaultdict(Counter) for _ in range(self.ORDER)]
        for label in types:
            chars = [c if c in self.alphabet else UNKNOWN for c in label] + [END]
            padded = [BOS] * (self.ORDER - 1) + chars
            for i in range(self.ORDER - 1, len(padded)):
                for n in range(self.ORDER):
                    self.counts[n][tuple(padded[i - n:i])][padded[i]] += 1
        self.types = len(types)
        self.types_sha256 = P.digest(P.canonical(types).encode())

    def probability(self, char, history):
        unigrams = self.counts[0][()]
        p = (unigrams[char] + 1) / (sum(unigrams.values()) + self.symbols)
        for n in range(1, self.ORDER):
            seen = self.counts[n].get(tuple(history[-n:]))
            if seen:
                total, kinds = sum(seen.values()), len(seen)
                p = (seen[char] + kinds * p) / (total + kinds)
        return p

    def bits(self, label):
        chars = [c if c in self.alphabet else UNKNOWN for c in label] + [END]
        history = [BOS] * (self.ORDER - 1)
        total = 0.
        for c in chars:
            total -= math.log2(self.probability(c, history))
            history.append(c)
        return total

    def descriptor(self):
        return dict(model='spelling-witten-bell-v1', order=self.ORDER, base='add-one',
                    alphabet=len(self.alphabet), symbols=self.symbols, training_types=self.types,
                    training_types_sha256=self.types_sha256)


_STATE = {}


def preparation_state(inputs, key):
    """One declaration of one preparation: its cut before and after pooling, vocabulary and spelling model."""
    inputs = Path(inputs)
    if (str(inputs), key) in _STATE:
        return _STATE[(str(inputs), key)]
    manifest = L.read_preparation(inputs)
    artifacts = manifest['artifacts']
    splits = {s: tuple(ids) for s, ids in manifest['splits'].items()}
    heldout = (*splits['validation'], *splits['test'])
    record = manifest['syllable_records'][key]
    reports = L.read_record(record, artifacts[record])
    cut, used = L.cut_training(reports, splits, manifest['budget'],
                               texts={d: r['lines'] for d, r in reports.items()})
    if {s: list(ids) for s, ids in used.items()} != manifest['budget_splits']:
        raise ValueError(f'Syllable record gives other budget splits than the manifest: {key}')
    pooled_cut, hapax, pairs = cut, [], None
    if manifest['oov_policy'] == 'pooled-hapax':
        pooled_cut, pooled, pairs = L.pool_rare(cut, used, heldout)
        hapax = pooled['training_hapax']
    vocabulary = {label: i for i, label in enumerate(sorted({s['label']
        for d in used['train'] for line in pooled_cut[d]['lines'] for s in line['syllables']}))}
    vocab_path = inputs.parent / key / 'vocabulary.json'
    if P.digest(vocab_path.read_bytes()) != artifacts[str(vocab_path)] or \
            json.loads(vocab_path.read_text())['vocabulary'] != vocabulary:
        raise ValueError(f'Syllable record gives another vocabulary than the preparation: {key}')
    alphabet = {c for d in used['train'] for line in cut[d]['lines'] for s in line['syllables'] for c in s['label']}
    state = dict(manifest=manifest, base=inputs.parent / key, cut=cut, pooled=pooled_cut, vocabulary=vocabulary,
                 allowed=None if pairs is None else {(f, vocabulary[label]) for f, label in pairs},
                 spelling=Spelling(hapax, alphabet))
    _STATE.clear(); _STATE[(str(inputs), key)] = state
    return state


def targets(state, document, rung, treatment, *, kenlm):
    """The document's scored targets in order: (original label, pooled) each.

    KenLM's token files (`pipeline.encode`) drop masked lines only across lines;
    the neural word corpus (`corpus_vectors`) drops them in both treatments and
    pools syllables only, never (flag, syllable) pairs.
    """
    out = []
    for original, line in zip(state['cut'][document]['lines'], state['pooled'][document]['lines']):
        if line.get('status') == 'masked' and (treatment == 'cross-line' or not kenlm or not line['syllables']):
            continue
        group = line['syllables']
        if len(group) != len(original['syllables']):
            raise ValueError('Pooling changed a line length')
        for i, (o, s) in enumerate(zip(original['syllables'], group)):
            if s['owner'] != o['owner'] or s['label'] not in (o['label'], L.POOLED):
                raise ValueError('Pooling changed something other than a label')
            pooled = s['label'] == L.POOLED
            if kenlm and rung not in PLAIN and state['allowed'] is not None:
                flag = int(i == 0 or s['owner'] != group[i - 1]['owner'])
                pooled = (flag, state['vocabulary'][s['label']]) not in state['allowed']
            out.append((o['label'], pooled))
    return out


def _pooled_in_file(data, rung, vocabulary):
    """Pooled targets in an encoded token file, counted from its text."""
    rare = vocabulary.get(L.POOLED)
    lines = data.decode().splitlines()
    if rung in PLAIN and rung != '1w':
        tokens = [t for line in lines for t in line.split()]
        return len(tokens), sum(t == f's{rare}' for t in tokens)
    targets = [line.split()[-1] for line in lines]
    if rung == '1w':
        return len(targets), sum(t == f's{rare}' for t in targets)
    return len(targets), sum(t.endswith('s' + L.POOLED_TARGET) for t in targets)


def job_escape(job):
    """Per rung and test document of one job: targets, pooled targets and their spelling bits."""
    estimator = job['estimator']['name']
    key = L.configuration_id(job['tokenisation']['declaration'])
    state = preparation_state(job['preparation'], key)
    pair_policy = None if state['allowed'] is None else dict(allowed=state['allowed'], pooled=L.POOLED_TARGET)
    rungs = {}
    for rung, spec in sorted(job['rungs'].items()):
        rows = []
        for row in spec['test_documents']:
            path = Path(row['path'])
            treatment = path.relative_to(state['base']).parts[0]
            if treatment not in P.TREATMENTS or path.relative_to(state['base']).parts[1] != rung:
                raise ValueError(f'Test file outside its rung: {path}')
            found = targets(state, row['document'], rung, treatment, kenlm=estimator == 'kenlm')
            if estimator == 'kenlm':
                # The bits belong to the file the job scored: same bytes, same pooled targets.
                data, meta = P.encode(state['pooled'][row['document']]['lines'], rung, treatment,
                                      vocabulary=state['vocabulary'], pooled_pairs=pair_policy)
                if P.digest(data) != (L.recorded(job['preparation'], path) or (None,))[0]:
                    raise ValueError(f'Rebuilt test file differs from the one recorded: {path}')
                n, pooled = _pooled_in_file(data, rung, state['vocabulary'])
                if (n, pooled) != (len(found), sum(p for _, p in found)) or meta['n_syllables'] != n:
                    raise ValueError(f'Escape targets disagree with the scored file: {path}')
            bits = sum(state['spelling'].bits(label) for label, pooled in found if pooled)
            rows.append(dict(document=row['document'], n_targets=len(found),
                             n_pooled=sum(p for _, p in found), escape_bits=bits))
        rungs[rung] = rows
    return dict(schema=SCHEMA, estimator=estimator, preparation=str(job['preparation']), declaration=key,
                spelling=state['spelling'].descriptor(), rungs=rungs)


SPANS_SCHEMA = 'spans-v1'


def _span_groups(lines, treatment, kenlm):
    """Each scored syllable as (its share of its word, word-initial), grouped as the scorer's context runs.

    As `targets` skips lines: within lines each line is a group (KenLM keeps a masked line's syllables, the
    neural corpus drops them); across lines unmasked lines are joined and a masked line breaks the context.
    A word is a run of syllables with one owner, so a share is 1 over the syllables in the whole word,
    counted before any context window cuts it.
    """
    groups, current = [], []
    for line in lines:
        if line.get('status') == 'masked' and (treatment == 'cross-line' or not kenlm):
            if current:
                groups.append(current); current = []
            continue
        syll = line['syllables']
        initial = [i == 0 or s['owner'] != syll[i - 1]['owner'] for i, s in enumerate(syll)]
        starts = [i for i, b in enumerate(initial) if b] + [len(syll)]
        shares = [(1 / (b - a), j == a) for a, b in zip(starts, starts[1:]) for j in range(a, b)]
        if treatment == 'line-bounded':
            if shares:
                groups.append(shares)
        else:
            current.extend(shares)
    if current:
        groups.append(current)
    return groups


def _span_arrays(groups):
    """A document's groups as flat arrays: each syllable's word share, its word-initial flag, and the position
    where its group starts (one pass, so each rung is a few array operations over the document)."""
    import numpy as np
    lengths = [len(g) for g in groups]
    share = np.array([w for g in groups for w, _ in g], dtype=float)
    initial = np.array([b for g in groups for _, b in g], dtype=bool)
    first = np.repeat(np.cumsum([0] + lengths)[:-1], lengths).astype(np.int64)
    return share, initial, first


def _rung_spans(arrays, rung):
    """Contexts, and the words and syllables the k previous syllables cover, summed over targets."""
    import numpy as np
    share, initial, first = arrays
    k = 0 if rung == '0' else 1 if rung.startswith('1') else int(rung[0])
    i = np.arange(len(share))
    if rung == '1w':
        # The previous syllable, only inside the current word (`pipeline.encode`, `nnlm.rung_contexts`).
        inside = (i > first) & ~initial
        return dict(contexts=len(share), words_sum=float(share[i[inside] - 1].sum()), syllables_sum=int(inside.sum()))
    lo = np.maximum(first, i - k); c = np.r_[0., np.cumsum(share)]
    return dict(contexts=len(share), words_sum=float((c[i] - c[lo]).sum()), syllables_sum=int((i - lo).sum()))


def _scored_group_lengths(state, document, treatment, kenlm):
    """The lengths of the stretches the scorer's context runs within, read from the scored text itself: the
    lines of KenLM's plain stream file (`pipeline.encode`), or the neural corpus's context starts
    (`corpus_vectors`: every line start within lines, the reset starts across lines)."""
    lines = state['pooled'][document]['lines']
    if kenlm:
        data, _ = P.encode(lines, '1', treatment, vocabulary=state['vocabulary'])
        return [len(line.split()) for line in data.decode().splitlines()]
    value = L.corpus_vectors(lines, state['vocabulary'], treatment)
    bounds = value['starts'] if treatment == 'line-bounded' else value['reset_starts']
    return [b - a for a, b in zip(bounds, bounds[1:] + [len(value['syllables'])])]


def job_spans(job):
    """Per rung of one job: the words and syllables each scored target's context covers, over the test text.

    Brett, 2026-10-17 (DECISIONS.md, from F2): the span beside every rung, in words covered, each syllable
    counting as its share of its word. Counted on the lines `targets` reads, so the contexts are the targets
    the job scored (checked by count, and the context stretches against the scored text's own); phones aren't
    counted, the syllable records holding no segments.
    """
    estimator = job['estimator']['name']
    key = L.configuration_id(job['tokenisation']['declaration'])
    state = preparation_state(job['preparation'], key)
    grouped, rungs = {}, {}
    for rung, spec in sorted(job['rungs'].items()):
        total = dict(contexts=0, words_sum=0., syllables_sum=0)
        for row in spec['test_documents']:
            path = Path(row['path'])
            treatment = path.relative_to(state['base']).parts[0]
            if treatment not in P.TREATMENTS or path.relative_to(state['base']).parts[1] != rung:
                raise ValueError(f'Test file outside its rung: {path}')
            if (row['document'], treatment) not in grouped:
                kenlm = estimator == 'kenlm'
                groups = _span_groups(state['cut'][row['document']]['lines'], treatment, kenlm)
                n = len(targets(state, row['document'], rung, treatment, kenlm=kenlm))
                if sum(map(len, groups)) != n:
                    raise ValueError(f"Span contexts differ from the scored targets: {row['document']}")
                if [len(g) for g in groups] != _scored_group_lengths(state, row['document'], treatment, kenlm):
                    raise ValueError(f"Span contexts break where the scored text doesn't: {row['document']}")
                grouped[(row['document'], treatment)] = _span_arrays(groups)
            for field, value in _rung_spans(grouped[(row['document'], treatment)], rung).items():
                total[field] += value
        rungs[rung] = total
    return dict(schema=SPANS_SCHEMA, estimator=estimator, preparation=str(job['preparation']), declaration=key,
                unit='words: each syllable counts 1/(syllables in its word); syllables: previous syllables in the context',
                rungs=rungs)


def apply(record, escape, digest, *, stand_in=False):
    """A score record with each rung's document losses and id_bits including the spelling bits.

    `digest` is the runner's score digest, so the record checks as a cached one does.
    stand_in: a simulated run's custom estimator, whose aggregate scores carry no
    documents and no real token count; each rung gains the mean spelling bits per target.
    """
    scores = {}
    for rung, score in record['scores'].items():
        score = json.loads(P.canonical(score))
        if rung not in escape['rungs']:
            raise ValueError(f'No escape bits for rung {rung}')
        rows = {r['document']: r for r in escape['rungs'][rung]}
        score['pooled_id_bits'] = score['id_bits']
        if 'documents' in score:
            if {d['document'] for d in score['documents']} != set(rows):
                raise ValueError(f'No escape bits for every test document of rung {rung}')
            for d in score['documents']:
                if rows[d['document']]['n_targets'] != d['n_tokens']:
                    raise ValueError(f"Escape targets differ from the scored tokens: {rung} {d['document']}")
                d['loss_sum_bits'] += rows[d['document']]['escape_bits']
            score['id_bits'] = sum(d['loss_sum_bits'] for d in score['documents']) / sum(d['n_tokens'] for d in score['documents'])
        elif stand_in:
            score['id_bits'] += sum(r['escape_bits'] for r in rows.values()) / sum(r['n_targets'] for r in rows.values())
        else:
            raise ValueError(f'A production score without per-document losses: rung {rung}')
        score['escape'] = dict(n_pooled=sum(r['n_pooled'] for r in rows.values()),
                               bits=sum(r['escape_bits'] for r in rows.values()), spelling=escape['spelling'])
        score['pooled_targets'] = score['escape']['n_pooled']
        scores[rung] = score
    return dict(record, scores=scores, scores_hash=digest(scores), score_variant='escape-coded')


def pooled_counts(record, escape, digest):
    """A pooled-symbol score record with each rung's pooled targets beside it and nothing else changed, so the
    pooled analysis reports pooled shares too (Brett's choice 4, 2026-10-17; Codex review)."""
    scores = {}
    for rung, score in record['scores'].items():
        if rung not in escape['rungs']:
            raise ValueError(f'No pooled counts for rung {rung}')
        score = json.loads(P.canonical(score))
        score['pooled_targets'] = sum(r['n_pooled'] for r in escape['rungs'][rung])
        scores[rung] = score
    return dict(record, scores=scores, scores_hash=digest(scores))
