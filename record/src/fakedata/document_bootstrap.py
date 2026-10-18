"""Simulated prototype: sample training/test documents and refit the rung ladder.

This is not connected to real-data assembly. Validation documents stay fixed;
model seeds, estimator settings and the syllable convention stay fixed. All
rungs receive the SAME document draw. A reduced token budget is explicit and
results must not be passed off as full-budget intervals.
"""
import os
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
             'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import numpy as np

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def budget_words(documents, draw, budget):
    """Expand sampled document copies, retaining complete words up to a token cap."""
    if type(budget) is not int or budget < 1:
        raise ValueError('positive integer training token budget required')
    lines, used = [], 0
    for index in draw:
        line = []
        for word in documents[int(index)]:
            if not word:
                raise ValueError('empty word')
            if used+len(word) > budget:
                if line:
                    lines.append(line)
                if not lines:
                    raise ValueError('budget cannot retain even one complete word')
                return lines, used
            line.append(list(word))
            used += len(word)
        if line:
            lines.append(line)
    if not lines:
        raise ValueError('empty sampled training text')
    return lines, used


def bootstrap_documents(train, validation, test, fit_score, n_boot=100,
                        train_budget=1_000_000, seed=2026101007, refit=True):
    """fit_score(train_lines, fixed_validation, test_lines, replicate) -> rung scores.

    The callback owns fitting/scoring and must free models after each score.
    Test documents are sampled with replacement and losses should be token
    weighted. A test-only comparator (refit=False) keeps the original training
    documents and budget; this does not contain training-sample variation.
    """
    if min(len(train), len(validation), len(test)) < 2 or n_boot < 2:
        raise ValueError('need two documents per split and two replicates')
    rng = np.random.default_rng(seed)
    rows = []
    for rep in range(n_boot):
        # Draw both splits even in the test-only comparator: test draws stay paired.
        train_draw = rng.integers(0, len(train), len(train))
        test_draw = rng.integers(0, len(test), len(test))
        active_train = train_draw if refit else np.arange(len(train))
        train_lines, n_train = budget_words(train, active_train, train_budget)
        test_lines = [test[int(j)] for j in test_draw]
        t0 = time.monotonic()
        scores = fit_score(train_lines, validation, test_lines, rep)
        if not scores or not all(np.isfinite(value) and value > 0 for value in scores.values()):
            raise ValueError('invalid density scores')
        rows.append(dict(replicate=rep, sampled_train_ids=train_draw.tolist(),
                         active_train_ids=active_train.tolist(), sampled_test_ids=test_draw.tolist(),
                         validation_ids=list(range(len(validation))), n_train=n_train,
                         n_test=sum(len(word) for line in test_lines for word in line),
                         refit_training=refit, scores=scores, seconds=time.monotonic()-t0))
    return rows


def fake_documents(n_docs=8, tokens=400, vocab=6, seed=1):
    """Every fake document has the inventory, plus heterogeneous copy/reset text."""
    rng = np.random.default_rng(seed)
    documents = []
    for doc in range(n_docs):
        words = [[j] for j in range(vocab)]
        used = vocab
        while used < tokens:
            length = min(int(rng.integers(1,5)), tokens-used)
            word = [int(rng.integers(vocab))]
            for j in range(1,length):
                word.append(word[-1] if rng.random() < .3+.6*doc/(n_docs-1) else int(rng.integers(vocab)))
            words.append(word)
            used += length
        documents.append(words)
    return documents


