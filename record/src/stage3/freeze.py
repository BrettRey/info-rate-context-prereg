"""Write/validate the code and resource manifest bound to a timestamped freeze archive.

Write before archiving: python -I -B src/stage3/freeze.py --output FREEZE.json
Include FREEZE.json in a tar archive, then obtain its detached SHA-256 .ots
proof separately. This helper never stamps, extracts files, or uses a network.
Validation also requires the lead's recorded block-headers JSON. This lock
catches mistakes (premature entropy or stale code), not deliberate forgery.
It trusts those records; it does not validate a Bitcoin chain or confirmations.
"""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import sys
import functools
from types import FunctionType, MappingProxyType, MethodType, ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT
# Every project file the post-stamp routes can execute: the production command
# (src/stage7/entropy_phases.py) and the B/10 refit tool, with everything they
# load (P7, adopted 2026-10-11). tests/test_p7_freeze_closure.py holds this
# list equal to a trace of their loads; a loaded project module reachable from
# a listed one but not listed fails validation.
CODE_FILES = (
    'src/fakedata/f1_mapped.py',
    'src/fakedata/f1_neural_final.py',
    'src/fakedata/f1v2.py',
    'src/fakedata/nn_compare.py',
    'src/fakedata/nn_tuning.py',
    'src/stage3/counters.py',
    'src/stage3/freeze.py',
    'src/stage3/french_lexicon.py',
    'src/stage3/japanese.py',
    'src/stage3/multiverse.py',
    'src/stage3/native_units.py',
    'src/stage3/onsets.py',
    'src/stage3/read_text_guard.py',
    'src/stage3/segment.py',
    'src/stage3/segment_entropy.py',
    'src/stage3/shared_settings.py',
    'src/stage3/thai.py',
    'src/stage3/tones.py',
    'src/stage3/word_segmenters.py',
    'src/stage4/budgets.py',
    'src/stage4/escape.py',
    'src/stage4/linguistic_inputs.py',
    'src/stage4/pipeline.py',
    'src/stage4/splits.py',
    'src/stage5/disk_space.py',
    'src/stage5/endpoints.py',
    'src/stage5/iterables.py',
    'src/stage5/neural_backend.py',
    'src/stage5/nnlm.py',
    'src/stage5/production.py',
    'src/stage5/rungs.py',
    'src/stage5/runner.py',
    'src/stage6/analysis.py',
    'src/stage6/assemble.py',
    'src/stage6/named_universes.py',
    'src/stage6/ns_lens.py',
    'src/stage6/plateau.py',
    'src/stage6/reading_adapter.py',
    'src/stage6/refit_sensitivity.py',
    'src/stage7/corpora.py',
    'src/stage7/counts_phase.py',
    'src/stage7/entropy_phases.py',
    'src/stage7/sensitivity_checks.py',
)
# Data files listed code reads that change results: the frozen lexicons and
# their provenance, the digit readings of the read texts, the disk reservation.
RESOURCE_FILES = (
    'resources/cat_function_words.tsv', 'resources/cmn_erhua.tsv',
    'resources/digit-readings/readings.tsv', 'resources/fra-lexique-provenance.json',
    'resources/fra_lexique.tsv', 'resources/ita_hiatus.tsv', 'resources/lexicons-provenance.json',
    # Binds the uncommitted onset lexicons through their recorded SHA-256s (Brett, 2026-10-15).
    'resources/onset-lexicons-provenance.json',
    'src/stage5/f1c_reservation.json',
)
# Third-party distributions the listed code imports or names (models and
# dictionaries ship inside them: unidic-lite, pyopenjtalk, the segmenters'
# packages), and the two tools it runs. tests/test_p7_freeze_closure.py checks
# the list against the listed code's imports and the paths against the code's.
DISTRIBUTIONS = (
    'cantoseg', 'cmudict', 'epitran', 'fugashi', 'g2p-en', 'g2pk2', 'jieba', 'kenlm', 'nltk', 'numpy',
    'opentimestamps', 'pkuseg', 'pycantonese', 'pyopenjtalk', 'pyopenjtalk-plus', 'pythainlp', 'pyvi',
    'regex', 'scipy', 'tltk', 'torch', 'underthesea', 'unidic-lite',
)
# Machine paths, read as the runtime modules read them, absolute (DECISIONS.md, 2026-10-17).
MACHINE_PATHS = {'INFO_RATE_KENLM': str(Path.home() / 'src/kenlm/build/bin'),
                 'INFO_RATE_ESPEAK': '/opt/homebrew/bin/espeak-ng',
                 'INFO_RATE_ATTACUT_VENV': '/Users/brettreynolds/projects/LLM-CLI-projects/papers/development/info-rate-context/.venv-attacut',
                 'INFO_RATE_THAI_MODEL': '/Users/brettreynolds/pythainlp-data/thaig2p-0.1.tar'}


