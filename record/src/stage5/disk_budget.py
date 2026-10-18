"""Cooperative per-process disk caps, serialized by a shared advisory lock.

Reservations deliberately charge each full cap, including already-written bytes.
This avoids counting the same free space twice; it is conservative, not a quota
against unrelated jobs or a builder's writes between monitoring observations.
"""
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage5_disk_budget_iterables", _BoundaryPath(__file__).with_name("iterables.py"))
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

from contextlib import contextmanager
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

_spec = importlib.util.spec_from_file_location("budget_disk_space", Path(__file__).with_name("disk_space.py"))
SPACE = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(SPACE)

GIB = 1024 ** 3
FLOOR = 40 * GIB

@_boundary
def directory_bytes(directory):
    total = 0
    for path in Path(directory).rglob("*"):
        try:
            if path.is_file():
                stat = path.stat()
                total += max(stat.st_size, stat.st_blocks * 512)
        except FileNotFoundError:
            pass
    return total

class DiskBudget:
    @_boundary
    def __init__(self, work, shared, cap, margin=2 * GIB, prefix=None):
        if type(cap) is not int or cap <= 0 or type(margin) is not int or margin < 2 * GIB:
            raise ValueError("Positive process cap and at least 2 GiB margin required")
        self.work, self.shared = Path(work).resolve(), Path(shared).resolve()
        self.cap, self.margin = cap, margin
        self.prefix = str(Path(prefix).resolve()) if prefix is not None else None
        self.owner = uuid.uuid4().hex
        self.active = False

    @contextmanager
    @_boundary
    def ledger(self):
        self.shared.mkdir(parents=True, exist_ok=True)
        with (self.shared / "disk-reservations.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.shared / "disk-reservations.json"
            records = json.loads(path.read_text()) if path.exists() else {}
            if not isinstance(records, dict):
                raise ValueError("Invalid shared reservation ledger")
            for value in records.values():
                if (not isinstance(value, dict) or type(value.get("pid")) is not int or value["pid"] <= 0
                        or type(value.get("cap")) is not int or value["cap"] <= 0
                        or type(value.get("margin")) is not int or value["margin"] < 2*GIB
                        or not isinstance(value.get("work"), str) or not Path(value["work"]).is_absolute()):
                    raise ValueError("Invalid shared reservation record")
            # A dead Python owner can leave a live builder. Retain stale caps;
            # reclaim only after an operator has verified that its children ended.
            try:
                yield records
            finally:
                tmp = path.with_suffix(".tmp")
                with tmp.open("w") as stream:
                    json.dump(records, stream, sort_keys=True)
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(tmp, path)
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _check(self, records, extra):
        SPACE.check_data(self.work, extra, directory_bytes)
        used = directory_bytes(self.work)
        free = shutil.disk_usage(self.shared).free
        reserved = sum(record["cap"] for record in records.values())
        margin = max([self.margin] + [record["margin"] for record in records.values()])
        if extra < 0 or used + extra > self.cap:
            raise RuntimeError(f"Disk stop: own work={used}, growth={extra}, cap={self.cap}")
        if free - reserved < FLOOR + margin:
            raise RuntimeError(f"Disk stop: free={free}, shared reservations={reserved}, floor={FLOOR}, margin={margin}")
        return dict(directory_bytes=used, free_bytes=free, reserve_bytes=extra,
                    shared_reserved_bytes=reserved, df="coordinated")

    def __enter__(self):
        # The project's explicit df preflight precedes reservations/large writes.
        print(subprocess.check_output(["df", "-g", "/"], text=True).rstrip(), flush=True)
        def existing(path):
            while not path.exists():
                path = path.parent
            return path
        if os.stat(existing(self.work)).st_dev != os.stat(existing(self.shared)).st_dev:
            raise ValueError("Work and shared reservation directory must use the same filesystem")
        with self.ledger() as records:
            for record in records.values():
                other = Path(record["work"])
                if (self.work == other or self.work.is_relative_to(other) or other.is_relative_to(self.work)
                        or self.prefix is not None and self.prefix == record.get("prefix")):
                    raise RuntimeError("Work directory or output prefix already reserved")
            records[self.owner] = dict(pid=os.getpid(), work=str(self.work), cap=self.cap,
                                       margin=self.margin, prefix=self.prefix)
            try:
                self._check(records, 0)
            except Exception:
                del records[self.owner]
                raise
        self.active = True
        return self

    @_boundary
    def check(self, extra=0, announce=False):
        if not self.active:
            raise RuntimeError("Disk budget is not reserved")
        if announce:
            print(subprocess.check_output(["df", "-g", "/"], text=True).rstrip(), flush=True)
        with self.ledger() as records:
            if self.owner not in records:
                raise RuntimeError("Lost shared disk reservation")
            return self._check(records, extra)

    def __exit__(self, *exc):
        with self.ledger() as records:
            records.pop(self.owner, None)
        self.active = False
