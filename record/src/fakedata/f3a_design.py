"""F3a design analysis using oracle densities and a shape-only reading panel.

The three archived scenarios run first, in their original order and RNG stream.
Intermediate scenarios have a separate stream, preserving the archived 17-language
simulation. Panel intervals are basic; language intervals are percentile, as in
Stage 6. Their targets are respectively the latent panel and the population.
"""
import os

# Set before importing numpy; this CLI is deliberately CPU-only and one-threaded.
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("f3a_oracle_design", HERE / "f3a_oracle.py")
O = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(O)
A = O.A

SCENARIOS = dict(O.SCEN)
SCENARIOS.update({f"D{abs(round(10 * r))}": [-0.8, -0.8] + [r] * 4
                  for r in (-0.6, -0.4, -0.2)})
TARGETS = {"panel": "latent_panel", "language": "population"}
NULL_TOL = 1e-12
SETTINGS = {
    "assumed": dict(sd_language=O.SD_A, sd_speaker=O.SD_SPK, sd_text=O.SD_TXT,
                    sd_language_text=O.SD_LT, sd_reading=O.SD_E, v=O.V, r_baseline=-0.8),
    "data": dict(sd_language=0.148, sd_speaker=0.093, sd_text=0.018,
                 sd_language_text=0.032, sd_reading=0.034, v=0.98, r_baseline=-0.83),
}
for _name, _scale in (("data_x0.5", 0.5), ("data_x2", 2.0)):
    SETTINGS[_name] = dict(SETTINGS["data"])
    for _component in ("sd_speaker", "sd_text", "sd_language_text", "sd_reading"):
        SETTINGS[_name][_component] *= _scale


def scenario_grid(setting="assumed"):
    """Round-1 correlations plus three contrasts derived by inverting R(r).

    The requested 0.05/0.10/0.15 are design inputs. Truth is subsequently
    computed from correlations (and, for the panel target, the latent panel).
    """
    parameters = SETTINGS[setting]
    v, baseline = parameters["v"], parameters["r_baseline"]
    scenarios = {name: [baseline if r == -0.8 else r for r in correlations]
                 for name, correlations in SCENARIOS.items()}
    r_start = float(population_truth([baseline], v)[0])
    for change in (0.05, 0.10, 0.15):
        correlation = ((r_start + change) ** 2 - 1 - v ** 2) / (2 * v)
        if not -1 <= correlation <= 1:
            raise ValueError("contrast requires an invalid correlation")
        scenarios[f"C{round(100 * change):02d}"] = [baseline, baseline] + [correlation] * 4
    return scenarios


def population_truth(correlations, v=O.V):
    """Computed from the SD/correlation identity, never a hard-coded contrast."""
    return np.sqrt(1 + v ** 2 + 2 * v * np.asarray(correlations))


