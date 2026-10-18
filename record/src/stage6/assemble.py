"""Assemble cross-language universes from cached scores without fitting any models.

Enumeration/drawing and shares are descriptive summary devices, not probabilities or
evidence strength. Each shared setting and estimator is reported separately. Option
families receive equal weight per fork; options divide their family's weight equally.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage6_assemble_iterables", _BoundaryPath(__file__).resolve().parents[1] / "stage5/iterables.py")
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import argparse, csv, hashlib, html, importlib.util, io, itertools, json, math, re
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
@_boundary
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m

A = load("assemble_analysis", HERE / "analysis.py")
RUNNER = load("assemble_runner", HERE.parent / "stage5/runner.py")
NAMED = load('assemble_named_builder', HERE / 'named_universes.py')
RUNGS = RUNNER.RUNGS
REGISTRY = load("assemble_registry", HERE.parent / "stage3/multiverse.py").REGISTRY
DISCLAIMER = "Universes are a summary device, not probabilities, total uncertainty, or evidence strength."

CONTRASTS = (("R_4_minus_R_1w", "4", "1w"),
             ("R_1_minus_R_1w", "1", "1w"), ("R_4_minus_R_1", "4", "1"))

@_boundary
def declared_family_map():
    """§4 families for every registered convention and applicable local fork.

    Calibration-only entries are excluded, as in registry enumeration.
    Reserved source/label categories never create additional universe options.
    """
    result = {}
    for language, entries in REGISTRY.items():
        source = 'A' if 'A' in entries else next(iter(entries))
        conventions = {option: ("source" if option == source else "variants")
                       for option, entry in entries.items() if not entry['calibration_only']}
        forks = {"convention": conventions,
                 "source": {v: v for v in ("dictionary", "tool")},
                 "labels": {v: v for v in ("marked", "unmarked")},
                 "stress": {v: v for v in ("marked", "unmarked")}}
        for entry in entries.values():
            for fork in entry['forks']:
                forks.setdefault(fork['setting'], {}).update({v: v for v in fork['values']})
        result[language] = forks
    return result

FAMILY_MAP = declared_family_map()

@_boundary
def record_families(record):
    """Registry families in production; explicit families for synthetic fixtures.

    Old fake records use invented languages/options (e.g. FIN-B2) to test
    weighting algebra. Only those synthetic records may supply their families.
    """
    j = job_metadata(record); language = j['language']; options = j['options']
    synthetic = (record['identity'].get('simulated') is True or
                 record.get('simulated_family_fixture') is True or
                 language.startswith('fake-'))
    # Preserve the deliberately arbitrary family fixtures on synthetic jobs.
    if synthetic:
        return j.get('families', {}), 'synthetic-declarations'
    if language not in FAMILY_MAP:
        raise ValueError(f'no registered families for language {language}')
    families = {}
    convention = options.get('convention')
    if convention not in REGISTRY[language]:
        raise ValueError(f'no registered convention {language}:{convention}')
    applicable = {f['setting']: f['values'] for f in REGISTRY[language][convention]['forks']}
    if set(options) != {'convention', *applicable}:
        raise ValueError(f'options must declare exactly the registry forks for {language}:{convention}')
    for fork, option in options.items():
        if fork not in FAMILY_MAP[language] or option not in FAMILY_MAP[language][fork]:
            raise ValueError(f'no registered family for {language}.{fork}:{option}')
        if fork != 'convention' and option not in applicable.get(fork, ()):
            raise ValueError(f'inapplicable family fork {language}.{fork}:{option}')
        families[fork] = FAMILY_MAP[language][fork][option]
    return families, 'registry'

@_boundary(arrays=('values',))
def contrasts(values, rungs):
    return {name: values[..., rungs.index(a)] - values[..., rungs.index(b)]
            for name, a, b in CONTRASTS}

@_boundary
def clean(value):
    """Encode undefined correlations as null, keeping JSON finite and portable."""
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value

class Records(list):
    """Carry missing-input diagnostics through assembly to its output status."""
    @_boundary
    def __init__(self, rows=(), issues=()):
        super().__init__(rows)
        self.issues = list(issues)

@_boundary
def job_metadata(record):
    return record.get("metadata", record["identity"])

@_boundary
def assembly_estimator(record):
    """Group common fit settings while retaining language inventories in score IDs."""
    settings = dict(record["identity"].get("estimator", {"name": "kenlm"}))
    if settings.get("name") == "neural":
        settings.pop("vocab", None)
    return settings

@_boundary
def cached_records(cache, allow_incomplete=False):
    """Require the active manifest and use its current metadata beside immutable scores."""
    cache = RUNNER.local(cache); manifest = cache.parent / "manifest.json"
    issues = []
    if not manifest.exists():
        if not allow_incomplete:
            raise ValueError("missing active manifest; resume the runner before assembly")
        issues.append("missing active manifest; cached metadata snapshots may be stale and expected languages/options cannot be verified")
        declared = None; active = None
    else:
        declared = json.loads(manifest.read_text())
        active = set(declared["job_ids"])
    scores = {}
    for p in sorted(cache.glob("*.json")):
        if active is not None and p.stem not in active:
            continue
        r = json.loads(p.read_text())
        if r.get("job_id") != RUNNER.digest(r["identity"]) or p.stem != r["job_id"]:
            raise ValueError(f"invalid cache identity: {p}")
        if r.get("scores_hash") != RUNNER.digest(r["scores"]):
            raise ValueError(f"invalid cache scores: {p}")
        RUNNER.validate_scores(r["scores"], r["identity"].get("estimator", {}))
        scores[r["job_id"]] = r
    if active is not None and set(scores) != active:
        missing = sorted(active - set(scores))
        if not allow_incomplete:
            raise ValueError(f"active manifest is incomplete; missing language cache(s): {missing}")
        issues.append(f"missing active language cache(s): {missing}")
    if declared is not None and declared.get("schema") == "manifest-v2":
        entries = declared.get("jobs")
        if not isinstance(entries, list) or {e["job_id"] for e in entries} != active:
            raise ValueError("active manifest jobs do not match its job_ids")
        rows = [dict(scores[e["job_id"]], metadata=e["metadata"]) for e in entries if e["job_id"] in scores]
    else:
        rows = list(scores.values())
    # The runner strips simulated=True from immutable score identities. Its
    # active manifest has entropy_authorization only for real jobs; retain an
    # explicit fixture marker for invented languages in simulated-only runs.
    if declared is not None and 'entropy_authorization' not in declared:
        rows = [dict(r, simulated_family_fixture=True) if job_metadata(r)['language'] not in REGISTRY else r
                for r in rows]
    if declared is not None:
        # Stamp where each row came from; assemble() checks real rows again.
        stamp = 'production_run' if 'entropy_authorization' in declared else 'simulated_run'
        rows = [dict(r, **{stamp: True}) for r in rows]
        production_records(rows)
    return Records(rows, issues)

def _absorb_inapplicable(grouped):
    """Records lacking only settings that don't apply to their language join the fuller groups.

    In the main run only YUE is Wikipedia text, so only its jobs carry gap and
    stub labels; a subtitle language's estimate is the same in every gap and
    stub universe. A group whose shared mapping is a restriction of another's,
    differing only in settings inapplicable to every record in it, is merged
    into each such fuller group and then dropped.
    """
    keys = {key: json.loads(key) for key in grouped}
    result = {key: list(rows) for key, rows in grouped.items()}
    absorbed, targets = set(), set()
    for small, (small_shared, small_estimator) in keys.items():
        for large, (large_shared, large_estimator) in keys.items():
            if small == large or large_estimator != small_estimator:
                continue
            extra = set(large_shared) - set(small_shared)
            if (not extra or any(large_shared.get(k) != v for k, v in small_shared.items())):
                continue
            run = lambda r: job_metadata(r)['shared'].get('run', SHARED.FIRST_LISTED['run'])
            if all(fork in SHARED.TEXT_FORKS and fork != 'run' and run(r) in SHARED.FORKS['run']
                   and not SHARED.applicable(fork, job_metadata(r)['language'], run(r))
                   for r in grouped[small] for fork in extra):
                result[large].extend(grouped[small])
                absorbed.add(small); targets.add(large)
    # One step only: with the current fork table no group is both absorbed and
    # absorbing; if forks' applicability ever diverges, stop rather than guess.
    if absorbed & targets:
        raise ValueError('nested absorption of inapplicable settings; check the fork applicability table')
    return {key: rows for key, rows in result.items() if key not in absorbed}

@_boundary
def production_records(records):
    """Real scores must be production-ready and share one frozen mask per language.

    A record counts as real if a production run stamped it, or if nothing marks it
    as simulated and its language is in the registry. Simulated runs, invented
    family fixtures and fake languages are exempt.
    """
    masks = {}
    for r in records:
        language = job_metadata(r)['language']
        simulated = (r.get('simulated_run') is True or r.get('simulated_family_fixture') is True
                     or r['identity'].get('simulated') is True or language.startswith('fake-'))
        if not (r.get('production_run') is True or (not simulated and language in REGISTRY)):
            continue
        tokenisation = r['identity'].get('tokenisation', {})
        mask = tokenisation.get('mask_sha256')
        if (tokenisation.get('production_ready') is not True or not isinstance(mask, str)
                or not re.fullmatch(r'[0-9a-f]{64}', mask)):
            raise ValueError(f'real scores need production-ready tokenisation under a frozen removal mask: {language}')
        masks.setdefault(SHARED.mask_key(language, job_metadata(r).get('shared')), set()).add(mask)
    mixed = sorted(str(key) for key, found in masks.items() if len(found) > 1)
    if mixed:
        raise ValueError(f'one frozen removal mask per language, text settings and inclusion set required: {mixed}')

@_boundary
def local_weights(records):
    """Convention family mass, then equal applicable fork shares within convention."""
    forks = sorted({f for r in records for f in job_metadata(r)['options']})
    declarations = {}; options = {}; undeclared = []
    for fork in forks:
        declarations[fork] = {}
        for r in records:
            j = job_metadata(r)
            if fork not in j['options']:
                continue
            option = j["options"][fork]
            declared, _ = record_families(r)
            family = declared.get(fork, option)
            if fork not in declared:
                undeclared.append(f"{j['language']}.{fork}:{option}")
            if option in declarations[fork] and declarations[fork][option] != family:
                raise ValueError(f"conflicting families for {fork}:{option}")
            declarations[fork][option] = family
        counts = {}
        for family in declarations[fork].values():
            counts[family] = counts.get(family, 0) + 1
        options[fork] = {o: 1 / len(counts) / counts[f] for o, f in declarations[fork].items()}
    q = np.zeros(len(records))
    conventions = sorted({job_metadata(r)['options'].get('convention') for r in records})
    for convention in conventions:
        indices = [i for i,r in enumerate(records) if job_metadata(r)['options'].get('convention') == convention]
        conditional = {f: {job_metadata(records[i])['options'][f] for i in indices
                          if f in job_metadata(records[i])['options']}
                       for f in forks if f != 'convention'}
        mass = options['convention'][convention] if convention is not None else 1.
        for i in indices:
            opts = job_metadata(records[i])['options']
            q[i] = math.prod(1/len(values) for f,values in conditional.items() if f in opts)
        # Retain the convention's full mass even if approved exclusions remove cells.
        q[indices] *= mass/q[indices].sum()
    q /= q.sum()
    return q, declarations, sorted(set(undeclared))

@_boundary(arrays=('x', 'weights'))
def distribution(x, weights, rungs=RUNGS):
    """Weighted empirical summaries; quantiles use the inverse empirical CDF."""
    result = {}
    for k, rung in enumerate(rungs):
        keep = np.isfinite(x[:, k]); a = x[keep, k]; w = weights[keep]
        if not len(a):
            result[rung] = {"defined_share": 0.0}; continue
        w = w / w.sum(); order = np.argsort(a, kind="stable")
        c = np.cumsum(w[order]); c[-1] = 1
        quant = a[order][np.searchsorted(c, [0.05, 0.5, 0.95])]
        mean = float(w @ a)
        result[rung] = dict(mean=mean, sd=float(np.sqrt(w @ (a - mean) ** 2)),
                            min=float(a.min()), q05=float(quant[0]), median=float(quant[1]),
                            q95=float(quant[2]), max=float(a.max()), defined_share=float(weights[keep].sum()))
    return result

@_boundary
def fork_labels(group):
    """Yield a single fork's universe labels at a time to avoid a large label matrix."""
    if "pooled_labels" in group:
        for fork, labels in sorted(group["pooled_labels"].items()):
            yield fork, labels, {o: o for o in set(labels)}
        return
    n = len(group["choices"])
    for fork, option in sorted(group["shared"].items()):
        yield f"shared.{fork}", np.full(n, option), {option: option}
    for l, language in enumerate(group["languages"]):
        records = group["records"][l]
        for fork in sorted({f for r in records for f in job_metadata(r)['options']}):
            options = np.array([job_metadata(r)['options'].get(fork, 'not applicable') for r in records])
            families = dict(group['families'][language][fork])
            families['not applicable'] = None
            yield f"{language}.{fork}", options[group["choices"][:, l]], families

