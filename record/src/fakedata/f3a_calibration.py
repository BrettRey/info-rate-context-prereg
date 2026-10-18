"""T7 round 3: paired interval candidates on disjoint selection/validation draws.

Uses shape identifiers only. Every candidate uses the same 2,000 language and
1,000 crossed panel draws; no candidate buys calibration by increasing B.
"""
import os
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
             'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import numpy as np
from scipy.stats import norm, t

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('calibration_design', HERE / 'f3a_design.py')
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)
A, O = D.A, D.O
METHODS = ('current', 'reverse', 'bias_corrected', 'studentized')
PHASES = {'selection': 0, 'validation': 1}
QUANTITIES = ('R_1w', 'R_4', 'R_4-R_1w')


def quantities(r):
    return np.concatenate((r, (r[..., 1] - r[..., 0])[..., None]), axis=-1)


def language_statistics(ids, sr):
    """R and its paired delta-method SE, allowing a leading bootstrap axis.

    Influence for R is R/2 * (centred IR^2 / Var(IR) - centred SR^2 / Var(SR)).
    The paired contrast subtracts influences BEFORE taking their variance.
    """
    x = sr - sr.mean(axis=-1, keepdims=True)
    y = ids + sr[..., None]
    y = y - y.mean(axis=-2, keepdims=True)
    vx = np.mean(x*x, axis=-1)
    vy = np.mean(y*y, axis=-2)
    with np.errstate(divide='ignore', invalid='ignore'):
        r = np.sqrt(vy / vx[..., None])
        influence = r[..., None, :] / 2 * (y*y / vy[..., None, :] -
                                          (x*x / vx[..., None])[..., None])
    influence = quantities(influence)
    se = influence.std(axis=-2, ddof=1) / np.sqrt(sr.shape[-1])
    return quantities(r), se


class CrossedPanel:
    """Count-weight implementation of the existing speaker/text resampling.

    One common text draw; independent speaker draws within languages. Missing
    cells stay absent, speaker means use observed selected texts, and a selected
    speaker with no available text is omitted. Entire invalid draws are rejected
    for ALL quantities together, rather than omitted rung by rung.
    """
    def __init__(self, shape):
        lang, speaker, text = map(np.asarray, shape)
        self.langs = np.unique(lang)
        self.texts = np.unique(text)
        self.layout = []
        for language in self.langs:
            rows = np.flatnonzero(lang == language)
            speakers, si = np.unique(speaker[rows], return_inverse=True)
            ti = np.searchsorted(self.texts, text[rows])
            mask = np.zeros((len(speakers), len(self.texts)))
            mask[si, ti] = 1
            self.layout.append((rows, si, ti, mask))
        self.min_speakers = min(len(layout[3]) for layout in self.layout)
        self.missing_cells = sum(int((layout[3] == 0).sum()) for layout in self.layout)

    def means(self, sr, n_boot=1000, seed=0):
        rng = np.random.default_rng(seed)
        n_texts = len(self.texts)
        text_draw = rng.integers(0, n_texts, (n_boot, n_texts))
        tc = np.zeros((n_boot, n_texts))
        np.add.at(tc, (np.arange(n_boot)[:, None], text_draw), 1)
        means = []
        empty_speakers = 0
        for rows, si, ti, mask in self.layout:
            matrix = np.zeros_like(mask)
            matrix[si, ti] = sr[rows]
            n_speakers = len(mask)
            sdraw = rng.integers(0, n_speakers, (n_boot, n_speakers))
            sc = np.zeros((n_boot, n_speakers))
            np.add.at(sc, (np.arange(n_boot)[:, None], sdraw), 1)
            den = tc @ mask.T
            available = den > 0
            spmean = np.divide(tc @ matrix.T, den, out=np.zeros_like(den), where=available)
            weights = sc * available
            empty_speakers += int(np.sum(sc * ~available))
            total = weights.sum(axis=1)
            means.append(np.divide(np.sum(weights * spmean, axis=1), total,
                                   out=np.full(n_boot, np.nan), where=total > 0))
        return np.column_stack(means), empty_speakers

    def bootstrap(self, sr, ids, n_boot=1000, seed=0):
        means, empty = self.means(sr, n_boot, seed)
        finite = np.isfinite(means).all(axis=1) & (means > 0).all(axis=1)
        invalid = int((~finite).sum())
        if invalid:
            # Pathological sparse panels cannot silently have fewer bootstrap draws.
            raise ValueError(f'{invalid} crossed draws have a language with no readings; '
                             'a missingness model is needed for this shape')
        log_sr = np.log(means)
        r = np.std(ids[None, :, :] + log_sr[:, :, None], axis=1, ddof=1) / log_sr.std(axis=1, ddof=1)[:, None]
        return quantities(r), empty, invalid


