"""Stage 6: information rate across the context ladder (notes/multiverse-spec.md §4–6, SPEC.md Stage 6).

Inputs: readings (language, speaker, text, SR) and per-language information density ID_k for each rung.
Aggregation is speaker-first, as in Stage 1 and the authors' code: mean over a speaker's readings,
then mean over a language's speakers. ID is constant within a language, so language-mean IR is
ID_k times language-mean SR.

  R_k = SD_l(log mean IR_lk) / SD_l(log mean SR_l)      (sample SDs over languages; spec-review item 4)
  v_k = SD_l(log ID_lk) / SD_l(log mean SR_l)
  r_k = corr_l(log ID_lk, log mean SR_l)

so that R_k^2 = 1 + v_k^2 + 2 r_k v_k. The bootstrap resamples languages, with the same resample used
at every rung, so paired differences between rungs are taken within each resample.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage6_analysis_iterables", _BoundaryPath(__file__).resolve().parents[1] / "stage5/iterables.py")
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import hashlib
import json
import numpy as np
from scipy.stats import t

PANEL_METHOD = 'finite_cluster_t'
POPULATION_METHOD = 'paired_bootstrap_t'
CONTRASTS = (('4', '1w'), ('1', '1w'), ('4', '1'))

class PanelDrawError(ValueError):
    """Unsupported panel run, with counts retained for failure reports."""
    @_boundary
    def __init__(self, audit):
        self.audit = audit
        super().__init__(f"{audit['undefined_draws']}/{audit['requested_draws']} unavailable "
                         "paired panel draws exceeds 1%; finite paired support required")


@_boundary
def panel_draw_audit(samples):
    """Keep original draw positions; omit an incomplete row jointly, never redraw.

    NaNs mark unavailable readings. The denominator of the 1% rule is the
    requested count, including omitted draws; exactly 1% is supported.
    """
    samples = np.asarray(samples, float)
    if samples.ndim != 2 or len(samples) < 2:
        raise ValueError('at least two paired panel draws required')
    valid = np.isfinite(samples).all(axis=1)
    invalid = int((~valid).sum())
    audit = dict(requested_draws=len(samples), usable_draws=int(valid.sum()),
                 undefined_draws=invalid)
    if invalid > .01*len(samples):
        raise PanelDrawError(audit)
    return valid, audit

@_boundary(arrays=('lang', 'speaker', 'sr'))
def language_means(lang, speaker, sr):
    """Speaker-first mean SR per language. Arrays of equal length; returns (languages, means)."""
    lang, speaker, sr = np.asarray(lang), np.asarray(speaker), np.asarray(sr, float)
    key = np.char.add(np.char.add(lang.astype(str), "\x1f"), speaker.astype(str))
    sk, inv = np.unique(key, return_inverse=True)
    sp_mean = np.bincount(inv, weights=sr) / np.bincount(inv)
    sp_lang = np.array([k.split("\x1f")[0] for k in sk])
    langs, linv = np.unique(sp_lang, return_inverse=True)
    lmean = np.bincount(linv, weights=sp_mean) / np.bincount(linv)
    return langs, lmean

@_boundary(arrays=('log_id', 'log_sr'))
def ladder(log_id, log_sr):
    """log_id: array (L, K) of log ID per language and rung; log_sr: (L,). Returns R, v, r, each (K,)."""
    log_id = np.atleast_2d(log_id)
    s_sr = np.std(log_sr, ddof=1)
    log_ir = log_id + log_sr[:, None]
    R = np.std(log_ir, axis=0, ddof=1) / s_sr
    R = np.where(np.ptp(log_id,axis=0)==0,1.,R)
    v = np.std(log_id, axis=0, ddof=1) / s_sr
    a = log_id - log_id.mean(0); b = (log_sr - log_sr.mean())[:, None]
    denominator = np.sqrt((a * a).sum(0) * (b * b).sum(0))
    r = np.divide((a*b).sum(0),denominator,out=np.full_like(R,np.nan),where=denominator>0)
    return R, v, r

@_boundary(arrays=('log_id', 'log_sr'))
def bootstrap(log_id, log_sr, n_boot=2000, seed=0):
    """Resample languages (same resample at every rung). Returns R_boot of shape (n_boot, K)."""
    rng = np.random.default_rng(seed)
    L = len(log_sr)
    idx = rng.integers(0, L, size=(n_boot, L))
    ids = log_id[idx]                     # (B, L, K)
    srs = log_sr[idx]                     # (B, L)
    s_sr = np.std(srs, axis=1, ddof=1)
    log_ir = ids + srs[:, :, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.std(log_ir, axis=1, ddof=1) / s_sr[:, None]

@_boundary
def interval(samples, level=0.90):
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    return np.nanquantile(samples, lo, axis=0), np.nanquantile(samples, hi, axis=0)

@_boundary
def panel_means(lang, speaker, text, sr, langs, n_boot=1000, seed=0, include_audit=False):
    """Uncertainty for these languages as given: languages fixed; speakers resampled within each
    language and texts resampled jointly across languages (they are translations of one another).
    Each language's readings form a speaker x text matrix (NaN where a reading is missing); a
    speaker's mean is over the drawn texts it has, and a speaker with none of them is skipped.
    A draw with no available readings in ANY language is marked NaN jointly
    across languages and counted. More than 1% unavailable draws stops.
    Omitted speakers with no selected readings retain the existing ignorable
    missingness assumption. Returns (B,L) speaker-first arithmetic means.
    """
    rng = np.random.default_rng(seed)
    lang, speaker, text, sr = map(np.asarray, (lang, speaker, text, sr))
    if (n_boot < 2 or not len(sr) or any(a.shape != sr.shape for a in (lang, speaker, text))
            or not np.isfinite(sr).all() or np.any(sr <= 0)
            or set(map(str, langs)) != set(map(str, lang))
            or len(set(zip(lang, speaker, text))) != len(sr)):
        raise ValueError('invalid reading panel, languages or bootstrap count')
    texts = np.unique(text); T = len(texts)
    tdraw = rng.integers(0, T, size=(n_boot, T))                     # shared across languages
    msr = np.empty((n_boot, len(langs)))
    for j, l in enumerate(langs):
        sel = lang == l
        spk_u, si = np.unique(speaker[sel], return_inverse=True)
        ti = np.searchsorted(texts, text[sel])
        M = np.full((len(spk_u), T), np.nan)
        M[si, ti] = sr[sel]
        sdraw = rng.integers(0, len(spk_u), size=(n_boot, len(spk_u)))
        sub = M[sdraw[:, :, None], tdraw[:, None, :]]                 # (B, S, T)
        with np.errstate(invalid="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)
            msr[:, j] = np.nanmean(np.nanmean(sub, axis=2), axis=1)
    valid, audit = panel_draw_audit(msr)
    msr[~valid] = np.nan
    return (msr, audit) if include_audit else msr


@_boundary
def panel_bootstrap(lang, speaker, text, sr, log_id_by_lang, langs, n_boot=1000, seed=0,
                    document_samples=None, include_audit=False):
    """Fixed-language crossed reading draws, optionally with paired held-out ID draws.

    document_samples is a (B,L,K) density array in bits/target, from document
    loss sums divided by counts. Training/validation, seeds and settings stay
    fixed; training plug-in columns are fixed by resample_document_scores.
    """
    msr = panel_means(lang, speaker, text, sr, langs, n_boot, seed)
    log_sr = np.log(msr)                                               # (B, L)
    if document_samples is None:
        ids = np.asarray(log_id_by_lang, float)[None, :, :]
    else:
        densities = np.asarray(document_samples, float)
        if densities.shape != (n_boot, len(langs), np.shape(log_id_by_lang)[1]):
            raise ValueError('document samples must be B by L by K')
        if not np.isfinite(densities).all() or np.any(densities <= 0):
            raise ValueError('panel document draw leaves a language unavailable')
        ids = np.log(densities)
    s_sr = np.std(log_sr, axis=1, ddof=1)
    valid, audit = panel_draw_audit(msr)
    if np.any(s_sr[valid] <= 0) or not np.isfinite(ids).all():
        raise ValueError('undefined panel statistic')
    log_ir = ids + log_sr[:, :, None]
    result = np.std(log_ir, axis=1, ddof=1) / s_sr[:, None]
    result = np.where(np.ptp(ids,axis=1)==0,1.,result)
    # Structural constants must not turn unavailable draws into usable ones.
    result[~valid] = np.nan
    if not np.isfinite(result[valid]).all():
        raise ValueError('undefined panel statistic')
    return (result, audit) if include_audit else result

@_boundary(arrays=('estimate', 'samples'))
def basic_interval(estimate, samples, level=0.90):
    """Basic (bias-reflecting) bootstrap interval: [2*est - q_hi, 2*est - q_lo]."""
    lo, hi = interval(samples, level)
    return 2 * estimate - hi, 2 * estimate - lo


@_boundary
def paired_values(values, rungs):
    """Append the three §4a contrasts, computed within every shared draw."""
    values = np.asarray(values)
    if len(set(rungs)) != len(rungs) or values.shape[-1] != len(rungs):
        raise ValueError('unique rungs must match the last array dimension')
    columns = [values]
    names = ['R_' + rung for rung in rungs]
    for last, first in CONTRASTS:
        if last in rungs and first in rungs:
            columns.append((values[..., rungs.index(last)] - values[..., rungs.index(first)])[..., None])
            names.append(f'R_{last}-R_{first}')
    return np.concatenate(columns, axis=-1), names


@_boundary
def panel_interval(estimate, samples, level=.90, clusters=10, method=PANEL_METHOD,
                   include_audit=False):
    """§4b's bias-reflected centre and finite-cluster t half-width (C=10)."""
    estimate, samples = np.asarray(estimate, float), np.asarray(samples, float)
    if (samples.ndim != 2 or len(samples) < 2 or samples.shape[1:] != estimate.shape
            or not np.isfinite(estimate).all()):
        raise ValueError('finite, complete paired panel statistics required')
    valid, audit = panel_draw_audit(samples)
    samples = samples[valid]
    if not 0 < level < 1 or type(clusters) is not int or clusters < 2:
        raise ValueError('invalid level or cluster count')
    if method == 'basic':
        endpoints = basic_interval(estimate, samples, level)
    elif method == 'percentile':
        endpoints = interval(samples, level)
    elif method == PANEL_METHOD:
        centre = 2*estimate - samples.mean(axis=0)
        half = t.ppf((1+level)/2, clusters-1) * np.sqrt(clusters/(clusters-1)) * samples.std(axis=0, ddof=1)
        endpoints = (centre-half, centre+half)
    else:
        raise ValueError('unknown panel interval method')
    return (*endpoints, audit) if include_audit else endpoints


