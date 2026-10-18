"""Filesystem lookup and the separate ceiling for writes beneath a data folder."""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage5_disk_space_iterables", _BoundaryPath(__file__).with_name("iterables.py"))
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

from pathlib import Path

DATA_CEILING = 50_000_000_000  # decimal GB, distinct from the 42 GiB free floor

@_boundary
def existing_directory(path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    return path if path.is_dir() else path.parent

@_boundary
def data_directory(work):
    """Return the nearest enclosing data folder, without visiting other folders."""
    path = Path(work).resolve()
    return next((p for p in (path, *path.parents) if p.name == 'data'), None)

@_boundary
def check_data(work, reserve, measure, ceiling=DATA_CEILING):
    directory = data_directory(work)
    if directory is not None:
        used = measure(directory)
        if used + reserve > ceiling:
            raise RuntimeError(f'data ceiling: used={used}, reserve={reserve}, ceiling={ceiling}')