def corrected_interval(estimate, samples, level=.9, acceleration=None):
    """BC if acceleration is omitted; BCa with delete-one-language acceleration."""
    alpha = np.array([(1-level)/2, (1+level)/2])
    fraction = ((samples < estimate).sum(axis=0) + .5 * (samples == estimate).sum(axis=0)) / len(samples)
    z0 = norm.ppf(np.clip(fraction, .5/len(samples), 1-.5/len(samples)))
    acc = np.zeros_like(estimate) if acceleration is None else acceleration
    z = z0[None, :] + norm.ppf(alpha)[:, None]
    adjusted = norm.cdf(z0[None, :] + z / (1 - acc[None, :] * z))
    bounds = np.array([[np.quantile(samples[:, k], adjusted[j, k])
                        for k in range(len(estimate))] for j in range(2)])
    return bounds[0], bounds[1]


def language_candidates(ids, sr, n_boot=2000, seed=0, level=.9):
    estimate, se = language_statistics(ids, sr)
    idx = np.random.default_rng(seed).integers(0, len(sr), (n_boot, len(sr)))
    samples, ses = language_statistics(ids[idx], sr[idx])
    finite = np.isfinite(samples).all(axis=1) & np.isfinite(ses).all(axis=1) & (ses > 0).all(axis=1)
    if finite.sum() < .99*n_boot:
        raise ValueError('too many undefined language bootstrap statistics')
    samples, ses = samples[finite], ses[finite]
    jack = np.array([language_statistics(np.delete(ids, j, 0), np.delete(sr, j))[0]
                     for j in range(len(sr))])
    delta = jack.mean(axis=0) - jack
    denom = 6 * np.sum(delta**2, axis=0)**1.5
    acceleration = np.divide(np.sum(delta**3, axis=0), denom,
                             out=np.zeros_like(denom), where=denom > 0)
    tlo, thi = A.interval((samples-estimate)/ses, level)
    return estimate, dict(current=A.interval(samples, level),
                          reverse=A.basic_interval(estimate, samples, level),
                          bias_corrected=corrected_interval(estimate, samples, level, acceleration),
                          studentized=(estimate-thi*se, estimate-tlo*se))


def panel_candidates(estimate, samples, min_speakers, n_texts, level=.9):
    # Approximate cluster-t interval: bias-reflected bootstrap centre; finite
    # cluster correction and t tails using the smaller crossed cluster count.
    clusters = min(min_speakers, n_texts)
    if clusters < 2:
        raise ValueError('need at least two clusters per dimension')
    centre = 2*estimate - samples.mean(axis=0)
    half = t.ppf((1+level)/2, clusters-1) * np.sqrt(clusters/(clusters-1)) * samples.std(axis=0, ddof=1)
    return dict(current=A.basic_interval(estimate, samples, level),
                reverse=A.interval(samples, level),
                bias_corrected=corrected_interval(estimate, samples, level),
                studentized=(centre-half, centre+half))


