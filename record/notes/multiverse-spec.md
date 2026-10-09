# Multiverse specification for Stages 3–6
<!-- SUMMARY: replaces selection-by-NS with a multiverse over every approved fork; lists the dimensions, how the universes are computed and what is reported; approved in principle by Brett, its eight open choices decided by him; cost estimated from the timing benchmark; awaiting the remaining dictionary checks and F1–F4 before his final read · status: proposal · updated: 2026-10-09 -->

Drafted 2026-10-09 by Claude (Claude Code) for Brett, who approved a multiverse design in principle ("can we just do a multiverse?", then "yes"). Not in force until he has read it, it is logged in `DECISIONS.md`, and it is in a timestamped snapshot. It replaces the selection rule in `notes/stage3-proposal-units-jpn-tha.md` §1–2 (convention chosen by the median ratio to NS, ties within 0.01, one sensitivity row for the runner-up) and supersedes the unlogged B+ draft in `notes/stage3-amendment-selection-rule.md`. Choices Brett hasn't seen are listed at the end.

Timing: no pipeline has produced a syllable count for any read text in any language, no ratio to NS exists, and no syllable entropy of any corpus has been computed. The read texts have been touched only by two spelling scans (SRP *ije*, CMN 儿).

## 1. The idea

Every reasonable combination of the analysis forks is a universe. Each universe gets the full headline curve (R<sub>k</sub> at every rung). The headline is reported as the spread of results across universes, with the forks that drive the spread identified. Nothing is chosen by matching NS: how well each universe's syllable counts match NS is reported as a lens on the results, not used to select one. A multiverse doesn't measure total uncertainty, and its spread is not a probability: it shows how much the answer depends on choices that could defensibly have gone either way (Gelman et al. 2020, *Bayesian workflow*, warn that a set of fitted models can seem to "bracket some total uncertainty").

## 2. Dimensions

### 2.1 Shared across languages

| Fork | Options | Source |
|---|---|---|
| Line treatment | cross-line; line-bounded | `DECISIONS.md` 2026-10-08 (run both, report both) |
| Training budget | B; B/2; 3B for the languages that reach it, with B recomputed on that subset | 2026-10-08, training-budget plan |
| Run | main (16 subtitle languages, YUE from Wikipedia); Wikipedia (all 17) | 2026-10-08, Cantonese option B |
| Language set | with YUE; without YUE (same B) | 2026-10-08 |
| Wikipedia stub threshold | 0.5; 0.3 (wherever Wikipedia text is used) | 2026-10-08, stub rule |
| Wikipedia gap treatment | split at gaps; drop sentences with gaps (YUE in the main run included, replacing "drop as main, split as a sensitivity row") | 2026-10-08, gap treatment and option C |
| Thai Wikipedia prose line | ≥ 80 Thai characters; ≥ 150; and whole paragraphs as the line-bounded unit | 2026-10-08 and 2026-10-09, option B |

The rungs (k = 0, 1w, 1, 1b-free, 1b-charged, 2, 3, 4) are the curve's axis, computed in every universe, not a fork.

### 2.2 Per language

- **Grouping convention:** the candidates in `notes/stage3-candidate-conventions.md`, as revised with the approved changes (§7), and JPN G1/G2.
- **Pronunciation source:** the main tool, and a published dictionary where one exists and its terms allow it (§8), with the tool for words the dictionary lacks.
- **Stress or accent labels:** marked and unmarked, for every language whose pronunciation source marks lexical stress or accent. The list is fixed with the counters. Tone stays part of the syllable in CMN, YUE, THA and VIE in every universe.
- **Word segmenter** (word-aware rungs only): CMN jieba or pkuseg; YUE PyCantonese or cantoseg; THA newmm or attacut; VIE underthesea or pyvi; JPN the reader's own tokens.
- **Reader or G2P where two were planned as independent routes:** JPN pyopenjtalk or fugashi with UniDic; THA thaig2p or TLTK.

### 2.3 Fixed in every universe

Stage 2 sampling, normalisation and filters; the primary-text definition; tone in the tonal languages; the estimator (modified Kneser–Ney held-out cross-entropy with KenLM, built at commit 4cb443e, approved by Brett 2026-10-09 on condition of a fake-data check: on simulated text from a process with known entropy, KenLM must recover that entropy at each order before any syllable estimate), its orders and its document-level split; the same test documents at every rung.

### 2.4 What counts as reasonable

