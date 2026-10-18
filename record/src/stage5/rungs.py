"""Word-aware KenLM losses, normalised over the outcomes each rung predicts.

Boundary windows use plain syllables as history and (flag, syllable) as targets.
Only the current flag is supplied for free rungs; past flags are never supplied.
Higher charged rungs predict that same pair from k plain previous syllables.
This higher-rung convention is provisional (notes/multiverse-spec.md §2).
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage5_rungs_iterables", _BoundaryPath(__file__).with_name("iterables.py"))
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import importlib.util
import gzip, json, math, os, re, shutil, subprocess, threading, time
from pathlib import Path
import numpy as np
import kenlm

_spec = importlib.util.spec_from_file_location("rungs_disk_space", Path(__file__).with_name("disk_space.py"))
SPACE = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(SPACE)

KENLM = os.path.expanduser("~/src/kenlm/build/bin")
RUNGS = ("0", "1w", "1", "1b-free", "1b-charged", "2-free", "2-charged",
         "3-free", "3-charged", "4-free", "4-charged")

class Corpus:
    """Flat syllables, true word-initial flags and line starts, without padding tokens."""
    @_boundary
    def __init__(self, syllables, initial, starts):
        self.s = np.asarray(syllables, dtype=np.int64)
        self.b = np.asarray(initial, dtype=np.int64)
        self.starts = np.asarray(starts, dtype=np.int64)
        if not len(self.s) or self.s.shape != self.b.shape or np.any(self.s < 0):
            raise ValueError("nonempty, nonnegative syllables and matching flags required")
        if np.any((self.b != 0) & (self.b != 1)):
            raise ValueError("flags must be zero or one")
        if not len(self.starts) or self.starts[0] != 0 or np.any(np.diff(self.starts) <= 0) or self.starts[-1] >= len(self.s):
            raise ValueError("line starts must increase from zero within the corpus")

    @classmethod
    @_boundary
    def from_words(cls, lines):
        """Flatten lines of complete words, retaining one boundary flag per syllable."""
        s, b, starts = [], [], []
        for line in lines:
            if not line:
                continue
            starts.append(len(s))
            for word in line:
                if not word:
                    raise ValueError("empty words are not syllable outcomes")
                s.extend(word); b.extend([1] + [0] * (len(word) - 1))
        return cls(s, b, starts)

@_boundary
def convention(rung):
    if rung not in RUNGS:
        raise ValueError(f"unknown rung {rung}")
    k = 0 if rung == "0" else (1 if rung.startswith("1") else int(rung[0]))
    flagged = rung not in ("0", "1", "1w")
    return k, flagged, rung.endswith("free")

@_boundary
def histories(corpus, rung, treatment):
    """Return plain syllable histories, with word or line starts where context is absent."""
    k, _, _ = convention(rung)
    if treatment not in ("bounded", "running"):
        raise ValueError("treatment must be bounded or running")
    starts = corpus.starts if treatment == "bounded" else np.array([0])
    start_at = np.repeat(starts, np.diff(np.r_[starts, len(corpus.s)]))
    for i, s in enumerate(corpus.s):
        if rung == "1w":
            # Context symbols are separate from targets, including at line starts.
            h = ("<w>",) if corpus.b[i] else ((f"c{corpus.s[i - 1]}",) if i > start_at[i] else ("<s>",))
        elif k == 0:
            h = ()
        else:
            j = max(int(start_at[i]), i - k)
            h = tuple(f"s{x}" for x in corpus.s[j:i])
            if len(h) < k:
                h = ("<s>",) + h
        yield h

@_boundary
def target(s, b, flagged):
    return f"b{b}s{s}" if flagged else f"s{s}"

@_boundary
def plugin(corpus, rung, treatment):
    """Training-sample plug-in entropy for the paper's unigram and within-word contexts."""
    if rung == "0":
        _, counts = np.unique(corpus.s, return_counts=True)
        p = counts / counts.sum()
        return float(-np.sum(p * np.log2(p)))
    if rung != "1w" or treatment not in ("bounded", "running"):
        raise ValueError("plug-in entropy is defined here for 0 and 1w")
    vocab = int(corpus.s.max()) + 1
    ctx = np.r_[vocab + 1, corpus.s[:-1]].copy()
    ctx[corpus.b == 1] = vocab
    if treatment == "bounded":
        missing = corpus.starts[corpus.b[corpus.starts] == 0]
        ctx[missing] = vocab + 1
    pairs, counts = np.unique(ctx * vocab + corpus.s, return_counts=True)
    totals = np.bincount(pairs // vocab, weights=counts)
    return float(-np.sum(counts / counts.sum() * np.log2(counts / totals[pairs // vocab])))

@_boundary
def text_bytes(corpus, rung):
    """Upper bound every token, separator and newline, including large integer IDs."""
    k, flagged, _ = convention(rung)
    syllable_width = 1 + len(str(int(np.max(corpus.s))))
    if flagged or rung == "1w":
        history_width = max(syllable_width, 3)  # c123 or the word marker <w>
        target_width = syllable_width + (2 if flagged else 0)
        return len(corpus.s) * (k * (history_width + 1) + target_width + 1)
    return len(corpus.s) * (syllable_width + 1)

@_boundary
def write_files(train, test, rung, treatment, directory, root=None, resource_budget=None, *, owned_paths=None):
    """Write stream files for plain rungs and explicit prediction windows for boundary rungs."""
    directory = Path(directory)
    disk_guard(directory, text_bytes(train, rung) + text_bytes(test, rung) + 16384,
               resource_budget=resource_budget, owned_paths=owned_paths)
    directory.mkdir(parents=True, exist_ok=True)
    k, flagged, _ = convention(rung)
    paths = []
    for name, corpus in (("train", train), ("test", test)):
        path = directory / f"{name}.txt"; paths.append(path)
        with open(path, "w") as f:
            if flagged or rung == "1w":
                for i, h in enumerate(histories(corpus, rung, treatment)):
                    # KenLM inserts <s>; it is not a literal token in the file.
                    toks = tuple(x for x in h if x != "<s>") + (target(corpus.s[i], corpus.b[i], flagged),)
                    f.write(" ".join(toks) + "\n")
            else:
                starts = corpus.starts if treatment == "bounded" else np.array([0])
                for a, z in zip(starts, np.r_[starts[1:], len(corpus.s)]):
                    # Chunk writes preserve a single running line without a giant string.
                    for j in range(a, z, 10000):
                        if j > a:
                            f.write(" ")
                        f.write(" ".join(f"s{x}" for x in corpus.s[j:min(j + 10000, z)]))
                    f.write("\n")
    return paths

@_boundary
def state_for(model, history):
    state, other = kenlm.State(), kenlm.State()
    model.NullContextWrite(state)
    for word in history:
        model.BaseScore(state, word, other); state, other = other, state
    return state

@_boundary
def open_arpa(path):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)

class ClassMass:
    """Sum ARPA probabilities exactly by target class, including recursive backoff mass."""
    @_boundary
    def __init__(self, arpa, model, wanted, flagged):
        self.model, self.flagged = model, flagged
        wanted = set(wanted)
        for h in list(wanted):
            wanted.update(h[j:] for j in range(len(h) + 1))
        self.mass, self.vocabulary = {}, set()
        observed, lower, backoff = {}, {}, {}
        root = np.zeros(2 if flagged else 1)
        order = 0; tmp = kenlm.State(); lower_states = {}
        for line in open_arpa(arpa):
            match = re.match(r"\\(\d+)-grams:", line)
            if match:
                order = int(match[1]); continue
            if not order or not line.strip() or line.startswith("\\"):
                continue
            parts = line.split()
            if len(parts) < order + 1:
                continue
            words = tuple(parts[1:order + 1]); h, word = words[:-1], words[-1]
            if words in wanted and len(parts) > order + 1:
                backoff[words] = 10 ** float(parts[-1])
            cls = self._class(word)
            if cls is None:
                continue
            probability = 10 ** float(parts[0])
            if order == 1:
                root[cls] += probability; self.vocabulary.add(word)
            elif h in wanted:
                if h not in observed:
                    observed[h] = np.zeros_like(root); lower[h] = np.zeros_like(root)
                observed[h][cls] += probability
                suffix = h[1:]
                st = lower_states.get(suffix)
                if st is None:
                    st = state_for(model, suffix); lower_states[suffix] = st
                lower[h][cls] += 10 ** model.BaseScore(st, word, tmp)
        self.mass[()] = root
        for h in sorted(wanted, key=len):
            if not h:
                continue
            self.mass[h] = observed.get(h, 0) + backoff.get(h, 1.0) * (self.mass[h[1:]] - lower.get(h, 0))
            if np.any(self.mass[h] < 0) or self.mass[h].sum() <= 0:
                raise ValueError(f"invalid outcome mass for history {h}")

    def _class(self, word):
        if self.flagged:
            return int(word[1]) if re.fullmatch(r"b[01]s\d+", word) else None
        return 0 if re.fullmatch(r"s\d+", word) else None

    @_boundary
    def normalizer(self, history, flag=None):
        p = self.mass[history]
        return float(p.sum() if flag is None else p[flag])

    @_boundary
    def brute(self, history, flag=None):
        """Independent direct sum for small-case verification of the ARPA recurrence."""
        st, tmp = state_for(self.model, history), kenlm.State()
        return sum(10 ** self.model.BaseScore(st, w, tmp) for w in self.vocabulary
                   if flag is None or self._class(w) == flag)

@_boundary
def score(model, arpa, corpus, rung, treatment, check=False):
    """Return raw and outcome-normalised bits per syllable; reject unsupported test outcomes."""
    _, flagged, free = convention(rung)
    wanted = set(histories(corpus, rung, treatment))
    masses = ClassMass(arpa, model, wanted, flagged)
    if check:
        for h in wanted:
            for b in ((0, 1) if flagged else (None,)):
                if not math.isclose(masses.normalizer(h, b), masses.brute(h, b), rel_tol=2e-5, abs_tol=2e-7):
                    raise AssertionError(f"class sum disagrees for {h}, flag {b}")
    raw = norm = joint = conditional = 0.0; tmp = kenlm.State(); previous = None
    for i, h in enumerate(histories(corpus, rung, treatment)):
        w = target(corpus.s[i], corpus.b[i], flagged)
        if w not in masses.vocabulary:
            raise ValueError(f"OOV target {w}; no syllable-only distribution is defined for it")
        if h != previous:
            st = state_for(model, h); previous = h
        lp = model.BaseScore(st, w, tmp)
        if lp <= -1e29:
            raise ValueError(f"Zero-probability target {w} under a zero backoff weight")
        z = masses.normalizer(h, int(corpus.b[i]) if free else None)
        raw += lp; norm += lp - math.log10(z)
        if flagged:
            joint += lp - math.log10(masses.normalizer(h))
            conditional += lp - math.log10(masses.normalizer(h, int(corpus.b[i])))
    scale = -math.log2(10) / len(corpus.s)
    result = dict(raw_bits=raw * scale, test_bits=norm * scale, n_scored=len(corpus.s), oov=0,
                  n_histories=len(wanted))
    if flagged:
        result.update(joint_bits=joint * scale, conditional_bits=conditional * scale)
    return result

@_boundary
def directory_bytes(directory):
    directory = Path(directory)
    if directory.is_file():
        return directory.stat().st_size
    total = 0
    for p in Path(directory).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except FileNotFoundError:  # builders can unlink a scratch file between these checks
            pass
    return total

@_boundary
def disk_guard(root, reserve, free=None, resource_budget=None, *, owned_paths=None):
    """Check the explicit run directory or owned output paths against disk limits.

    File writers may supply all their artifacts instead of charging an unrelated
    shared parent. `root` still identifies the filesystem and enclosing data cap.
    """
    if reserve < 0:
        raise ValueError("reserve must be nonnegative")
    SPACE.check_data(root, reserve, directory_bytes)
    if free is None:
        record = subprocess.run(["df", "-g", "/"], capture_output=True, text=True, check=True)
        free = shutil.disk_usage(SPACE.existing_directory(root)).free
    else:
        record = None
    used = sum(directory_bytes(path) for path in owned_paths) if owned_paths is not None else directory_bytes(root)
    cap = getattr(resource_budget, "cap", None)
    over_cap = used + reserve > cap if type(cap) is int else used + reserve >= 3_000_000_000
    if free - reserve < 42 * 1024 ** 3 or over_cap:
        raise RuntimeError(f"disk guard: free={free}, used={used}, reserve={reserve}")
    if resource_budget is not None:
        # Shared scratch reservations supplement the destination's own limits.
        resource_budget.check(reserve)
    return dict(free_bytes=free, directory_bytes=used, reserve_bytes=reserve,
                df=record.stdout.strip() if record else "simulated")

@_boundary
def guarded_run(cmd, stdin, stdout, root, log_path, limit=2_750_000_000, compressed=False, headroom=100_000_000, resource_budget=None, *, owned_paths=None):
    """Run one builder, stopping it before measured disk use reaches either floor."""
    errors = []
    zero_backoffs = 0
    initial = disk_guard(root, headroom + 16384, resource_budget=resource_budget, owned_paths=owned_paths)
    peak = initial["directory_bytes"]
    def measure():
        nonlocal peak
        used = disk_guard(root, headroom, free=shutil.disk_usage(SPACE.existing_directory(root)).free,
                          resource_budget=resource_budget,
                          owned_paths=owned_paths)["directory_bytes"]
        peak = max(peak, used)
        if resource_budget is None and used >= limit:
            raise RuntimeError(f"disk guard stopped builder at {used} bytes")
    with open(stdin) as inp, open(stdout, "wb") as out, open(log_path, "w") as err:
        p = subprocess.Popen(cmd, stdin=inp, stdout=subprocess.PIPE if compressed else out, stderr=err)
        def drain():
            nonlocal zero_backoffs
            try:
                with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=1, mtime=0) as gz:
                    carry = b""
                    while True:
                        block = p.stdout.read(1024 * 1024)
                        if not block:
                            break
                        block = carry + block
                        end = block.rfind(b"\n") + 1
                        body, carry = block[:end], block[end:]
                        # lmplz can produce a valid zero backoff when its discount
                        # is zero. The Python loader rejects -inf. A finite log
                        # sentinel underflows to exactly zero in probability
                        # arithmetic; the scorer rejects any outcome using it.
                        zero_backoffs += body.count(b"\t-inf\n")
                        gz.write(body.replace(b"\t-inf\n", b"\t-1e30\n"))
                    if carry:
                        gz.write(carry)
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=drain) if compressed else None
        if worker:
            worker.start()
        try:
            while p.poll() is None:
                measure()
                if errors:
                    raise RuntimeError(f"ARPA compression failed: {errors[0]}")
                time.sleep(0.1)
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait()
            if worker:
                worker.join(); p.stdout.close()
        measure()  # Also measure fast children and the completed gzip drain.
        if errors:
            raise RuntimeError(f"ARPA compression failed: {errors[0]}")
    disk_guard(root, 16384, resource_budget=resource_budget, owned_paths=owned_paths)
    with open(log_path, "a") as record:
        record.write(f"\nZero backoffs encoded: {zero_backoffs}\n")
    return p.returncode, peak

@_boundary
def reservation_calibration():
    """Static reviewed calibration, fingerprinted by the F1c driver."""
    value = json.loads(Path(__file__).with_name("f1c_reservation.json").read_text())
    fields = ("n_train", "max_n_test", "max_peak_directory_bytes", "round_up_bytes")
    if (value.get("schema") != "f1c-reservation-v1"
            or any(type(value.get(key)) is not int or value[key] <= 0 for key in fields)
            or type(value.get("max_syllable_id")) is not int or value["max_syllable_id"] < 0
            or type(value.get("margin_percent")) is not int or value["margin_percent"] <= 0):
        raise ValueError("invalid F1c reservation calibration")
    return value


@_boundary
def default_reserve(train, test, rung, compressed, text_reserve):
    """Use measured aggregate growth for the covered full F1c budget only.

    Ten percent over the largest of 66 sampled aggregate directory peaks, rounded
    up to 100 MB, is 2.7 GB. Taking an old total-directory peak as new additional
    growth is conservative about the new root's existing files. The measurement
    already includes both text files: do not add them a second time.
    """
    calibration = reservation_calibration()
    if (compressed and len(train.s) == calibration["n_train"]
            and len(test.s) <= calibration["max_n_test"]
            and max(int(np.max(train.s)), int(np.max(test.s))) <= calibration["max_syllable_id"]):
        peak = calibration["max_peak_directory_bytes"]
        quantum = calibration["round_up_bytes"]
        rounded = ((peak * (100 + calibration["margin_percent"]) + 100 * quantum - 1)
                   // (100 * quantum)) * quantum
        return max(text_reserve, rounded)
    k, _, _ = convention(rung)
    return max(100_000_000, len(train.s) * (120 + 45 * k)) + text_reserve


@_boundary
def estimate(train, test, rung, treatment, work, root, log_path, check=False, reserve=None, compressed=True,
             sort_memory="256M", resource_budget=None, *, owned_paths=None):
    """Fit one KenLM model, score held-out syllables and delete model and scratch files."""
    work = Path(work)
    # Legacy root is a path-containment argument; disk accounting is local to work.
    root = work
    k, _, _ = convention(rung); t0 = time.time()
    # An upper budget, checked again while the builder runs, includes text and scratch.
    text_reserve = text_bytes(train, rung) + text_bytes(test, rung) + 65536
    reserve = reserve if reserve is not None else default_reserve(train, test, rung, compressed, text_reserve)
    if reserve < text_reserve:
        raise RuntimeError("disk guard: declared reserve does not cover both text files")
    accounting = dict(resource_budget=resource_budget, owned_paths=owned_paths)
    record = disk_guard(root, reserve, **accounting)
    work.mkdir(parents=True, exist_ok=True)
    try:
        train_path, test_path = write_files(train, test, rung, treatment, work, root=root, **accounting)
        arpa = work / ("model.arpa.gz" if compressed else "model.arpa")
        order = k + 1
        cmd = [f"{KENLM}/lmplz", "-o", str(order), "-S", sort_memory, "-T", str(work)]
        disk_guard(root, max(100_000_000, reserve - directory_bytes(work)), **accounting)
        ret, peak = guarded_run(cmd, train_path, arpa, root, log_path, compressed=compressed, **accounting)
        log = Path(log_path).read_text(); fallback = False
        if ret:
            if "BadDiscountException" not in log and "Could not calculate Kneser-Ney discounts" not in log:
                raise RuntimeError(log[-2000:])
            fallback = True
            disk_guard(root, max(100_000_000, reserve - directory_bytes(work)), **accounting)
            ret, peak2 = guarded_run(cmd + ["--discount_fallback"], train_path, arpa, root, str(log_path) + ".retry", compressed=compressed, **accounting)
            log += Path(str(log_path) + ".retry").read_text(); peak = max(peak, peak2)
            disk_guard(root, len(log.encode()) + 16384, **accounting)
            Path(log_path).write_text(log); Path(str(log_path) + ".retry").unlink()
            if ret:
                raise RuntimeError(log[-2000:])
        if rung == "0":
            # Python KenLM does not load order-one models; score its ARPA directly.
            lp = {}
            for line in open_arpa(arpa):
                parts = line.split()
                if len(parts) >= 2 and re.fullmatch(r"s\d+", parts[1]):
                    lp[int(parts[1][1:])] = float(parts[0])
            if any(int(s) not in lp for s in np.unique(test.s)):
                raise ValueError("OOV syllable in unigram test set")
            z = sum(10 ** x for x in lp.values())
            loss = -math.log2(10) * float(np.mean([lp[int(s)] for s in test.s]))
            result = dict(raw_bits=loss, test_bits=loss + math.log2(z), n_scored=len(test.s), oov=0)
        else:
            model = kenlm.Model(str(arpa))
            result = score(model, arpa, test, rung, treatment, check)
            del model
        counts = re.findall(r"^Zero backoffs encoded: (\d+)$", log, re.M)
        result.update(seconds=round(time.time() - t0, 2), fallback=fallback,
                      zero_backoffs=int(counts[-1]) if counts else 0,
                      discounts=";".join(re.findall(r"^\d+ \d+ D1=.*$", log, re.M)),
                      peak_directory_bytes=max(peak, directory_bytes(root)), **record)
        return result
    finally:
        for p in work.iterdir():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
