"""Run one language's full ladder serially, keeping scores and deleting fitted models.

Jobs name pre-tokenised train, validation and test files for every rung. Text is UTF-8,
one context-bounded sequence per line, with whitespace-separated tokens. Tokenisation
and document ids are declared, not inferred. Simulated jobs remain available;
real jobs require the existing verified freeze before any input hash or fit.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage5_runner_iterables", _BoundaryPath(__file__).with_name("iterables.py"))
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import argparse, fcntl, hashlib, importlib.util, json, math, os, re, shutil, signal, subprocess, sys
from pathlib import Path

GB = 1024 ** 3
RUNGS = ("0", "1w", "1", "2", "3", "4", "1b-free", "1b-charged",
         "2-free", "2-charged", "3-free", "3-charged", "4-free", "4-charged")
NEURAL_RUNGS = ("1w", "1", "4")
ORDERS = tuple(1 if r == "0" else int(r[0]) + 1 for r in RUNGS)

@_boundary
def production_rungs(estimator="kenlm"):
    name = estimator.get("name", "kenlm") if isinstance(estimator, dict) else estimator
    return NEURAL_RUNGS if name == "neural" else RUNGS

HERE = Path(__file__).resolve().parent
ROOT = Path.cwd().resolve()
KENLM = Path(os.environ.get("INFO_RATE_KENLM", Path.home() / "src/kenlm/build/bin"))  # machine path (DECISIONS.md, 2026-10-17)
if not KENLM.is_absolute():
    raise ValueError(f"INFO_RATE_KENLM must be an absolute path: {KENLM}")

@_boundary
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m

SPACE = load("runner_disk_space", HERE / "disk_space.py")
F = load("runner_f1v2", HERE.parent / "fakedata/f1v2.py")
ENDPOINTS = load('runner_endpoints', HERE / 'endpoints.py')
SHARED = load('runner_shared_settings', HERE.parent / 'stage3/shared_settings.py')

@_boundary
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

@_boundary
def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

@_boundary
def local(path):
    """Resolve within the working copy so jobs cannot read or write elsewhere."""
    p = Path(path).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError(f"path outside working copy: {path}")
    return p

@_boundary
def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

@_boundary
def tree_bytes(path):
    """Count regular files without following links outside the working copy."""
    total = 0
    for base, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not Path(base, d).is_symlink()]
        total += sum(Path(base, f).stat().st_size for f in files if not Path(base, f).is_symlink())
    return total

@_boundary
def empty(path):
    for p in path.iterdir():
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()

class DiskStop(RuntimeError):
    pass

class DiskGuard:
    """Budget each allocation, including atomic replacements and directory overhead."""
    @_boundary
    def __init__(self, floor=40 * GB, margin=GB, free_bytes=None, limit=3 * GB, *, work):
        self.work = Path(work)
        self.floor, self.margin, self.free_bytes, self.limit = floor, margin, free_bytes, limit

    @_boundary
    def check(self, size):
        reason = check_disk(self.work, size, self.floor, self.free_bytes, self.limit, self.margin)
        if reason:
            raise DiskStop(reason)

    @_boundary
    def mkdir(self, path):
        if path.exists():
            return
        missing = []
        p = path
        while not p.exists():
            missing.append(p); p = p.parent
        self.check(4096 * len(missing))
        path.mkdir(parents=True, exist_ok=True)

    @_boundary
    def allocation(self, size):
        # Round data up and reserve an extra block for filesystem metadata.
        self.check(((size + 4095) // 4096 + 1) * 4096)

@_boundary
def write_json(path, value, guard=None):
    """Commit complete scores atomically; an exception never leaves a partial cache entry."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = canonical(value) + "\n"
    (guard or DiskGuard(work=path.parent)).allocation(len(text.encode()))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

@_boundary
def check_disk(root, peak, floor=40 * GB, free_bytes=None, limit=3 * GB, margin=GB):
    """Check projected free space and the explicit run directory before allocating."""
    if peak < 0 or floor < 0 or margin < 0:
        raise ValueError("peak, floor and margin must be nonnegative")
    free = (free_bytes or (lambda: shutil.disk_usage(SPACE.existing_directory(root)).free))()
    required = max(max(floor, 40 * GB) + margin, 42 * GB)
    if peak > 100_000_000:
        # The pre-write 42 GiB rule is stricter than the usual per-estimate floor.
        df = subprocess.run(["df", "-g", "/"], capture_output=True, text=True, check=True)
        print(df.stdout.strip(), flush=True)
        # df is the required diagnostic; acceptance uses the destination above.
        required = max(required, 42 * GB)
    if free - peak < required:
        return f"disk stop: free={free}, peak={peak}, required_floor={required} bytes"
    try:
        SPACE.check_data(root, peak, tree_bytes)
    except RuntimeError as error:
        return str(error)
    if tree_bytes(root) + peak > limit:
        return f"working-copy stop: projected size exceeds {limit} bytes"
    return None

METADATA_KEYS = ("language", "shared", "options", "families", "documents", "source_hashes", "rates",
                 "comment", "comments", "label", "labels", "device", "document_alignment", "named_universe")

@_boundary
def metadata(job):
    """Keep analytical declarations separate so corrections can reuse fitted scores."""
    return {k: job[k] for k in METADATA_KEYS if k in job}

@_boundary
def estimator_settings(job, builtin=True):
    """Hash effective KenLM defaults; callbacks declare all their consumed settings."""
    settings = job.get("estimator", {})
    if builtin and settings.get("name", "kenlm") == "kenlm":
        return dict(name="kenlm", memory=settings.get("memory", "64M"),
                    fallback=settings.get("fallback", [0.5, 1.0, 1.5]))
    if builtin and settings.get("name") == "neural":
        return neural_backend().effective_settings(job)
    return settings

