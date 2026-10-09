# Context-window sensitivity of cross-linguistic information rate

Spec for a local replication-and-extension of Coupé, Oh, Dediu & Pellegrino (2019), *Science Advances* 5(9): eaaw2594.

[withheld: from private correspondence with the paper's authors]

## Purpose

Two questions:

1. **Does the density–rate compression survive as the conditioning context grows past the word boundary?** The paper's information density (ID) conditions each syllable only on the previous syllable *within the same word*. The "39 bits/s" figure is expected to move with context. The question is whether languages stay more similar in information rate (IR) than in syllable rate (SR) as context grows.
2. **Is the trade-off mostly syllable complexity?** If segments take roughly similar time across languages and carry roughly similar information, a density–rate trade-off at the syllable level follows without any information-rate regulation. Test whether ID predicts SR once segments per syllable is accounted for, and how much segment rate varies across languages.

The deliverable is a **curve** (compression as a function of context), not a single number.

## What the paper did (verified from the full text)

- 17 languages, 9 families: VIE, EUS, CAT, DEU, ENG, FRA, ITA, SPA, SRP, JPN, KOR, CMN, YUE, THA, TUR, FIN, HUN (ISO 639-3). Seven are Indo-European.
- 170 speakers read 15 short texts, translated from MULTEXT English originals (new translations for 14 languages).
- **SR** = syllables in the text's *canonical* transcription ÷ reading duration, with pauses over 150 ms excluded.
- **ID** = conditional entropy of syllables given the previous syllable, with a null marker word-initially and no bigrams across word boundaries. Probabilities are maximum-likelihood plug-in estimates from independent written corpora. The within-word restriction was forced because several corpora were word-frequency lists, not running text.
- **ShE** = unconditioned syllable entropy (unigram). The paper reports it but doesn't use it.
- **IR** = ID × SR for each reading.
- Syllables differing in tone or accent count as distinct types.
- Syllabification used a rule-based program by Y. M. Oh, except where corpora came pre-syllabified (ENG, FRA, DEU, VIE multisyllabic words) or went through a G2P converter (CAT, SPA, THA). For CMN and YUE each character was treated as a syllable. The main text doesn't say how word boundaries were fixed for CMN, YUE or THA; details are deferred to Oh's 2015 Lyon thesis.

## Data

- Repo: <https://github.com/keruiduo/SupplMatInfoRate>
- `InfoRateData.csv` is tab-separated with columns `Speaker, Language, Text, Sex, Duration, NS, ShE, ID, Age`.
  - It has 2288 rows, but the paper reports 2265 data points. Find out why before relying on row-level results.
  - `ID` and `ShE` are one value per language: these are the validation targets for Stage 4.
- Neither the syllabified corpora nor the texts' canonical transcriptions are in the repo.
  - **Ask the authors first** (Coupé or Pellegrino) for the 15 texts' canonical transcriptions per language, and the syllabified corpora or Oh's syllabifier.
  - With those, Stages 3–4 become an exact reproduction instead of an approximation.
  - *Note (2026-09-28):* the 15 texts themselves, in orthographic form for all 17 languages, are printed in the supplement (SM Text S3, `literature/coupe_etal_2019_comparable_information_rates_SM.md`). What only the authors can supply is the canonical transcriptions and syllable counts behind NS, the syllabified corpora or the syllabifier, and the source of the 2265 and −0.71.

## Stage 1: reproduce the reference numbers from the CSV

Expected values, computed by collapsing to speaker means and then language means:

| Quantity | Value |
|---|---|
| Pooled mean IR (bits/s) | 39.15 |
| Pooled mean ShE × SR (bits/s) | 56.71 |
| Pooled CV: SR / IR | 17.3% / 13.0% |
| CV of language means: SR | 13.9% |
| CV of language means: ShE × SR | 12.6% |
| CV of language means: ID × SR | 8.6% |
| CV of language means: semantic rate | 10.3% |
| r(SR, ID), 17 language means | −0.83 (p ≈ 4 × 10⁻⁵) |
| r(SR, ShE), 17 language means | −0.55 (p ≈ 0.02) |
| r(SR, SDIR), 17 language means | −0.83 |
| r(SR, ID), row level | −0.69 (paper: −0.71 on 2265 rows) |

[withheld: from private correspondence with the paper's authors]

The **semantic rate** is the Vietnamese syllable count for a text divided by the reading's duration: the same content per second. **SDIR** is the paper's syllabic density ratio against Vietnamese, averaged over texts.

```python
import pandas as pd
d = pd.read_csv("InfoRateData.csv", sep="\t")
d["SR"] = d.NS / d.Duration
d["IR"] = d.SR * d.ID
d["ShIR"] = d.SR * d.ShE
nsv = d[d.Language == "VIE"].groupby("Text").NS.first()
d["SemIR"] = d.Text.map(nsv) / d.Duration
sp = d.groupby(["Language", "Speaker"])[["SR", "IR", "ShIR", "SemIR"]].mean().reset_index()
lg = sp.groupby("Language")[["SR", "IR", "ShIR", "SemIR"]].mean()
cv = lambda x: x.std() / x.mean() * 100
```

## Stage 2: corpora

Requirements:
- **Running text, not frequency lists.** Cross-word context needs real sequences.
- **Same source type across all 17 languages.**
- **Document IDs retained**, so the held-out split can be made by document.

Candidates (check availability and licences, don't assume):
- OpenSubtitles via OPUS: closer to speech. This is the primary choice.
- Leipzig Corpora Collection (news or web): run as the secondary genre if feasible.
- Wikipedia dumps: fallback.

For corpus size, don't pick a number in advance. Run a learning curve: estimate each entropy on growing subsamples and require a plateau before accepting a language's estimate. Report the curves.

Normalization:
- Serbian: pick one script and transliterate the rest.
- Strip markup, subtitle timing lines and non-target-language lines.
- Log every filter in `DECISIONS.md`.

## Stage 3: transcription, syllabification, word segmentation

Record one config entry per language in `config/languages.yaml`: tool, version, settings, and a one-line rationale. Candidate tools to evaluate (verify coverage; don't assume they're adequate):

| Task | Candidates |
|---|---|
| G2P | espeak-ng, Epitran |
| Mandarin with tones | pypinyin |
| Cantonese (Jyutping) | PyCantonese |
| Other languages | Language-specific rule sets |
| Word segmentation (CMN, YUE, THA) | jieba or pkuseg (CMN), PyCantonese (YUE), PyThaiNLP (THA) |

Word segmentation for these three is a *major* forking path, because the word boundary defines the paper's ID.

Decisions to make explicitly and log before seeing results:
- **Japanese**: syllables, not morae (to match the paper). Decide how long vowels, the moraic nasal and geminates are grouped.
- **Korean**: syllabify the phonological form after resyllabification, not Hangul blocks.
- **French**: schwa and liaison handling. Match the canonical-pronunciation convention (full forms).
- **Tone and accent**: tone-distinct syllable types for CMN, YUE, THA and VIE. Decide whether Japanese pitch accent or lexical stress anywhere counts as "accent", as the paper says it did.

Validation of syllabification:
- Sample 100 random word tokens per language and check them against dictionary syllabifications where they exist.
- For languages nobody on the project reads, run a second independent method and report agreement.
- A language that fails is flagged and analysed with and without it.

**Unit consistency matters.** SR comes from the authors' canonical syllable counts; ID will come from this pipeline. If the two syllable definitions diverge for a language, IR mixes units. Check by syllabifying any available translation of the texts (or comparable sentences) with this pipeline and comparing against the NS column's per-text counts. Report the ratio per language.

## Stage 4: validate against the published values

Recompute ShE (unigram) and within-word bigram ID with **maximum-likelihood plug-in estimates**, matching the paper, and compare with the 17 published pairs.

Criteria, fixed before running:
- Spearman ρ ≥ 0.9 across languages for both ShE and ID.
- Per-language absolute differences reported.
- Any language off by more than 0.5 bits is flagged and examined.

Exact matches aren't expected, because plug-in estimates depend on corpus size and source. Rank order and spread are what matter.

**Don't go on to Stage 5 until Stage 4 passes or the failures are understood and logged.**

## Stage 5: the context ladder

Estimate information per syllable for each language at each rung:

| k | Context |
|---|---|
| 0 | None (unigram) |
| 1w | Previous syllable, within word (the paper's ID) |
| 1 | Previous syllable, across word boundaries |
| 2, 3, 4 | Syllable n-grams across word boundaries |
| LM | Small neural syllable-level LM (optional long-context end) |

Estimation:
- For k ≥ 1, use held-out **cross-entropy** from a smoothed model (modified Kneser–Ney n-grams; tool to choose and verify), trained and tested on a document-level split.
- Use the same test documents at every rung.
- For k = 0 and 1w, also report the plug-in estimates, for continuity with the paper.
- Cross-entropy is an upper bound on the true conditional entropy, so say that in the write-up.

## Stage 6: information rate at each rung

Compute IR_k = ID_k × SR for each reading, using SR from the CSV. For each k, report:

- Mean IR (bits/s). This is expected to fall as k grows.
- CV of language-mean IR, and the ratio R_k = CV(IR_k) / CV(SR), with a bootstrap interval that resamples **languages** (N = 17).
  - *Note (2026-10-09):* superseded: R_k is defined on SDs of logs, with v_k and r_k beside it (spec-review item 4, confirmed by Brett 2026-10-09), and two intervals are reported, one for these 17 languages and one for languages in general (`notes/multiverse-spec.md` §4–5).
- r(ID_k, SR) on the 17 language means, with its interval.
- A leave-one-family-out sensitivity check, since Indo-European has 7 of the 17 languages.

How the results will be read (stated in advance, not treated as significance tests):
- **Compression survives**: R_k stays clearly below 1 and doesn't drift towards 1 as k grows.
- **Compression is a within-word artefact**: R_k rises towards 1 once context crosses word boundaries.
- **In between**: report the curve and the per-language movements that drive it. Pay attention to whether isolating and tone languages (VIE, CMN, YUE, THA) lose more bits when context crosses words than the agglutinative ones (FIN, HUN, TUR, EUS) do.

## Stage 7: syllable complexity and segment rate

From the same pipeline, per language:

- Mean segments per syllable, token-weighted, with tone counted as an extra constituent as in Pellegrino et al. (2011).
- Estimated segment rate = SR × segments per syllable. The canonical transcriptions would allow per-reading segment counts; without them, this is a language-level approximation, and should be labelled as one.
- Segment-level information ladder: the same rungs as Stage 5, with phones as units.

Report:
- CV of language-mean segment rate, compared with the CV of SR.
- Whether ID_k adds predictive value for SR beyond segments per syllable, using leave-one-language-out prediction error.
- The segment-level version of R_k.

With N = 17 and the near-collinearity Pellegrino et al. (2011) found (ρ ≈ 0.98 with N = 7), the two predictors may simply not be separable. If so, say so; don't force a verdict.

## Stage 8: multilevel refit

Refit the rate–density relation properly: `SR ~ ID_k + Sex + (1 | Language) + (1 | Speaker) + (1 | Text)`, with ID_k as a language-level predictor and the language intercept kept. The paper dropped it; that's the pseudoreplication.

Use bambi/PyMC or brms. Report the posterior for the ID_k slope at each rung, and do posterior predictive checks.

## Outputs

- `results/ladder.csv`: one row per language × rung, with ID_k, mean IR, segments per syllable.
- `results/figs/compression_curve.pdf`: R_k against k with intervals, plus mean IR against k.
- `results/figs/language_shifts.pdf`: per-language ID_k across rungs, to show which languages move.
- `report.md`: a short write-up with methods, validation outcomes, the curve, and limitations.
- `DECISIONS.md`: a dated log of every analytic choice, flagging any made after seeing results.

## Layout

```
info-rate-context/
  SPEC.md
  DECISIONS.md
  config/languages.yaml
  data/raw/           # corpora (gitignored)
  data/interim/       # syllabified text (gitignored)
[withheld: from private correspondence with the paper's authors]
  src/
  results/
  report.md
```

## Limitations to state in the report

- SR comes from read speech of translated texts and canonical (not realized) syllable counts. This project doesn't touch SR.
- The sample is 17 Eurasian languages. The authors' 2024 follow-up on 36 DoReCo languages (Coupé, Oh, Dediu, Seifart & Pellegrino, SLE 2024 talk) is the natural next target if the curve is interesting.
- Genre effects: subtitles and news text may shift languages differently.
- Word segmentation for CMN, YUE and THA is itself an analytic choice that the within-word rung depends on.

## References

```bibtex
@article{coupe2019,
  author  = {Coup{\'e}, Christophe and Oh, Yoon Mi and Dediu, Dan and Pellegrino, Fran{\c c}ois},
  title   = {Different languages, similar encoding efficiency: Comparable information rates across the human communicative niche},
  journal = {Science Advances}, volume = {5}, number = {9}, pages = {eaaw2594}, year = {2019},
  doi     = {10.1126/sciadv.aaw2594}}
@article{pellegrino2011,
  author  = {Pellegrino, Fran{\c c}ois and Coup{\'e}, Christophe and Marsico, Egidio},
  title   = {A cross-language perspective on speech information rate},
  journal = {Language}, volume = {87}, number = {3}, pages = {539--558}, year = {2011}}
@inproceedings{pimentel2021,
  author    = {Pimentel, Tiago and Meister, Clara and Salesky, Elizabeth and Teufel, Simone and Blasi, Dami{\'a}n and Cotterell, Ryan},
  title     = {A surprisal--duration trade-off across and within the world's languages},
  booktitle = {Proceedings of the 2021 Conference on Empirical Methods in Natural Language Processing},
  pages     = {949--962}, year = {2021}, doi = {10.18653/v1/2021.emnlp-main.73}}
```

- Full text: <https://pmc.ncbi.nlm.nih.gov/articles/PMC6984970/>
- Pellegrino et al. (2011) PDF: <http://www.ddl.cnrs.fr/fulltext/pellegrino/Pellegrino_2011_Language.pdf>
- SLE 2024 slides: <https://yoonmioh.github.io/files/SLE57_slides.pdf>
