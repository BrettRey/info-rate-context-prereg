# Spec review at setup
<!-- SUMMARY: design issues in SPEC.md found at setup (rung nesting, estimator, data budget, R_k decomposition, type vs token complexity, inventory size, exact-source Stage 4 check); adopted 2026-10-08 · status: settled · updated: 2026-09-28 -->

Written at setup from the spec alone, before any data were run. Each item wants a decision logged in `DECISIONS.md` before Stage 5.

## 1. Rungs 1w and 1 aren't nested

At 1w the context for a word-initial syllable is the null marker, so the model is told where every word starts. Rung 1 conditions on the previous syllable across boundaries and loses that information. The step from 1w to 1 therefore removes boundary knowledge and adds cross-word context in one move, and the curve can't separate the two.

Suggested fix: add a rung **1b** (previous syllable across boundaries, plus a word-initial flag) and give every higher rung the same flag. Then 1w → 1b isolates cross-word context. Keep rung 1 as the segmenter-free variant: for CMN, YUE and THA the flag is segmenter output, so 1b and above inherit the segmentation choice and rung 1 doesn't.

## 2. One estimator along the curve

The spec uses held-out cross-entropy for k ≥ 1 and adds plug-in estimates for k = 0 and 1w. Say explicitly that the curve uses held-out cross-entropy at every rung, including 0 and 1w, and that plug-in values serve only the Stage 4 validation. Otherwise the 1w → 1 step also changes estimator (plug-in is biased low, cross-entropy is an upper bound).

## 3. Equal data budgets, or the curve tracks corpus size

Higher-order n-gram models need more data, so any cross-language difference in training size or syllable-inventory size shows up as extra cross-entropy that grows with k. That would move R_k for reasons unrelated to the question. Train every language on the same number of syllable tokens, report out-of-vocabulary rates per language, and rerun the curve at a second budget to show it holds. The learning-curve plateau in Stage 2 is stated for the plug-in entropies; extend it to the cross-entropies at k = 3 and 4, where it matters most.

## 4. R_k decomposes into two numbers

ID is constant within a language, so the language-mean IR is exactly ID × language-mean SR, and log IR = log ID + log SR. Writing v_k = SD(log ID_k) / SD(log SR) and r_k = corr(log ID_k, log SR) across the 17 languages:

  R_k² = 1 + v_k² + 2 r_k v_k,  so R_k < 1 exactly when r_k < −v_k / 2.

Define R_k on SDs of logs (CV approximates this at these spreads) and report v_k and r_k alongside it. The three readings in Stage 6 then become statements about those two quantities, and a language whose ID moves can be traced to its effect on each. Mean IR falling with k says nothing about compression: a proportional drop in every language's ID leaves R_k unchanged.

## 5. Compare rungs with a paired bootstrap

Every rung is computed on the same 17 languages with the same SR, so their intervals are strongly correlated. Separate intervals per rung will overlap and hide a consistent shift. Bootstrap R_k − R_1w (or the change between adjacent rungs) within each resample of languages.

## 6. Checks before Stage 2

- **Cantonese source text.** The paper's Cantonese corpus was "A linguistic corpus of mid-20th century Hong Kong Cantonese" (SM Table S2), not general written Chinese. Hong Kong subtitles are often in Standard Written Chinese rather than written Cantonese; read through a Cantonese G2P, that would give Cantonese syllables in Mandarin word order. Checked 2026-10-08: OPUS OpenSubtitles' `yue` file is Standard Written Chinese (0 Cantonese markers against 2,524 SWC markers in a 64 KB sample; `results/stage2/README.md`), so it can't be the Cantonese source.
- **Pimentel et al. (2021)** is in the spec's references but not used in the body. It's the nearest neighbour for the LM rung; now in `literature/` (`pimentel_etal_2021_surprisal_duration_tradeoff`). Read it before Stage 5.
- **Bergey & DeDeo (2024)**, cited in the Elicit audit, not in the spec: "13.21±0.04 bits/second" for continuous conversational English (CANDOR corpus), from a language model's word surprisal. It's a second neighbour for the LM rung, from a different register and unit. Now in `literature/`.
- **Outward check.** The portfolio search found nothing on this question (`DECISIONS.md`, setup). That says nothing about the outside literature, and the Elicit audit (C27) makes the same point about the critique's own negative claim. Trott (2020), now read, doesn't raise the context window (`notes/source-verification.md`); that's one source checked, not a search. So a light-tier `/hyperresearch` run on "context length and the Coupé et al. 2019 information-rate result" would check whether the extension already exists before Stage 2 costs anything.