@_boundary
def language_statistics(ids, sr, rungs):
    """R and delta-method SEs, including paired differences of influences.

    Supports a leading bootstrap dimension. Sample/population variance factors
    cancel in R; the influence SE uses sample variance and sqrt(L).
    """
    ids, sr = np.asarray(ids, float), np.asarray(sr, float)
    if ids.shape[:-1] != sr.shape or len(rungs) != ids.shape[-1] or sr.shape[-1] < 3:
        raise ValueError('need matching language arrays and at least three languages')
    x = sr - sr.mean(axis=-1, keepdims=True)
    y = ids + sr[..., None]
    y = y - y.mean(axis=-2, keepdims=True)
    vx, vy = np.mean(x*x, axis=-1), np.mean(y*y, axis=-2)
    with np.errstate(divide='ignore', invalid='ignore'):
        r = np.sqrt(vy/vx[..., None])
        influence = r[..., None, :]/2 * (y*y/vy[..., None, :] - (x*x/vx[..., None])[..., None])
    constant_ids = np.ptp(ids,axis=-2)==0
    r = np.where(constant_ids & (vx[...,None]>0),1.,r)
    influence = np.where(constant_ids[...,None,:] & (vx[...,None,None]>0),0.,influence)
    values, _ = paired_values(r, rungs)
    influences, _ = paired_values(influence, rungs)
    return values, influences.std(axis=-2, ddof=1)/np.sqrt(sr.shape[-1])


