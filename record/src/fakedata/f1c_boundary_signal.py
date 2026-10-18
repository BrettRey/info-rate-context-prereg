"""F1c second process: overlapping, different start and continuation marginals.

Types are randomly assigned to two equal-sized (or nearly equal) groups. Starts
put 0.85 of their mass on group 0; fresh continuations put 0.15 there. Both
are uniform within each group and have full support. The original uniform
process is unchanged. Lengths remain iid uniform 1..4; continuations copy their
predecessor with probability 0.7, otherwise draw from the continuation marginal.

At age a=0..3, p_a = c**a*p_start + (1-c**a)*p_fresh. Stationary age mass is
(0.4,0.3,0.2,0.1). For a history, a four-age forward filter gives its mass and
next-boundary probability. Exact entropy sums enumerate group-labelled equality
patterns, weighted by falling factorials within each group. This compresses the
sum over V**k labelled histories without approximation, including k=4.

Marginal I(S;B) and H(B|S) use a separate unigram fit on joint bNsN targets,
paired with rung 0. Context-conditioned rung differences are reported separately.
All fits use the existing outcome-normalized CPU KenLM scorer and disk guards.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from functools import lru_cache
import numpy as np

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f1c_uniform_reference", HERE / "f1c_boundaries.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
R = F.R


def entropy(probabilities):
    p = np.asarray(probabilities)
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)))


class Process:
    def __init__(self, vocab, ranking_seed=1701, start_mass=.85, fresh_mass=.15):
        if vocab < 2 or not 0 < start_mass < 1 or not 0 < fresh_mass < 1:
            raise ValueError("at least two types and strictly interior group masses required")
        self.vocab = vocab
        self.ranking_seed = ranking_seed
        self.start_mass, self.fresh_mass = start_mass, fresh_mass
        permutation = np.random.default_rng(ranking_seed).permutation(vocab)
        self.groups = (permutation[:vocab//2], permutation[vocab//2:])
        self.p_start, self.p_fresh = np.empty(vocab), np.empty(vocab)
        for i, group in enumerate(self.groups):
            self.p_start[group] = (start_mass if i == 0 else 1-start_mass) / len(group)
            self.p_fresh[group] = (fresh_mass if i == 0 else 1-fresh_mass) / len(group)
        powers = (1-F.EPS) ** np.arange(4)
        self.p_age = powers[:, None]*self.p_start + (1-powers[:, None])*self.p_fresh
        self.p_s = F.AGE @ self.p_age
        self.p_cont = (F.AGE[1:] @ self.p_age[1:]) / (1-F.ALPHA)

    def descriptor(self):
        return dict(name="two-group-boundary-signal-v1", vocab=self.vocab,
                    ranking_seed=self.ranking_seed, start_group0_mass=self.start_mass,
                    fresh_continuation_group0_mass=self.fresh_mass,
                    group_sha256=hashlib.sha256(np.concatenate(self.groups).tobytes()).hexdigest(),
                    lengths=F.LENGTHS.tolist(), copy=1-F.EPS, boundary_rate=F.ALPHA,
                    initialization="stationary joint age/syllable", cross_word="independent starts")

    def simulate(self, n, line, seed):
        rng = np.random.default_rng(seed)
        first_length = rng.choice(np.arange(1, 5), p=np.arange(1, 5)*F.LENGTHS/F.SURV.sum())
        age = int(rng.integers(1, first_length+1))-1
        residual = first_length-age
        lengths = rng.choice(np.arange(1, 5), size=n, p=F.LENGTHS)
        boundaries = residual + np.r_[0, np.cumsum(lengths)]
        boundaries = boundaries[boundaries < n]
        b = np.zeros(n, dtype=np.int64)
        b[boundaries] = 1
        b[0] = int(age == 0)
        del lengths, boundaries
        fresh = (rng.random(n) < F.EPS) | (b == 1)
        fresh[0] = True
        values = rng.choice(self.vocab, n, p=self.p_fresh)
        values[b == 1] = rng.choice(self.vocab, int(b.sum()), p=self.p_start)
        values[0] = rng.choice(self.vocab, p=self.p_age[age])
        last = np.maximum.accumulate(np.where(fresh, np.arange(n), 0))
        return R.Corpus(values[last], b, np.arange(0, n, line))

    def history_mass(self, history):
        if not history:
            return F.AGE.copy()
        mass = F.AGE*self.p_age[:, history[0]]
        for prev, target in zip(history[:-1], history[1:]):
            new = np.zeros(4)
            new[0] = np.dot(mass, F.HAZARD)*self.p_start[target]
            q = (1-F.EPS)*(prev == target) + F.EPS*self.p_fresh[target]
            new[1:] = mass[:-1]*(1-F.HAZARD[:-1])*q
            mass = new
        return mass

    def next_joint(self, history):
        if not history:
            return np.array([(1-F.ALPHA)*self.p_cont, F.ALPHA*self.p_start])
        mass = self.history_mass(history)
        pb = float(np.dot(mass, F.HAZARD)/mass.sum())
        cont = F.EPS*self.p_fresh.copy()
        cont[history[-1]] += 1-F.EPS
        return np.array([(1-pb)*cont, pb*self.p_start])

    def compressed_histories(self, k):
        """Canonical labelled partitions; each group's new IDs occur in order."""
        def walk(history, used):
            if len(history) == k:
                multiplicity = math.prod(math.prod(range(len(g)-m+1, len(g)+1))
                                         for g, m in zip(self.groups, used))
                actual = tuple(int(self.groups[g][j]) for g, j in history)
                yield actual, multiplicity
                return
            for g in (0, 1):
                for j in range(used[g]+1):
                    if j >= len(self.groups[g]):
                        continue
                    counts = list(used)
                    counts[g] += int(j == used[g])
                    yield from walk(history+((g, j),), tuple(counts))
        yield from walk((), (0, 0))

    @lru_cache(None)
    def entropies(self, k):
        total = plain = free = joint = 0.
        for history, multiplicity in self.compressed_histories(k):
            weight = multiplicity*(float(self.history_mass(history).sum()) if history else 1.)
            q = self.next_joint(history)
            pb = q.sum(1)
            hj = entropy(q)
            total += weight
            plain += weight*entropy(q.sum(0))
            free += weight*(hj-entropy(pb))
            joint += weight*hj
        if not math.isclose(total, 1., abs_tol=2e-12):
            raise AssertionError(f"exact history mass: {total}")
        return dict(plain=plain, free=free, joint=joint)

    def quantities(self):
        e0, e1 = self.entropies(0), self.entropies(1)
        return dict(h_s=e0['plain'], h_within=e1['free'], h_prev=e1['plain'],
                    h_free=e1['free'], h_charged=e1['joint'],
                    h_s_given_b=e0['free'], h_s_b=e0['joint'],
                    i_s_b=e0['plain']-e0['free'], h_b_given_s=e0['joint']-e0['plain'],
                    i_s_b_given_prev=e1['plain']-e1['free'],
                    h_b_given_s_prev=e1['joint']-e1['plain'])

    def truth(self, rung, treatment, line, n):
        k, _, _ = R.convention(rung)
        if treatment not in ('bounded', 'running'):
            raise ValueError('unknown line treatment')
        if rung == '0':
            return self.entropies(0)['plain']
        kind = 'plain' if rung == '1' else 'joint' if rung.endswith('charged') else 'free'
        values = np.array([self.entropies(c)[kind] for c in range(k+1)])
        pos = np.arange(n) % line if treatment == 'bounded' else np.arange(n)
        return float(values[np.minimum(k, pos)].mean())

    def oracle(self, corpus, rung, treatment):
        k, _, _ = R.convention(rung)
        n = len(corpus.s)
        pos = np.arange(n)
        starts = corpus.starts if treatment == 'bounded' else np.array([0])
        have = np.minimum(k, pos-np.repeat(starts, np.diff(np.r_[starts, n])))
        q = self.p_s[corpus.s].copy()
        if rung == '0':
            return float(-np.log2(q).mean())
        for c in range(k+1):
            ix = pos[have == c]
            if not len(ix):
                continue
            if c == 0:
                pb = np.full(len(ix), F.ALPHA)
                cont = self.p_cont[corpus.s[ix]]
            else:
                mass = F.AGE[None, :]*self.p_age[:, corpus.s[ix-c]].T
                for j in range(1, c):
                    target = corpus.s[ix-c+j]
                    prev = corpus.s[ix-c+j-1]
                    new = np.zeros_like(mass)
                    new[:, 0] = (mass @ F.HAZARD)*self.p_start[target]
                    transition = (1-F.EPS)*(prev == target)+F.EPS*self.p_fresh[target]
                    new[:, 1:] = mass[:, :-1]*(1-F.HAZARD[:-1])*transition[:, None]
                    mass = new
                pb = (mass @ F.HAZARD)/mass.sum(1)
                cont = (1-F.EPS)*(corpus.s[ix-1] == corpus.s[ix])+F.EPS*self.p_fresh[corpus.s[ix]]
            initial = self.p_start[corpus.s[ix]]
            if rung == '1':
                q[ix] = pb*initial+(1-pb)*cont
            else:
                q[ix] = np.where(corpus.b[ix] == 1, initial, cont)
                if rung.endswith('charged'):
                    q[ix] *= np.where(corpus.b[ix] == 1, pb, 1-pb)
        return float(-np.log2(q).mean())


