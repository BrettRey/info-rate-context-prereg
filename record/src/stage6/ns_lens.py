"""NS calibration lens and matched-count reading command, offline and explicit.

Run with the pinned Python (-I -B): ns_lens.py READINGS.tsv TEXTS.tsv
--output DIRECTORY [--universes MANIFEST.json] [--densities DENSITIES.json].
The manifest is a list of {name, languages: {Language: configuration_id}, R:
{rung: value}}; shared settings/estimator metadata may be included. R is optional
until corpus scores exist. Densities map configuration_id to {rung: id_bits}.
Without a manifest, counts, language diagnostics and assembly rates are still
written; no cross-language universe is invented or selected.
Supply corpus densities for one shared setting and estimator per call; the same
configuration can have different densities across those runs. Universe curves
may carry different language panels: each score averages its own languages.

Counting read texts requires the existing anchored freeze or BOTH input files
inside tests/. This is a guard against mistakes, not deliberate forgery.
Library functions accept already supplied simulated inputs. Secondary analysis
uses the fixed digit/letter readings TSV (--digit-readings overrides its path),
or explicitly supplied per-language callables via the API.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage6_ns_lens_iterables", _BoundaryPath(__file__).resolve().parents[1] / "stage5/iterables.py")
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import argparse
import html
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np

_spec = importlib.util.spec_from_file_location('p4_reading_adapter', Path(__file__).with_name('reading_adapter.py'))
B = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = B
_spec.loader.exec_module(B)
TIE_RULE = 'Exact score ties use the first candidate in the supplied declared order; no tolerance.'


@_boundary
def option_summary(rows, excluded=frozenset()):
    remaining = [r for r in rows if (r['Language'], r['Text']) not in excluded]
    if not remaining or any(r['status'] != 'complete' for r in remaining):
        return {'status': 'unavailable', 'texts': len(remaining), 'median_abs_log_u': None}
    values = np.array([float(r['u']) for r in remaining])
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError('u must be positive and finite')
    return dict(status='complete', texts=len(values), median_u=float(np.median(values)),
                median_abs_log_u=float(np.median(np.abs(np.log(values)))),
                range=[float(values.min()), float(values.max())])


@_boundary
def closest(scores):
    """Do not rank a reduced candidate set when a candidate is unavailable."""
    if not scores or any(value is None for _, value in scores):
        return None
    return min(scores, key=lambda item: item[1])[0]


@_boundary
def evaluate(readings, counts, universes=(), *, selected_texts, configs, leaveout_mode='joint-text', densities=None):
    """All options/configurations share a language's selected text denominator.

    configs declares every expected candidate, including candidates with no records.
    Leave-one-text-out selection is diagnostic only; no universe is excluded by
    calibration. FIN-C may be counted separately, but explicit manifests must
    use production configurations and cannot select calibration-only options.
    """
    selected_texts = set(selected_texts)
    if leaveout_mode not in {'joint-text', 'language-text'}:
        raise ValueError('Unknown leaveout mode')
    B.validate_selected_counts(readings, counts, selected_texts, configs)
    if any(not math.isfinite(float(v)) or float(v) <= 0
           for ids in (densities or {}).values() for v in ids.values()):
        raise ValueError('Information density must be positive and finite')
    ns = {(r['Language'], r['Text']): float(r['NS']) for r in readings}
    # Preserve the prospective order, including exact-score tie precedence.
    configs = {B.configuration_id({k: c[k] for k in ('language', 'option', 'counter_options', 'settings')}):
               {k: c[k] for k in ('language', 'option', 'counter_options', 'settings')} for c in configs}
    groups, seen = {}, set()
    enriched = []
    for count in counts:
        c = dict(count)
        key = (c['Language'], c['Text'])
        cid = c['configuration_id']
        if key not in ns or (*key, cid) in seen:
            raise ValueError('Missing NS or duplicate count')
        seen.add((*key, cid))
        cfg = c['configuration']
        if cfg['language'] != c['Language'] or B.configuration_id(cfg) != cid:
            raise ValueError('Count configuration mismatch')
        if cid in configs and configs[cid] != cfg:
            raise ValueError('Conflicting count configuration')
        configs[cid] = cfg
        c['NS'] = ns[key]
        c['u'] = None
        if c['status'] == 'complete':
            if not isinstance(c['P'], int) or isinstance(c['P'], bool) or c['P'] <= 0:
                raise ValueError('P must be a positive integer')
            c['u'] = c['P']/c['NS']
        c['cancellation'] = {k: dict(ID=float(v), u_times_ID=c['u']*float(v) if c['u'] else None)
                             for k, v in (densities or {}).get(cid, {}).items()}
        enriched.append(c)
        groups.setdefault(cid, []).append(c)
    by_language = {}
    for cid, config in configs.items():
        by_language.setdefault(config['language'], []).append(cid)
    summaries = {cid: option_summary(rows) for cid, rows in groups.items()}
    language_results = {}
    for language, candidates in by_language.items():
        text_sets = [{r['Text'] for r in groups[cid]} for cid in candidates]
        if any(s != text_sets[0] for s in text_sets):
            raise ValueError('Options must cover identical selected texts')
        # FIN-C is a calibration diagnostic, not a possible production winner.
        production = [cid for cid in candidates if not B.M.REGISTRY[language][configs[cid]['option']]['calibration_only']]
        winner = closest([(cid, summaries[cid]['median_abs_log_u']) for cid in production])
        leaveouts = []
        for text in sorted(text_sets[0]):
            scores = {cid: option_summary(groups[cid], {(language, text)})['median_abs_log_u'] for cid in candidates}
            chosen = closest([(cid, scores[cid]) for cid in production])
            leaveouts.append(dict(Text=text, median_abs_log_u=scores, closest_configuration=chosen,
                closest_option=configs[chosen]['option'] if chosen else None,
                configuration_changed=(chosen != winner) if chosen and winner else None,
                option_changed=(configs[chosen]['option'] != configs[winner]['option']) if chosen and winner else None))
        language_results[language] = dict(closest_configuration=winner,
            closest_option=configs[winner]['option'] if winner else None, leave_one_text_out=leaveouts)
    universe_rows, names = [], set()
    for u in universes:
        if not isinstance(u.get('name'), str) or not u['name'] or u['name'] in names or not u.get('languages'):
            raise ValueError('Universes require unique names and language selections')
        names.add(u['name'])
        for language, cid in u['languages'].items():
            if cid not in configs or configs[cid]['language'] != language:
                raise ValueError('Universe references unavailable language configuration')
            if B.M.REGISTRY[language][configs[cid]['option']]['calibration_only']:
                raise ValueError('Calibration-only option cannot enter a universe')
        scores = [summaries[cid]['median_abs_log_u'] for cid in u['languages'].values()]
        score = math.fsum(scores)/len(scores) if all(s is not None for s in scores) else None
        curve = {k: float(v) for k, v in u.get('R', {}).items()}
        if any(not math.isfinite(float(v)) for v in curve.values()):
            raise ValueError('Universe R must be finite')
        universe_rows.append(dict(u, R=curve, calibration_score=score, status='complete' if score is not None else 'unavailable'))
    winner = closest([(u['name'], u['calibration_score']) for u in universe_rows])
    # For an unrestricted crossing, the separable language-mean objective is
    # minimized by each language's closest production configuration. Expose
    # that named target even before the corpus-side universe manifest exists.
    # When a manifest is supplied, its declared candidates determine the name.
    target = None
    if universe_rows and winner is not None:
        chosen = next(u for u in universe_rows if u['name'] == winner)
        target = dict(languages=chosen['languages'], calibration_score=chosen['calibration_score'],
                      scope='supplied-universe-manifest')
    elif not universe_rows and language_results and all(v['closest_configuration'] for v in language_results.values()):
        languages = {l: v['closest_configuration'] for l, v in language_results.items()}
        target = dict(languages=languages, calibration_score=math.fsum(
            summaries[cid]['median_abs_log_u'] for cid in languages.values())/len(languages),
            scope='unrestricted-crossing-of-supplied-production-configurations')
    panel = {language for u in universe_rows for language in u['languages']}
    keys = sorted({(r['Language'], r['Text']) for r in enriched if r['Language'] in panel})
    omitted = ([dict(Text=text, keys=[key for key in keys if key[1] == text]) for text in sorted({t for _, t in keys})]
               if leaveout_mode == 'joint-text' else [dict(Language=l, Text=t, keys=[(l, t)]) for l, t in keys])
    stability = []
    for omit in omitted:
        scores = []
        for u in universe_rows:
            values = [option_summary(groups[cid], set(omit['keys']))['median_abs_log_u'] for cid in u['languages'].values()]
            score = math.fsum(values)/len(values) if all(v is not None for v in values) else None
            scores.append((u['name'], score))
        chosen = closest(scores)
        stability.append({k: v for k, v in omit.items() if k != 'keys'} | dict(
            calibration_scores=dict(scores), closest_universe=chosen,
            changed=(chosen != winner) if chosen and winner else None))
    return dict(schema='ns-lens-v1', log='natural', tie_rule=TIE_RULE, leaveout_mode=leaveout_mode,
        per_text=enriched, per_configuration=summaries, per_language=language_results,
        universes=universe_rows, closest_universe=winner, ns_closest=target, leave_one_text_out=stability,
        unavailable_leaveouts=sum(r['closest_universe'] is None for r in stability),
        interpretation='NS matching is a diagnostic lens; all universes are retained without a cutoff.')


@_boundary
def calibration_svg(report):
    """Simple white-background panels; every available universe at every rung.

    Unlike the assembly rank display, no point is subsampled. Unavailable
    counts or absent R values are listed explicitly alongside the plot.
    """
    universes = report['universes']
    rungs = list(dict.fromkeys(k for u in universes for k in u.get('R', {})))
    parts, ybase = [], 70
    palette = ('#1b9e77', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02', '#a6761d')
    for rung in rungs:
        rows = [u for u in universes if u['calibration_score'] is not None and rung in u.get('R', {})]
        parts.append(f'<text x="10" y="{ybase}" font-size="12">R{html.escape(str(rung))}; {len(rows)}/{len(universes)} universes with coordinates</text>')
        ybase += 20
        parts.append(f'<path d="M 280 {ybase} V {ybase+130} H 1070" fill="none" stroke="#222"/>')
        if rows:
            xs = [u['calibration_score'] for u in rows]
            ys = [float(u['R'][rung]) for u in rows]
            xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
            for i, u in enumerate(rows):
                x = 290 + 770*(u['calibration_score']-xmin)/(xmax-xmin or 1)
                y = ybase + 120 - 110*(float(u['R'][rung])-ymin)/(ymax-ymin or 1)
                tip = html.escape(f"{u['name']}; calibration={u['calibration_score']:.8g}; R{rung}={u['R'][rung]:.8g}")
                parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{palette[i%len(palette)]}"><title>{tip}</title></circle>')
            parts.append(f'<text x="10" y="{ybase+70}" font-size="12">R: {ymin:.4g} to {ymax:.4g}</text>')
            parts.append(f'<text x="280" y="{ybase+150}" font-size="12">Calibration score: {xmin:.4g} to {xmax:.4g}</text>')
        ybase += 180
    unavailable = [u['name'] for u in universes if u['calibration_score'] is None or set(u.get('R', {})) != set(rungs)]
    message = ('No corpus R supplied; scatter coordinates unavailable.' if not rungs else
               'Incomplete coordinates: ' + ', '.join(unavailable) if unavailable else 'All universes shown; no cutoff or point subsampling.')
    parts.append(f'<text x="10" y="{ybase}" font-size="12">{html.escape(message)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{ybase+30}">'
        '<rect width="100%" height="100%" fill="white"/>'
        '<text x="10" y="20" font-size="13">NS calibration against R; a diagnostic lens, without a cutoff.</text>'
        + ''.join(parts) + '</svg>\n')


@_boundary
def run_files(readings_path, texts_path, output, *, configs=None, universes=(), densities=None,
              subset='primary', expanders=None, leaveout_mode='joint-text', freeze_archive=None,
              freeze_proof=None, block_headers=None, backends=None, digit_readings=None):
    # Apply the existing hold before reading, transcribing, counting or writing.
    authorizations = [B.E.entropy_authorization(path, freeze_archive, freeze_proof, block_headers)
                      for path in (readings_path, texts_path)]
    if backends and any(a.get('kind') == 'freeze-archive' for a in authorizations):
        raise ValueError("Read texts in a real run are counted by the registry's production G2P routes only")
    output = Path(output)
    if any(Path(p).resolve().is_relative_to(output.resolve()) for p in (readings_path, texts_path)):
        raise ValueError('Inputs must be outside the output directory')
    if digit_readings is not None and (subset != 'secondary' or expanders is not None):
        raise ValueError('Digit readings require secondary analysis without custom expanders')
    supplied_texts = B.table(texts_path, B.TEXT_FIELDS)
    readings, texts = B.validate_tables(B.table(readings_path, B.READING_FIELDS), supplied_texts)
    if subset == 'secondary' and expanders is None:
        digit_readings = digit_readings if digit_readings is not None else B.DIGIT_READINGS
        expanders = B.load_digit_expanders(digit_readings, supplied_texts)
    selected, excluded = B.subset_texts(texts, subset, expanders)
    if {t['Language'] for t in selected} != {r['Language'] for r in readings}:
        raise ValueError('A language has no texts in the selected subset')
    configs = B.configurations({r['Language'] for r in readings}) if configs is None else configs
    if {c['language'] for c in configs} != {r['Language'] for r in readings}:
        raise ValueError('Configurations must cover every reading language')
    if len({B.configuration_id({k: c[k] for k in ('language','option','counter_options','settings')}) for c in configs}) != len(configs):
        raise ValueError('Duplicate configurations')
    counts = B.count_texts(selected, configs, output / 'g2p-cache', backends=backends)
    selected_keys = {(t['Language'],t['Text']) for t in selected}
    report = evaluate(readings, counts, universes, selected_texts=selected_keys, configs=configs, leaveout_mode=leaveout_mode, densities=densities)
    rates = B.matched_rates(readings, counts, densities, selected_texts=selected_keys, configs=configs)
    report.update(subset=subset, excluded_texts=excluded, authorization=authorizations,
        selection_inputs=dict(writer='ns_lens.run_files', configs=configs,
            selected_texts=sorted(selected_keys), universes=universes),
        input_sha256={name: B.P.digest(Path(path).read_bytes()) for name, path in
                      (('readings', readings_path), ('texts', texts_path))})
    if digit_readings is not None:
        # Use the hash of the exact snapshot expanded, rather than rereading it.
        report['input_sha256']['digit_readings'] = next(iter(expanders.values())).provenance['table_sha256']
    for authorization in authorizations:
        B.E.F.unchanged_since(authorization)
    for name, value in (('counts.json', counts), ('lens.json', report), ('matched-rates.json', rates)):
        B.P.atomic(output / name, (B.P.canonical(value)+'\n').encode())
    B.P.atomic(output / 'calibration.svg', calibration_svg(report).encode())
    return report, rates


@_boundary
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('readings', type=Path)
    parser.add_argument('texts', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--universes', type=Path)
    parser.add_argument('--densities', type=Path)
    parser.add_argument('--subset', choices=('primary', 'secondary'), default='primary')
    parser.add_argument('--digit-readings', type=Path,
                        help='Fixed token readings TSV for the secondary subset')
    parser.add_argument('--leaveout-mode', choices=('joint-text', 'language-text'), default='joint-text')
    parser.add_argument('--freeze-archive', type=Path)
    parser.add_argument('--freeze-proof', type=Path)
    parser.add_argument('--block-headers', type=Path)
    args = parser.parse_args()
    try:
        universes = json.loads(args.universes.read_text()) if args.universes else ()
        densities = json.loads(args.densities.read_text()) if args.densities else None
        report, rates = run_files(args.readings, args.texts, args.output, universes=universes, densities=densities,
            subset=args.subset, leaveout_mode=args.leaveout_mode, freeze_archive=args.freeze_archive,
            freeze_proof=args.freeze_proof, block_headers=args.block_headers, digit_readings=args.digit_readings)
    except B.E.EntropyGuardError:
        print('NS hold: supply the anchored freeze archive, proof and recorded block headers, or both inputs inside tests/.', file=sys.stderr)
        return 1
    except (ValueError, TypeError, KeyError, RuntimeError, LookupError, OSError, ImportError):
        print('Reading analysis failed; check table schemas, declared configurations, expansion rules and local resources.', file=sys.stderr)
        return 1
    failed = sum(c['status'] != 'complete' for c in report['per_text'])
    print(f"Text/configuration counts: {len(report['per_text'])}; failed: {failed}; rate configurations: {len(rates)}; closest universe: {report['closest_universe']}")
    return 2 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