@_boundary(arrays=('log_id', 'log_sr', 'draw'))
def population_components(log_id, log_sr, rungs, draw):
    """Unfiltered paired statistics and a validity mask on original draw indices."""
    point, se = language_statistics(log_id, log_sr, rungs)
    if not np.isfinite(point).all() or not np.isfinite(se).all():
        raise ValueError('undefined original population statistic or standard error')
    values, ses = language_statistics(log_id[draw], log_sr[draw], rungs)
    constant = se <= 1e-14
    supported = (ses > 1e-14) | (constant[None, :] & np.isclose(values, point, rtol=0, atol=1e-12))
    valid = np.isfinite(values).all(1) & np.isfinite(ses).all(1) & supported.all(1)
    return point, se, values, ses, constant, valid


@_boundary
def population_interval(log_id, log_sr, rungs, n_boot=2000, seed=0, level=.90,
                        method=POPULATION_METHOD, *, paired_log_ids=()):
    """Paired language bootstrap-t, with the influence SE recomputed per draw.

    Undefined draws are omitted JOINTLY and counted. More than 1% stops.
    paired_log_ids applies the same validity mask across additional rate reports.
    Deterministic quantities (e.g. identical rung contrasts) have point intervals;
    a zero SE with a different resampled estimate is undefined, not deterministic.
    """
    if n_boot < 2 or not 0 < level < 1 or method not in (POPULATION_METHOD, 'percentile', 'basic'):
        raise ValueError('invalid population method, count or level')
    log_id, log_sr = np.asarray(log_id, float), np.asarray(log_sr, float)
    if not np.isfinite(log_id).all() or not np.isfinite(log_sr).all():
        raise ValueError('finite language data required')
    draw = np.random.default_rng(seed).integers(0, len(log_sr), (n_boot, len(log_sr)))
    point, se, values, ses, constant, valid = population_components(log_id, log_sr, rungs, draw)
    for paired in paired_log_ids:
        paired = np.asarray(paired, float)
        if paired.shape != log_id.shape or not np.isfinite(paired).all():
            raise ValueError('paired population densities must have the same finite shape')
        valid &= population_components(paired, log_sr, rungs, draw)[-1]
    invalid = int((~valid).sum())
    if invalid > .01*n_boot:
        raise ValueError(f'{invalid}/{n_boot} undefined paired population draws exceeds 1%')
    values, ses = values[valid], ses[valid]
    if len(values) < 2:
        raise ValueError('fewer than two supported population draws')
    if method == 'percentile':
        lo, hi = interval(values, level)
    elif method == 'basic':
        lo, hi = basic_interval(point, values, level)
    else:
        student = np.divide(values-point, ses, out=np.zeros_like(values), where=ses > 1e-14)
        qlo, qhi = interval(student, level)
        lo, hi = point-qhi*se, point-qlo*se
        lo[constant] = point[constant]; hi[constant] = point[constant]
    return dict(method=method, estimate=point, se=se, lo=lo, hi=hi, level=level,
                requested_draws=n_boot, usable_draws=len(values), undefined_draws=invalid,
                quantities=paired_values(point[:len(rungs)], rungs)[1],
                target='latent language-level population',
                condition='Conditional on these languages being exchangeable draws; no SR measurement-error correction.',
                pointwise=True, approximate=True)


