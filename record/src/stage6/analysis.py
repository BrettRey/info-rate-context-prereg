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
import numpy as np

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

def ladder(log_id, log_sr):
    """log_id: array (L, K) of log ID per language and rung; log_sr: (L,). Returns R, v, r, each (K,)."""
    log_id = np.atleast_2d(log_id)
    s_sr = np.std(log_sr, ddof=1)
    log_ir = log_id + log_sr[:, None]
    R = np.std(log_ir, axis=0, ddof=1) / s_sr
    v = np.std(log_id, axis=0, ddof=1) / s_sr
    a = log_id - log_id.mean(0); b = (log_sr - log_sr.mean())[:, None]
    r = (a * b).sum(0) / np.sqrt((a * a).sum(0) * (b * b).sum(0))
    return R, v, r

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

def interval(samples, level=0.90):
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    return np.nanquantile(samples, lo, axis=0), np.nanquantile(samples, hi, axis=0)

def panel_bootstrap(lang, speaker, text, sr, log_id_by_lang, langs, n_boot=2000, seed=0):
    """Uncertainty for these languages as given: languages fixed; speakers resampled within each
    language and texts resampled jointly across languages (they are translations of one another).
    Each language's readings form a speaker x text matrix (NaN where a reading is missing); a
    speaker's mean is over the drawn texts it has, and a speaker with none of them is skipped.
    log_id_by_lang: (L, K) aligned with `langs`. Returns R_boot of shape (n_boot, K). ID is held
    fixed here; for real data the corpus documents behind ID are resampled as well."""
    rng = np.random.default_rng(seed)
    lang, speaker, text, sr = map(np.asarray, (lang, speaker, text, sr))
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
    log_sr = np.log(msr)                                               # (B, L)
    s_sr = np.std(log_sr, axis=1, ddof=1)
    log_ir = log_id_by_lang[None, :, :] + log_sr[:, :, None]
    return np.std(log_ir, axis=1, ddof=1) / s_sr[:, None]

def basic_interval(estimate, samples, level=0.90):
    """Basic (bias-reflecting) bootstrap interval: [2*est - q_hi, 2*est - q_lo]."""
    lo, hi = interval(samples, level)
    return 2 * estimate - hi, 2 * estimate - lo