_NEURAL = None
@_boundary
def neural_backend():
    global _NEURAL
    if _NEURAL is None:
        _NEURAL = load("runner_neural_backend", HERE / "neural_backend.py")
    return _NEURAL

@_boundary
def neural_version():
    backend = neural_backend()
    return canonical(dict(source={Path(p).name: file_hash(p) for p in
                          (backend.__file__, backend.NN.__file__, backend.W.__file__, backend.PRODUCTION.__file__,
                           HERE.parent / 'fakedata/f1_neural_final.py',
                           HERE / 'iterables.py', HERE.parent / 'stage6/named_universes.py', HERE.parent / 'stage3/multiverse.py')},
                          torch=str(backend.NN.torch.__version__), numpy=backend.np.__version__))

@_boundary
def estimate_neural(job, scratch, guard=None, lock=None):
    """In-memory models, one complete ladder, no model file writes."""
    return neural_backend().estimate(job, local, NEURAL_RUNGS)

@_boundary
def one_mask_per_language(jobs):
    """Real jobs of a language with the same text-changing shared settings (run,
    stub, gap, Thai prose line) must be scored on the same frozen line mask."""
    masks = {}
    for job in jobs:
        if job.get('simulated') is not True:
            tokenisation = job.get('tokenisation') if isinstance(job.get('tokenisation'), dict) else {}
            key = SHARED.mask_key(job.get('language'), job.get('shared'))
            masks.setdefault(key, set()).add(tokenisation.get('mask_sha256'))
    mixed = sorted(str(key) for key, found in masks.items() if len(found) > 1)
    if mixed:
        raise ValueError(f'one frozen removal mask per language, text settings and inclusion set required: {mixed}')

@_boundary
def identity(job, code_version=None, estimator_version="kenlm-v1", *, builtin=True, authorized_real=False):
    """Hash code, settings and split contents, omitting storage paths and wall-clock times."""
    if job.get("simulated") is not True and not authorized_real:
        raise ValueError("F4 runner accepts simulated=True jobs only")
    if not isinstance(job.get("language"), str) or not job["language"]:
        raise ValueError("job needs a language")
    for key in ("shared", "options", "documents", "rungs", "tokenisation"):
        if not isinstance(job.get(key), dict):
            raise ValueError(f"job needs a {key} mapping")
    mask = job["tokenisation"].get("mask_sha256")
    if job.get("simulated") is not True and (job["tokenisation"].get("production_ready") is not True
                                             or not isinstance(mask, str) or not re.fullmatch(r"[0-9a-f]{64}", mask)):
        # Only Stage 4 inputs prepared from registry routes under a frozen
        # common mask may be scored; diagnostic bundles never reach here.
        raise ValueError("real jobs require production-ready tokenisation under a frozen removal mask")
    for key in ("shared", "options"):
        if any(not isinstance(v, str) for v in job[key].values()):
            raise ValueError(f"{key} values must be string labels")
    rungs = production_rungs(job.get("estimator", {}))
    if set(job["rungs"]) != set(rungs):
        raise ValueError(f"each estimate must declare exactly its production rungs: {rungs}")
    docs = job["documents"]
    if set(docs) != {"train", "validation", "test"}:
        raise ValueError("declare document ids for train, validation and test")
    sets = [set(docs[k]) for k in ("train", "validation", "test")]
    if any(not s for s in sets) or any(sets[i] & sets[j] for i in range(3) for j in range(i)):
        raise ValueError("document splits must be nonempty and disjoint")
    result = dict(schema="score-v2", estimator=estimator_settings(job, builtin),
                  tokenisation=job["tokenisation"], rungs={})
    hashes = {}
    neural = builtin and job.get("estimator", {}).get("name") == "neural"
    if neural:
        if job.get('simulated') is not True:
            result['named_universe'] = job['named_universe']
            result['named_declaration'] = neural_backend().PRODUCTION.resolve_named(job)
        neural_backend().read_splits(job, local)  # Validate document provenance even on cache reuse.
        result["word_corpora"] = {split: [file_hash(path) for _, path in entries]
                                  for split, entries in neural_backend().document_paths(job, local).items()}
        result['test_document_units'] = docs['test']
    for rung in rungs:
        order = 1 if rung == "0" else int(rung[0]) + 1
        r = job["rungs"][rung]
        if r.get("order") != order:
            raise ValueError(f"rung {rung} requires order {order}")
        if not r.get("encoding"):
            raise ValueError(f"declare tokenisation/encoding for rung {rung}")
        if r.get("score_mode") not in ("raw", "normalised"):
            raise ValueError("declare score_mode: raw or normalised")
        result["rungs"][rung] = {k: r[k] for k in ("order", "encoding", "score_mode", "target_prefix") if k in r}
        for split in (() if neural else docs):
            if builtin and split=='test' and 'test_documents' in r:
                continue  # Only the declared document files are consumed by scoring.
            path = local(r[split])
            if path not in hashes:
                hashes[path] = file_hash(path)
            result["rungs"][rung][split] = hashes[path]
        if builtin and not neural:
            result['rungs'][rung]['test_documents'] = [dict(document=d,sha256=file_hash(path))
                                                       for d,path in test_document_paths(job,r)]
    code = {"runner": file_hash(__file__), "fake_scorer": file_hash(F.__file__),
            "window_masses": file_hash(HERE / 'rungs.py'), "endpoints": file_hash(ENDPOINTS.__file__),
            "iterable_boundary": file_hash(HERE / "iterables.py")}
    result["code"] = {"source": code, "declared": code_version, "estimator": estimator_version}
    if job.get("simulated") is not True:
        consumed = dict(hashes)
        for rung in rungs:
            if builtin and not neural:
                consumed.update({local(path): file_hash(local(path)) for _, path in test_document_paths(job, job["rungs"][rung])})
        if neural:
            consumed.update({local(path): file_hash(local(path)) for entries in
                             neural_backend().document_paths(job, local).values() for _, path in entries})
        _production_provenance(job, consumed)
    return json.loads(canonical(result))