def metric_summary(estimate, truth, lo, hi, null_tol=NULL_TOL, reference=0.0):
    """Summarise intervals and conditional sign/magnitude errors, with denominators.

    An effect of zero relative to reference has no sign or exaggeration. Strict
    exclusion of reference defines significance. Exaggeration is the absolute
    estimated/true effect ratio; signed_ratio reports its signed counterpart.
    Both condition on significance
    and a nonzero effect. Empty conditional subsets are represented by blank TSV
    cells, not zero. Monte Carlo SEs describe the simulation, not data uncertainty.
    """
    estimate, truth, lo, hi = np.broadcast_arrays(
        *[np.asarray(x, dtype=float) for x in (estimate, truth, lo, hi)])
    if estimate.ndim != 1 or len(estimate) < 2:
        raise ValueError("need at least two one-dimensional replicates")
    if not all(np.isfinite(x).all() for x in (estimate, truth, lo, hi)):
        raise ValueError("nonfinite simulation or interval")
    if np.any(lo > hi) or not np.isfinite(null_tol) or null_tol < 0:
        raise ValueError("invalid interval or null tolerance")
    n = len(estimate)
    error = estimate - truth
    covered = (lo <= truth) & (truth <= hi)
    if not np.isfinite(reference):
        raise ValueError("nonfinite reference")
    significant = (lo > reference) | (hi < reference)
    effect, true_effect = estimate - reference, truth - reference
    nonzero = np.abs(true_effect) > null_tol
    usable = significant & nonzero
    n_sig, n_usable = int(significant.sum()), int(usable.sum())

    def mean_se(values):
        return float(np.std(values, ddof=1) / np.sqrt(len(values))) if len(values) > 1 else ""

    coverage, power = float(covered.mean()), float(significant.mean())
    rmse = float(np.sqrt(np.mean(error ** 2)))
    result = dict(truth=float(truth.mean()), truth_sd=float(truth.std(ddof=1)),
                  mean_est=float(estimate.mean()), bias=float(error.mean()),
                  bias_mcse=mean_se(error), rmse=rmse,
                  rmse_mcse=mean_se(error ** 2) / (2 * rmse) if rmse else 0.0,
                  width=float(np.mean(hi - lo)), width_mcse=mean_se(hi - lo),
                  coverage=coverage, coverage_mcse=float(np.sqrt(coverage * (1 - coverage) / n)),
                  reference=float(reference), exclusion_frequency=power,
                  exclusion_frequency_mcse=float(np.sqrt(power * (1 - power) / n)),
                  power=power, power_mcse=float(np.sqrt(power * (1 - power) / n)),
                  sign_error="", sign_error_mcse="", n_nonzero=int(nonzero.sum()),
                  n_significant=n_sig, n_nonzero_significant=n_usable,
                  type_s="", type_s_mcse="", exaggeration="", exaggeration_mcse="",
                  signed_ratio="", signed_ratio_mcse="", n_rep=n)
    if nonzero.any():
        wrong_all = np.sign(effect[nonzero]) != np.sign(true_effect[nonzero])
        sign_error = float(wrong_all.mean())
        result.update(sign_error=sign_error,
                      sign_error_mcse=float(np.sqrt(sign_error * (1 - sign_error) / nonzero.sum())))
    if n_usable:
        wrong = np.sign(effect[usable]) != np.sign(true_effect[usable])
        ratios = effect[usable] / true_effect[usable]
        type_s = float(wrong.mean())
        result.update(type_s=type_s,
                      type_s_mcse=float(np.sqrt(type_s * (1 - type_s) / n_usable)),
                      exaggeration=float(np.abs(ratios).mean()),
                      exaggeration_mcse=mean_se(np.abs(ratios)),
                      signed_ratio=float(ratios.mean()), signed_ratio_mcse=mean_se(ratios))
    return result


def simulations(shape, n_rep=500, n_boot=2000, panel_boot=1000,
                seed=20261009, level=0.90, zero_noise=False, scenarios=None,
                model_settings="assumed"):
    """Yield complete replicate arrays per scenario/experiment, keeping old draws.

    The legacy RNG consumes only S0/S1/S2, fixed then redrawn. Round-1 added
    scenarios consume SeedSequence([seed, 7]); round-2 additions use
    SeedSequence([seed, 7, 2]). All rungs share each bootstrap resample.
    """
    parameters = SETTINGS[model_settings]
    density_options = {key: parameters[key] for key in ("sd_language", "v")}
    reading_options = {key: parameters[key] for key in
                       ("sd_speaker", "sd_text", "sd_language_text", "sd_reading")}
    scenarios = (SCENARIOS if model_settings == "assumed" else scenario_grid(model_settings)) if scenarios is None else scenarios
    lang, spk, txt = shape
    langs = np.unique(lang)
    rng = np.random.default_rng(seed)
    a_fixed = rng.normal(O.MU, parameters["sd_language"], len(langs))
    added_rng = np.random.default_rng(np.random.SeedSequence([seed, 7]))
    small_rng = np.random.default_rng(np.random.SeedSequence([seed, 7, 2]))
    original = [name for name in O.SCEN if name in scenarios]
    added = [name for name in scenarios if name in SCENARIOS and name not in O.SCEN]
    small = [name for name in scenarios if name not in SCENARIOS]
    cases = [(exp, name, rng) for exp in ("fixed", "redrawn") for name in original]
    cases += [(exp, name, added_rng) for exp in ("fixed", "redrawn") for name in added]
    cases += [(exp, name, small_rng) for exp in ("fixed", "redrawn") for name in small]
    for experiment, scenario, stream in cases:
        r = scenarios[scenario]
        fixed_id = O.densities(a_fixed, r, np.random.default_rng(7), exact=True, **density_options)
        values = {key: [] for key in ("estimate", "latent_panel", "population",
                                      "language_lo", "language_hi", "panel_lo", "panel_hi",
                                      "language_pair_lo", "language_pair_hi",
                                      "panel_pair_lo", "panel_pair_hi")}
        for rep in range(n_rep):
            if experiment == "fixed":
                a, log_id = a_fixed, fixed_id
            else:
                a = stream.normal(O.MU, parameters["sd_language"], len(langs))
                log_id = O.densities(a, r, stream, exact=False, **density_options)
            sr = np.exp(O.readings(a, lang, spk, txt, stream, zero_noise, **reading_options))
            _, means = A.language_means(lang, spk, sr)
            estimate = A.ladder(log_id, np.log(means))[0]
            lb = A.bootstrap(log_id, np.log(means), n_boot=n_boot, seed=rep)
            pb = A.panel_bootstrap(lang, spk, txt, sr, log_id, langs, n_boot=panel_boot, seed=rep)
            llo, lhi = A.interval(lb, level)
            plo, phi = A.basic_interval(estimate, pb, level)
            ldlo, ldhi = A.interval(lb - lb[:, [1]], level)
            pdlo, pdhi = A.basic_interval(estimate - estimate[1], pb - pb[:, [1]], level)
            for key, value in zip(values, (estimate, A.ladder(log_id, a)[0], population_truth(r, parameters["v"]),
                                          llo, lhi, plo, phi, ldlo, ldhi, pdlo, pdhi)):
                values[key].append(value)
        yield experiment, scenario, {key: np.asarray(value) for key, value in values.items()}