FIELDS = ['code', 'process', 'vocab', 'n_train', 'n_test', 'line', 'seed', 'treatment', 'rung',
          'truth', 'estimate', 'estimate_minus_truth', 'oracle', 'oracle_minus_truth', 'fit_minus_oracle',
          'raw_bits', 'n_scored', 'oov', 'seconds', 'fallback', 'discounts', 'peak_directory_bytes',
          'free_bytes', 'reserve_bytes', 'model_fit']
MARGINAL_FIELDS = ['code', 'process', 'vocab', 'n_train', 'n_test', 'line', 'seed', 'treatment',
                   'h_s_estimate', 'h_s_given_b_estimate', 'h_s_b_estimate',
                   'i_s_b_truth', 'i_s_b_estimate', 'i_s_b_oracle',
                   'h_b_given_s_truth', 'h_b_given_s_estimate', 'h_b_given_s_oracle',
                   'n_scored', 'seconds', 'fallback', 'discounts', 'peak_directory_bytes', 'free_bytes', 'reserve_bytes', 'model_fit']


def code_id():
    files = [Path(__file__), HERE/'f1c_boundaries.py', HERE/'f1c_provenance.py',
             HERE.parent/'stage5/rungs.py', HERE.parent/'stage5/f1c_reservation.json', HERE.parent/'stage5/disk_space.py']
    return hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()