# Brett, 2026-10-17 (DECISIONS.md, from F2): the matched-count rate is read mainly at the longest rungs, and
# forks whose options delete material are alternative definitions of the quantity, not uncertainty around one
# value. The list is a first pass from the candidate-conventions note, pending Brett's confirmation
# (notes/decision-brief-2026-10-17-f2-followups.md, question 4).
HEADLINE_RUNGS = ('3', '4')
DEFINITIONAL_FORKS = {
    'CAT.convention': 'CAT-B drops vowels in sandhi (el, es and que after or before a vowel; a word-final unstressed vowel before a vowel)',
    'FRA.convention': 'FRA-B drops elidable schwas',
    'TUR.convention': 'TUR-B deletes intervocalic ğ (except between front vowels), fusing identical vowels',
}
TIE_POLICY = "Numerical tolerance only: abs(R4 - R1w) <= 1e-9 * max(1, abs(R1w)); not a substantive equivalence threshold."
# The shared forks come from the registry (src/stage3/shared_settings.py).
SHARED = load('assemble_shared_settings', HERE.parent / 'stage3/shared_settings.py')
SHARED_FORKS = tuple(SHARED.FORKS)

@_boundary(arrays=('R', 'weights'))
def direction_shares(R, weights, sampled=False, rungs=RUNGS):
    """Partition endpoint changes with a scale-aware tolerance for roundoff only."""
    delta = R[:, rungs.index("4")] - R[:, rungs.index("1w")]
    tolerance = 1e-9 * np.maximum(1, np.abs(R[:, rungs.index("1w")]))
    result = {"share_R_4_above_R_1w": float(weights @ (delta > tolerance)),
              "share_R_4_below_R_1w": float(weights @ (delta < -tolerance)),
              "share_R_4_tied_R_1w": float(weights @ (np.abs(delta) <= tolerance))}
    if sampled:
        # These three shares use the same self-normalised importance weights.
        ess = float(weights.sum() ** 2 / (weights @ weights))
        result["importance_weight_ess_by_share"] = {k: ess for k in result}
    return result

@_boundary(arrays=('weights', 'R'))
def rate_summaries(group, weights, R, sampled=False, *, comparison=False):
    """Compute conditional shares and overlapping marginal variance ratios for one rate."""
    valid = np.isfinite(R).all(axis=1)
    availability = dict(usable_universes=int(valid.sum()), unavailable_universes=int((~valid).sum()),
                        available_weight_share=float(weights[valid].sum()))
    if not valid.all() and not comparison:
        return dict(status='unavailable', reason='non-finite canonical R; weights were not renormalised', **availability)
    if not valid.any():
        return dict(status='unavailable', **availability)
    if not valid.all():
        group = dict(group, choices=group['choices'][valid])
        if 'pooled_labels' in group:
            group['pooled_labels'] = {f: labels[valid] for f, labels in group['pooled_labels'].items()}
        R = R[valid]
        weights = weights[valid] / weights[valid].sum()
    rungs = group.get("rungs", RUNGS)
    anchor = rungs.index("1w")
    result = {**availability, "R": distribution(R, weights, rungs),
              "R_minus_1": distribution(R - 1, weights, rungs),
              "contrasts": {name: distribution(x[:, None], weights, (name,))[name]
                            for name, x in contrasts(R, rungs).items()},
              "R_minus_R_1w": distribution(R - R[:, anchor, None], weights, rungs),
              **direction_shares(R, weights, sampled, rungs), "by_fork": {}, "marginal_variation": {}}
    roundoff = (1e-12 * max(1, float(np.max(np.abs(R))))) ** 2
    for fork, labels, families in fork_labels(group):
        applicable = labels != 'not applicable'
        applicable_count = int(applicable.sum())
        if not applicable_count:
            result['by_fork'][fork] = {}
            result['marginal_variation'][fork] = dict(status='not-applicable',applicable_count=0,
                by_rung={r:None for r in rungs},interaction_with_rung=None)
            continue
        fork_weights = weights[applicable]/weights[applicable].sum()
        fork_mean = fork_weights @ R[applicable]
        fork_variance = fork_weights @ (R[applicable]-fork_mean)**2
        fork_interaction = R[applicable]-fork_mean-R[applicable].mean(1)[:,None]+fork_mean.mean()
        fork_interaction_var = float(fork_weights @ np.mean(fork_interaction**2,axis=1))
        shares = {}; between = np.zeros(len(rungs)); between_interaction = 0.0
        for option in sorted(set(labels[applicable])):
            sel = labels == option; raw_mass = float(weights[sel].sum()); sub = weights[sel] / raw_mass
            mass = raw_mass/float(weights[applicable].sum())
            conditional_mean = sub @ R[sel]
            shares[option] = {"count": int(sel.sum()), "weight_share": mass, "family": families[option],
                              "applicable_count": applicable_count,
                              "applicable_weight_share": float(weights[applicable].sum()),
                              **direction_shares(R[sel], sub, sampled, rungs),
                              "R_mean": dict(zip(rungs, conditional_mean.tolist()))}
            if fork in DEFINITIONAL_FORKS:  # the spread within each definition, beside the spread across them
                shares[option]["R_distribution"] = distribution(R[sel], sub, rungs)
            if sampled:
                shares[option]["importance_weight_ess_by_share"]["weight_share"] = float(1 / (fork_weights @ fork_weights))
            between += mass * (conditional_mean - fork_mean) ** 2
            between_interaction += mass * float(np.mean((sub @ fork_interaction[labels[applicable]==option]) ** 2))
        with np.errstate(invalid="ignore", divide="ignore"):
            explained = np.where(fork_variance > roundoff, between / fork_variance, np.nan)
        result["by_fork"][fork] = shares
        if fork in DEFINITIONAL_FORKS:
            result.setdefault("definitional_forks", []).append(fork)
        result["marginal_variation"][fork] = {"by_rung": dict(zip(rungs, explained.tolist())),
                                             "applicable_count": applicable_count,
                                             "interaction_with_rung": between_interaction / fork_interaction_var
                                             if fork_interaction_var > roundoff else None}
    return clean(result)