def combine_panel_draws(reading_means, documents_by_language):
    """Combine a common crossed reading draw with independent language ID draws.

    reading_means is (B,L) in declared language order. Each language contributes
    B document-bootstrap rows in that SAME replicate order. No language draw is
    performed. This composition is tested on simulated values, not wired into
    cached real-data assembly.
    """
    means=np.asarray(reading_means,float)
    if means.ndim!=2 or means.shape[1]!=len(documents_by_language) or means.shape[1]<3:
        raise ValueError('need B by L means for at least three languages')
    if not np.isfinite(means).all() or np.any(means<=0):
        raise ValueError('invalid reading means')
    rungs=list(documents_by_language[0][0]['scores'])
    if '1w' not in rungs:
        raise ValueError('paired baseline rung 1w required')
    ids=[]
    for rows in documents_by_language:
        if len(rows)!=len(means) or any(list(row['scores'])!=rungs for row in rows):
            raise ValueError('all language/document draws must share replicate count and rungs')
        if any(row['replicate']!=b for b,row in enumerate(rows)):
            raise ValueError('document replicate order mismatch')
        ids.append([[row['scores'][rung] for rung in rungs] for row in rows])
    log_id=np.log(np.stack(ids,axis=1))
    log_sr=np.log(means)
    if not np.isfinite(log_id).all() or np.any(log_sr.std(axis=1)==0):
        raise ValueError('invalid densities or zero between-language SR spread')
    R=np.std(log_id+log_sr[:,:,None],axis=1,ddof=1)/log_sr.std(axis=1,ddof=1)[:,None]
    return dict(rungs=rungs,R=R,paired=R-R[:,[rungs.index('1w')]])


def kenlm_demo(n_boot=8, budget=2000, rungs=('0','1w','1','4-free'), treatment='bounded'):
    W = load('document_bootstrap_rungs', HERE.parent/'stage5/rungs.py')
    train, val, test = [fake_documents(seed=seed) for seed in (701,702,703)]
    root = HERE.parents[1]
    with tempfile.TemporaryDirectory(dir=root/'tests', prefix='.document-bootstrap-') as directory:
        work = Path(directory)
        def fit_score(training, validation, testing, rep):
            train_corpus, test_corpus = W.Corpus.from_words(training), W.Corpus.from_words(testing)
            # Each toy document is one line. Both requested line treatments
            # therefore reset at exactly these document starts. Actual running
            # contexts must never cross duplicated or unrelated documents.
            effective_treatment='bounded'
            scores = {}
            for rung in rungs:
                if rung in ('0','1w'):
                    # The runner uses training plug-in entropies at these rungs.
                    scores[rung] = W.plugin(train_corpus, rung, effective_treatment)
                else:
                    result = W.estimate(train_corpus,test_corpus,rung,effective_treatment,
                                        work/f'model-{rep}-{rung}',work,work/f'{rep}-{rung}.log',
                                        reserve=101_000_000, sort_memory='32M')
                    scores[rung] = result['test_bits']
                    if result['n_scored'] != len(test_corpus.s):
                        raise ValueError('incomplete document score')
            return scores
        started = time.monotonic()
        rows = bootstrap_documents(train,val,test,fit_score,n_boot,budget)
        if list(work.rglob('*.arpa*')) or list(work.rglob('*.bin')):
            raise AssertionError('a scored model was not deleted')
        return dict(schema='simulated-document-refit-v1', n_boot=n_boot, budget=budget,
                    original_train_tokens=sum(len(w) for line in train for w in line),
                    rungs=list(rungs), treatment=treatment, seed=2026101007,
                    one_line_per_document=True, document_boundaries='always reset',
                    fixed=['validation documents','model settings','model seed','syllable convention','reading panel'],
                    resampled=['training documents independently within language','test documents independently within language'],
                    cpu_threads=1, rows=rows, seconds=time.monotonic()-started,
                    code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('out',type=Path)
    p.add_argument('--n-boot',type=int,default=8)
    p.add_argument('--budget',type=int,default=2000)
    p.add_argument('--all-rungs',action='store_true')
    p.add_argument('--treatment',choices=('bounded','running'),default='bounded')
    args=p.parse_args()
    rungs=load('document_demo_rungs',HERE.parent/'stage5/rungs.py').RUNGS if args.all_rungs else ('0','1w','1','4-free')
    result=kenlm_demo(args.n_boot,args.budget,rungs,args.treatment)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(f'simulated document refits: replicates={args.n_boot} rungs={len(rungs)} '
          f'budget={args.budget} seconds={result["seconds"]:.3f} models_deleted=True cpu_threads=1')

if __name__=='__main__':
    main()