def checkpoint(path, value):
    data = value.encode()
    R.disk_guard(path.parent, len(data)+65536)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    with tmp.open('wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_rows(path, rows, fields):
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter='\t', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    checkpoint(path, buffer.getvalue())


def read_rows(path, fields, config, processes, marginal=False):
    if not path.exists():
        return []
    data = path.read_bytes()
    if not data.endswith(b'\n'):
        raise ValueError('unterminated boundary-signal checkpoint')
    reader = csv.DictReader(io.StringIO(data.decode(), newline=''), delimiter='\t', strict=True)
    if reader.fieldnames != fields:
        raise ValueError('unknown boundary-signal checkpoint schema')
    rows = list(reader)
    seen = set()
    for row in rows:
        if None in row or any(v is None for v in row.values()):
            raise ValueError('incomplete boundary-signal checkpoint')
        if (row['code'] != config['code'] or row['process'] != 'two-group-boundary-signal-v1'
                or any(int(row[name]) != config[name] for name in ('n_train', 'n_test', 'seed'))
                or int(row['vocab']) not in config['vocabs'] or int(row['line']) not in config['lines']
                or row['treatment'] not in config['treatments'] or int(row['n_scored']) != config['n_test']):
            raise ValueError('incompatible/incomplete boundary-signal checkpoint')
        key = (row['vocab'], row['line'], row['treatment']) + (() if marginal else (row['rung'],))
        if key in seen:
            raise ValueError('duplicate boundary-signal checkpoint')
        seen.add(key)
        process = processes[int(row['vocab'])]
        if not marginal:
            if row['rung'] not in R.RUNGS or int(row['oov']) != 0:
                raise ValueError('unknown rung or OOV boundary-signal checkpoint')
            reference = process.truth(row['rung'], row['treatment'], int(row['line']), int(row['n_test']))
            values = {name: float(row[name]) for name in ('truth', 'estimate', 'oracle', 'estimate_minus_truth', 'oracle_minus_truth', 'fit_minus_oracle')}
            pairs = [(values['truth'], reference), (values['estimate_minus_truth'], values['estimate']-reference),
                     (values['oracle_minus_truth'], values['oracle']-reference),
                     (values['fit_minus_oracle'], values['estimate']-values['oracle'])]
        else:
            quantities = process.quantities()
            numeric = [name for name in MARGINAL_FIELDS if name.endswith(('estimate', 'truth', 'oracle'))]
            values = {name: float(row[name]) for name in numeric}
            pairs = [(values['i_s_b_truth'], quantities['i_s_b']),
                     (values['h_b_given_s_truth'], quantities['h_b_given_s']),
                     (values['i_s_b_estimate'], values['h_s_estimate']-values['h_s_given_b_estimate']),
                     (values['h_b_given_s_estimate'], values['h_s_b_estimate']-values['h_s_estimate'])]
        if not all(math.isfinite(value) for value in values.values()) or any(
                not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10) for a, b in pairs):
            raise ValueError('inconsistent boundary-signal checkpoint score')
    return rows


