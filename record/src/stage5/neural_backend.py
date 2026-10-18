"""Word-aware neural ladder for versioned simulated runner jobs.

word_corpora maps each split to [{document, path}], in declared document order.
Each JSON file has schema word-corpus-v1, document, syllables, initial and starts,
and reset_starts: the starts where context must reset (the document start and
the first retained line after a masked one). The inventory is explicitly
declared, never inferred from held-out text. Running context crosses ordinary
lines within a document and resets at every declared reset and document boundary.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage5_neural_backend_iterables", _BoundaryPath(__file__).with_name("iterables.py"))
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import json, math
from pathlib import Path
import numpy as np


def _reset_starts(value, corpus, treatment):
    """Mandatory resets, kept apart from ordinary line starts.

    A running-context corpus with more than one start must say which of them
    are resets; without that, a masked line's gap can't be told from a line break.
    """
    starts = [int(s) for s in corpus.starts]
    if 'reset_starts' not in value:
        if treatment == 'running' and starts != [0]:
            raise ValueError('running-context word corpora must declare reset_starts')
        return [0]
    resets = value['reset_starts']
    if (not isinstance(resets, (list, tuple)) or not resets or resets[0] != 0
            or any(type(x) is not int for x in resets)
            or list(resets) != sorted(set(resets)) or not set(resets).issubset(set(starts))):
        raise ValueError('word-corpus reset starts must be ordered declared sequence starts')
    return list(resets)

@_boundary
def load(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

HERE = Path(__file__).resolve().parent
NN = load("runner_neural_model", HERE / "nnlm.py")
W = load("runner_word_rungs", HERE / "rungs.py")
PRODUCTION = load('runner_production', HERE / 'production.py')

@_boundary
def effective_settings(job):
    declaration = job["estimator"]
    allowed = {"name", "settings", "vocab", "higher_rungs", "line_treatment", "device"}
    if set(declaration) - allowed:
        raise ValueError("unknown neural estimator declaration")
    settings = declaration.get("settings")
    if not isinstance(settings, dict) or set(settings) - (set(NN.SETTINGS) | set(NN.OPTIONS)):
        raise ValueError("declare a neural settings mapping with supported keys")
    settings = NN.SETTINGS | (NN.OPTIONS if job.get('simulated') is not True else {}) | settings
    for key in ("dim", "hidden", "batch", "max_epochs", "evals_per_epoch", "patience"):
        if type(settings[key]) is not int or settings[key] < 1:
            raise ValueError(f"neural {key} must be a positive integer")
    if type(settings["seed"]) is not int or settings["seed"] < 0 or not math.isfinite(settings["lr"]) or settings["lr"] <= 0:
        raise ValueError("invalid neural seed or learning rate")
    vocab = declaration.get("vocab")
    if type(vocab) is not int or vocab < 1:
        raise ValueError("declare a positive neural inventory size")
    NN._settings(settings, vocab, 0, tuning=False)
    labels = {"bounded": "bounded", "line-bounded": "bounded", "running": "running", "cross-line": "running"}
    label = declaration.get("line_treatment", job["shared"].get("line"))
    if label not in labels:
        raise ValueError("declare bounded or running neural line treatment")
    treatment = labels[label]
    shared_label = job["shared"].get("line")
    if shared_label in labels and labels[shared_label] != treatment:
        raise ValueError("neural line treatment conflicts with shared setting")
    higher = declaration.get("higher_rungs", "plain")
    if higher != "plain":
        raise ValueError("production neural higher_rungs must be plain")
    effective = dict(name="neural", settings=settings, vocab=vocab, higher_rungs=higher, line_treatment=treatment)
    PRODUCTION.validate_neural(job, effective)
    return effective

@_boundary
def document_paths(job, local):
    declarations = job.get("word_corpora")
    if not isinstance(declarations, dict) or set(declarations) != set(job["documents"]):
        raise ValueError("declare word_corpora for all three document splits")
    result = {}; seen = set()
    for split, ids in job["documents"].items():
        entries = declarations[split]
        if not isinstance(entries, tuple) or tuple(e.get("document") for e in entries) != ids:
            raise ValueError("word corpora must match the declared documents and their order")
        paths = []
        for entry in entries:
            path = local(entry["path"])
            if path in seen:
                raise ValueError("word-corpus paths must be disjoint across documents and splits")
            seen.add(path); paths.append((entry["document"], path))
        result[split] = paths
    return result

@_boundary
def read_splits(job, local, return_documents=False):
    effective = effective_settings(job); paths = document_paths(job, local)
    splits = {}; documents = {}
    for split, entries in paths.items():
        syllables, initial, starts = [], [], []
        documents[split] = []
        for document, path in entries:
            value = json.loads(path.read_text())
            if value.get("schema") != "word-corpus-v1" or value.get("document") != document:
                raise ValueError("word corpus does not identify its declared document")
            arrays = [value.get(key) for key in ("syllables", "initial", "starts")]
            if any(not isinstance(a, list) or any(type(x) is not int for x in a) for a in arrays):
                raise ValueError("word corpora require integer vectors")
            corpus = W.Corpus(*arrays)
            documents[split].append(dict(document=document,n_tokens=len(corpus.s)))
            if np.max(corpus.s) >= effective["vocab"]:
                raise ValueError("word-corpus syllable outside declared inventory")
            resets = _reset_starts(value, corpus, effective["line_treatment"])
            offsets = corpus.starts if effective["line_treatment"] == "bounded" else resets
            starts.extend(int(s) + len(syllables) for s in offsets)
            syllables.extend(corpus.s); initial.extend(corpus.b)
        splits[split] = W.Corpus(syllables, initial, starts)
    return (splits, documents) if return_documents else splits

@_boundary
def estimate(job, local, rungs):
    effective = effective_settings(job); splits, documents = read_splits(job, local, return_documents=True)
    device = job.get("device", job["estimator"].get("device", "cpu"))
    scores = {}
    for rung in rungs:
        if job["rungs"][rung]["score_mode"] != "normalised":
            raise ValueError("neural outcomes require normalised score_mode")
        if rung in ("1", "2", "3", "4") and (rung == "1" or effective["higher_rungs"] == "plain"):
            result = NN.estimate(splits["train"], splits["validation"], splits["test"],
                                 effective["vocab"], int(rung), device=device, settings=effective["settings"],
                                 test_documents=documents['test'])
            definition = "plain"
        else:
            definition = rung if not rung.isdigit() or rung == "0" else rung + "-" + effective["higher_rungs"]
            result = NN.estimate_rung(splits["train"], splits["validation"], splits["test"],
                                      effective["vocab"], definition, "bounded", device=device, settings=effective["settings"],
                                      test_documents=documents['test'])
        scores[rung] = dict(id_bits=result["test_bits"], val_bits=result["val_bits"],
                            n_train=len(splits["train"].s), n_validation=len(splits["validation"].s),
                            n_test=len(splits["test"].s), steps=result["steps"], history=result["history"],
                            settings=result["settings"], device=result["device"], rung_definition=definition,
                            density_source='heldout_model',documents=result['test_documents'],n_scored=result['n_scored'])
    return scores