@_boundary(arrays=('weights',))
def summaries(group, weights, sampled=False):
    result = rate_summaries(group, weights, group["R"], sampled)
    result.update(v=distribution(group["v"], weights, group.get("rungs", RUNGS)), r=distribution(group["r"], weights, group.get("rungs", RUNGS)))
    if group["matched_R"] is not None:
        result["matched_count"] = rate_summaries(group, weights, group["matched_R"], sampled, comparison=True)
    if group.get('paper_subset_R') is not None:
        result['paper_subset'] = rate_summaries(group, weights, group['paper_subset_R'], sampled, comparison=True)
    return clean(result)

@_boundary
def assemble(records, seed=0, enumerate_limit=1_000_000, draws=100_000,
             allow_incomplete=False, named_universes=None):
    """Enumerate each shared setting up to the limit; otherwise draw uniform tuples with replacement."""
    records = Records(records, getattr(records, 'issues', ()))
    if enumerate_limit < 1 or draws < 1:
        raise ValueError("need records and positive enumeration/draw sizes")
    issues = list(getattr(records, "issues", []))
    if not records:
        if not allow_incomplete:
            raise ValueError("need records and positive enumeration/draw sizes")
        return Records(issues=issues + ["no available language caches; no universes can be computed"])
    named_universes = _boundary_module.freeze(NAMED.consume(named_universes or {}))
    grouped = {}
    for r in records:
        RUNNER.validate_scores(r["scores"], r["identity"].get("estimator", {}))
        j = job_metadata(r)
        if not isinstance(j.get("language"), str) or not j["language"]:
            raise ValueError("assembly metadata needs a language")
        for key in ("shared", "options", "families"):
            values = j.get(key, {}) if key == "families" else j.get(key)
            if not isinstance(values, dict) or any(not isinstance(v, str) or not v for v in values.values()):
                raise ValueError(f"assembly {key} declarations must be nonempty string labels")
        if not isinstance(j.get("rates"), dict) or "mean_sr" not in j["rates"]:
            raise ValueError("missing canonical mean SR")
        for rate in ("mean_sr", "matched_sr", "paper_subset_sr"):
            if rate in j["rates"]:
                value = j["rates"][rate]
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError("rates must be positive and finite")
        for rate, label in (('matched_sr', 'matched'), ('paper_subset_sr', 'paper subset')):
            if rate not in j['rates']:
                issues.append(f"missing {label} rate: {j['language']} {j.get('options')}")
        if set(record_families(r)[0]) != set(j["options"]):
            issues.append(f"missing family declaration: {j['language']} {j['options']}")
        settings = assembly_estimator(r)
        key = RUNNER.canonical([j["shared"], settings])
        grouped.setdefault(key, []).append(r)
    grouped = _absorb_inapplicable(grouped)
    if issues and not allow_incomplete:
        raise ValueError("required assembly input missing: " + "; ".join(sorted(set(issues))))
    production_records(records)
    unknown = set(named_universes) - {json.loads(k)[1].get("name", "kenlm") for k in grouped}
    if unknown:
        message = f"named universes declare unavailable estimator(s): {sorted(unknown)}"
        if not allow_incomplete:
            raise ValueError(message)
        issues.append(message + "; declared universes omitted")
    available = [json.loads(key) for key in grouped]
    for estimator, declarations in named_universes.items():
        if not isinstance(declarations, tuple):
            raise ValueError("named universes must be a list per estimator")
        for declaration in declarations:
            if declaration.get('status') == 'pending':
                continue
            if "shared" in declaration and not any(
                    shared == declaration["shared"] and settings.get("name", "kenlm") == estimator
                    for shared, settings in available):
                message = (f"named universe {declaration['name']} lacks declared shared setting "
                           f"{RUNNER.canonical(declaration['shared'])}; omitted")
                if not allow_incomplete:
                    raise ValueError(message)
                issues.append(message)
    groups = Records(issues=issues)
    for key, rows in sorted(grouped.items()):
        shared, estimator = json.loads(key)
        declarations = named_universes.get(estimator.get("name", "kenlm"))
        if len({RUNNER.canonical(r["identity"].get("code")) for r in rows}) > 1:
            raise ValueError("cannot mix code/backend versions within a shared setting")
        languages = sorted({job_metadata(r)["language"] for r in rows})
        if len(languages) < 2:
            if allow_incomplete:
                groups.issues.append(f"fewer than two available language caches in setting {key}; omitted")
                continue
            raise ValueError("a universe requires at least two languages")
        own = []; q = []; families = {}; undeclared = []; incomplete = []
        for language in languages:
            rr = sorted((r for r in rows if job_metadata(r)["language"] == language),
                        key=lambda r: RUNNER.canonical(job_metadata(r)["options"]))
            labels = [RUNNER.canonical(job_metadata(r)["options"]) for r in rr]
            if len(set(labels)) != len(labels):
                raise ValueError(f"duplicate estimate/options for {language}; choose one code version")
            if any(job_metadata(r)["documents"] != job_metadata(rr[0])["documents"] for r in rr):
                raise ValueError("language options use different source-document splits")
            if any(job_metadata(r).get("source_hashes") != job_metadata(rr[0]).get("source_hashes") for r in rr):
                raise ValueError("language options use different source documents")
            for convention in {job_metadata(r)['options'].get('convention') for r in rr}:
                local = [job_metadata(r)['options'] for r in rr if job_metadata(r)['options'].get('convention')==convention]
                forks = {f for opts in local for f in opts}
                if any(set(opts) != forks for opts in local) or math.prod(len({opts[f] for opts in local}) for f in forks) != len(local):
                    incomplete.append(language)
                    break
            weight, ff, missing = local_weights(rr)
            own.append(rr); q.append(weight); families[language] = ff; undeclared.extend(missing)
        sizes = [len(rr) for rr in own]; total = math.prod(sizes)
        shared, estimator = json.loads(key)
        declarations = named_universes.get(estimator.get("name", "kenlm"))
        if estimator.get("name") == "neural" and declarations is None:
            raise ValueError("neural estimates require declared named universes")
        names = None
        group_issues = list(issues)
        if declarations is not None:
            choices, names = named_choices(declarations, shared, languages, own, allow_incomplete, group_issues)
            groups.issues.extend(issue for issue in group_issues if issue not in groups.issues)
            if not len(choices):
                continue
            mode = "declared-named-universes"
        elif total <= enumerate_limit:
            choices = np.array(list(itertools.product(*(range(n) for n in sizes))), dtype=np.int64)
            mode = "enumerated"
        else:
            # A key-derived seed makes a setting reproducible regardless of other settings/input order.
            group_seed = int(hashlib.sha256(RUNNER.canonical([seed, key]).encode()).hexdigest()[:16], 16)
            rng = np.random.default_rng(group_seed)
            choices = np.column_stack([rng.integers(n, size=draws) for n in sizes])
            mode = "uniform-with-replacement"
        rungs = RUNNER.production_rungs(estimator)
        n = len(choices); R = np.empty((n, len(rungs))); v = R.copy(); corr = R.copy()
        ids = [np.array([[r["scores"][k]["id_bits"] for k in rungs] for r in rr]) for rr in own]
        sr = [np.array([job_metadata(r)["rates"]["mean_sr"] for r in rr]) for rr in own]
        if any(not np.allclose(x, x[0], rtol=1e-12, atol=0) for x in sr):
            raise ValueError("canonical mean SR must be fixed across a language's options")
        msr = [np.array([job_metadata(r)['rates'].get('matched_sr', np.nan) for r in rr]) for rr in own]
        psr = [np.array([job_metadata(r)['rates'].get('paper_subset_sr', np.nan) for r in rr]) for rr in own]
        matched_R = np.full_like(R, np.nan)
        paper_subset_R = np.full_like(R, np.nan)
        for u, choice in enumerate(choices):
            log_id = np.log(np.stack([ids[l][c] for l, c in enumerate(choice)]))
            log_sr = np.log([sr[l][c] for l, c in enumerate(choice)])
            if np.std(log_sr, ddof=1) == 0:
                raise ValueError("R is undefined when canonical language rates have zero spread")
            with np.errstate(invalid="ignore", divide="ignore"):
                R[u], v[u], corr[u] = A.ladder(log_id, log_sr)
                if all(np.isfinite(msr[l][c]) for l,c in enumerate(choice)):
                    # Keep the canonical SR denominator, as specified in §6.
                    effective_id = log_id + (np.log([msr[l][c] for l, c in enumerate(choice)]) - log_sr)[:, None]
                    matched_R[u] = A.ladder(effective_id, log_sr)[0]
                if all(np.isfinite(psr[l][c]) for l,c in enumerate(choice)):
                    effective_id = log_id + (np.log([psr[l][c] for l,c in enumerate(choice)])-log_sr)[:,None]
                    paper_subset_R[u] = A.ladder(effective_id, log_sr)[0]
        invalid = np.flatnonzero(~np.isfinite(R).all(axis=1))
        if len(invalid):
            message = f'non-finite canonical R in setting {key}; universe indices {invalid.tolist()}'
            if not allow_incomplete:
                raise ValueError(message)
            group_issues.append(message)
            groups.issues.append(message)
        family_weights = np.ones(n)
        for l, weight in enumerate(q):
            # For draws, this is the target/uniform importance ratio up to a constant.
            family_weights *= weight[choices[:, l]] * sizes[l]
        family_weights /= family_weights.sum()
        shared, estimator = json.loads(key)
        group = dict(shared=shared, estimator=estimator, languages=languages, records=own, families=families,
                     choices=choices, rungs=rungs, R=R, v=v, r=corr, matched_R=matched_R, family_weights=family_weights,
                     paper_subset_R=paper_subset_R, names=names, issues=sorted(set(group_issues)), mode=mode)
        group["summary"] = dict(shared=shared, estimator=estimator, rungs=rungs, languages=languages, mode=mode,
                                total_possible=total, reported=n, unique_draws=int(len(np.unique(choices, axis=0))),
                                families=families, undeclared_families=sorted(set(undeclared)),
                                family_sources=sorted({record_families(r)[1] for r in rows}),
                                inapplicable_forks={language: [dict(options=job_metadata(r)['options'],
                                    not_applicable=sorted(set(families[language])-set(job_metadata(r)['options'])))
                                    for r in own[l]] for l,language in enumerate(languages)},
                                incomplete_local_crossings=incomplete,
                                job_ids={language: [r["job_id"] for r in own[l]] for l, language in enumerate(languages)},
                                named_universes=names, incomplete=bool(group_issues), missing_inputs=sorted(set(group_issues)),
                                tie_policy=TIE_POLICY,
                                ordinary=summaries(group, np.full(n, 1 / n)),
                                family_weighted=summaries(group, family_weights, mode == "uniform-with-replacement"))
        if declarations is not None:
            group['summary']['named_declarations'] = [d for d in declarations if d.get('shared', shared) == shared]
        if estimator.get("name") == "neural":
            group["summary"]["language_inventories"] = {
                language: sorted({r["identity"]["estimator"]["vocab"] for r in own[l]
                                  if "vocab" in r["identity"]["estimator"]})
                for l, language in enumerate(languages)}
        groups.append(group)
    return groups