def machine_paths():
    """The machine paths this process is configured with; each must be absolute (Codex review, 2026-10-17)."""
    values = {name: os.environ.get(name, default) for name, default in MACHINE_PATHS.items()}
    for name, value in values.items():
        if not os.path.isabs(value):
            raise ValueError(f'{name} must be an absolute path: {value}')
    return values


KENLM = Path(machine_paths()['INFO_RATE_KENLM'])
KENLM_BINARIES = ('lmplz', 'build_binary')
ESPEAK = machine_paths()['INFO_RATE_ESPEAK']
# Models the listed code reads from outside the installed packages: the NLTK
# data English G2P is restricted to, the pinned Thai G2P model, and the separate
# interpreter that runs attacut (paths as in counters.py and thai.py).
NLTK_DATA = Path(sys.prefix) / 'nltk_data'
THAI_MODEL = Path(machine_paths()['INFO_RATE_THAI_MODEL'])
ATTACUT_VENV = Path(machine_paths()['INFO_RATE_ATTACUT_VENV'])
_IMPORTED_PATHS = machine_paths()
SCHEMA = 'production-freeze-v2'


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def code_digests(root=None):
    """Hash every listed code file."""
    root = ROOT if root is None else Path(root)
    return {name: sha256_file(root / name) for name in CODE_FILES}


def resource_digests(root=None):
    """Hash every listed resource file."""
    root = ROOT if root is None else Path(root)
    return {name: sha256_file(root / name) for name in RESOURCE_FILES}


_HASHES = {}


def _data_sha256(path):
    """SHA-256 of a data file, cached in this process by path, size and modification time."""
    path = Path(path).resolve()
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _HASHES:
        _HASHES[key] = sha256_file(path)
    return _HASHES[key]


def _tree(directory):
    directory = Path(directory)
    if not directory.is_dir():
        return None
    return {p.relative_to(directory).as_posix(): _data_sha256(p) for p in sorted(directory.rglob('*')) if p.is_file()}


