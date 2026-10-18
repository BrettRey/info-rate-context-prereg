"""Finite declaration inputs are snapshotted once at every public boundary.

Mappings retain their schema; nested sequences become tuples. Numerical arrays,
models, corpus objects, callbacks and open files retain their native interfaces.
Explicit output sinks (issues, log and process I/O) are not input declarations.
Snapshots are idempotent, including aliases of the same one-shot iterator.
Public return values retain the existing list/dict schema.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
from collections.abc import Iterable, Mapping
from functools import wraps
from inspect import signature
from io import IOBase


class _Mapping(dict):
    pass


class _Tuple(tuple):
    pass


def freeze(value, memo=None):
    """Retain finite inputs recursively without flattening arrays or streams."""
    if isinstance(value, (_Mapping, _Tuple)):
        return value
    if memo is None:
        memo = {}
    if id(value) in memo:
        return memo[id(value)][1]
    if isinstance(value, Mapping):
        result = _Mapping()
        memo[id(value)] = (value, result)
        result.update((key, freeze(item, memo)) for key, item in value.items())
        return result
    # NumPy/Torch arrays and word corpora are scientific objects, not metadata
    # streams. Keep their shapes, dtypes, ownership and device without copying.
    if (isinstance(value, (str, bytes, bytearray, IOBase))
            or hasattr(value, 'shape') or hasattr(value, 's') or callable(value)):
        return value
    if isinstance(value, Iterable):
        result = _Tuple(freeze(item, memo) for item in value)
        memo[id(value)] = (value, result)
        if hasattr(value, 'issues'):
            result.issues = freeze(value.issues, memo)
        return result
    return value


def _out(value):
    """Undo snapshot wrappers only; leave ordinary results/arrays untouched."""
    if isinstance(value, _Tuple):
        if hasattr(value, 'issues'):
            # Diagnostic containers are consumed internally, not returned as
            # new API results. Preserve the metadata if one is returned.
            result = _Tuple(_out(item) for item in value)
            result.issues = value.issues
            return result
        return [_out(item) for item in value]
    if isinstance(value, dict):
        return {key: _out(item) for key, item in value.items()}
    if isinstance(value, list):
        # Keep e.g. Records and its missing-input diagnostics.
        for index, item in enumerate(value):
            value[index] = _out(item)
    elif isinstance(value, tuple):
        return tuple(_out(item) for item in value)
    return value


def boundary(function=None, *, arrays=(), sinks=()):
    """Snapshot each supplied input before validation, reuse or serialization.

    arrays names numerical inputs whose API also accepts sequence equivalents;
    corpora and existing arrays pass through. sinks names intentional outputs.
    Defaults participate too, so internal logic sees a consistent tuple schema.
    """
    arrays, sinks = tuple(arrays), tuple(sinks)
    if function is None:
        return lambda f: boundary(f, arrays=arrays, sinks=sinks)
    parameters = signature(function)
    excluded = {'self', 'cls', 'issues', 'log', 'stdin', 'stdout'} | set(sinks)

    @wraps(function)
    def retained(*args, **kwargs):
        bound = parameters.bind(*args, **kwargs)
        bound.apply_defaults()
        memo = {}
        for name, value in bound.arguments.items():
            if name not in excluded:
                bound.arguments[name] = freeze(value, memo)
        for name in arrays:
            value = bound.arguments[name]
            if value is not None and not hasattr(value, 's'):
                import numpy as np
                bound.arguments[name] = np.asarray(value)
        return _out(function(*bound.args, **bound.kwargs))

    retained.__iterable_boundary__ = True
    retained.__boundary_arrays__ = arrays
    return retained