@_boundary
def named_choices(declarations, shared, languages, own, allow_incomplete=False, issues=None):
    """Resolve complete named combinations directly, never crossing their local options."""
    if not isinstance(declarations, tuple):
        raise ValueError("named universes must be a list per estimator")
    selected = [d for d in declarations if "shared" not in d or d["shared"] == shared]
    if len({d["name"] for d in selected}) != len(selected):
        raise ValueError("need unique named universes within each shared setting")
    choices = []; names = []
    for d in selected:
        if d.get('status') == 'pending':
            continue
        if set(d["options"]) != set(languages):
            missing = set(d["options"]) - set(languages)
            if allow_incomplete and missing and set(languages).issubset(d["options"]):
                if issues is not None:
                    issues.append(f"named universe {d['name']} missing language caches {sorted(missing)}; omitted")
                continue
            raise ValueError(f"named universe {d['name']} must declare exactly this setting's languages")
        row = []
        for language, rr in zip(languages, own):
            matches = [i for i, r in enumerate(rr) if job_metadata(r)["options"] == d["options"][language]]
            if len(matches) != 1:
                if allow_incomplete and not matches:
                    if issues is not None:
                        issues.append(f"named universe {d['name']} lacks one estimate for {language}; omitted")
                    break
                raise ValueError(f"named universe {d['name']} lacks one estimate for {language}")
            row.append(matches[0])
        if len(row) != len(languages):
            continue
        choices.append(row); names.append(d["name"])
    return np.array(choices, dtype=np.int64).reshape(-1, len(languages)), names

@_boundary
def shared_variation(groups, pooling="equal-setting"):
    """Pool within each estimator to expose shared-fork marginal variation and rung interactions."""
    if pooling not in ("equal-setting", "equal-universe"):
        raise ValueError("pooling must be equal-setting or equal-universe")
    estimators = {}
    for g in groups:
        estimators.setdefault(RUNNER.canonical(g["estimator"]), []).append(g)
    results = []
    for key, gg in sorted(estimators.items()):
        masses = np.ones(len(gg))
        # Named estimators pool declared combinations, never hypothetical crossings.
        if pooling == "equal-universe":
            masses = np.array([len(g["R"]) if g["names"] is not None else g["summary"]["total_possible"] for g in gg], float)
        masses /= masses.sum()
        pool = {"rungs": gg[0]["rungs"], "R": np.concatenate([g["R"] for g in gg]),
                "shared": {}, "languages": [], "choices": np.empty((sum(len(g["R"]) for g in gg), 0))}
        labels = {}
        declared_forks = set().union(*(g["shared"] for g in gg))
        for fork in sorted(set(SHARED_FORKS) | declared_forks):
            # Missing forks use the same excluded label as local conditional forks.
            labels[f"shared.{fork}"] = np.concatenate([np.full(len(g["R"]), g["shared"].get(fork, "not applicable")) for g in gg])
        pool["pooled_labels"] = labels
        result = dict(estimator=json.loads(key), settings=len(gg), pooling=pooling,
                      undeclared_shared_forks=sorted(set(SHARED_FORKS) - declared_forks),
                      setting_weights=[dict(shared=g["shared"], weight=float(m)) for g, m in zip(gg, masses)])
        for kind in ("ordinary", "family_weighted"):
            weights = np.concatenate([m * (g["family_weights"] if kind == "family_weighted" else np.full(len(g["R"]), 1 / len(g["R"])))
                                      for g, m in zip(gg, masses)])
            sampled = kind == "family_weighted" and any(g["mode"] == "uniform-with-replacement" for g in gg)
            summary = rate_summaries(pool, weights, pool["R"], sampled)
            for field, label in (('matched_R', 'matched_count'), ('paper_subset_R', 'paper_subset')):
                values = np.concatenate([g[field] if g.get(field) is not None else np.full_like(g['R'], np.nan) for g in gg])
                summary[label] = rate_summaries(pool, weights, values, sampled, comparison=True)
            result[kind] = summary
        results.append(result)
    return clean(results)

@_boundary
def universe_options(group, u):
    return {language: job_metadata(group["records"][l][c])["options"]
            for l, (language, c) in enumerate(zip(group["languages"], group["choices"][u]))}

def _pooled_share(score):
    """Share of test targets pooled as the rare symbol; None where the count or the test size is missing."""
    n = score.get('pooled_targets', (score.get('escape') or {}).get('n_pooled'))
    return n / score['n_test'] if n is not None and score.get('n_test') else None


def _headline(groups, comparison):
    """The rungs the matched-count rate is read at, per setting and estimator, and the neural estimate beside
    KenLM's at k = 4 in each named universe both score (Brett, 2026-10-17)."""
    rows = []
    for gi, g in enumerate(groups):
        fw = g['summary']['family_weighted']
        def at(summary):
            if not summary or 'R' not in summary:
                return None
            return {r: summary['R'][r] for r in HEADLINE_RUNGS if r in summary['R']}
        rows.append(dict(setting=gi + 1, shared=g['shared'], estimator=g['estimator'],
                         canonical=at(fw), matched_count=at(fw.get('matched_count'))))
    paired = []
    for c in comparison['contrasts']:
        if 'kenlm_R' not in c or 'neural_R' not in c:
            continue
        k4, n4 = c['kenlm_R'].get('4'), c['neural_R'].get('4')
        paired.append(dict(name=c['name'], shared=c['shared'], options=c['options'], kenlm_settings=c['kenlm_settings'],
                           neural_settings=c['neural_settings'], rate=c['rate'], kenlm_R_4=k4, neural_R_4=n4,
                           kenlm_minus_neural_R_4=None if k4 is None or n4 is None else k4 - n4))
    return dict(rungs=list(HEADLINE_RUNGS),
                basis='Brett, 2026-10-17 (DECISIONS.md, from F2): read mainly at the longest rungs, where unmatched '
                      'spans move the rate least; lower rungs are reported beside them',
                settings=rows,
                neural_pairing=dict(rung='4', difference='KenLM minus neural', rows=paired,
                                    note='k = 3 is KenLM only: the neural estimator is fitted at rungs 1w, 1 and 4'))


@_boundary
def estimator_comparison(groups):
    """Align named selections by shared setting, languages and exact options.

    KenLM is looked up directly in its records: its full enumeration need not
    be named or even contain a sampled tuple. Different fit configurations
    produce separate pairs. Differences are neural minus KenLM throughout.
    """
    rows, changes, missing = [], [], []
    for neural in groups:
        if neural['estimator'].get('name') != 'neural':
            continue
        candidates = [g for g in groups if g['estimator'].get('name', 'kenlm') == 'kenlm'
                      and g['shared'] == neural['shared'] and g['languages'] == neural['languages']]
        for u, name in enumerate(neural['names'] or []):
            options = universe_options(neural, u)
            found = False
            for kenlm in candidates:
                selected = []
                for language, records in zip(kenlm['languages'], kenlm['records']):
                    matches = [r for r in records if job_metadata(r)['options'] == options[language]]
                    if len(matches) != 1:
                        break
                    selected.append(matches[0])
                if len(selected) != len(neural['languages']):
                    continue
                nn = [neural['records'][l][c] for l, c in enumerate(neural['choices'][u])]
                # Equal option labels alone cannot establish a paired comparison.
                for a, b in zip(selected, nn):
                    for key in ('documents', 'source_hashes', 'document_alignment'):
                        if job_metadata(a).get(key) != job_metadata(b).get(key):
                            raise ValueError(f'estimator comparison differs in {key}')
                    if job_metadata(a)['rates'] != job_metadata(b)['rates']:
                        raise ValueError('estimator comparison differs in rates')
                found = True
                common = dict(name=name, shared=neural['shared'], options=options,
                              kenlm_settings=kenlm['estimator'], neural_settings=neural['estimator'])
                ids = np.array([[r['scores'][k]['id_bits'] for k in ('1w', '1', '4')] for r in selected])
                sr = np.array([job_metadata(r)['rates']['mean_sr'] for r in selected])
                kr = A.ladder(np.log(ids), np.log(sr))[0]
                nr = neural['R'][u, [neural['rungs'].index(k) for k in ('1w', '1', '4')]]
                for l, language in enumerate(neural['languages']):
                    for k in ('1w', '1', '4'):
                        a, b = selected[l]['scores'][k]['id_bits'], nn[l]['scores'][k]['id_bits']
                        ks, ns = selected[l]['scores'][k], nn[l]['scores'][k]
                        rows.append(dict(common, language=language, rung=k, kenlm_job=selected[l]['job_id'],
                                         neural_job=nn[l]['job_id'], kenlm_ID_bits=a, neural_ID_bits=b,
                                         neural_minus_kenlm_ID_bits=b-a,
                                         kenlm_IR_bits_per_second=a*sr[l], neural_IR_bits_per_second=b*sr[l],
                                         # Brett, 2026-10-17: inventory-driven bias is judged against the neural model.
                                         kenlm_inventory_train=ks.get('inventory_train'),
                                         neural_vocab=nn[l]['identity'].get('estimator', {}).get('vocab'),
                                         kenlm_pooled_share=_pooled_share(ks), neural_pooled_share=_pooled_share(ns)))
                changes.append(dict(common, rate='canonical',
                    kenlm_R=dict(zip(('1w','1','4'), kr)), neural_R=dict(zip(('1w','1','4'), nr)),
                    kenlm_contrasts=contrasts(kr, ('1w','1','4')),
                    neural_contrasts=contrasts(nr, ('1w','1','4')),
                    neural_minus_kenlm_contrasts=contrasts(nr-kr, ('1w','1','4'))))
                if neural['matched_R'] is not None and all('matched_sr' in job_metadata(r)['rates'] for r in selected):
                    effective = np.log(ids) + (np.log([job_metadata(r)['rates']['matched_sr'] for r in selected])-np.log(sr))[:,None]
                    a = A.ladder(effective, np.log(sr))[0]
                    b = neural['matched_R'][u, [neural['rungs'].index(k) for k in ('1w','1','4')]]
                    changes.append(dict(common, rate='matched',
                                        kenlm_R=dict(zip(('1w','1','4'), a)), neural_R=dict(zip(('1w','1','4'), b)),
                                        kenlm_contrasts=contrasts(a, ('1w','1','4')),
                                        neural_contrasts=contrasts(b, ('1w','1','4')),
                                        neural_minus_kenlm_contrasts=contrasts(b-a, ('1w','1','4'))))
            if not found:
                missing.append(dict(name=name, shared=neural['shared'], options=options,
                                    reason='no aligned KenLM selection'))
    return clean(dict(status=('partial' if missing else 'reported') if rows else 'unavailable', difference='neural minus KenLM',
                      estimates=rows, contrasts=changes, missing_pairs=missing))

