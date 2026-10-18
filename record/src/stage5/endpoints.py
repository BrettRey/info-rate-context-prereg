"""Training maximum-likelihood endpoints, kept separate from held-out losses."""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage5_endpoints_iterables", _BoundaryPath(__file__).with_name("iterables.py"))
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

from collections import Counter
import math


@_boundary
def entropy(pairs):
    return _entropy(pairs)

def _entropy(pairs):
    counts = Counter(pairs)
    if not counts:
        raise ValueError('empty training text for plug-in endpoint')
    contexts = Counter()
    for (context, _), count in counts.items():
        contexts[context] += count
    n = sum(counts.values())
    return dict(id_bits=-math.fsum(count/n * math.log2(count/contexts[context])
                                  for (context, _), count in counts.items()),
                density_source='training_plugin', n_train=n,
                definition='maximum-likelihood training entropy')


@_boundary
def encoded(path, rung, prefix=None):
    """Read the same training targets/windows the held-out runner consumes.

    1w windows contain one context (the word-initial null marker or previous
    syllable) and one target. Missing context at a cut uses the start marker.
    """
    if rung not in ('0', '1w'):
        raise ValueError('plug-ins are defined only at 0 and 1w')
    if rung == '1w' and not prefix:
        raise ValueError('1w plug-in requires explicit context/target windows and target_prefix')
    def pairs():
        with open(path, encoding='utf-8') as source:
            for line in source:
                words = line.split()
                if rung == '0':
                    for word in words:
                        if prefix is None or word.startswith(prefix):
                            yield (), word
                elif words:
                    targets = [i for i, word in enumerate(words) if word.startswith(prefix)]
                    if targets != [len(words)-1] or len(words) > 2:
                        raise ValueError('1w plug-in needs one context/target window per line')
                    yield (words[0] if len(words) == 2 else '<s>',), words[-1]
    return _entropy(pairs())