def _listed_module(name):
    """The loaded instance of a listed file, loading it (as load_closure would) if none is loaded."""
    path = (SOURCE_ROOT / name).resolve()
    for module in tuple(sys.modules.values()):
        if isinstance(getattr(module, '__file__', None), str) and Path(module.__file__).resolve() == path:
            return module
    spec = importlib.util.spec_from_file_location('freeze_closure__' + name[:-3].replace('/', '__'), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def environment():
    """What outside the project changes results: Python, the listed distributions (version and
    installed-file record), the data files the segmenters declare, the Japanese readers' dictionaries,
    the KenLM binaries, espeak-ng and its data, the NLTK data, the Thai model and attacut's interpreter."""
    from importlib import metadata
    if machine_paths() != _IMPORTED_PATHS:
        raise ValueError('The machine paths changed after the freeze module was loaded')
    versions, records = {}, {}
    for name in DISTRIBUTIONS:
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            versions[name] = records[name] = None
            continue
        versions[name] = distribution.version
        record = distribution.read_text('RECORD')
        records[name] = None if record is None else hashlib.sha256(record.encode()).hexdigest()
    segmenters = _listed_module('src/stage3/word_segmenters.py')
    segmenter_data = {}
    for package, files in [*segmenters.RESOURCES.items(), *segmenters.DEPENDENCIES.values()]:
        try:
            distribution = metadata.distribution(package)
        except metadata.PackageNotFoundError:
            segmenter_data[package] = None
            continue
        for name in files:
            path = Path(distribution.locate_file(name))
            segmenter_data.setdefault(package, {})[name] = _data_sha256(path) if path.is_file() else None
    dictionaries = {}
    try:
        import unidic_lite
        dictionaries['unidic-lite'] = _tree(unidic_lite.DICDIR)
    except ImportError:
        dictionaries['unidic-lite'] = None
    try:
        import pyopenjtalk
        dictionaries['pyopenjtalk'] = _tree(pyopenjtalk.OPEN_JTALK_DICT_DIR.decode())
    except ImportError:
        dictionaries['pyopenjtalk'] = None
    espeak = subprocess.run([ESPEAK, '--version'], check=True, capture_output=True, text=True).stdout.strip()
    data = espeak.split('Data at:')[-1].strip() if 'Data at:' in espeak else None
    site = [str(p) for p in ATTACUT_VENV.glob('lib/python*/site-packages')]
    attacut = {}
    for distribution in metadata.distributions(path=site):
        record = distribution.read_text('RECORD')
        attacut[distribution.metadata['Name']] = [distribution.version,
                                                  None if record is None else hashlib.sha256(record.encode()).hexdigest()]
    interpreter = Path(os.path.realpath(ATTACUT_VENV / 'bin/python'))
    # attacut's own files, its model weights among them; compiled caches change with use.
    attacut_files = {str(Path(s).name): {k: v for k, v in _tree(Path(s) / 'attacut').items()
                                         if '__pycache__' not in k and not k.endswith('.pyc')}
                     for s in site if (Path(s) / 'attacut').is_dir()}
    return {'python': sys.version, 'machine_paths': _IMPORTED_PATHS, 'distributions': versions, 'distribution_records': records,
            'segmenter_data': segmenter_data, 'japanese_dictionaries': dictionaries,
            'kenlm': {name: sha256_file(KENLM / name) for name in KENLM_BINARIES},
            'espeak_ng': {'version': espeak, 'sha256': sha256_file(ESPEAK), 'data': _tree(data) if data else None},
            'nltk_data': _tree(NLTK_DATA), 'thai_model': _data_sha256(THAI_MODEL) if THAI_MODEL.is_file() else None,
            'attacut_environment': dict(sorted(attacut.items())),
            'attacut_interpreter': sha256_file(interpreter) if interpreter.is_file() else None,
            'attacut_package': attacut_files}


def manifest(root=None):
    return {'schema': SCHEMA, 'code_sha256': code_digests(root), 'resource_sha256': resource_digests(root),
            'environment': environment()}


def load_closure():
    """Load every listed file that no loaded module already comes from (matched by file, not name)."""
    present = {Path(m.__file__).resolve() for m in tuple(sys.modules.values())
               if isinstance(getattr(m, '__file__', None), str)}
    # Some listed modules set process state at import (refit_sensitivity.py sets
    # thread variables); loading them to validate must not change the run.
    saved = dict(os.environ)
    try:
        for name in CODE_FILES:
            path = SOURCE_ROOT / name
            if path.resolve() in present:
                continue
            spec = importlib.util.spec_from_file_location('freeze_closure__' + name[:-3].replace('/', '__'), path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
    finally:
        os.environ.clear(); os.environ.update(saved)


def unchanged_since(authorization):
    """Refuse if listed code, resources or the environment changed after a freeze authorization (end of a run).

    Other authorizations (invented test input) carry no freeze and are left alone.
    """
    if not isinstance(authorization, dict) or authorization.get('kind') != 'freeze-archive':
        return
    if (authorization.get('code_sha256') != code_digests()
            or authorization.get('resource_sha256') != resource_digests()
            or authorization.get('environment') != environment()):
        raise ValueError('Listed code, resources or environment changed during the run; its results are not covered by the freeze')


def write_manifest(path, root=None):
    result = manifest(root)
    Path(path).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return result


def _project_name(module):
    """A module's path relative to the project if it comes from src/, else None."""
    return _namespace_name(vars(module)) if hasattr(module, '__dict__') else None


def _namespace_name(namespace):
    """A namespace's file relative to the project if it is a module namespace from src/, else None."""
    filename = namespace.get('__file__') if isinstance(namespace, dict) else None
    if not isinstance(filename, str):
        return None
    path = Path(filename).resolve()
    if not path.is_relative_to(SOURCE_ROOT / 'src'):
        return None
    return path.relative_to(SOURCE_ROOT).as_posix()


_LEAVES = (str, bytes, bytearray, int, float, complex, bool, type(None), range, memoryview)


def _project_type(kind):
    return any(isinstance(v, FunctionType) and _namespace_name(v.__globals__) is not None
               for v in vars(kind).values())


def running_code_digests(loaded_modules=None, resources=None):
    """Hash retained, verified source for every project namespace the loaded listed code can reach.

    A pathname or loader's current disk source alone does not identify executed
    code. Every listed module retains its executing module code object and
    source bytes; recompilation must match that object before its digest is
    used. The walk starts from every loaded instance of a listed file (in
    sys.modules or passed as a live alias) and follows module attributes,
    functions (their defining namespace, closure cells, defaults, wrapped
    functions), methods, partials, containers and instances of project classes
    to every project namespace they lead to, registered or not. A namespace from
    src/ that isn't listed fails; two instances of one file with different
    source fail (a stale function kept in a registry leads to its old
    namespace). A namespace's `__freeze_resources__` (resource hashes it read
    into memory) must equal `resources` when given. Every listed file must be
    loaded (`load_closure`); unknown source identity fails shut.
    """
    digests, cached = {}, {}
    loaded_modules = dict(loaded_modules or {})
    for name, modules in loaded_modules.items():
        if name not in CODE_FILES or any(
                Path(getattr(module, '__file__', '')).resolve() != SOURCE_ROOT / name
                for module in modules):
            raise ValueError('Running dependency does not come from its manifest-named file: ' + name)
    start = tuple(sys.modules.values()) + tuple(
        module for aliases in loaded_modules.values() for module in aliases)
    seen_namespaces, seen, objects = set(), set(), []

    def visit(namespace):
        if id(namespace) in seen_namespaces:
            return
        seen_namespaces.add(id(namespace))
        name = _namespace_name(namespace)
        if name is None:
            return  # outside src/: not followed
        if name not in CODE_FILES:
            raise ValueError('Loaded project module is held by frozen code but not in the freeze list: ' + name)
        source = namespace.get('__freeze_source__')
        code = namespace.get('__freeze_module_code__')
        if not isinstance(source, bytes) or code is None:
            raise ValueError('Loaded module has no verified source identity: ' + name)
        compiled = compile(source, code.co_filename, 'exec', dont_inherit=True,
                           optimize=sys.flags.optimize)
        if compiled != code:
            raise ValueError('Loaded module differs from its retained source: ' + name)
        digest = hashlib.sha256(source).hexdigest()
        if name in digests and digests[name] != digest:
            raise ValueError('Loaded module aliases contain different source: ' + name)
        digests[name] = digest
        for path, value in dict(namespace.get('__freeze_resources__') or {}).items():
            cached.setdefault(path, set()).add(value)
        objects.extend(namespace.values())

    for module in start:
        if _project_name(module) in CODE_FILES:
            visit(vars(module))
    while objects:
        obj = objects.pop()
        if isinstance(obj, _LEAVES) or id(obj) in seen:
            continue
        seen.add(id(obj))
        if isinstance(obj, ModuleType):
            visit(vars(obj))
        elif isinstance(obj, FunctionType):
            visit(obj.__globals__)
            for cell in obj.__closure__ or ():
                try:
                    objects.append(cell.cell_contents)
                except ValueError:
                    pass  # an empty cell
            objects.extend(obj.__defaults__ or ())
            objects.extend((obj.__kwdefaults__ or {}).values())
            objects.extend(obj.__dict__.values())
        elif isinstance(obj, MethodType):
            objects.append(obj.__func__)
        elif isinstance(obj, functools.partial):
            objects.extend((obj.func, *obj.args, *obj.keywords.values()))
        elif isinstance(obj, (dict, MappingProxyType)):
            objects.extend(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            objects.extend(obj)
        elif isinstance(obj, type):
            if _project_type(obj):
                objects.extend(vars(obj).values())
        else:
            wrapped = getattr(obj, '__wrapped__', None)  # lru_cache and other wrappers
            if wrapped is not None:
                objects.append(wrapped)
            if hasattr(obj, '__dict__') and _project_type(type(obj)):
                objects.append(type(obj))
                objects.extend(vars(obj).values())
    if set(digests) != set(CODE_FILES):
        raise ValueError('Load all frozen analysis modules before validating their source')
    for path, values in cached.items():
        if path not in RESOURCE_FILES:
            raise ValueError('Loaded code read a resource that is not in the freeze list: ' + path)
        if resources is not None and values != {resources[path]}:
            raise ValueError('Loaded code holds a resource that differs from the listed file: ' + path)
    return digests


def verify_bitcoin_attestations(proof, block_headers):
    """Verify all Bitcoin commitments against the lead's offline header records.

    JSON uses display-order hexadecimal hashes; OpenTimestamps expects the
    Merkle root's internal byte order. These records are trusted inputs, not
    independently verified chain evidence. This catches mistakes, not forgery.
    """
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
    bitcoin = [(message, attestation) for message, attestation in proof.timestamp.all_attestations()
               if isinstance(attestation, BitcoinBlockHeaderAttestation)]
    if not bitcoin:
        raise ValueError('A completed Bitcoin block-header attestation is required')
    if block_headers is None or not Path(block_headers).is_file():
        raise ValueError('An existing --block-headers JSON file is required')
    records = json.loads(Path(block_headers).read_text(encoding='utf-8'))
    blocks = records.get('blocks') if isinstance(records, dict) else None
    if not isinstance(blocks, dict):
        raise ValueError('Block headers must contain a blocks mapping keyed by height')
    verified = {}
    for message, attestation in bitcoin:
        height = str(attestation.height)
        if height not in blocks:
            raise ValueError('Unknown Bitcoin block height: ' + height)
        record = blocks[height]
        try:
            block_hash, merkle_root, time = record['hash'], record['merkle_root'], record['time']
            for value in (block_hash, merkle_root):
                if not isinstance(value, str) or len(value) != 64 or len(bytes.fromhex(value)) != 32:
                    raise ValueError('Hashes must be 32-byte hexadecimal strings')
            if type(time) is not int or not 0 <= time <= 0xffffffff:
                raise ValueError('Block time must be a uint32 Unix timestamp')
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Invalid recorded Bitcoin block header at height ' + height) from exc
        header = SimpleNamespace(hashMerkleRoot=bytes.fromhex(merkle_root)[::-1], nTime=time)
        verified_time = attestation.verify_against_blockheader(message, header)
        verified[attestation.height] = {'height': attestation.height, 'hash': block_hash,
                                        'merkle_root': merkle_root, 'time': verified_time}
    return [verified[height] for height in sorted(verified)]


def validate_freeze(archive, proof_path, *, block_headers=None, running_digests=None, loaded_modules=None):
    """Offline binding with Bitcoin commitments verified against recorded headers.

    This requires the Bitcoin attestation type, never just a pending calendar
    URL, and verifies its Merkle root against the lead's recorded block header.
    The lock catches mistakes (premature entropy/stale code), not deliberate
    forgery. Header records are trusted; no chain/confirmation check is made.
    Loaded source identities are always checked, even if a caller supplies
    additional digests. They must equal the files named by the freeze manifest.
    """
    from opentimestamps.core.timestamp import DetachedTimestampFile
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
    from opentimestamps.core.serialize import BytesDeserializationContext

    proof_path = Path(proof_path)
    if proof_path.suffix != '.ots' or not proof_path.is_file():
        raise ValueError('An existing detached .ots proof is required')
    proof_bytes = proof_path.read_bytes()
    proof = DetachedTimestampFile.deserialize(BytesDeserializationContext(proof_bytes))
    bitcoin = [(message, attestation) for message, attestation in proof.timestamp.all_attestations()
               if isinstance(attestation, BitcoinBlockHeaderAttestation)]
    if not isinstance(proof.file_hash_op, OpSHA256) or not bitcoin:
        raise ValueError('A SHA-256 proof with a completed Bitcoin block-header attestation is required')
    if any(len(message) != 32 for message, _ in bitcoin):
        raise ValueError('Bitcoin block-header attestations require a 32-byte Merkle root')
    verified_blocks = verify_bitcoin_attestations(proof, block_headers)
    archive_digest = sha256_file(archive)
    if proof.file_digest.hex() != archive_digest:
        raise ValueError('Proof digest does not match the freeze archive SHA-256')
    # Never extract the archive. Permit a snapshot's enclosing directory, but
    # require exactly one ordinary FREEZE.json, with no path traversal.
    with tarfile.open(archive, 'r:*') as snapshot:
        matches = [member for member in snapshot.getmembers()
                   if PurePosixPath(member.name).name == 'FREEZE.json']
        if len(matches) != 1:
            raise ValueError('Archive must contain exactly one FREEZE.json')
        member = matches[0]
        name = PurePosixPath(member.name)
        if not member.isfile() or name.is_absolute() or '..' in name.parts or member.size > 1024 * 1024:
            raise ValueError('FREEZE.json must be a small regular archive member')
        with snapshot.extractfile(member) as stream:
            frozen = json.load(stream)
    resources = resource_digests()
    loaded = running_code_digests(loaded_modules, resources)
    current = code_digests()
    env = environment()
    if loaded != current:
        raise ValueError('Loaded analysis source differs from the manifest-named code files; restart and freeze again')
    if frozen != {'schema': SCHEMA, 'code_sha256': current, 'resource_sha256': resources, 'environment': env}:
        raise ValueError('Freeze manifest does not match the current code, resource files and environment')
    if running_digests is not None and current != running_digests:
        raise ValueError('Code files changed after the running analysis was imported; restart and freeze again')
    return {'kind': 'freeze-archive', 'archive_sha256': archive_digest,
            'proof_sha256': hashlib.sha256(proof_bytes).hexdigest(),
            'code_sha256': loaded, 'resource_sha256': resources, 'environment': env,
            'bitcoin_block_heights': [block['height'] for block in verified_blocks],
            'bitcoin_blocks': verified_blocks,
            'block_headers_sha256': sha256_file(block_headers),
            'validation': 'offline SHA-256 archive/proof binding, matching loaded source, code and resource files and manifest, Bitcoin commitments verified against trusted recorded headers; catches mistakes, not deliberate forgery; no chain or confirmation check'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('FREEZE.json'))
    args = parser.parse_args()
    write_manifest(args.output)
    print('Wrote ' + str(args.output))


if __name__ == '__main__':
    main()