@_boundary
def positive_number(value, label, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f'{label} must be {"nonnegative" if zero else "positive"} and finite')
    return value

@_boundary
def segment_context_spans(documents, rungs=RUNGS, treatment='bounded'):
    """Observed context spans from documents → lines → words → syllable lengths.

    Each syllable length counts atomic segments supplied by upstream
    segmentation. Word/line start markers and boundary flags count zero.
    Running text crosses lines but resets at document boundaries; 1w resets
    at each word. Means include targets whose context is empty or truncated.
    """
    if treatment not in ('bounded', 'running'):
        raise ValueError('context span treatment must be bounded or running')
    totals = {r: dict(segments_sum=0, contexts=0) for r in rungs}
    for document in documents:
        history = []
        for line in document:
            if treatment == 'bounded':
                history = []
            for word in line:
                for i, length in enumerate(word):
                    if type(length) is not int or length < 1:
                        raise ValueError('syllable segment lengths must be positive integers')
                    for rung, total in totals.items():
                        if rung not in RUNGS:
                            raise ValueError('unknown context span rung')
                        k = 0 if rung == '0' else int(rung[0])
                        span = 0 if not k or (rung == '1w' and i == 0) else sum(history[-k:])
                        total['segments_sum'] += span; total['contexts'] += 1
                    history.append(length)
                    history = history[-4:]
    if not totals or any(v['contexts'] == 0 for v in totals.values()):
        raise ValueError('context spans require scored syllables and rungs')
    return totals

@_boundary
def french_coverage(documents):
    """Aggregate pipeline token counts, never the mean of document shares.

    Input: [{corpus: label, report: pipeline_document_json}, ...]. Group by
    option, counter settings and G2P descriptor to keep distinct routes apart.
    Blocked lines are excluded by the pipeline and remain explicit here.
    """
    grouped = {}; seen = set()
    for item in documents:
        doc = item['report']; cfg = doc['config']
        if cfg['language'] != 'FRA':
            raise ValueError('French coverage requires FRA pipeline reports')
        key = RUNNER.canonical([item['corpus'], cfg['option'], cfg['counter_options'], cfg['g2p']])
        identity = (key, doc['document'])
        if identity in seen:
            raise ValueError('duplicate French coverage document')
        seen.add(identity)
        total = doc['fallback_total_word_tokens']; fallback = doc['fallback_word_tokens']
        if type(total) is not int or type(fallback) is not int or not 0 <= fallback <= total:
            raise ValueError('invalid French pipeline fallback counts')
        row = grouped.setdefault(key, dict(corpus=item['corpus'], option=cfg['option'],
            counter_options=cfg['counter_options'], g2p=cfg['g2p'], documents=0, word_tokens=0,
            fallback_word_tokens=0, failed_lines=0, blocked_documents=0))
        row['documents'] += 1; row['word_tokens'] += total; row['fallback_word_tokens'] += fallback
        row['blocked_documents'] += doc['status'] != 'complete'
        row['failed_lines'] += sum(line['counter_count'] is None for line in doc['lines'])
    for row in grouped.values():
        row['dictionary_word_tokens'] = row['word_tokens']-row['fallback_word_tokens']
        row['fallback_share'] = row['fallback_word_tokens']/row['word_tokens'] if row['word_tokens'] else None
        row['dictionary_coverage'] = 1-row['fallback_share'] if row['word_tokens'] else None
    return dict(status='reported' if grouped else 'unavailable', denominator='successfully counted word tokens',
                rows=list(grouped.values()))

# Context span measures and their means per target: segments where upstream segmentation gives them; words
# covered, each syllable counting as its share of its word, and syllables (Brett, 2026-10-17).
SPAN_MEASURES = {'segments_sum': 'mean_segments', 'words_sum': 'mean_words', 'syllables_sum': 'mean_syllables'}


@_boundary
def diagnostic_tables(groups, inputs=None):
    """Report supplied measurements; absent diagnostics are unavailable, not zero.

    Schema: {jobs: {analysis_id: {u?, baseline_job?, context_spans?:
    {rung: {contexts, segments_sum?, words_sum?, syllables_sum?}} (segments or
    words required), segment_contexts?: {documents, treatment},
    changes?: {sample: {splits, merges,
    deletions, net_count_change, inventory_before, inventory_after, oov_before,
    oov_after, affected_tokens, total_tokens}}}}, french_documents?: [...]}.
    Samples name each corpus and the read texts. OOV counts must use the same
    held-out population before/after. Upstream code defines event alignment.
    An analysis_id hashes [job_id, language, shared, options]. A job_id may
    substitute only when it identifies exactly one analysis selection: cached
    fits can legitimately be reused by distinct options and shared settings.
    """
    inputs = inputs or {}; supplied = inputs.get('jobs', {})
    if set(inputs)-{'jobs', 'french_documents'}:
        raise ValueError('unknown diagnostic input field')
    records = {}; aliases = {}
    for g in groups:
        for own in g['records']:
            for r in own:
                meta = job_metadata(r)
                key = RUNNER.digest([r['job_id'], meta['language'], meta['shared'], meta['options']])
                previous = records.setdefault(key, r)
                aliases.setdefault(r['job_id'], set()).add(key)
                if job_metadata(previous) != job_metadata(r) or previous['scores'] != r['scores']:
                    raise ValueError('diagnostic analysis identity has conflicting metadata or scores')
    def resolve(key):
        if key in records:
            return key
        if len(aliases.get(key, ())) == 1:
            return next(iter(aliases[key]))
        raise ValueError('diagnostics refer to unavailable or ambiguous job IDs; use analysis_id')
    expanded = {}
    for key, value in supplied.items():
        key = resolve(key)
        if key in expanded:
            raise ValueError('duplicate diagnostic analysis selection')
        expanded[key] = value
    supplied = expanded
    cancellation, spans, changes, rates, unavailable = [], [], [], [], []
    for key, r in sorted(records.items()):
        meta = job_metadata(r); values = supplied.get(key, {})
        if set(values)-{'u','baseline_job','context_spans','segment_contexts','changes'}:
            raise ValueError('unknown job diagnostic input field')
        if 'segment_contexts' in values and 'context_spans' in values:
            raise ValueError('supply context spans or segment documents, not both')
        observed_spans = values.get('context_spans', {})
        if 'segment_contexts' in values:
            source = values['segment_contexts']
            observed_spans = segment_context_spans(source['documents'], tuple(r['scores']), source['treatment'])
        label = dict(job_id=r['job_id'], analysis_id=key, language=meta['language'], options=meta['options'], shared=meta['shared'],
                     estimator=assembly_estimator(r))
        if 'u' in values:
            positive_number(values['u'], 'u')
        baseline_key = resolve(values['baseline_job']) if 'baseline_job' in values else None
        baseline = records.get(baseline_key)
        if baseline is not None and 'u' not in values:
            raise ValueError('cancellation comparison requires u for both jobs')
        if 'baseline_job' in values and (baseline is None or job_metadata(baseline)['language'] != meta['language']
                or job_metadata(baseline)['shared'] != meta['shared'] or assembly_estimator(baseline) != assembly_estimator(r)):
            raise ValueError('cancellation baseline must share language, shared setting and estimator')
        if baseline is not None and 'u' not in supplied.get(baseline_key, {}):
            raise ValueError('cancellation baseline requires u')
        for rung, score in r['scores'].items():
            bits = score['id_bits']; sr = meta['rates']['mean_sr']; matched = meta['rates'].get('matched_sr')
            rates.append(dict(label, rung=rung, ID_bits=bits, canonical_SR=sr,
                canonical_IR_bits_per_second=bits*sr, matched_SR=matched,
                matched_IR_bits_per_second=bits*matched if matched is not None else None))
            row = dict(label, rung=rung, u=values.get('u'), ID_bits=bits,
                       u_times_ID_bits=bits*values['u'] if 'u' in values else None,
                       inventory_train=score.get('inventory_train', r['identity'].get('estimator', {}).get('vocab')),
                       n_test=score.get('n_test'))
            if baseline is not None:
                if rung not in baseline['scores']:
                    raise ValueError('cancellation baseline missing rung')
                before = baseline['scores'][rung]['id_bits']
                row.update(baseline_job=baseline['job_id'], baseline_analysis_id=baseline_key, ID_difference=bits-before,
                    u_times_ID_difference=row['u_times_ID_bits']-before*supplied[baseline_key]['u'])
            cancellation.append(row)
            span = observed_spans.get(rung)
            if span is None:
                unavailable.append(dict(label, rung=rung, diagnostic='context_span'))
            else:
                if set(span) - {'contexts', *SPAN_MEASURES} or not {'segments_sum', 'words_sum'} & set(span):
                    raise ValueError('context span requires contexts and segments_sum or words_sum')
                n = span.get('contexts')
                if type(n) is not int or n < 1:
                    raise ValueError('context span requires positive integer contexts')
                row = dict(label, rung=rung, contexts=n)
                for field, mean in SPAN_MEASURES.items():
                    value = positive_number(span[field], field, zero=True) if field in span else None
                    row.update({field: value, mean: None if value is None else value / n})
                spans.append(row)
        if set(observed_spans)-set(r['scores']):
            raise ValueError('context span supplied for unavailable rung')
        if 'u' not in values:
            unavailable.append(dict(label, diagnostic='cancellation_u'))
        if baseline is None:
            unavailable.append(dict(label, diagnostic='cancellation_baseline'))
        if not values.get('changes'):
            unavailable.append(dict(label, diagnostic='option_changes'))
        for sample, measures in values.get('changes', {}).items():
            required = ('splits','merges','deletions','net_count_change','inventory_before','inventory_after',
                        'oov_before','oov_after','affected_tokens','total_tokens')
            if set(measures) != set(required) or any(type(measures[k]) is not int for k in required):
                raise ValueError('option changes require all integer measurements in the diagnostic schema')
            if any(measures[k] < 0 for k in required if k != 'net_count_change') or measures['affected_tokens'] > measures['total_tokens']:
                raise ValueError('invalid option change counts')
            changes.append(dict(label, sample=sample, **measures,
                inventory_change=measures['inventory_after']-measures['inventory_before'],
                oov_change=measures['oov_after']-measures['oov_before'],
                affected_frequency=measures['affected_tokens']/measures['total_tokens'] if measures['total_tokens'] else None))
    coverage = french_coverage(inputs.get('french_documents', []))
    return clean(dict(completeness='INCOMPLETE' if unavailable or coverage['status']=='unavailable' else 'COMPLETE',
                     cancellation=cancellation, context_spans=spans, option_changes=changes,
                     absolute_information_rates=rates, unavailable=unavailable,
                     french_dictionary_coverage=coverage))