An option enters if it was approved as a fork, or if a cited source attests it (a candidate convention) or publishes it (a dictionary). Declared exception: FIN-C (three exact word forms, *pian*, *tae*, *teos*) is reported for calibration and affected share only, since it changes three word types; its class version C′ is a full option.

## 3. Computing it

- **The expensive unit** is one estimate: a language under one combination of its own options and the shared settings, giving the whole rung ladder. Universes across languages are assembled from stored estimates by arithmetic.
- **Same text across options.** Within a language, every option is trained and tested on the same source documents, chosen once at budget B (in syllable tokens under the first-listed options). An option that merges syllables sees the same text in fewer tokens; the token count is reported. This keeps the unit's effect apart from the effect of more or less text.
- **Cross-language universes.** For each shared setting, all per-language combinations are enumerated if there are at most 10<sup>6</sup>; otherwise 10<sup>5</sup> are drawn uniformly with a fixed seed. Uniform drawing is a way of summarising the space, not a probability for any universe.
- **Disk.** Only the scores are kept: each model is deleted as soon as its test set is scored, and KenLM's temporary files go to one scratch directory that is emptied after each estimate. Before each estimate the runner checks free space and stops if the estimate's measured peak would take the drive below the 40 GB floor (`DECISIONS.md`, disk budget). The benchmark records peak disk use beside time.
- **Cost** (timing benchmark on synthetic tokens, `results/benchmark/`). One estimate (orders 1 to 5 plus the three extra bigram models of rungs 1w, 1b-free and 1b-charged) took 1–2 minutes at 10M training tokens and 2–3.5 minutes at 30M, with peak memory of 2–4 GB and model files up to 2.3 GB before deletion. With roughly 60–70 per-language option combinations (counting the dictionaries still to be confirmed) and about 30 shared settings (main run: line treatment × three budgets; Wikipedia run: those × stub threshold × gap treatment), the full crossing is about 2,000 estimates, 50–80 hours of single-job computing. The disk floor, not time, limits parallelism: at about 2 GB peak per job, two jobs at once keep the drive above 40 GB, so roughly 1.5–3 days of wall time locally. Assumptions: B is about 10M syllable tokens (the real B comes from counting corpus syllables, which needs no entropy), and syllable inventories of 2,000–10,000 types; both are rechecked once the counters exist, and F1 runs at the real sizes. Syllabification itself is done once per word type and pronunciation source and cached, so it adds little. If the benchmark shows the full crossing won't fit on the laptop (in time, or under the 40 GB disk floor), it runs on Modal, after OpenSubtitles' terms are checked for processing on a cloud machine (Brett, 2026-10-09). Only if that fails is it reduced, in this order, declared now so that nothing is cut after seeing a result: (1) B/2 and 3B run only at the first-listed per-language options; (2) the Wikipedia run crosses its own forks with the first-listed per-language options only; (3) stress labels cross only with the first-listed convention and source.

## 3a. Fake-data checks before any real estimate

Brett, 2026-10-09: fake data before running. Following *Bayesian workflow* §4.1 (Gelman et al. 2020: "check whether our procedure recovers the correct parameter values when fitting fake data", with fake data "of the same size, shape, and structure as the original data", looking at "point estimates and also the coverage" of intervals), the whole pipeline runs on simulated data with known answers before any syllable entropy of a real corpus or any ratio to NS is computed. Four checks:

- **F1, the estimator.** Token streams from processes whose conditional entropy at each order is known (Markov chains of order 1 to 3 and independent draws, with inventories of about 600, 2,000 and 10,000 types, Zipf-like frequencies), at budgets B/2, B and 3B. KenLM at each order; reported: held-out cross-entropy minus the true conditional entropy, by order, inventory and budget, and how the plateau check behaves. The same with simulated word boundaries of known entropy, to check rungs 1, 1b-free and 1b-charged and the quantities H(S), H(S | B), H(S, B) and I(S; B) built from them.
- **F1b, short lines** (side agent, 2026-10-09). F1 with lines of 15 tokens and contexts stopping at each line, for the line-bounded mode; the true value is the mean over line positions of the entropy at the context actually available, and the bias includes the cost of the probability given to the end of each line.
- **F1 version 2** (after Sol's estimator review, 2026-10-09; declared before it runs). Processes: independent Zipf draws and lag-m copy processes (m = 1–4); inventories of 600, 2,000 and 10,000 types; training budgets of 5M, 10M and 30M tokens; three seeds per cell; a fixed test set of 1M tokens; lines of 1,000 tokens, and of 15 tokens at 10M only. The reference is the entropy at the context actually available (the mean over line positions of H<sub>min(k, j)</sub>). Recorded per model: the discounts KenLM used at every order and whether each fell back, from its own log. In short lines, each syllable's probability is also scored after leaving out the probability of the end of the line (normalised over syllable outcomes), beside the raw score. Added: plug-in entropy at k = 0 and 1, computed on the training sample, against the truth (the direction Dunning's rare-event warning points); and a fallback ablation at 2,000 types and 10M tokens, three settings of the fallback discounts, chosen by loss on separate validation text. Declared tolerance: at k ≤ 1 for the independent and lag-1 processes, the held-out estimate is within 0.05 bits of the reference at every budget, and the unigram within 0.01; failing that, the scorer or the setup is wrong and is fixed before anything else. Every other cell describes the estimator's bias rather than passing or failing, and F3 propagates it into R<sub>k</sub>. The word-boundary rungs (1w, 1b-free, 1b-charged) are checked when their encoding is built (F1c), not here.
- **F2, conventions.** A fine-unit process with known entropy, regrouped losslessly (pairs, as in Sol's counterexample) and lossily (merging chosen adjacent pairs, deleting a class of units, as the real conventions do); estimated at the same k and at matched spans. Reported: how far the matched-count correction is from cancellation in cases where the true answer is known, which sets how the matched-count rate (§6) is read.
- **F3, the whole analysis.** Seventeen fake languages built in the shape of the real data (speakers, texts, durations as in the CSV, all simulated), with known ID<sub>k</sub> curves and syllable rates under two scenarios: compression that survives as k grows, and compression that disappears once context crosses word boundaries. The full Stage 6 code runs on them (R<sub>k</sub> on SDs of logs, v<sub>k</sub>, r<sub>k</sub>, the language bootstrap, paired differences, the matched-count rate, and multiverse assembly with fake per-language options). Reported: whether each scenario is recovered, and over repeated simulations how often the bootstrap interval covers the true R<sub>k</sub>.
- **F3 in detail** (Sol's design, approved by Brett 2026-10-09; drafted for his read before it runs). A fake panel in the shape of the real data: 17 languages, 10 speakers and 15 texts each, with the CSV's pattern of missing readings (2,288 of 2,550), and syllable rates built as log SR = language effect + speaker effect + text effect + noise. True information density per language and rung under three scenarios: **S0**, no trade-off at any k (r<sub>k</sub> = 0); **S1**, a trade-off that holds at every k (r<sub>k</sub> = −0.8); **S2**, a trade-off within words that disappears once context crosses word boundaries (r<sub>k</sub> from −0.8 at 1w to 0 at k ≥ 1). S0 and S1 are the controls in which the true R<sub>k</sub> doesn't change with k.
  - **F3a, oracle entropies.** The Stage 6 code runs on the true densities: speaker-first aggregation, R<sub>k</sub> on SDs of logs, v<sub>k</sub>, r<sub>k</sub>, the bootstrap over languages, paired rung differences. Two experiments, since they answer different questions: the panel fixed and only speakers, texts and noise redrawn (500 replicates), and the panel itself redrawn from a declared population of languages each time (500 replicates), which is what the language bootstrap's interval claims to cover.
  - **F3b, fitted entropies.** Each fake language's density is estimated by KenLM, at budget B, from simulated text whose entropy at each order is known, with inventories of 600 to 10,000 types assigned three ways: independently of syllable rate, larger inventories with slower rates, and the reverse. Two families of fake text (Brett, 2026-10-09): **local**, where dependence runs between adjacent syllables, at varying strengths (the main family for reading F3b, closer to phonotactics); and **skipped**, F1's processes in which a token depends on one several places back (a stress test, reported as such).
  - **No pass/fail bar** (Brett, 2026-10-09, after asking what Gelman would do). Thresholds declared in advance protect decisions taken after seeing real results; F3 is fake data, and looking at fake results and changing the design is what the workflow's fake-data step is for (Gelman et al. 2020, §4.1: if a check fails, "we recommend breaking down the model"), provided every such change is made and logged before any real estimate. F3a's code is checked by its zero-noise test (exact recovery); its bias and coverage are reported with their Monte Carlo error, and anything off is treated as a bug to find. F3b reports how far the estimator moves R<sub>k</sub> and R<sub>4</sub> − R<sub>1w</sub>, as plots of estimated against true, and in units of the contrast the research question turns on (the gap between S1 and S2 at k ≥ 1); the second estimator is then decided as a matter of design and cost, still before any real estimate, and if added it enters the multiverse as an estimator fork. F3b's distortions are reported beside the real results, not subtracted from them.
- **F4, plumbing.** The same seed gives the same output; an interrupted run resumes; models are deleted after scoring; the runner stops before the disk floor (tested with a simulated low free-space reading).

No real syllable estimate and no ratio to NS until F1–F4 have run and Brett has seen the results. Anything fixed because of them is logged.

## 4. What is reported

For every universe: R<sub>k</sub> at each rung, v<sub>k</sub> and r<sub>k</sub> beside it, with information rate computed both as the paper does (ID<sub>k</sub> × SR) and as a matched-count rate (§6).

Across universes:
- the distribution of R<sub>k</sub> at each rung, and of paired changes between rungs (R<sub>k</sub> − R<sub>1w</sub> within each universe), with the share of universes in which R rises from 1w to 4, reported as a description of the multiverse, not a measure of how strong the evidence is. Because a share depends on how many options each fork lists (side agent, 2026-10-09: Finnish lists three variants beside the traditional reading), it is never reported alone: it comes broken down by each option of each fork, and also with near-duplicate options grouped into families that count once. The families are declared now: for each language's conventions, the source's own reading (A) is one family and the variants derived from the same ambiguity are another (FIN B, C′, D; ITA B, C; EUS B, C); a dictionary and the tool are two families; marked and unmarked labels are two. Within a family the options share its weight equally;
- which forks drive the spread: the share of variation in R<sub>k</sub> attributable to each fork and to its interaction with k;
- a specification curve: universes ordered by R<sub>4</sub>, with each one's options shown beneath.

Two intervals are reported for every named universe, labelled by what they are about (Brett, 2026-10-09: "why wouldn't we report both?"): **for these 17 languages**, a bias-reflecting (basic) bootstrap over speakers within each language and texts jointly across languages, and for real data the corpus documents behind each language's ID; and **for languages in general**, the bootstrap over languages, which treats the 17 as if sampled from a population and so carries that caveat, with a leave-one-family-out check beside it. F3a measured both on fake data: the panel interval covers 84–88% of the time for a nominal 90%, the language interval 83–88% of its own target; the percentile version of the panel interval was dropped because sampling error in language-mean SR biases R<sub>k</sub> slightly and the percentile interval carried the bias (coverage of a large paired change fell to 0.53–0.60). Named universes, with both intervals (paired across rungs): the first-listed universe; the dictionary universe (every language at its dictionary option where one exists); and the NS-closest universe (every language at its option with the smallest median |log *u*|). The universes at either end of R<sub>4</sub> are not given intervals: they are picked by their result, and the specification curve already shows them.

The NS lens: for each universe, its calibration score (the mean over languages of median |log *u*|), plotted against R<sub>k</sub>, with no cut-off subset. Per language and option: per-text *u*, its median, median |log *u*|, range, and leave-one-text-out stability.

Diagnostics carried over from the B+ draft: whether conventions cancel (per option *u*, ID<sub>k</sub>, *u* × ID<sub>k</sub>, and how differences vary with k, budget and inventory size); context span per rung in segments; what each option changes on the corpus (splits, merges and deletions separately, net count change, inventory and out-of-vocabulary change, frequency in the read texts and in each corpus); paired differences rather than overlapping intervals (Gelman & Stern 2006).

## 5. Headline measure

R<sub>k</sub> = SD<sub>l</sub>(log mean IR<sub>lk</sub>) / SD<sub>l</sub>(log mean SR<sub>l</sub>), with v<sub>k</sub> and r<sub>k</sub> beside it (spec-review item 4; confirmed by Brett 2026-10-09). `SPEC.md`'s CV ratio is superseded by a dated pointer, not a silent edit.

## 6. Matched-count information rate

Beside IR = ID<sub>k</sub> × SR (the replication), each universe reports IR = ID<sub>k</sub> × *P* / *D*: bits per pipeline syllable times pipeline syllables per second, per reading, averaged by the approved speaker-first aggregation, where *P* is the pipeline's count for the text and *D* the reading's duration. It exists for the primary texts, and for all 15 once the secondary run's digit and letter readings are fixed (before any comparison with NS); the paper's formula is recomputed on the same subset for comparison. It is a corpus-based proxy: it assumes the written corpus's information per pipeline syllable carries over to the read texts. The ratio *u* = *P*/NS compares this pipeline with NS; it doesn't show whether the original paper's corpus syllabification matched its NS counts. R<sub>k</sub>'s denominator is the paper's canonical SR in both versions.

## 7. Candidate-list changes (approved 2026-10-09)

As listed in `notes/stage3-amendment-selection-rule.md` §10, now options in the multiverse: the corrections (TUR-B front vowels; CMN erhua on the corpus side; SPA relabelled; ITA exception list, precedence and the excluded supporting schwa; EUS exclusions; FRA vowel–glide variation recorded; the shared rules made exact and the counters frozen before the stamp) and the additions (ITA-C; EUS-C; a narrow CAT-B from the passage, checked against Wheeler or Hualde before freezing; FIN A, B, C′ and D, with C for calibration only). The candidate note is revised to match before the stamp.

## 8. Pronunciation dictionaries

Candidates, each entering only after its terms, size and fields are checked and Brett has seen them: WebCelex for ENG and DEU and Lexique 3.80 for FRA (the paper's own sources, SM Table S2); E-Hitz for EUS (the paper's Basque corpus); PhonItalia for ITA; EsPal for SPA if it gives syllabified forms. For each: the share of corpus words it covers, with the tool supplying the rest.

Status of the checks (2026-10-09; two web searches, the Lexique manual and the EsPal paper read directly; terms quoted by the search agent came through a summarising model and are rechecked verbatim before any is logged as fact):

- **FRA, Lexique:** `syll` is the "forme phonologique syllabée"; schwa is "°" when elidable (*abordera*) and "3" when not (*parvenu*); syllabification is computed after removing final schwas (Lexique 3 manual, read directly). So FRA-A keeps every schwa and FRA-B drops the elidable ones, both from the lexicon. Version 3.80 is no longer on the server (3.82, 3.83, 4.0 and 4.1 are; 3.83 is 27 MB zipped, 4.1 is 49 MB); later releases corrected more of the phonology, so 3.80 can't be matched exactly. Licence conflict confirmed: the French homepage's text says BY-SA and its link goes to BY-NC.
- **ENG and DEU, CELEX:** WebCelex needs a CLARIN account; the full English and German data are only in LDC96L14, for a fee, research use only, no onward distribution. Open: whether UofT has LDC membership.
- **EUS, E-Hitz:** a Windows program; whether it gives syllabified forms is unverified. Its successor EHME has orthographic syllables only.
- **ITA, PhonItalia:** described as having syllable boundaries and stress for 120,000 forms, under a non-commercial Creative Commons licence (2013 announcement), but the site no longer resolves and no copy was found by the routes tried. Writing to the authors is Brett's call.
- **SPA, EsPal:** gives orthographic syllable boundaries (`orth_syll_structure`, from the Silabeador TIP rules), the stressed syllable's position (`syll_accent`) and a rule-derived phonetic transcription (`phon_structure`, from the SAGA rules, "taking advantage, when necessary, of the syllabification"), per its paper (Duchon et al. 2013, read directly). It is rule-based, so it is a documented G2P rather than an independent lexicon. Whether full lists can be exported is unknown.
- **CAT:** no verified syllabified lexicon. Leads: Festcat's `upc_ca_base` (a Festival lexicon, 3.8 MB, terms not shown) and the SPPAS Catalan dictionary (GPL; syllables unknown).
- **HUN:** nothing freely downloadable found.

## 9. Choices decided by Brett (2026-10-09, one by one)

1. The YUE gap treatment is a plain fork: drop and split are both options (§2.1).
2. Same text, not same tokens, across a language's options (§3).
3. Cross-language combinations enumerated up to 10<sup>6</sup>, otherwise 10<sup>5</sup> drawn uniformly (§3).
4. Modal first if the full crossing won't fit locally; the cut order only as a fallback (§3).
5. FIN-C for calibration only (§2.4).
6. The NS lens is a plot with no cut-off subset (§4).
7. Named universes: first-listed, dictionary and NS-closest; no intervals for the extremes (§4).
8. KenLM, after a fake-data check (§2.3).

## 10. Added since Brett's decisions, for his read

1. The fake-data gate, F1–F4 (§3a), at Brett's suggestion.
2. The cost estimate (§3), from the timing benchmark.
3. Shares of universes reported by fork and with near-duplicate options grouped into declared families (§4), after a side agent pointed out that a pooled share moves with the number of options listed.