ANALYSIS_METADATA = ("rates", "families", "comment", "comments", "label", "labels", "document_alignment")


_INPUTS = None
def _linguistic_inputs():
    global _INPUTS
    if _INPUTS is None:
        _INPUTS = load("runner_linguistic_inputs", HERE.parent / "stage4/linguistic_inputs.py")
    return _INPUTS

def _production_provenance(job, consumed):
    """A real job must be one its preparation manifest lists, under that manifest's mask.

    The manifest (written by src/stage4/linguistic_inputs.py, read by its
    `read_preparation`) is checked against its own hash; the job must appear in it
    unchanged (as rebuilt from the manifest, P9 at real size), the manifest must
    record a production preparation, its removal mask must hash to the job's mask
    and pass the pipeline's own mask check, and every file the job consumes must be
    one the manifest records, with the same hash. The manifest path is not hashed
    into the identity, which stays path-independent.
    """
    path = job.get("preparation")
    if not isinstance(path, str):
        raise ValueError("real jobs must name the preparation manifest that produced them")
    inputs = _linguistic_inputs()
    try:
        manifest = inputs.read_preparation(local(path), verify=True)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("invalid preparation manifest")
    if manifest.get("production") is not True:
        raise ValueError("the preparation manifest is not a production preparation")
    # Analysis declarations (rates, families, labels) are attached after
    # preparation and don't change any input, so they are left out of the match.
    def inputs_of(value):
        return canonical({k: v for k, v in value.items() if k not in ANALYSIS_METADATA})
    listed = inputs.preparation_jobs(local(path), key=inputs.configuration_id(job["tokenisation"]["declaration"]))
    if inputs_of(job) not in {inputs_of(j) for j in listed}:
        raise ValueError("job is not listed unchanged in its preparation manifest")
    mask = job["tokenisation"]["mask_sha256"]
    if manifest.get("removal_mask_sha256") != mask or manifest.get("language") != job["language"]:
        raise ValueError("job mask or language differs from its preparation manifest")
    artifacts = manifest.get("artifacts", {})
    masks = [Path(p) for p in artifacts if Path(p).name == "removal-mask.json"]
    if len(masks) != 1 or file_hash(local(masks[0])) != artifacts[str(masks[0])]:
        raise ValueError("preparation manifest's removal mask is missing or changed")
    pipeline = load("runner_production_pipeline", HERE.parent / "stage4/pipeline.py")
    if pipeline.read_mask(local(masks[0]))["sha256"] != mask:
        raise ValueError("removal mask file does not match the job's mask")
    for consumed_path, value in consumed.items():
        if (inputs.recorded(local(path), consumed_path) or (None,))[0] != value:
            raise ValueError(f"consumed file not among the preparation's artifacts: {consumed_path}")

@_boundary
def validate_scores(scores, estimator="kenlm"):
    rungs = production_rungs(estimator)
    if set(scores) != set(rungs):
        raise ValueError("estimator did not return the full ladder")
    for rung in rungs:
        r = scores[rung]
        if 'plugin' in r:
            p = r['plugin']
            if (rung not in ('0', '1w') or p.get('density_source') != 'training_plugin'
                    or not math.isfinite(p['id_bits']) or p['id_bits'] < 0
                    or type(p.get('n_train')) is not int or p['n_train'] <= 0
                    or p['n_train'] != r.get('n_train')):
                raise ValueError('invalid training plug-in endpoint')
        if not math.isfinite(r["id_bits"]) or r["id_bits"] <= 0 or r["n_test"] <= 0:
            raise ValueError(f"invalid score at rung {rung}")
        if r.get('density_source') == 'heldout_model' and r.get('n_scored', r['n_test']) != r['n_test']:
            raise ValueError('incomplete document score: scored targets differ from test targets')
    if len({r["n_test"] for r in scores.values()}) != 1:
        raise ValueError("all rungs must score the same number of syllable targets")
    partitions = []
    for score in scores.values():
        if 'documents' not in score:
            continue  # Versioned callback/legacy caches can still be described.
        rows = score['documents']
        if (not rows or len({r['document'] for r in rows}) != len(rows)
                or any(type(r['n_tokens']) is not int or r['n_tokens'] <= 0
                       or not math.isfinite(r['loss_sum_bits']) or r['loss_sum_bits'] < 0 for r in rows)
                or sum(r['n_tokens'] for r in rows) != score['n_test']):
            raise ValueError('invalid or incomplete document scores')
        if score.get('density_source') not in ('heldout_model','training_plugin'):
            raise ValueError('document scores require density_source')
        if score['density_source']=='heldout_model' and not math.isclose(
                sum(r['loss_sum_bits'] for r in rows)/score['n_test'],score['id_bits'],rel_tol=2e-6,abs_tol=1e-7):
            raise ValueError('document loss sum disagrees with aggregate density')
        partitions.append([(r['document'],r['n_tokens']) for r in rows])
    if partitions and (len(partitions) != len(scores) or any(p != partitions[0] for p in partitions)):
        raise ValueError('every rung must share the same test document partition')