def analyse(shape, null_tol=NULL_TOL, progress=None, **settings):
    """One row per experiment/scenario/quantity/interval, with target-specific truth."""
    rows = []
    model_settings = settings.get("model_settings", "assumed")
    scenarios = settings.get("scenarios")
    if scenarios is None:
        scenarios = SCENARIOS if model_settings == "assumed" else scenario_grid(model_settings)
    for exp, scenario, arrays in simulations(shape, **settings):
        for interval, target in TARGETS.items():
            truth = arrays[target]
            for quantity, k in (("R_1w", 1), ("R_4", 5), ("R_4-R_1w", None)):
                if k is None:
                    est = arrays["estimate"][:, 5] - arrays["estimate"][:, 1]
                    tr = truth[:, 5] - truth[:, 1]
                    lo, hi = (arrays[f"{interval}_pair_{end}"][:, 5] for end in ("lo", "hi"))
                else:
                    est, tr = arrays["estimate"][:, k], truth[:, k]
                    lo, hi = (arrays[f"{interval}_{end}"][:, k] for end in ("lo", "hi"))
                rows.append(dict(experiment=exp, scenario=scenario, quantity=quantity,
                                 interval=interval, target=target,
                                 r_1w=scenarios[scenario][1], r_4=scenarios[scenario][5],
                                 exclusion_interpretation=exclusion_label(exp, scenario, interval, quantity),
                                 **metric_summary(est, tr, lo, hi, null_tol,
                                                  reference=0 if k is None else 1)))
        if progress:
            progress(exp, scenario)
    return rows


def exclusion_label(experiment, scenario, interval, quantity):
    if quantity != "R_4-R_1w":
        return "exclusion frequency relative to R=1"
    if experiment == "redrawn" and interval == "panel":
        return "exclusion frequency for realised panel contrasts"
    if scenario in ("S0", "S1"):
        return "false exclusion frequency under zero population change"
    return "power for declared contrast"