def marginal_fit(train, test, work, root, log_path, reserve):
    """One unigram ARPA fit on joint targets; score conditional and joint losses."""
    root = work
    t0 = time.time()
    text_bound = len(train.s)*(len(str(int(train.s.max())))+5)+65536
    if reserve < text_bound:
        raise RuntimeError('disk guard: marginal reserve does not cover training text')
    record = R.disk_guard(root, reserve)
    work.mkdir(parents=True, exist_ok=True)
    try:
        path = work/'joint.txt'
        with path.open('w') as f:
            for i in range(0, len(train.s), 10000):
                f.write(' '.join(f'b{b}s{s}' for s, b in zip(train.s[i:i+10000], train.b[i:i+10000])))
                f.write('\n')
        arpa = work/'joint.arpa.gz'
        command = [f'{R.KENLM}/lmplz', '-o', '1', '-S', '256M', '-T', str(work)]
        ret, peak = R.guarded_run(command, path, arpa, root, log_path, compressed=True)
        log = Path(log_path).read_text()
        fallback = False
        if ret and ('BadDiscountException' in log or 'Could not calculate Kneser-Ney discounts' in log):
            fallback = True
            R.disk_guard(root, max(100_000_000, reserve-R.directory_bytes(work)))
            retry = str(log_path)+'.retry'
            ret, retry_peak = R.guarded_run(command+['--discount_fallback'], path, arpa, root, retry, compressed=True)
            peak = max(peak, retry_peak)
            log += Path(retry).read_text()
            checkpoint(Path(log_path), log)
            Path(retry).unlink()
        if ret:
            raise RuntimeError(log[-2000:])
        probabilities = {}
        with R.open_arpa(arpa) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and re.fullmatch(r'b[01]s\d+', parts[1]):
                    probabilities[parts[1]] = 10**float(parts[0])
        masses = [math.fsum(p for word, p in probabilities.items() if int(word[1]) == b) for b in (0, 1)]
        joint = conditional = 0.
        for s, b in zip(test.s, test.b):
            word = f'b{b}s{s}'
            if word not in probabilities:
                raise ValueError(f'OOV joint unigram target {word}')
            joint -= math.log2(probabilities[word]/sum(masses))
            conditional -= math.log2(probabilities[word]/masses[b])
        return dict(joint=joint/len(test.s), conditional=conditional/len(test.s),
                    n_scored=len(test.s), seconds=round(time.time()-t0, 2),
                    fallback=fallback, discounts=';'.join(re.findall(r'^\d+ \d+ D1=.*$', log, re.M)),
                    peak_directory_bytes=peak, **record)
    finally:
        shutil.rmtree(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    parser.add_argument('--vocabs', type=int, nargs='+', default=[600, 2000])
    parser.add_argument('--n-train', type=int, default=10_000_000)
    parser.add_argument('--n-test', type=int, default=100_000)
    parser.add_argument('--lines', type=int, nargs='+', default=[40, 1000])
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--ranking-seed', type=int, default=1701)
    parser.add_argument('--start-mass', type=float, default=.85)
    parser.add_argument('--fresh-mass', type=float, default=.15)
    parser.add_argument('--reserve-bytes', type=int, default=2_700_000_000,
                        help='explicit empirical aggregate reserve, inherited uniform calibration; runtime guard remains active')
    args = parser.parse_args()
    root = Path.cwd()
    output = Path(args.output).resolve()
    if not output.is_relative_to(root) or min(args.n_train, args.n_test, args.reserve_bytes, *args.lines) < 1:
        raise ValueError('positive sizes and worktree-local output required')
    processes = {v: Process(v, args.ranking_seed, args.start_mass, args.fresh_mass) for v in args.vocabs}
    environment = dict(python=os.sys.version, numpy=np.__version__,
                       kenlm=importlib.metadata.version('kenlm'),
                       lmplz_sha256=hashlib.sha256(Path(R.KENLM, 'lmplz').read_bytes()).hexdigest(),
                       builder_memory='256M', cpu_only=True, omp_threads=os.environ.get('OMP_NUM_THREADS'))
    config = dict(schema='f1c-boundary-signal-v1', code=code_id(), environment=environment,
                  n_train=args.n_train, n_test=args.n_test, lines=args.lines, vocabs=args.vocabs,
                  seed=args.seed, treatments=['bounded', 'running'], reserve_bytes=args.reserve_bytes,
                  processes={str(v): p.descriptor() for v, p in processes.items()})
    manifest = output/'manifest.json'
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        if saved['config'] != config:
            raise ValueError('refusing boundary-signal resume with changed code/settings/environment')
        if saved['status'] == 'complete':
            for name, sha in saved['artifacts'].items():
                if hashlib.sha256((output/name).read_bytes()).hexdigest() != sha:
                    raise ValueError('corrupt completed boundary-signal artifact')
    elif output.exists() and any(output.iterdir()):
        raise ValueError('unmarked boundary-signal output')
    rows = read_rows(output/'rungs.tsv', FIELDS, config, processes)
    marginals = read_rows(output/'marginals.tsv', MARGINAL_FIELDS, config, processes, marginal=True)
    checkpoint(manifest, json.dumps(dict(config=config, status='running'), indent=2)+'\n')
    truths = dict(derivation=__doc__, processes={str(v): dict(descriptor=p.descriptor(),
                      quantities=p.quantities(), context_entropies={str(k): p.entropies(k) for k in range(5)})
                      for v, p in processes.items()})
    checkpoint(output/'truth.json', json.dumps(truths, indent=2)+'\n')
    logs = output/'logs'
    logs.mkdir(exist_ok=True)
    work = output/'scratch'
    if work.exists():
        shutil.rmtree(work)
    done = {(int(r['vocab']), int(r['line']), r['treatment'], r['rung']) for r in rows}
    marginal_done = {(int(r['vocab']), int(r['line']), r['treatment']) for r in marginals}
    for v, process in processes.items():
        if all((v, line, t, rung) in done for line in args.lines for t in config['treatments'] for rung in R.RUNGS) and all(
                (v, line, t) in marginal_done for line in args.lines for t in config['treatments']):
            continue
        base = args.seed*100000+v*10
        train = process.simulate(args.n_train, args.lines[0], base+1)
        test = process.simulate(args.n_test, args.lines[0], base+2)
        for line in args.lines:
            tr = R.Corpus(train.s, train.b, np.arange(0, len(train.s), line))
            te = R.Corpus(test.s, test.b, np.arange(0, len(test.s), line))
            for treatment in config['treatments']:
                paired = {}
                common = dict(code=config['code'], process='two-group-boundary-signal-v1', vocab=v,
                              n_train=args.n_train, n_test=args.n_test, line=line, seed=args.seed, treatment=treatment)
                for rung in R.RUNGS:
                    if (v, line, treatment, rung) in done:
                        continue
                    shared = next((r for r in rows if int(r['vocab']) == v and r['treatment'] == 'running'
                                   and r['rung'] == rung), None) if treatment == 'running' else None
                    if shared is not None:
                        # Same syllables, flags and single running stream: the
                        # original line cuts affect neither fitting nor scoring.
                        row = dict(shared, **common, seconds=0.)
                        rows.append(row)
                        save_rows(output/'rungs.tsv', rows, FIELDS)
                        done.add((v, line, treatment, rung))
                        print(f'V={v} line={line} running {rung}: reused {row["model_fit"]} (identical stream and score)', flush=True)
                        continue
                    name = f'v{v}_l{line}_{treatment}_{rung}'
                    if rung in paired:
                        result, fit_name = paired[rung]
                        result = dict(result)
                    else:
                        result = R.estimate(tr, te, rung, treatment, work, root, logs/(name+'.log'),
                                            reserve=args.reserve_bytes)
                        fit_name = name
                        if R.convention(rung)[1]:
                            other = rung.replace('free', 'charged') if rung.endswith('free') else rung.replace('charged', 'free')
                            paired[other] = (dict(result, test_bits=result['joint_bits'] if rung.endswith('free') else result['conditional_bits']), name)
                    ref = process.truth(rung, treatment, line, args.n_test)
                    oro = process.oracle(te, rung, treatment)
                    est = result['test_bits']
                    row = dict.fromkeys(FIELDS, '')
                    row.update(common, rung=rung, truth=ref, estimate=est, oracle=oro,
                               estimate_minus_truth=est-ref, oracle_minus_truth=oro-ref, fit_minus_oracle=est-oro,
                               model_fit=fit_name)
                    row.update({k: result[k] for k in FIELDS if k in result})
                    rows.append(row)
                    save_rows(output/'rungs.tsv', rows, FIELDS)
                    done.add((v, line, treatment, rung))
                    print(f'V={v} line={line} {treatment} {rung}: truth={ref:.6f} estimate={est:.6f} bias={est-ref:+.6f} fit-oracle={est-oro:+.6f} {result["seconds"]}s', flush=True)
                if (v, line, treatment) not in marginal_done:
                    shared = next((r for r in marginals if int(r['vocab']) == v and r['treatment'] == treatment), None) if treatment == 'running' else None
                    if shared is not None:
                        row = dict(shared, **common, seconds=0.)
                        marginals.append(row)
                        save_rows(output/'marginals.tsv', marginals, MARGINAL_FIELDS)
                        marginal_done.add((v, line, treatment))
                        print(f'Marginal V={v} line={line} {treatment}: reused identical joint unigram fit', flush=True)
                        continue
                    fitted = marginal_fit(tr, te, work, root, logs/f'v{v}_l{line}_{treatment}_marginal.log', args.reserve_bytes)
                    h0 = float(next(r['estimate'] for r in rows if int(r['vocab']) == v and int(r['line']) == line and r['treatment'] == treatment and r['rung'] == '0'))
                    h0_oracle = process.oracle(te, '0', treatment)
                    joint_q = np.where(te.b == 1, F.ALPHA*process.p_start[te.s], (1-F.ALPHA)*process.p_cont[te.s])
                    conditional_q = joint_q/np.where(te.b == 1, F.ALPHA, 1-F.ALPHA)
                    q = process.quantities()
                    row = dict.fromkeys(MARGINAL_FIELDS, '')
                    row.update(common, model_fit=f'v{v}_l{line}_{treatment}_marginal',
                               h_s_estimate=h0, h_s_given_b_estimate=fitted['conditional'],
                               h_s_b_estimate=fitted['joint'], i_s_b_truth=q['i_s_b'],
                               i_s_b_estimate=h0-fitted['conditional'],
                               i_s_b_oracle=h0_oracle+float(np.log2(conditional_q).mean()),
                               h_b_given_s_truth=q['h_b_given_s'],
                               h_b_given_s_estimate=fitted['joint']-h0,
                               h_b_given_s_oracle=float(-np.log2(joint_q).mean())-h0_oracle)
                    row.update({k: fitted[k] for k in MARGINAL_FIELDS if k in fitted})
                    marginals.append(row)
                    save_rows(output/'marginals.tsv', marginals, MARGINAL_FIELDS)
                    marginal_done.add((v, line, treatment))
                    print(f'Marginal V={v} line={line} {treatment}: I={row["i_s_b_estimate"]:.6f}/{q["i_s_b"]:.6f} H(B|S)={row["h_b_given_s_estimate"]:.6f}/{q["h_b_given_s"]:.6f}', flush=True)
        del train, test, tr, te
    if work.exists():
        work.rmdir()
    artifacts = {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ('rungs.tsv', 'marginals.tsv', 'truth.json')}
    checkpoint(manifest, json.dumps(dict(config=config, status='complete', artifacts=artifacts), indent=2)+'\n')
    print(f'complete: {len(rows)} rung rows, {len(marginals)} marginal rows; all models removed', flush=True)


if __name__ == '__main__':
    main()