@_boundary
def test_document_paths(job, rung):
    """Ordered encoded document files; never guess boundaries in a merged file."""
    declared = job['documents']['test']
    rows = rung.get('test_documents')
    if rows is None:
        if len(declared) != 1:
            raise ValueError('multiple test documents require per-document encoded paths')
        return [(declared[0],local(rung['test']))]
    if not isinstance(rows,tuple) or tuple(r['document'] for r in rows) != declared:
        raise ValueError('encoded test files must identify each declared document in order')
    paths = [local(r['path']) for r in rows]
    if len(set(paths)) != len(paths):
        raise ValueError('test document encoded paths must be distinct')
    return list(zip(declared,paths))

@_boundary
def child_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False

@_boundary
def terminate_child(pid):
    """Kill a recorded process group before deleting files its children may still use."""
    if not child_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    # An orphan may briefly remain a zombie; SIGKILL has stopped all group writers.

@_boundary
def lock_child(lock, pid, guard):
    # Append rather than overwrite: a torn update leaves the prior pid recoverable.
    lock.seek(0); previous = lock.read()
    text = ("\n" if previous and not previous.endswith("\n") else "") + canonical({"child_pid": pid}) + "\n"
    guard.allocation(len(text.encode()))
    lock.seek(0, os.SEEK_END); lock.write(text); lock.flush(); os.fsync(lock.fileno())

@_boundary
def recorded_child(text):
    """Recover the last complete pid record, tolerating a crash during a later append."""
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        pid = value.get("child_pid")
        if pid is not None and (not isinstance(pid, int) or pid <= 1):
            raise ValueError("invalid child pid in runner lock")
        return pid
    return None

@_boundary
def manifest_value(entries, authorization=None):
    """The active manifest for (job_id, job) pairs in run order; assembly scores only these."""
    value = {"schema": "manifest-v2", "job_ids": sorted({jid for jid, _ in entries}),
             "jobs": [{"job_id": jid, "metadata": metadata(job)} for jid, job in entries]}
    if authorization is not None:
        value['entropy_authorization'] = authorization
    return value

@_boundary
def cross_job_checks(jobs, builtin=True):
    """What `run` checks across its jobs, for a caller that runs them one at a time.

    The production entropy phases run each job alone so that its token files exist
    only while it runs (P9); `run` still makes every per-job check, including the
    provenance check against the preparation's recorded digests.
    """
    if any(job.get('simulated') is not True for job in jobs):
        one_mask_per_language(jobs)
    source_docs, assignments = {}, set()
    for job in jobs:
        key = canonical([job["language"], job["shared"]])
        source = [job["documents"], job.get("source_hashes")]
        if key in source_docs and source_docs[key] != source:
            raise ValueError("options must use the same source documents within a language/setting")
        source_docs[key] = source
        assignment = canonical([key, estimator_settings(job, builtin), job["options"]])
        if assignment in assignments:
            raise ValueError("duplicate jobs in specification")
        assignments.add(assignment)