@_boundary
def resample_document_scores(records, n_boot=1000, seed=0, include_draws=False):
    """Document bootstrap shared by every rung/estimator/option on those sources.

    Scores contain documents=[{document, loss_sum_bits, n_tokens}], plus an
    explicit density_source. document_alignment={group, source_units:{id:unit}}
    pairs translations across languages; absent alignment, languages are independent.
    Draw seeds depend on source units, not record order, estimator or option.
    Work is blocked to avoid a B*D*K array for large document collections.
    """
    if not records or n_boot < 2:
        raise ValueError('records and at least two document draws required')
    groups, prepared, keys, source_hashes = {}, [], set(), {}
    for record in records:
        key = record.get('sampling_key',record['job_id'])
        if key in keys:
            raise ValueError('duplicate document score key')
        keys.add(key)
        meta = record.get('metadata', record.get('identity', {}))
        declared = meta['documents']['test']
        if not declared or len(set(declared)) != len(declared):
            raise ValueError('declare unique test document IDs')
        alignment = meta.get('document_alignment')
        if alignment is None:
            units = {d:d for d in declared}
            namespace = ['language', meta['language'], None]
        else:
            if not isinstance(alignment.get('group'), str) or not alignment['group']:
                raise ValueError('declare a nonempty document alignment group')
            units = alignment['source_units']
            if (set(units) != set(declared) or any(not isinstance(v,str) or not v for v in units.values())
                    or len(set(units.values())) != len(units)):
                raise ValueError('alignment must map every document to a distinct source unit')
            namespace = ['aligned', alignment['group']]
        ordered = sorted(units, key=units.get)
        group = json.dumps([namespace, [units[d] for d in ordered]], sort_keys=True)
        source=meta.get('source_hashes',{}).get('test')
        if alignment is None and source is not None:
            source=json.dumps(source,sort_keys=True)
            if group in source_hashes and source_hashes[group]!=source:
                raise ValueError('shared document IDs have conflicting source identities')
            source_hashes[group]=source
        # An aligned namespace must have exactly the same source-unit support.
        if alignment and any(g[0] == namespace and g[1] != [units[d] for d in ordered] for g in groups.values()):
            raise ValueError('aligned languages have different document support')
        groups[group] = (namespace, [units[d] for d in ordered])
        losses, counts, fixed = [], [], []
        for rung, score in record['scores'].items():
            rows = score.get('documents')
            if (not isinstance(rows,tuple) or len(rows) != len(declared)
                    or {r['document'] for r in rows} != set(declared)):
                raise ValueError('complete per-document scores required at every rung')
            lookup = {r['document']:r for r in rows}
            loss = np.array([lookup[d]['loss_sum_bits'] for d in ordered], float)
            count = [lookup[d]['n_tokens'] for d in ordered]
            if (not np.isfinite(loss).all() or np.any(loss < 0)
                    or any(type(n) is not int or n < 0 for n in count)
                    or any(n == 0 and value != 0 for n,value in zip(count,loss))
                    or sum(count) != score['n_test'] or sum(count) <= 0):
                raise ValueError('invalid or incomplete document loss/count')
            source = score.get('density_source')
            if source not in ('heldout_model','training_plugin'):
                raise ValueError('declare heldout_model or training_plugin density_source')
            if source == 'heldout_model' and not np.isclose(loss.sum()/sum(count),score['id_bits'],rtol=2e-6,atol=1e-7):
                raise ValueError('document totals disagree with aggregate score')
            losses.append(loss); counts.append(count)
            fixed.append(score['id_bits'] if source == 'training_plugin' else np.nan)
        prepared.append((key, group, np.array(losses).T, np.array(counts).T, np.array(fixed)))
    output = {key:np.empty((n_boot,len(fixed))) for key,_,_,_,fixed in prepared}
    audit = dict(requested_draws=n_boot, languages_fixed=True, training_fixed=True, groups=[])
    for group, (namespace, units) in sorted(groups.items()):
        draw_seed = int(hashlib.sha256(json.dumps([seed,group]).encode()).hexdigest()[:16],16)
        rng = np.random.default_rng(draw_seed)
        own = [row for row in prepared if row[1] == group]
        description = dict(namespace=namespace, source_units=units, seed=draw_seed,
                           members=[row[0] for row in own], draws=[] if include_draws else None)
        digest = hashlib.sha256()
        for start in range(0,n_boot,64):
            end = min(start+64,n_boot)
            indices = rng.integers(0,len(units),(end-start,len(units)))
            digest.update(indices.astype('<i8').tobytes())
            if include_draws:
                description['draws'].extend(indices.tolist())
            weights = np.zeros((end-start,len(units)),dtype=int)
            np.add.at(weights,(np.arange(end-start)[:,None],indices),1)
            for key,_,loss,count,fixed in own:
                den = weights @ count
                if np.any(den == 0):
                    raise ValueError('panel document draw leaves a language unavailable')
                values = (weights @ loss) / den
                is_fixed = np.isfinite(fixed)
                values[:,is_fixed] = fixed[is_fixed]
                if not np.isfinite(values).all() or np.any(values <= 0):
                    raise ValueError('panel document density unavailable')
                output[key][start:end] = values
        description['draw_sha256'] = digest.hexdigest()
        audit['groups'].append(description)
    return output, audit