@_boundary
def curve_svg(groups, path=None):
    """Draw R4 in rank order with each fork's option rows beneath; TSV retains every row."""
    parts = []; ybase = 50; width = 1100
    palette = ("#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d")
    for gi, g in enumerate(groups):
        order = np.argsort(g["R"][:, g["rungs"].index("4")], kind="stable"); n = len(order)
        displayed = order[np.unique(np.linspace(0, n - 1, min(n, 200)).astype(int))]
        title = html.escape(f"Setting {gi + 1}: {RUNNER.canonical(g['shared'])} / {RUNNER.canonical(g['estimator'])}")
        parts.append(f'<text x="10" y="{ybase}" font-size="12">{title}</text>')
        ybase += 20
        values = g["R"][order, g["rungs"].index("4")]; lo, hi = float(values.min()), float(values.max())
        span = hi - lo or 1
        points = []
        for rank in np.unique(np.linspace(0, n - 1, min(n, 1000)).astype(int)):
            x = 280 + 790 * rank / max(1, n - 1); y = ybase + 110 - 100 * (values[rank] - lo) / span
            points.append(f"{x:.2f},{y:.2f}")
        parts.append(f'<polyline fill="none" stroke="#222" points="{" ".join(points)}"/>')
        parts.append(f'<text x="10" y="{ybase + 55}" font-size="12">R4: {lo:.4g} to {hi:.4g}</text>')
        ybase += 140
        for fork, labels, families in fork_labels(g):
            categories = sorted(set(labels)); colors = {c: palette[i % len(palette)] for i, c in enumerate(categories)}
            legend = html.escape(fork + " | " + ", ".join(categories))
            parts.append(f'<text x="10" y="{ybase + 10}" font-size="10">{legend}</text>')
            dx = 790 / len(displayed)
            for col, u in enumerate(displayed):
                option = labels[u]; tip = html.escape(f"{fork}: {option}; family: {families[option]}")
                parts.append(f'<rect x="{280 + col * dx:.2f}" y="{ybase}" width="{dx:.2f}" height="12" '
                             f'fill="{colors[option]}"><title>{tip}</title></rect>')
            ybase += 18
        parts.append(f'<text x="280" y="{ybase + 12}" font-size="10">Universe rank; option rows show '
                     f'{len(displayed)} evenly spaced ranks of {n}. Full options in specification-curve.tsv.</text>')
        ybase += 60
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{ybase}">'
           '<rect width="100%" height="100%" fill="white"/>'
           f'<text x="10" y="20" font-size="13">{DISCLAIMER}</text>' + "".join(parts) + '</svg>\n')
    if path is not None:
        RUNNER.DiskGuard(work=Path(path).parent).allocation(len(svg.encode()))
        path.write_text(svg)
    return svg

@_boundary
def subset_panel_means(rows, values, langs, n_boot, seed):
    """Subset means using the canonical panel's exact text and speaker draws.

    None denotes an excluded reading, never a zero rate. Speakers with no
    drawn selected readings are omitted under the existing panel assumption.
    """
    rng = np.random.default_rng(seed)
    texts = sorted({r['text'] for r in rows})
    text_index = {t:i for i,t in enumerate(texts)}
    tdraw = rng.integers(0,len(texts),size=(n_boot,len(texts)))
    output = np.empty((n_boot,len(langs)))
    for j,language in enumerate(langs):
        speakers = sorted({r['speaker'] for r in rows if r['language']==language})
        speaker_index = {s:i for i,s in enumerate(speakers)}
        matrix = np.full((len(speakers),len(texts)),np.nan)
        for r,value in zip(rows,values):
            if r['language']==language and value is not None:
                if not math.isfinite(value) or value <= 0:
                    raise ValueError('subset reading rates must be positive and finite')
                matrix[speaker_index[r['speaker']],text_index[r['text']]] = value
        sdraw = rng.integers(0,len(speakers),size=(n_boot,len(speakers)))
        sub = matrix[sdraw[:,:,None],tdraw[:,None,:]]
        with __import__('warnings').catch_warnings():
            __import__('warnings').simplefilter('ignore',RuntimeWarning)
            output[:,j] = np.nanmean(np.nanmean(sub,axis=2),axis=1)
    A.panel_draw_audit(output)
    return output