@_boundary
def run(jobs, work, estimator=None, estimator_version=None, code_version=None,
        floor_bytes=40 * GB, free_bytes=None, limit_bytes=3 * GB, margin_bytes=GB,
        error_on_input_change=False,freeze_archive=None,freeze_proof=None,block_headers=None):
    """Resume current score identities and refresh metadata without refitting unchanged inputs.

    A callback(job, scratch) returns the full ladder and releases models after scoring.
    Its declared peak must bound all scratch writes; all its consumed settings belong
    in job['estimator']. Inputs are rehashed before reuse and after estimation.
    """
    work = local(work)
    if work == ROOT:
        raise ValueError("use a dedicated work directory")
    builtin = estimator is None
    authorization = None
    if any(job.get('simulated') is not True for job in jobs):
        if not builtin:
            raise ValueError('custom estimators accept simulated=True only')
        entropy_gate=load('runner_freeze_gate',HERE.parent/'stage3/segment_entropy.py')
        authorization=entropy_gate.entropy_authorization(
            freeze_archive=local(freeze_archive) if freeze_archive is not None else None,
            freeze_proof=local(freeze_proof) if freeze_proof is not None else None,
            block_headers=local(block_headers) if block_headers is not None else None)
        one_mask_per_language(jobs)
    if not builtin and not estimator_version:
        raise ValueError("custom estimator needs estimator_version")
    versions = {}
    guard = DiskGuard(floor_bytes, margin_bytes, free_bytes, limit_bytes, work=work)
    cache, scratch = work / "cache", work / "scratch"
    report = {"completed": [], "skipped": [], "stopped": None}
    if authorization is not None:
        report['entropy_authorization']=authorization
    jid = None
    try:
        guard.mkdir(work)
        lockpath = work / "runner.lock"
        if not lockpath.exists():
            guard.allocation(0)
        with open(lockpath, "r+" if lockpath.exists() else "w+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock.seek(0); previous = lock.read().strip()
            if previous:
                pid = recorded_child(previous)
                if pid is not None:
                    terminate_child(pid)
                    lock_child(lock, None, guard)
            guard.check(0)  # Even a completed resume respects the safety margin.
            guard.mkdir(cache); guard.mkdir(scratch)
            empty(scratch)
            for p in cache.glob("*.json.tmp"):
                p.unlink()
            source_docs = {}; prepared = []; assignments = set()
            for job in jobs:
                if builtin:
                    name = job.get("estimator", {}).get("name", "kenlm")
                    if name not in ("kenlm", "neural"):
                        raise ValueError("unknown built-in estimator; supply a versioned callback")
                    backend = estimate_neural if name == "neural" else estimate_kenlm
                    if name not in versions:
                        versions[name] = neural_version() if name == "neural" else kenlm_version()
                    version = versions[name]
                else:
                    backend, version = estimator, estimator_version
                key = canonical([job["language"], job["shared"]])
                source = [job["documents"], job.get("source_hashes")]
                if key in source_docs and source_docs[key] != source:
                    raise ValueError("options must use the same source documents within a language/setting")
                source_docs[key] = source
                ident = identity(job, code_version, version, builtin=builtin,authorized_real=authorization is not None)
                assignment = canonical([key, estimator_settings(job, builtin), job["options"]])
                if assignment in assignments:
                    raise ValueError("duplicate jobs in specification")
                assignments.add(assignment)
                prepared.append([job, ident, digest(ident), version, backend])
            def manifest():
                return manifest_value([(x[2], x[0]) for x in prepared], authorization)
            write_json(work / "manifest.json", manifest(), guard)
            for item in prepared:
                job, ident, jid, version, backend = item
                current = identity(job, code_version, version, builtin=builtin,authorized_real=authorization is not None)
                if current != ident:
                    if error_on_input_change:
                        raise ValueError("input changed before cache reuse")
                    ident = current; jid = digest(ident); item[1:3] = [ident, jid]
                    write_json(work / "manifest.json", manifest(), guard)
                path = cache / f"{jid}.json"
                if path.exists():
                    saved = json.loads(path.read_text())
                    if saved.get("job_id") != jid or saved.get("identity") != ident:
                        raise ValueError(f"inconsistent cache: {path}")
                    validate_scores(saved["scores"], job.get("estimator", {}))
                    if saved.get("scores_hash") != digest(saved["scores"]):
                        raise ValueError(f"damaged scores: {path}")
                    guard.check(0)
                    report["skipped"].append(jid); continue
                peak = job.get("peak_bytes")
                if not isinstance(peak, int) or peak <= 0 or job.get("peak_source") not in ("declared", "measured"):
                    raise ValueError("declare positive peak_bytes and peak_source: declared or measured")
                guard.check(peak)
                try:
                    scores = (backend(job, scratch, guard, lock) if builtin else backend(job, scratch))
                    validate_scores(scores, job.get("estimator", {}))
                    if identity(job, code_version, version, builtin=builtin,authorized_real=authorization is not None) != ident:
                        raise ValueError("input changed while estimating")
                    saved = {"job_id": jid, "identity": ident, "metadata": metadata(job), "scores": scores,
                             "scores_hash": digest(scores)}
                    if authorization is not None:
                        saved['entropy_authorization']=authorization
                    write_json(path, saved, guard)
                    report["completed"].append(jid)
                finally:
                    empty(scratch)
    except DiskStop as error:
        report["stopped"] = {"job_id": jid, "reason": str(error)}
    if authorization is not None:
        # Child processes and fresh loads read code from disk: it must still be what was authorized.
        entropy_gate.F.unchanged_since(authorization)
    return report

@_boundary
def kenlm_version():
    """Include the actual training and binary-builder versions in each cache identity."""
    import kenlm
    return canonical({n: file_hash(KENLM / n) for n in ("lmplz", "build_binary")} |
                     {"module": file_hash(kenlm.__file__)})

@_boundary
def tokens(path, prefix=None):
    with open(path, encoding="utf-8") as f:
        for line in f:
            for w in line.split():
                if prefix is None or w.startswith(prefix):
                    yield w

@_boundary
def unigrams(arpa):
    """Read KenLM's own unigram probabilities, closing ARPA before deleting it."""
    lp = {}; in1 = False
    with open(arpa, encoding="utf-8") as f:
        for line in f:
            if line.startswith("\\1-grams:"):
                in1 = True; continue
            if in1:
                if not line.strip() or line.startswith("\\"):
                    break
                fields = line.split(); lp[fields[1]] = float(fields[0])
    return lp

@_boundary
def window_masses(arpa, model, test, order, prefix, flagged):
    """Reuse the exact ARPA recurrence rather than sum V outcomes per history."""
    word_rungs = load('runner_window_masses', HERE / 'rungs.py')
    class Masses(word_rungs.ClassMass):
        def _class(self, word):
            if not word.startswith(prefix):
                return None
            if not flagged:
                return 0
            suffix = word[len(prefix):]
            return int(suffix[0]) if suffix and suffix[0] in '01' else None
    wanted = set()
    for path in (test if isinstance(test, (list, tuple)) else (test,)):
        with open(path, encoding='utf-8') as stream:
            for line in stream:
                window = line.split()
                if window:
                    history = tuple(window[:-1])
                    wanted.add(('<s>',) + history if len(history) < order-1 else history)
    return Masses(arpa, model, wanted, flagged)


# As src/stage5/rungs.py encodes lmplz's zero backoffs (guarded_run) and refuses the
# targets that use them (score); rungs.py is pinned by F1c's code identity, so the
# values are repeated here and tests/test_p9_zero_backoff.py checks they agree.
ZERO_BACKOFF, ZERO_BACKOFF_SENTINEL = b"\t-inf\n", b"\t-1e30\n"
ZERO_PROBABILITY = -1e29

@_boundary
def encode_arpa_zero_backoffs(arpa):
    """Encode a fitted ARPA's zero backoffs in place, before build_binary.

    lmplz can write a valid zero backoff (-inf) when a discount is zero; build_binary
    and the Python loader reject it. The finite sentinel underflows to exactly zero
    in probability arithmetic, and the scorer refuses any target that uses it. The
    file is rewritten only if one occurs, so a model without one is byte-identical.
    Returns how many backoffs it encoded.
    """
    with open(arpa, 'rb') as f:
        count = sum(line.endswith(ZERO_BACKOFF) for line in f)
    if count:
        encoded = Path(str(arpa) + '.zero-backoffs')
        with open(arpa, 'rb') as source, open(encoded, 'wb') as out:
            for line in source:
                out.write(line.replace(ZERO_BACKOFF, ZERO_BACKOFF_SENTINEL))
        os.replace(encoded, arpa)
    return count

# The rung being scored (P9 at real size): `estimate_kenlm` names it and its test documents, and
# `score` builds its model, unigrams, window masses and normalisers once for all of them instead of
# once per document. Each history's mass depends only on that history and its suffixes, so scores
# are unchanged.
_SCORING = {}


def _scoring_context(arpa, binary, tests, order, prefix=None, outcome_policy='all'):
    """What `score` would load or compute for each of `tests`, once for all of them."""
    import kenlm
    context = dict(key=(str(arpa), str(binary), order, prefix, outcome_policy), normalisers={})
    if prefix is None and order == 1:
        context['unigrams'] = unigrams(arpa)
        return context
    context['model'] = kenlm.Model(str(binary))
    if prefix is not None:
        context['unigrams'] = unigrams(arpa)
        if order > 2:
            context['masses'] = window_masses(arpa, context['model'], tuple(map(str, tests)), order, prefix,
                                              outcome_policy == 'current-boundary')
    return context


@_boundary
def score(arpa, binary, test, order, prefix=None, outcome_policy='all', *, brute=False):
    """Score raw and outcome-normalised bits, counting only declared target tokens.

    Prefix scoring is for explicit context/target pairs: each line is C:context T:target.
    It conditions on C and normalises over the training T vocabulary, excluding scaffolding.
    """
    import kenlm
    shared, rung = None, _SCORING.get('rung')
    if (not brute and rung is not None and rung['key'] == (str(arpa), str(binary), order, prefix, outcome_policy)
            and str(test) in rung['tests']):
        if 'context' not in _SCORING:
            _SCORING['context'] = _scoring_context(arpa, binary, rung['tests'], order, prefix, outcome_policy)
        shared = _SCORING['context']
    if prefix is None and order == 1:
        lp = shared['unigrams'] if shared else unigrams(arpa)
        z = sum(10 ** v for w, v in lp.items() if w not in ("</s>", "<s>", "<unk>"))
        raw = norm = 0.0; n = oov = 0
        with open(test, encoding="utf-8") as f:
            for line in f:
                for w in line.split():
                    v = lp.get(w, lp["<unk>"]); oov += int(w not in lp)
                    raw += v; norm += v - math.log10(z); n += 1
        if not n:
            raise ValueError("empty test text")
        c = -math.log2(10) / n
        return raw * c, norm * c, n, oov
    if prefix is None:
        m = shared['model'] if shared else kenlm.Model(str(binary))
        s, s2, tmp = kenlm.State(), kenlm.State(), kenlm.State()
        raw = norm = 0.0; n = oov = 0
        with open(test, encoding="utf-8") as f:
            for line in f:
                m.BeginSentenceWrite(s)
                for w in line.split():
                    v = m.BaseScore(s, w, s2)
                    if v <= ZERO_PROBABILITY:
                        raise ValueError(f"Zero-probability target {w} under a zero backoff weight")
                    pe = 10 ** m.BaseScore(s, "</s>", tmp); pu = 10 ** m.BaseScore(s, "<unk>", tmp)
                    raw += v; norm += v - math.log10(1 - pe - pu)
                    n += 1; oov += int(w not in m); s, s2 = s2, s
        if not n:
            raise ValueError("empty test text")
        c = -math.log2(10) / n
        return raw * c, norm * c, n, oov
    if outcome_policy not in ('all', 'current-boundary'):
        raise ValueError('unknown window outcome policy')
    lp = shared['unigrams'] if shared else unigrams(arpa)
    outcomes = sorted(w for w in lp if w.startswith(prefix))
    if not outcomes:
        raise ValueError("training has no declared outcome vocabulary")
    m = shared['model'] if shared else kenlm.Model(str(binary))
    s, s2, tmp = kenlm.State(), kenlm.State(), kenlm.State()
    if shared:
        masses = shared.get('masses')
    else:
        masses = (window_masses(arpa, m, test, order, prefix, outcome_policy == 'current-boundary')
                  if order > 2 and not brute else None)
    normalisers = shared['normalisers'] if shared else {}
    raw = norm = 0.0; n = oov = 0
    with open(test, encoding="utf-8") as f:
        for line in f:
            window = line.split()
            if (not window or len(window) > order or any(w.startswith(prefix) for w in window[:-1])
                    or not window[-1].startswith(prefix)):
                raise ValueError("prefix-scored test lines must be history/target windows")
            context, target = tuple(window[:-1]), window[-1]
            m.BeginSentenceWrite(s)
            for word in context:
                m.BaseScore(s, word, s2); s, s2 = s2, s
            v = m.BaseScore(s, target, tmp)
            if v <= ZERO_PROBABILITY:
                raise ValueError(f"Zero-probability target {target} under a zero backoff weight")
            if target not in m:
                oov += 1
            boundary = None
            if outcome_policy == 'current-boundary':
                suffix = target[len(prefix):]
                if not suffix or suffix[0] not in '01':
                    raise ValueError('free outcomes require an explicit current boundary flag')
                boundary = suffix[0]
            key = (context, boundary)
            if key not in normalisers:
                if masses is None:
                    allowed = outcomes if boundary is None else [w for w in outcomes if w[len(prefix):].startswith(boundary)]
                    z = sum(10 ** m.BaseScore(s, w, tmp) for w in allowed)
                else:
                    history = ('<s>',) + context if len(context) < order-1 else context
                    z = masses.normalizer(history, int(boundary) if boundary is not None else None)
                normalisers[key] = math.log10(z)
            raw += v; norm += v - normalisers[key]; n += 1
    if not n:
        raise ValueError("empty test text")
    c = -math.log2(10) / n
    return raw * c, norm * c, n, oov

@_boundary
def kenlm_child(cmd, guard, lock, peak, **kwargs):
    """Launch one isolated group and persist its pid until every writer has stopped."""
    guard.check(peak)
    guard.allocation(128)
    # The wrapper cannot start KenLM until its pid is durable. Parent death before
    # that point closes the gate, so an unrecorded child exits without fitting.
    read_gate, write_gate = os.pipe()
    gate_code = ("import os,sys; fd=int(sys.argv[1]); token=os.read(fd,1); os.close(fd); "
                 "sys.exit(1) if token != b'1' else os.execv(sys.argv[2],sys.argv[2:])")
    try:
        child = subprocess.Popen([sys.executable, "-I", "-B", "-c", gate_code, str(read_gate), *cmd],
                                 start_new_session=True, pass_fds=(read_gate,), **kwargs)
    except BaseException:
        os.close(read_gate); os.close(write_gate)
        raise
    os.close(read_gate)
    try:
        if lock is not None:
            lock_child(lock, child.pid, guard)
        guard.check(peak)
        os.write(write_gate, b"1"); os.close(write_gate); write_gate = None
        stdout, stderr = child.communicate()
        return subprocess.CompletedProcess(cmd, child.returncode, stdout, stderr)
    finally:
        if write_gate is not None:
            os.close(write_gate)
        terminate_child(child.pid)
        child.wait()
        if lock is not None:
            lock_child(lock, None, guard)

@_boundary
def estimate_kenlm(job, scratch, guard=None, lock=None):
    """Fit the fourteen encodings in order, deleting each model after scoring."""
    guard = guard or DiskGuard(work=scratch)
    peak = job["peak_bytes"]
    settings = estimator_settings(job)
    if settings.get("name", "kenlm") != "kenlm":
        raise ValueError("built-in backend is KenLM; supply a versioned callback for another estimator")
    memory = settings.get("memory", "64M")
    fallback = settings.get("fallback", [0.5, 1.0, 1.5])
    scores = {}
    for rung in RUNGS:
        r = job["rungs"][rung]; arpa, binary = scratch / "model.arpa", scratch / "model.bin"
        tmp = scratch / "kenlm-tmp"; guard.mkdir(tmp)
        cmd = [str(KENLM / "lmplz"), "-o", str(r["order"]), "-S", memory, "-T", str(tmp)]
        try:
            guard.check(peak)
            with open(local(r["train"]), "rb") as train, open(arpa, "wb") as out:
                fit = kenlm_child(cmd, guard, lock, peak, stdin=train, stdout=out, stderr=subprocess.PIPE)
            log = fit.stderr.decode()
            if fit.returncode:
                if "BadDiscountException" not in log and "Could not calculate Kneser-Ney discounts" not in log:
                    raise RuntimeError(log[-2000:])
                guard.check(peak)
                with open(local(r["train"]), "rb") as train, open(arpa, "wb") as out:
                    retry = kenlm_child(cmd + ["--discount_fallback"] + [str(v) for v in fallback],
                                        guard, lock, peak, stdin=train, stdout=out, stderr=subprocess.PIPE)
                log += retry.stderr.decode()
                if retry.returncode:
                    raise RuntimeError(log[-2000:])
            zero_backoffs = 0
            if r["order"] > 1:
                # A zero backoff is encoded as rungs.py encodes it; no scored target may use it.
                guard.check(peak)
                zero_backoffs = encode_arpa_zero_backoffs(arpa)
                build = kenlm_child([str(KENLM / "build_binary"), str(arpa), str(binary)],
                                    guard, lock, peak, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if build.returncode:
                    error = build.stderr.decode()[-2000:]
                    if "Bad backoff -inf" in error:
                        raise RuntimeError(f"non-finite KenLM backoff at rung {rung} (order {r['order']}): {error}")
                    raise RuntimeError(f"build_binary at rung {rung}: {error}")
            prefix = r.get("target_prefix")
            documents = []; raw_loss = norm_loss = 0.; n = oov = 0
            kwargs = {'outcome_policy': 'current-boundary'} if prefix and rung.endswith('-free') else {}
            paths = test_document_paths(job,r)
            _SCORING.clear()
            _SCORING['rung'] = dict(key=(str(arpa), str(binary), r['order'], prefix, kwargs.get('outcome_policy', 'all')),
                                    tests=tuple(str(path) for _, path in paths))
            for document, path in paths:
                raw_bits, norm_bits, count, unknown = score(arpa,binary,path,r['order'],prefix,**kwargs)
                if count <= 0:
                    raise ValueError('unavailable test document score')
                raw_loss += raw_bits*count; norm_loss += norm_bits*count
                n += count; oov += unknown
                documents.append(dict(document=document,n_tokens=count,
                    loss_sum_bits=(raw_bits if r['score_mode']=='raw' else norm_bits)*count))
            raw, norm = raw_loss/n, norm_loss/n
            # The scorer's model object has gone out of scope; delete files before bookkeeping.
            _SCORING.clear()
            arpa.unlink(); binary.unlink(missing_ok=True)
            if r["score_mode"] == "normalised" and oov:
                raise ValueError("normalised score excludes <unk>; OOVs need an explicit policy")
            fell, discounts = F.discounts(log)
            counts = {f"n_{split}": sum(1 for _ in tokens(local(r[split]), prefix))
                      for split in ("train", "validation")}
            counts['n_test'] = sum(sum(1 for _ in tokens(path,prefix)) for _,path in test_document_paths(job,r))
            if counts['n_test'] != n:
                raise ValueError('per-document scores do not partition the aggregate test targets')
            scores[rung] = dict(counts, id_bits=raw if r["score_mode"] == "raw" else norm,
                                raw_bits=raw, normalised_bits=norm, oov=oov,
                                inventory_train=len(set(tokens(local(r["train"]), prefix))),
                                fallback_orders=fell, discounts=discounts,
                                density_source='heldout_model',documents=documents,n_scored=n)
            if zero_backoffs:
                scores[rung]['zero_backoffs'] = zero_backoffs
            if rung in ('0', '1w'):
                scores[rung]['plugin'] = ENDPOINTS.encoded(local(r['train']), rung, prefix)
        finally:
            _SCORING.clear()
            arpa.unlink(missing_ok=True); binary.unlink(missing_ok=True)
            shutil.rmtree(tmp)
    return scores

@_boundary
def demo_encoding(base, streams, guard=None):
    """Fourteen production streams/windows over the same invented targets."""
    guard = guard or DiskGuard(work=base)
    guard.mkdir(base)
    paths = {r: {} for r in RUNGS}
    for split, stream in streams.items():
        syll = [f"s{t}" for t in stream]; n = len(syll)
        guard.check(n * 900 + 65536)
        for rung in RUNGS:
            k = 0 if rung == "0" else int(rung[0])
            flagged = rung.endswith(("-free", "-charged"))
            path = base / f"{split}-{rung}.txt"
            with path.open('w') as out:
                if not flagged and rung != "1w":
                    out.write("".join(" ".join(syll[t:t+100]) + "\n" for t in range(0,n,100)))
                else:
                    for t, value in enumerate(syll):
                        b = int(t % 100 % 3 == 0)
                        if rung == "1w":
                            history = ["C:WORD"] if b else ["C:" + syll[t-1]]
                        else:
                            history = ["C:" + v for v in syll[max(t-t%100,t-k):t]]
                        target = f"T:{b}:{value}" if flagged else "T:" + value
                        out.write(" ".join([*history,target]) + "\n")
            paths[rung][split] = str(path)
    return {r: dict(paths[r], order=o, encoding="history-target-window-v2" if r.endswith(("-free","-charged")) or r == "1w" else "syllable-line",
                    score_mode="normalised", **({'target_prefix':'T:'} if r.endswith(("-free","-charged")) or r == "1w" else {}))
            for r,o in zip(RUNGS,ORDERS)}

@_boundary
def demo_jobs(out, seed=0, n_train=100_000, vocab=100, guard=None):
    """Cross two fake type conventions on the same F1v2 source documents in each language."""
    import numpy as np
    out = local(out)
    guard = guard or DiskGuard(work=out)
    guard.mkdir(out)
    jobs = []
    for i, language in enumerate(("fake-a", "fake-b", "fake-c")):
        docids = {s: [f"{language}-{s}-0"] for s in ("train", "validation", "test")}
        streams = {split: F.simulate(n, F.zipf(vocab), i, seed + 100 * i + j)
                   for j, (split, n) in enumerate((("train", n_train), ("validation", 10_000), ("test", 10_000)))}
        source_hashes = {s: hashlib.sha256(x.tobytes()).hexdigest() for s, x in streams.items()}
        for option in ("A", "B"):
            # B conflates the two most frequent types; no token or source document is removed.
            mapped = streams if option == "A" else {s: np.where(x == 0, 1, x) for s, x in streams.items()}
            rungs = demo_encoding(out / language / option, mapped, guard)
            jobs.append(dict(simulated=True, language=language, shared={"line": "line-bounded", "budget": "fake-B"},
                             options={"convention": option}, families={"convention": "source" if option == "A" else "variants"},
                             documents=docids, source_hashes=source_hashes,
                             tokenisation={"format": "whitespace-lines-v1", "word_length": 3, "line_length": 100},
                             estimator={"name": "kenlm", "memory": "64M", "seed": seed}, rungs=rungs,
                             rates={"mean_sr": float(np.exp(1.6 + 0.2 * i)), "matched_sr": float(np.exp(1.6 + 0.2 * i)),
                                    "paper_subset_sr": float(np.exp(1.6 + 0.2 * i))},
                             peak_bytes=96 * 1024 ** 2, peak_source="declared"))
    return jobs

@_boundary
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("jobs", help="JSON jobs; real scoring additionally requires a verified freeze")
    p.add_argument("work", help="dedicated cache/scratch directory")
    p.add_argument("--demo", action="store_true", help="create a small fake job specification first")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--floor-gb", type=float, default=40)
    p.add_argument("--margin-gb", type=float, default=1)
    p.add_argument("--error-on-input-change", action="store_true")
    p.add_argument('--freeze-archive'); p.add_argument('--freeze-proof'); p.add_argument('--block-headers')
    args = p.parse_args()
    guard = DiskGuard(int(args.floor_gb * GB), int(args.margin_gb * GB), work=local(args.jobs).parent)
    if args.demo:
        try:
            path = local(args.jobs); guard.mkdir(path.parent)
            write_json(path, demo_jobs(path.parent / "fake-text", args.seed, guard=guard), guard)
        except DiskStop as error:
            p.exit(2, str(error) + "\n")
    report = run(json.loads(local(args.jobs).read_text()), args.work, floor_bytes=guard.floor,
                 margin_bytes=guard.margin, error_on_input_change=args.error_on_input_change,
                 freeze_archive=args.freeze_archive,freeze_proof=args.freeze_proof,block_headers=args.block_headers)
    print(canonical(report))
    if report["stopped"]:
        raise SystemExit(2)

if __name__ == "__main__":
    main()