def evaluate(shape, phase='selection', n_rep=500, n_boot=2000, panel_boot=1000,
             seed=20261010, settings=None, scenarios=None, progress=None):
    """All methods share every replicate, enabling paired coverage MC errors."""
    crossed = CrossedPanel(shape)
    lang, spk, txt = shape
    rows, audit = [], []
    settings = list(D.SETTINGS) if settings is None else settings
    for setting in settings:
        parameters = D.SETTINGS[setting]
        grid = D.scenario_grid(setting)
        if scenarios is not None:
            grid = {name: grid[name] for name in scenarios}
        density = {key: parameters[key] for key in ('sd_language', 'v')}
        reading = {key: parameters[key] for key in ('sd_speaker', 'sd_text', 'sd_language_text', 'sd_reading')}
        fixed_a = np.random.default_rng(20261009).normal(O.MU, parameters['sd_language'], len(crossed.langs))
        for exp in ('fixed', 'redrawn'):
            for scenario, correlations in grid.items():
                # Tags are independent of iteration order/subsetting.
                tag = int.from_bytes(hashlib.sha256(f'{setting}/{exp}/{scenario}'.encode()).digest()[:4], 'little')
                stream = np.random.default_rng(np.random.SeedSequence([seed, 7, 3, PHASES[phase], len(crossed.langs), tag]))
                fixed_id = O.densities(fixed_a, correlations, np.random.default_rng(7), True, **density)[:, [1, 5]]
                estimates, truths = [], {'panel': [], 'language': []}
                bounds = {(interval, method): [] for interval in ('panel', 'language', 'known_sr_language') for method in METHODS}
                known_estimates = []
                empty_total = invalid_total = 0
                sr_errors = []
                for rep in range(n_rep):
                    if exp == 'fixed':
                        a, ids = fixed_a, fixed_id
                    else:
                        a = stream.normal(O.MU, parameters['sd_language'], len(crossed.langs))
                        ids = O.densities(a, correlations, stream, False, **density)[:, [1, 5]]
                    sr = np.exp(O.readings(a, lang, spk, txt, stream, False, **reading))
                    means = A.language_means(lang, spk, sr)[1]
                    # Bootstrap randomness has its own phase namespace as well.
                    boot_seed = np.random.SeedSequence([seed, 7, 3, PHASES[phase], rep, 19])
                    est, lb = language_candidates(ids, np.log(means), n_boot, boot_seed)
                    known_est, kb = language_candidates(ids, a, n_boot, boot_seed)
                    pb, empty, invalid = crossed.bootstrap(sr, ids, panel_boot, boot_seed)
                    pc = panel_candidates(est, pb, crossed.min_speakers, len(crossed.texts))
                    for interval, candidates in (('panel', pc), ('language', lb), ('known_sr_language', kb)):
                        for method, pair in candidates.items():
                            bounds[interval, method].append(pair)
                    estimates.append(est)
                    known_estimates.append(known_est)
                    truths['panel'].append(quantities(A.ladder(ids, a)[0]))
                    truths['language'].append(quantities(D.population_truth(correlations, parameters['v'])[[1, 5]]))
                    empty_total += empty
                    invalid_total += invalid
                    sr_errors.append(np.log(means)-a)
                estimates, known_estimates = np.array(estimates), np.array(known_estimates)
                for interval in ('panel', 'language', 'known_sr_language'):
                    truth = np.array(truths['panel' if interval == 'panel' else 'language'])
                    point = known_estimates if interval == 'known_sr_language' else estimates
                    baseline = np.array(bounds[interval, 'current'])
                    for method in METHODS:
                        bound = np.array(bounds[interval, method])
                        for q, quantity in enumerate(QUANTITIES):
                            covered = (bound[:, 0, q] <= truth[:, q]) & (truth[:, q] <= bound[:, 1, q])
                            base_cov = (baseline[:, 0, q] <= truth[:, q]) & (truth[:, q] <= baseline[:, 1, q])
                            improvement = covered.astype(float)-base_cov
                            ref = 0 if q == 2 else 1
                            rows.append(dict(phase=phase, n_languages=len(crossed.langs), setting=setting,
                                             experiment=exp, scenario=scenario, interval=interval,
                                             candidate=method, quantity=quantity,
                                             target='latent_panel' if interval == 'panel' else 'population',
                                             population_contrast=float(D.population_truth(correlations, parameters['v'])[5]-D.population_truth(correlations, parameters['v'])[1]),
                                             exclusion_interpretation=D.exclusion_label(exp, scenario, 'language' if interval == 'known_sr_language' else interval, quantity),
                                             coverage_gain=float(improvement.mean()),
                                             coverage_gain_mcse=float(improvement.std(ddof=1)/np.sqrt(n_rep)),
                                             **D.metric_summary(point[:, q], truth[:, q], bound[:, 0, q], bound[:, 1, q], reference=ref)))
                noise = estimates-known_estimates
                for q, quantity in enumerate(QUANTITIES):
                    audit.append(dict(phase=phase, n_languages=len(crossed.langs), setting=setting,
                                      experiment=exp, scenario=scenario, quantity=quantity,
                                      sr_sampling_bias=float(noise[:, q].mean()),
                                      sr_sampling_bias_mcse=float(noise[:, q].std(ddof=1)/np.sqrt(n_rep)),
                                      sr_sampling_rmse=float(np.sqrt(np.mean(noise[:, q]**2))),
                                      language_sampling_bias=float((known_estimates[:, q]-np.array(truths['language'])[:, q]).mean()),
                                      missing_cells=crossed.missing_cells,
                                      empty_selected_speakers=empty_total, invalid_panel_draws=invalid_total,
                                      sr_error_sd=float(np.std(np.array(sr_errors), ddof=1)), n_rep=n_rep))
                if progress:
                    progress(setting, exp, scenario)
    return rows, audit