@_boundary
def named_intervals(groups, readings, n_panel=1000, n_population=2000, seed=0,
                    panel_method=A.PANEL_METHOD, population_method=A.POPULATION_METHOD,
                    clusters=10, level=.90, language_families=None):
    """§4b intervals only for prospectively declared named universes.

    Reading rows contain language, speaker, text, sr. Canonical speaker-first
    SR must agree with assembly metadata. Matched-count intervals additionally
    require matched_sr on the selected subset only (a number, or an
    options-JSON keyed mapping). All canonical rows remain in the input;
    paper_subset_sr accompanies matched_sr on that same subset.
    Family membership is supplied, never inferred from the option families.
    """
    if getattr(groups, 'issues', []):
        raise ValueError('named intervals require complete assembly inputs')
    named = [g for g in groups if g['names'] is not None]
    def sample_key(record):
        meta=job_metadata(record)
        return RUNNER.digest([record['job_id'],meta['language'],meta['shared'],meta['options']])
    records = {sample_key(record):dict(record,sampling_key=sample_key(record))
               for g in named for own in g['records'] for record in own}
    if not records:
        return dict(universes=[], panel_method=panel_method, population_method=population_method)
    doc_samples, audit = A.resample_document_scores(list(records.values()), n_panel, seed)
    output = dict(schema='named-intervals-4b-v1', level=level, approximate=True, pointwise=True,
                  panel_method=panel_method, population_method=population_method,
                  panel_draws=n_panel,population_draws=n_population,
                  document_resampling=audit, universes=[],
                  measurement_error=dict(primary_correction='none',
                      published_S2_diagnostics=[dict(noise='data', observed_minus_latent=-.03610, mcse=.00151),
                                                dict(noise='data_x2', observed_minus_latent=-.14195, mcse=.00331)],
                      interpretation='Scenario-dependent simulation diagnostics, never real-data corrections or bounds.'))
    for g in named:
        langs = g['languages']
        rows = [r for r in readings if r['language'] in langs]
        lang, speaker, text = [np.array([r[key] for r in rows]) for key in ('language','speaker','text')]
        sr = np.array([r['sr'] for r in rows],float)
        order, means = A.language_means(lang,speaker,sr)
        if tuple(order) != langs:
            raise ValueError('named universe lacks a reading language')
        boot_means = A.panel_means(lang,speaker,text,sr,langs,n_panel,seed)
        reading_valid = np.isfinite(boot_means).all(axis=1)
        log_sr = np.log(means)
        # The adopted real neural report is restricted to its rehearsed rungs.
        rungs = g['rungs']
        for u, name in enumerate(g['names']):
            selected = [g['records'][l][c] for l,c in enumerate(g['choices'][u])]
            declared_sr = [job_metadata(r)['rates']['mean_sr'] for r in selected]
            if not np.allclose(means,declared_sr,rtol=1e-10,atol=0):
                raise ValueError('reading means disagree with canonical assembly SR')
            ids = np.array([[r['scores'][k]['id_bits'] for k in rungs] for r in selected])
            density_draws = np.stack([doc_samples[sample_key(r)][:,[list(r['scores']).index(k) for k in rungs]] for r in selected],axis=1)
            point, quantities = A.paired_values(A.ladder(np.log(ids),log_sr)[0],rungs)
            log_means = np.log(boot_means)
            if np.any(log_means.std(axis=1,ddof=1) <= 0):
                raise ValueError('undefined panel statistic')
            draws = np.std(np.log(density_draws)+log_means[:,:,None],axis=1,ddof=1)/log_means.std(axis=1,ddof=1)[:,None]
            draws = np.where(np.ptp(density_draws,axis=1)==0,1.,draws)
            draws[~reading_valid] = np.nan
            draws,_ = A.paired_values(draws,rungs)
            panel_draws = {"canonical": (point, draws)}
            panel_audit = {}
            lo = hi = None
            population_inputs = {'canonical': np.log(ids)}
            population = None
            family_check = dict(status='unavailable',reason='language families not supplied')
            if language_families is not None:
                if not set(langs).issubset(language_families):
                    raise ValueError('leave-one-family-out needs every language family')
                family_check = dict(status='reported',rows=[])
                for family in sorted({language_families[l] for l in langs}):
                    keep = np.array([language_families[l] != family for l in langs])
                    if keep.sum() < 3 or np.std(log_sr[keep]) == 0:
                        family_check['rows'].append(dict(omitted=family,status='unsupported',reason='insufficient language support'))
                    else:
                        values,_ = A.paired_values(A.ladder(np.log(ids[keep]),log_sr[keep])[0],rungs)
                        family_check['rows'].append(dict(omitted=family,status='ok',estimate=values,languages=np.array(langs)[keep]))
            panel = dict(method=panel_method,estimate=point,lo=lo,hi=hi,clusters=clusters,draws=n_panel,
                         **panel_audit,
                         level=level,quantities=quantities,target='these languages conditional on training',
                         resampled=['speakers within language','reading texts jointly','test documents'],
                         fixed=['languages','training and validation documents','fitted models or training counts',
                                'model seeds','estimator settings','linguistic processing'],
                         context='declared line treatment; always reset at document boundaries',
                         missing_readings='speakers with no selected readings omitted; unavailable-language draws omitted jointly and counted; stop above 1%; assumes ignorable missingness')
            result = dict(name=name,shared=g['shared'],estimator=g['estimator'],languages=langs,rungs=rungs,
                          quantities=quantities,panel=panel,population=population,
                          leave_one_family_out=family_check,
                          matched_count=dict(status='unavailable',reason='per-reading matched rates not supplied'))
            by_language={job_metadata(r)['language']:r for r in selected}
            supports = {}
            for field,label in (('matched_sr','matched_count'),('paper_subset_sr','paper_subset')):
                values=[]
                for row in rows:
                    value=row.get(field)
                    if isinstance(value,dict):
                        value=value.get(RUNNER.canonical(job_metadata(by_language[row['language']])['options']))
                    values.append(value)
                if not any(v is not None for v in values):
                    if label=='paper_subset':
                        result[label]=dict(status='unavailable',reason='per-reading paper subset rates not supplied')
                    continue
                keep=np.array([v is not None for v in values])
                supports[field]=keep
                if field=='paper_subset_sr' and ('matched_sr' not in supports or not np.array_equal(keep,supports['matched_sr'])):
                    raise ValueError('paper and matched rates must use the same selected reading subset')
                order,subset_means=A.language_means(lang[keep],speaker[keep],np.array([v for v in values if v is not None],float))
                if tuple(order)!=langs:
                    raise ValueError('selected reading subset lacks a language')
                declared=[job_metadata(r)['rates'].get(field) for r in selected]
                if any(v is None for v in declared) or not np.allclose(subset_means,declared,rtol=1e-10,atol=0):
                    raise ValueError(f'reading means disagree with {field} assembly SR')
                subset_boot=subset_panel_means(rows,values,langs,n_panel,seed)
                joint_valid=reading_valid & np.isfinite(subset_boot).all(axis=1)
                effective=np.log(ids)+(np.log(subset_means)-log_sr)[:,None]
                population_inputs[label] = effective
                subset_point,_=A.paired_values(A.ladder(effective,log_sr)[0],rungs)
                md=np.std(np.log(density_draws)+np.log(subset_boot)[:,:,None],axis=1,ddof=1)/log_means.std(axis=1,ddof=1)[:,None]
                md[~joint_valid]=np.nan
                md,_=A.paired_values(md,rungs)
                panel_draws[label] = (subset_point, md)
                ml = mh = None
                subset_audit = {}
                result[label]=dict(status='reported',panel=dict(panel,estimate=subset_point,lo=ml,hi=mh,**subset_audit),
                    population=None,
                    selected_readings=int(keep.sum()),canonical_readings=len(rows),
                    denominator='canonical SR in both point and paired draws')
            common_valid = np.logical_and.reduce([np.isfinite(d).all(axis=1) for _, d in panel_draws.values()])
            for label, (estimate, samples) in panel_draws.items():
                samples[~common_valid] = np.nan
                low, high, draw_audit = A.panel_interval(estimate,samples,level,clusters,panel_method,include_audit=True)
                target = result['panel'] if label == 'canonical' else result[label]['panel']
                target.update(lo=low, hi=high, **draw_audit)
            for label, effective in population_inputs.items():
                population = A.population_interval(effective,log_sr,rungs,n_population,seed,level,population_method,
                    paired_log_ids=[value for key,value in population_inputs.items() if key != label])
                target = result if label == 'canonical' else result[label]
                target['population'] = population
            if family_check['status'] == 'reported':
                family_check['condition'] = result['population']['condition']
            result['paired_panel_draws'] = dict(requested_draws=n_panel, usable_draws=int(common_valid.sum()),
                undefined_draws=int((~common_valid).sum()), reports=list(panel_draws))
            output['universes'].append(result)
    return clean(output)


@_boundary
def table_text(rows):
    """Portable TSV: nested labels are JSON and absent values are blank."""
    fields = list(dict.fromkeys(k for row in rows for k in row))
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fields, delimiter='\t', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: RUNNER.canonical(value) if isinstance(value, (dict, list, tuple)) else
                         '' if value is None else value for key, value in clean(row).items()})
    return stream.getvalue()

@_boundary
def plugin_continuity(groups):
    """Paper continuity estimates and R; never substitute them into group R."""
    estimates, ratios, missing = [], [], []
    for g in groups:
        if g['estimator'].get('name', 'kenlm') != 'kenlm':
            continue
        for language, own in zip(g['languages'], g['records']):
            for record in own:
                for rung in ('0', '1w'):
                    plugin = record['scores'][rung].get('plugin')
                    common = dict(language=language, shared=g['shared'], estimator=g['estimator'],
                                  options=job_metadata(record)['options'], job_id=record['job_id'], rung=rung)
                    if plugin is None:
                        missing.append(dict(common, reason='training plug-in absent from cache'))
                    else:
                        estimates.append(dict(common, **plugin))
        for u, choice in enumerate(g['choices']):
            selected = [g['records'][l][c] for l, c in enumerate(choice)]
            sr = np.log([job_metadata(r)['rates']['mean_sr'] for r in selected])
            for rung in ('0', '1w'):
                plugins = [r['scores'][rung].get('plugin') for r in selected]
                values = [p['id_bits'] for p in plugins if p is not None]
                available = len(values) == len(selected) and all(x > 0 for x in values)
                ratio = float(A.ladder(np.log(values)[:, None], sr)[0][0]) if available else None
                ratios.append(dict(shared=g['shared'], estimator=g['estimator'], universe_index=u,
                                   name=g['names'][u] if g['names'] else None, options=universe_options(g, u),
                                   rung=rung, R=ratio, density_source='training_plugin',
                                   status='reported' if available else 'unavailable',
                                   reason=None if available else 'missing or zero plug-in; logarithmic R is undefined'))
    return clean(dict(label='Continuity check with the paper', density_source='training_plugin',
                      separate_from_multiverse_R=True, estimates=estimates, ratios=ratios, missing=missing))

def _continuity_summary(continuity):
    """The continuity block for summary.json: the per-universe rows stay in plugin-continuity-R.tsv."""
    counts = {}
    for row in continuity['ratios']:
        cell = counts.setdefault(row['rung'], dict(rows=0, reported=0, unavailable=0))
        cell['rows'] += 1
        cell['reported' if row['status'] == 'reported' else 'unavailable'] += 1
    return dict({key: value for key, value in continuity.items() if key != 'ratios'},
                ratios_table='plugin-continuity-R.tsv', ratio_counts=counts,
                named_ratios=[row for row in continuity['ratios'] if row['name'] is not None])