def diagnostic_table(rows):
    """Every scenario/quantity is shown separately, with its actual reference."""
    lines = ["| Setting | Experiment | Scenario | Interval | Quantity | Reference | Truth | Bias | RMSE | Width | Coverage ± MCSE | Exclusion ± MCSE | Sign error | Type S | Exaggeration |",
             "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(value):
        return "—" if value == "" else f"{float(value):.3f}"
    for row in rows:
        values = [row.get('setting', 'assumed'), row['experiment'], row['scenario'],
                  row['interval'], row['quantity']]
        values += [fmt(row[key]) for key in ('reference', 'truth', 'bias', 'rmse', 'width')]
        values += [f"{row[key]:.3f} ± {row[key + '_mcse']:.3f}" for key in
                   ('coverage', 'exclusion_frequency')]
        values += [fmt(row[key]) for key in ('sign_error', 'type_s', 'exaggeration')]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def diagnostic_notes():
    return ["", "Individual R uses reference 1; paired R₄ − R₁w uses reference 0. "
            "Sign error is unconditional on interval exclusion, among replicates with a nonzero "
            "effect relative to the reference. Type S and exaggeration condition on exclusion "
            "and a nonzero effect; exaggeration is |(estimate−reference)/(truth−reference)|. "
            "Blank values are undefined, not zero. power remains a compatibility alias for "
            "exclusion_frequency in the TSV.", "",
            "Redrawn S0/S1 panel exclusions are exclusion frequencies for realised panel contrasts, "
            "not power under no change: their realised targets vary and need not be zero. "
            "Population S0/S1 contrast exclusions are false exclusions under zero population "
            "change. Fixed-panel experiments do not repeatedly sample languages, so their "
            "population-interval coverage is a conditional diagnostic.", "",
            "Oracle ID stays fixed in the panel bootstrap. No corpus-document uncertainty "
            "is included. All reading values and ID values are simulated; the resource holds "
            "identifiers only. Nominal coverage is 0.90. MCSE describes simulation uncertainty."]


def write_summary(path, rows, metadata):
    lines = [f"# F3a design analysis: {metadata['n_languages']} languages", "",
             f"{metadata['n_rep']} replicates per scenario/experiment; "
             f"{metadata['n_readings']} readings. {metadata['level']:.0%} intervals. "
             f"{metadata['n_boot']} language and {metadata['panel_boot']} panel draws; one CPU thread.", "",
             "Panel: basic crossed speaker/text interval for latent panel R. "
             "Language: percentile language interval for population R.", ""]
    lines += diagnostic_table(rows) + diagnostic_notes()
    lines += ["", "## Reproduction metadata", "", "```json",
              json.dumps(metadata, indent=2, sort_keys=True), "```", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def detection_thresholds(rows, minimum_power=0.8):
    """Smallest positive *grid* contrast detected, for each experiment/target.

    Use the design's population contrast to order scenarios, including for
    redrawn panel targets whose realised contrasts vary between replicates.
    Null designs are excluded; no interpolation or monotonicity is assumed.
    """
    groups = sorted({(row["setting"], row["experiment"], row["interval"]) for row in rows})
    result = []
    for setting, experiment, interval in groups:
        eligible = [row for row in rows if
                    (row["setting"], row["experiment"], row["interval"], row["quantity"]) ==
                    (setting, experiment, interval, "R_4-R_1w") and
                    row["population_contrast"] > NULL_TOL and row["power"] >= minimum_power]
        best = min(eligible, key=lambda row: row["population_contrast"]) if eligible else None
        result.append(dict(setting=setting, experiment=experiment, interval=interval,
                           target=TARGETS[interval], scenario=best["scenario"] if best else "",
                           population_contrast=best["population_contrast"] if best else "",
                           truth=best["truth"] if best else "", power=best["power"] if best else ""))
    return result


def write_settings_summary(path, rows, metadata):
    lines = [f"# F3a settings design: {metadata['n_languages']} languages", "",
             f"{metadata['n_rep']} replicates per setting/scenario/experiment; "
             f"{metadata['n_readings']} readings. {metadata['level']:.0%} intervals; "
             f"{metadata['n_boot']} language and {metadata['panel_boot']} panel draws. One CPU thread.", "",
             "Panel: basic crossed speaker/text interval for latent panel R. "
             "Language: percentile language interval for population R.", "",
             "## Smallest grid contrast with power ≥ 0.8", "",
             "| Setting | Experiment | Interval | Scenario | Design contrast | Exclusion frequency |",
             "|---|---|---|---|---:|---:|"]
    for row in detection_thresholds(rows):
        number = lambda value: "—" if value == "" else f"{float(value):.3f}"
        lines.append("| " + " | ".join([row['setting'], row['experiment'], row['interval'],
                     row['scenario'] or 'none', number(row['population_contrast']), number(row['power'])]) + " |")
    lines += ["", "The threshold is the smallest positive design contrast tested; no interpolation. "
              "For redrawn panel targets this is an exclusion-frequency threshold for realised "
              "contrasts. The 0.8 comparison uses point estimates.", "", "## Scenario diagnostics", ""]
    lines += diagnostic_table(rows) + diagnostic_notes()
    lines += ["", "## Reproduction metadata", "", "```json",
              json.dumps(metadata, indent=2, sort_keys=True), "```", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--panel-shape", default=O.DEFAULT_PANEL, type=Path)
    parser.add_argument("--drop-languages", nargs="+", default=[])
    parser.add_argument("--n-rep", type=int, default=500)
    parser.add_argument("--n-boot", type=int, default=2000)
    parser.add_argument("--panel-boot", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--level", type=float, default=0.90)
    parser.add_argument("--null-tol", type=float, default=NULL_TOL)
    parser.add_argument("--zero-noise", action="store_true")
    parser.add_argument("--settings", nargs="+", choices=list(SETTINGS), default=None,
                        help="select settings and include C05/C10/C15; omit to reproduce round 1")
    args = parser.parse_args()
    if min(args.n_rep, args.n_boot, args.panel_boot) < 2:
        parser.error("replicate and bootstrap counts must be at least two")
    if not 0 < args.level < 1 or not np.isfinite(args.null_tol) or args.null_tol < 0:
        parser.error("level must be in (0,1); null tolerance must be finite and nonnegative")
    if args.settings and len(set(args.settings)) != len(args.settings):
        parser.error("settings must not be repeated")
    shape = O.panel(args.panel_shape, args.drop_languages)
    source_hash = hashlib.sha256()
    for path in (Path(__file__), HERE / "f3a_oracle.py", HERE.parent / "stage6" / "analysis.py"):
        source_hash.update(path.name.encode() + b"\0" + path.read_bytes())
    metadata = dict(n_languages=len(np.unique(shape[0])), n_readings=len(shape[0]),
                    panel_shape=str(args.panel_shape.resolve().relative_to(HERE.parents[1])),
                    panel_sha256=hashlib.sha256(args.panel_shape.read_bytes()).hexdigest(),
                    filtered_shape_sha256=hashlib.sha256("\n".join("\t".join(row) for row in zip(*shape)).encode()).hexdigest(),
                    dropped_languages=sorted(args.drop_languages), n_rep=args.n_rep, n_boot=args.n_boot,
                    panel_boot=args.panel_boot, seed=args.seed, level=args.level, null_tol=args.null_tol,
                    zero_noise=args.zero_noise, cpu_threads=1, v=O.V, rung_variation=O.RUNG_VAR,
                    mu=O.MU, sd_language=O.SD_A, sd_speaker=O.SD_SPK, sd_text=O.SD_TXT,
                    sd_language_text=O.SD_LT, sd_reading=O.SD_E, mean_log_id=O.M_K.tolist(),
                    scenarios=SCENARIOS, added_seed_namespace=7, code_sha256=source_hash.hexdigest(),
                    numpy_version=np.__version__, python_version=__import__('sys').version.split()[0])
    selected_settings = args.settings or ["assumed"]
    if args.settings:
        metadata.update(settings={name: SETTINGS[name] for name in selected_settings},
                        scenarios={name: scenario_grid(name) for name in selected_settings},
                        small_contrast_seed_namespace=[7, 2])
        # Per-setting metadata supersedes the round-1 scalar parameters.
        for key in ('v', 'sd_language', 'sd_speaker', 'sd_text', 'sd_language_text', 'sd_reading'):
            metadata.pop(key)
    started = time.monotonic()
    rows = []
    for setting in selected_settings:
        def progress(exp, scenario):
            print(f"complete {setting} {exp} {scenario}: {args.n_rep} replicates; {time.monotonic()-started:.1f}s", flush=True)
        parameters = SETTINGS[setting]
        scenarios = scenario_grid(setting) if args.settings else SCENARIOS
        setting_rows = analyse(shape, n_rep=args.n_rep, n_boot=args.n_boot, panel_boot=args.panel_boot,
                               seed=args.seed, level=args.level, null_tol=args.null_tol,
                               zero_noise=args.zero_noise, progress=progress,
                               model_settings=setting, scenarios=scenarios)
        for row in setting_rows:
            population = population_truth(scenarios[row['scenario']], parameters['v'])
            row.update(setting=setting, **parameters,
                       population_contrast=float(population[5] - population[1]))
        rows.extend(setting_rows)
    run_id = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()[:16]
    for row in rows:
        row.update(run_id=run_id, n_languages=metadata['n_languages'], n_readings=metadata['n_readings'],
                   level=args.level, n_boot=args.n_boot, panel_boot=args.panel_boot, seed=args.seed,
                   null_tol=args.null_tol, zero_noise=args.zero_noise, cpu_threads=1,
                   dropped_languages=",".join(sorted(args.drop_languages)),
                   code_sha256=metadata['code_sha256'], panel_sha256=metadata['panel_sha256'],
                   filtered_shape_sha256=metadata['filtered_shape_sha256'])
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    metadata['run_id'] = run_id
    metadata['seconds'] = time.monotonic() - started
    if args.settings:
        write_settings_summary(args.out.with_suffix(".md"), rows, metadata)
    else:
        write_summary(args.out.with_suffix(".md"), rows, metadata)
    print(f"done {args.out}: rows={len(rows)} elapsed={metadata['seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()