def eligible(row):
    # A fixed panel repeated with new readings is not repeated sampling of
    # languages from the population; its population-interval coverage is diagnostic.
    return row['interval'] == 'panel' or (row['interval'] == 'language' and row['experiment'] == 'redrawn')


def choose(rows):
    """Freeze one candidate per target using selection data only."""
    result = {}
    for interval in ('panel', 'language'):
        scores = {method: float(np.mean([abs(row['coverage']-.9) for row in rows
                  if row['interval'] == interval and row['candidate'] == method and eligible(row)]))
                  for method in METHODS}
        result[interval] = dict(candidate=min(scores, key=scores.get), mean_absolute_coverage_error=scores)
    return result


def validate_choice(selection, rows):
    """Conservative held-out rule, fixed before looking at validation.

    Need lower mean absolute calibration error, positive mean paired gain,
    no cell below .84, and no cell worse by >2 paired MCSE. This is a
    descriptive gate, not proof of nominal calibration or a multiple-test CI.
    """
    result = {}
    for interval, choice in selection.items():
        candidate = choice['candidate']
        selected = [row for row in rows if row['interval'] == interval and
                    row['candidate'] == candidate and eligible(row)]
        baseline = [row for row in rows if row['interval'] == interval and
                    row['candidate'] == 'current' and eligible(row)]
        error = float(np.mean([abs(row['coverage']-.9) for row in selected]))
        base_error = float(np.mean([abs(row['coverage']-.9) for row in baseline]))
        gain = float(np.mean([row['coverage_gain'] for row in selected]))
        worse = sum(row['coverage_gain'] < -2*row['coverage_gain_mcse'] for row in selected)
        poor = sum(row['coverage'] < .84 for row in selected)
        adopt = candidate != 'current' and error < base_error and gain > 0 and worse == poor == 0
        result[interval] = dict(selected_candidate=candidate, adopted_candidate=candidate if adopt else 'current',
                                adopted=adopt, heldout_error=error, baseline_error=base_error,
                                mean_coverage_gain=gain, worse_cells=worse, below_84_cells=poor)
    return result