@_boundary
def write_outputs(groups, out, seed=0, pooling="equal-setting", guard=None, interval_report=None,
                  diagnostics=None):
    """Write finite JSON summaries and a complete ranked curve, checking projected disk first."""
    groups = Records(groups, getattr(groups, 'issues', ()))
    out = RUNNER.local(out)
    # Bound the TSV length conservatively before any substantial output write.
    projected = 0
    for g in groups:
        labels = sum(max(len(RUNNER.canonical(job_metadata(r)["options"]).encode()) for r in rr)
                     + len(RUNNER.canonical(language).encode()) + 8
                     for language, rr in zip(g["languages"], g["records"]))
        metadata = len(RUNNER.canonical(g["shared"]).encode()) + len(RUNNER.canonical(g["estimator"]).encode())
        # CSV quoting can double every quote in JSON strings; float fields have fixed widths.
        projected += len(g["R"]) * (2 * (labels + metadata) + 3600)
    missing_inputs = sorted(set(getattr(groups, "issues", [])) | {issue for g in groups for issue in g["issues"]})
    incomplete = bool(missing_inputs) or any(g["summary"]["incomplete"] for g in groups)
    summary = dict(completeness="INCOMPLETE" if incomplete else "COMPLETE",
                   completeness_scope='cached scores, rates and universe declarations; diagnostic availability is reported separately',
                   missing_inputs=missing_inputs,
                   disclaimer=DISCLAIMER, seed=seed, rungs=RUNGS, tie_policy=TIE_POLICY,
                   shared_pooling_choice=f"Project lead choice: {pooling}; default is equal weight per shared setting",
                   shared_fork_variation=shared_variation(groups, pooling),
                   quantiles="inverse empirical CDF; sd is the descriptive population SD",
                   grouping="within-setting results plus pooled shared-fork variation; estimators remain separate",
                   weighting="equal convention families, equal conventions within families; equal values per applicable fork within convention; "
                             "inapplicable forks contribute one; exclusions renormalised within convention; "
                             "sampled shares use self-normalised importance weights; ESS = (sum w)^2 / sum(w^2), "
                             "conditional shares use weights within the condition",
                   variation="one-fork marginal variance ratios, which overlap and do not sum to one; "
                             "interaction uses the universe- and rung-centred ladder",
                   matched_count="canonical mean SR remains R's denominator; matched v/r are not relabelled as ID statistics",
                   groups=[g["summary"] for g in groups])
    comparison = estimator_comparison(groups)
    diagnostic_report = diagnostic_tables(groups, diagnostics)
    summary['declared_family_map'] = FAMILY_MAP
    summary['headline_rungs'] = _headline(groups, comparison)
    summary['definitional_forks'] = dict(
        forks=DEFINITIONAL_FORKS,
        basis='Brett, 2026-10-17 (DECISIONS.md, from F2): options that delete material are alternative definitions; '
              'each option\'s R_distribution is reported under by_fork beside the spread across options')
    summary['estimator_comparison'] = comparison
    summary['diagnostics'] = diagnostic_report
    continuity = plugin_continuity(groups)
    # One row per universe and rung is millions of rows, so the summary names the TSV (Brett, 2026-10-18).
    summary['plugin_continuity'] = _continuity_summary(continuity)
    tables = {'estimator-comparison.tsv': table_text(comparison['estimates']),
              'estimator-contrasts.tsv': table_text(comparison['contrasts']),
              'plugin-estimates.tsv': table_text(continuity['estimates']),
              'plugin-continuity-R.tsv': table_text(continuity['ratios'])}
    del continuity
    for name, key in [('cancellation', 'cancellation'), ('context-spans', 'context_spans'),
                      ('option-changes', 'option_changes'), ('absolute-information-rates', 'absolute_information_rates')]:
        tables[name+'.tsv'] = table_text(diagnostic_report[key])
    tables['french-dictionary-coverage.tsv'] = table_text(diagnostic_report['french_dictionary_coverage']['rows'])
    projected += sum(len(value.encode()) for value in tables.values())
    summary['interval_methods'] = dict(panel=(interval_report or {}).get('panel_method',A.PANEL_METHOD),
                                      population=(interval_report or {}).get('population_method',A.POPULATION_METHOD),
                                      panel_draws=(interval_report or {}).get('panel_draws',1000),
                                      population_draws=(interval_report or {}).get('population_draws',2000),
                                      level=(interval_report or {}).get('level',.90))
    summary['intervals'] = interval_report or dict(status='not computed',reason='named declarations and reading panel required')
    summary_text = RUNNER.canonical(clean(summary)) + "\n"
    svg_text = curve_svg(groups)
    if incomplete:
        svg_text = svg_text.replace(DISCLAIMER, "INCOMPLETE — " + DISCLAIMER)
    projected += len(summary_text.encode()) + len(svg_text.encode())
    del summary_text
    guard = guard or RUNNER.DiskGuard(work=out)
    try:
        guard.check(projected + 16384)
        guard.mkdir(out)
        RUNNER.write_json(out / "summary.json", clean(summary), guard)
        guard.allocation(projected)  # Includes the complete temporary TSV beside existing outputs.
    except RUNNER.DiskStop as error:
        return {"stopped": str(error)}
    fields = ["completeness", "setting", "rank", "universe_index", "name", "shared", "estimator", "options", "family_weight"]
    for prefix in ("R", "v", "r", "R_minus_1", "R_minus_R_1w", "matched_R", "matched_R_minus_1", "matched_R_minus_R_1w", "paper_subset_R"):
        fields.extend(f"{prefix}_{k}" for k in RUNGS)
    fields.extend(name for name, _, _ in CONTRASTS)
    fields.extend('matched_'+name for name, _, _ in CONTRASTS)
    fields.extend('paper_subset_'+name for name, _, _ in CONTRASTS)
    tmp = out / "specification-curve.tsv.tmp"
    try:
        with open(tmp, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n"); writer.writerow(fields)
            for gi, g in enumerate(groups):
                for rank, u in enumerate(np.argsort(g["R"][:, g["rungs"].index("4")], kind="stable"), 1):
                    row = [summary["completeness"], gi + 1, rank, int(u), g["names"][u] if g["names"] else "", RUNNER.canonical(g["shared"]), RUNNER.canonical(g["estimator"]),
                           RUNNER.canonical(universe_options(g, u)), f"{g['family_weights'][u]:.12g}"]
                    values = [g["R"][u], g["v"][u], g["r"][u], g["R"][u]-1, g["R"][u] - g["R"][u, g["rungs"].index("1w")]]
                    matched = g["matched_R"]
                    values += ([matched[u], matched[u]-1, matched[u] - matched[u, g["rungs"].index("1w")]] if matched is not None
                               else [np.full(len(g["rungs"]), np.nan)] * 3)
                    paper = g.get('paper_subset_R')
                    values += [paper[u] if paper is not None else np.full(len(g['rungs']),np.nan)]
                    row.extend(f"{x:.12g}" if np.isfinite(x) else "" for a in values for x in [dict(zip(g["rungs"], a)).get(r, np.nan) for r in RUNGS])
                    for array in (g['R'], matched, paper):
                        row.extend([f'{x:.12g}' if np.isfinite(x) else '' for x in contrasts(array[u], g['rungs']).values()]
                                   if array is not None else ['']*len(CONTRASTS))
                    writer.writerow(row)
        tmp.replace(out / "specification-curve.tsv")
    finally:
        tmp.unlink(missing_ok=True)
    try:
        for name, value in tables.items():
            guard.allocation(len(value.encode()))
            target = out / (name+'.tmp')
            try:
                target.write_text(value)
                target.replace(out / name)
            finally:
                target.unlink(missing_ok=True)
        guard.allocation(len(svg_text.encode()))
        (out / "specification-curve.svg").write_text(svg_text)
    except RUNNER.DiskStop as error:
        return {"stopped": str(error)}
    return {"settings": len(groups), "universes": sum(len(g["R"]) for g in groups), "stopped": None}

@_boundary
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cache"); p.add_argument("out")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--allow-incomplete", action="store_true")
    p.add_argument("--named-universes", help="JSON mapping estimator name to a list of {name, options, shared?}")
    p.add_argument("--shared-pooling", choices=("equal-setting", "equal-universe"), default="equal-setting")
    p.add_argument('--readings', help='JSON list of reading rows: language, speaker, text, sr, optional matched_sr')
    p.add_argument('--diagnostics', help='JSON inputs for diagnostic_tables (analysis-keyed u, context spans, changes, French pipeline documents)')
    p.add_argument('--language-families', help='JSON language-to-family mapping for the leave-one-family-out check')
    p.add_argument('--panel-method',choices=(A.PANEL_METHOD,'basic','percentile'),default=A.PANEL_METHOD)
    p.add_argument('--population-method',choices=(A.POPULATION_METHOD,'percentile','basic'),default=A.POPULATION_METHOD)
    p.add_argument('--panel-draws',type=int,default=1000)
    p.add_argument('--population-draws',type=int,default=2000)
    p.add_argument('--clusters',type=int,default=10)
    p.add_argument("--floor-gb", type=float, default=40)
    p.add_argument("--margin-gb", type=float, default=1)
    args = p.parse_args()
    named = json.loads(RUNNER.local(args.named_universes).read_text()) if args.named_universes else None
    groups = assemble(cached_records(args.cache, args.allow_incomplete), args.seed,
                      allow_incomplete=args.allow_incomplete, named_universes=named)
    intervals = None
    if args.readings:
        intervals=named_intervals(groups,json.loads(RUNNER.local(args.readings).read_text()),
            args.panel_draws,args.population_draws,args.seed,args.panel_method,args.population_method,args.clusters,
            language_families=json.loads(RUNNER.local(args.language_families).read_text()) if args.language_families else None)
    report = write_outputs(groups, args.out, args.seed, args.shared_pooling,
                           RUNNER.DiskGuard(int(args.floor_gb * RUNNER.GB), int(args.margin_gb * RUNNER.GB), work=RUNNER.local(args.out)),
                           interval_report=intervals,
                           diagnostics=json.loads(RUNNER.local(args.diagnostics).read_text()) if args.diagnostics else None)
    print(RUNNER.canonical(report))
    if report["stopped"]:
        raise SystemExit(2)

if __name__ == "__main__":
    main()