## 7. Type or token complexity in Stage 7

Stage 7 specifies token-weighted segments per syllable and cites Pellegrino et al.'s (2011) ρ ≈ 0.98 as the collinearity to expect. That 0.98 is for their type-based complexity measure (ρ with ID, p. 550); with syllable rate, type-based gives ρ = −0.98 and token-based ρ = −0.89. Compute both, and compare like with like when citing the 2011 figure.

## 8. Add syllable-inventory size to Stage 7

Trott (2020, Limitation 1) asks whether the trade-off comes from syllable predictability or just from the number of possible syllables. That's the spec's second question from another side: segments per syllable measures syllable complexity, inventory size measures how many syllable types are in use. The paper's own Introduction gives the range ("from a few hundred in Japanese to almost 7000 in English"). Put log inventory size beside segments per syllable in Stage 7, and read ShE as close to an inventory measure. The three are likely collinear at N = 17, and the spec's instruction not to force a verdict applies.

## 9. Exact-source check for English, German and French in Stage 4 (added 2026-10-08)

[withheld: from private correspondence with the paper's authors]

## Pending decisions for Brett (2026-10-08)

Items 1–5 and 7–9 are logged as working defaults (`DECISIONS.md`, 2026-10-08); Claude recommends confirming all of them. Settled 2026-10-08 (Brett): all defaults confirmed, item 1 as below, Cantonese option B.

**Item 1, free or charged boundaries: do both (Brett, 2026-10-08).** Run rung 1 (no boundary information), 1b-free (the word-initial flag given as context) and 1b-charged (boundaries as symbols the model predicts, their bits counted per syllable). Writing S for the syllable string and B for the boundaries, the three estimate H(S), H(S | B) and H(S, B) per syllable. By the chain rule, 1 − 1b-free estimates I(S; B), how much knowing the boundaries helps predict syllables, and 1b-charged − 1 estimates H(B | S), how much boundary uncertainty remains given the syllables. Both are per-language quantities that bear on the spec's isolating-versus-agglutinative contrast. Cross-entropy estimates satisfy the chain rule only approximately, so report the three rungs and treat the differences as derived. Rationale: Gelman & Loken (2014), "A starting point would be to analyze all relevant comparisons" (`literature/gelmanLoken2014.md`).

**Cantonese source** (`results/stage2/README.md`). OpenSubtitles `yue` is Standard Written Chinese; Cantonese Wikipedia is written Cantonese. Options:
- A. Cantonese Wikipedia for YUE only. Written Cantonese, running text with article IDs; a different genre from the subtitles, and bot stubs need filtering.
- B. **Chosen (Brett, 2026-10-08).** A, plus a second run on Wikipedia for all 17 languages, so one full run has a single source type. Report the main curve with and without YUE.
- C. Spoken Cantonese transcripts (e.g. the corpus distributed with PyCantonese): closest to speech, probably small (size not checked), so better as a low-rung side check than inside the equal-budget scheme.
- D. The paper's own corpus ("A linguistic corpus of mid-20th century Hong Kong Cantonese", SM ref. 55): useful for Stage 4 validation; availability not checked.
- E. Drop YUE: loses one of the four isolating/tone languages the spec's hypothesis is about.

Ruled out: SWC subtitles read through a Cantonese G2P (Mandarin word order in Cantonese syllables, matching neither the read texts nor speech).