def write_tsv(path, rows):
    with Path(path).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--phase', choices=list(PHASES), required=True)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--panel-shape', type=Path, default=O.DEFAULT_PANEL)
    parser.add_argument('--drop-languages', nargs='+', default=[])
    parser.add_argument('--n-rep', type=int, default=500)
    parser.add_argument('--n-boot', type=int, default=2000)
    parser.add_argument('--panel-boot', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=20261010)
    parser.add_argument('--settings', nargs='+', choices=list(D.SETTINGS), default=list(D.SETTINGS))
    args = parser.parse_args()
    if min(args.n_rep, args.n_boot, args.panel_boot) < 2 or len(set(args.settings)) != len(args.settings):
        parser.error('invalid counts or repeated settings')
    if args.phase == 'validation' and args.selection is None:
        parser.error('freeze selection before validation')
    code_hash = hashlib.sha256(b''.join(path.read_bytes() for path in
                  (Path(__file__), HERE/'f3a_design.py', HERE/'f3a_oracle.py', HERE.parent/'stage6/analysis.py'))).hexdigest()
    frozen = json.loads(args.selection.read_text()) if args.selection else None
    shape = O.panel(args.panel_shape, args.drop_languages)
    n_languages = len(np.unique(shape[0]))
    shape_hash = hashlib.sha256(args.panel_shape.read_bytes()).hexdigest()
    size_matches = not frozen or frozen['n_languages'] == n_languages or (
        frozen['n_languages'] == 17 and n_languages == 15 and
        sorted(args.drop_languages) == ['JPN', 'THA'] and not frozen['dropped_languages'])
    if frozen and (frozen['phase'] != 'selection' or frozen['seed'] != args.seed or
                   not size_matches or frozen['panel_sha256'] != shape_hash or
                   frozen['code_sha256'] != code_hash or
                   frozen['settings'] != args.settings or frozen['n_boot'] != args.n_boot or
                   frozen['panel_boot'] != args.panel_boot):
        parser.error('selection configuration mismatch')
    started = time.monotonic()
    def progress(setting, exp, scenario):
        print(f'{args.phase} {len(np.unique(shape[0]))} {setting} {exp} {scenario}: '
              f'{args.n_rep} replicates; {time.monotonic()-started:.1f}s', flush=True)
    rows, audit = evaluate(shape, args.phase, args.n_rep, args.n_boot, args.panel_boot,
                           args.seed, args.settings, progress=progress)
    metadata = dict(phase=args.phase, seed=args.seed, seed_namespace=[args.seed, 7, 3, PHASES[args.phase]],
                    n_languages=len(np.unique(shape[0])), n_readings=len(shape[0]), settings=args.settings,
                    n_rep=args.n_rep, n_boot=args.n_boot, panel_boot=args.panel_boot,
                    panel_sha256=shape_hash, level=.90,
                    dropped_languages=args.drop_languages, code_sha256=code_hash, cpu_threads=1,
                    selection=choose(rows) if frozen is None else frozen['selection'],
                    validation_rule='mean error improves; mean paired gain positive; no cell <.84; no cell worse >2 paired MCSE',
                    numpy_version=np.__version__, scipy_version=__import__('scipy').__version__,
                    python_version=__import__('sys').version.split()[0],
                    model_settings={name: D.SETTINGS[name] for name in args.settings},
                    seconds=time.monotonic()-started)
    if frozen:
        metadata['decision'] = validate_choice(frozen['selection'], rows)
        metadata['selection_sha256'] = hashlib.sha256(args.selection.read_bytes()).hexdigest()
        metadata['selection_language_count'] = frozen['n_languages']
    run_id = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()[:16]
    metadata['run_id'] = run_id
    for row in rows+audit:
        row.update(run_id=run_id, code_sha256=code_hash, seed=args.seed, cpu_threads=1)
    write_tsv(args.out, rows)
    write_tsv(args.out.with_name(args.out.stem+'_audit.tsv'), audit)
    args.out.with_suffix('.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(metadata.get('decision', metadata['selection']), indent=2), flush=True)
    print(f'done {args.out}: rows={len(rows)} seconds={metadata["seconds"]:.1f}', flush=True)

if __name__ == '__main__':
    main()
