# Amendment to the Stage 3 selection rule and the headline measure
<!-- SUMMARY: replaces selection-by-NS with a calibration default plus full headline curves for every candidate, adds a matched-count information rate, confirms R_k on SDs of logs, and lists the approved candidate-list changes; superseded before it was logged by the multiverse design (`notes/multiverse-spec.md`); its §10 candidate-list changes carry over · status: superseded · updated: 2026-10-09 -->

Drafted 2026-10-09 by Claude (Claude Code) for Brett. Brett approved the three changes in principle ("1-3 yes"); this text is not in force until he has read it, it is logged in `DECISIONS.md`, and it is in a timestamped snapshot. The places where this draft makes a choice he hasn't yet seen are listed at the end.

## Why, and why now

The approved rule (`notes/stage3-proposal-units-jpn-tha.md`, §1–2; restated in `DECISIONS.md`, 2026-10-09) picks each language's syllable-grouping convention by the median per-text ratio of pipeline syllables to NS, keeps candidates "within 0.01 of the best" as arms, and gives the runner-up one sensitivity row for the headline. Two reviews by Sol (gpt-6.1-sol; `private/reviews/`) found that "within 0.01" is ambiguous (medians of 0.98 and 1.02 are equally far from 1 but 0.04 apart) and that a median of ratios measures bias, not fit (ratios 0.90, 0.90, 0.90, 1.00, 1.10, 1.10, 1.10 have median 1 and beat a candidate at 1.02 on every text). Asked what Gelman would do, the drafting agent proposed using the ratio to rescale instead of to choose, on the claim that a convention change would then largely cancel. Sol showed that claim is false for finite-context entropy estimates: grouping a sequence into larger units changes what a context of k units covers, so a count ratio can't be assumed to undo a convention change. This amendment keeps a calibration default, removes the dependence of the headline on it, and measures cancellation instead of assuming it.

Timing. No pipeline has produced a syllable count for any read text in any language, and no ratio to NS exists (`results/stage3/` holds only the corpus-word agreement check). What has touched the read texts so far: spelling scans for SRP *ije* and CMN 儿, with no count and no NS value. The amendment therefore applies to all 17 languages, including JPN and THA, whose candidate lists were approved under the old rule. The old rule stays in the record; this text replaces it from the date it is logged.

## 1. Notation

For language *l*, candidate convention *c* and primary text *t*: *P*<sub>lct</sub> is the pipeline's syllable count, *NS*<sub>lt</sub> the paper's canonical count, and the count ratio is *u*<sub>lct</sub> = *P*<sub>lct</sub> / *NS*<sub>lt</sub>. (The letter *u* avoids the spec review's *r*<sub>k</sub>, which is a correlation.) Over a language's primary texts:

- *m*<sub>c</sub> = median<sub>t</sub> *u*<sub>lct</sub>, and *d*<sub>c</sub> = |*m*<sub>c</sub> − 1| (bias);
- *e*<sub>c</sub> = median<sub>t</sub> |log *u*<sub>lct</sub>| (typical per-text discrepancy).

## 2. The calibration default

- **Default:** the candidate with the smallest *d*<sub>c</sub>. Exact ties go to the smaller *e*<sub>c</sub>, then to the candidate listed first.
- **Calibration set:** the default, every candidate with *d*<sub>c</sub> ≤ min *d* + 0.01 (inclusive), and every candidate with the smallest *e*<sub>c</sub>. The set is reported and marked in the headline figures; it carries no extra computing.
- **What the default is:** a calibration default, the convention whose counts on these texts sit closest to NS. It is not a claim that the convention is linguistically correct, and where NS chose it, its ratio is a calibration, not an independent check of unit consistency.
- **What the default is for:** the full grid of other forks (rungs × line treatment × budgets B, B/2, 3B × gap treatment × Wikipedia threshold × segmenter) runs on the default only.

## 3. Every candidate gets the full headline curve

Every frozen candidate in every language gets the complete headline R<sub>k</sub> curve: every rung of the ladder, at the first-listed setting of each other fork (cross-line contexts, budget B, the main gap treatment, the OpenSubtitles corpus, the first-listed segmenter where a language has two). This replaces the runner-up's single sensitivity row. Exception, declared now: FIN-C (three exact word forms; §10) is a calibration candidate only, with its NS ratio and affected share reported but no headline curve, since it changes three word types.

## 4. Two information rates, both reported

For each candidate and rung:

1. **As the paper computes it:** IR = ID<sub>k</sub> × SR, with SR from the authors' CSV. This is the replication.
2. **Matched-count rate:** IR = ID<sub>k</sub> × *P* / *D*, bits per pipeline syllable times pipeline syllables per second of the reading, computed per reading and averaged by the approved speaker-first aggregation (so no language-level median ratio enters). It exists only where *P* does: the primary texts, and all 15 texts once the secondary run's digit and letter readings are fixed (they are fixed before any comparison with NS, as already logged). For a like-for-like comparison, the paper's formula is also recomputed on the same subset.

The matched-count rate is a corpus-based proxy: it assumes that the written corpus's information per pipeline syllable carries over to the syllables of the read texts. It fixes the counting denominator, not differences in genre, lexicon or model fit.

The ratio *u* compares this pipeline with NS. It does not show whether the original paper's corpus syllabification was compatible with its NS counts; that would need the original syllabifier or its output. The write-up states the question as a compatibility concern.

R<sub>k</sub>'s denominator stays the paper's canonical SR in both versions (this project doesn't touch SR). A version with the pipeline's own rate *P*/*D* in the denominator asks a different question and is reported for the default convention only.

## 5. Cancellation is measured, not assumed

For each candidate: *u*, ID<sub>k</sub>, *u* × ID<sub>k</sub>, and the matched-count curve. Cancellation fails to the extent that:

- matched-count densities differ between candidates;
- the differences change with k, especially across word boundaries;
- they change between budgets B/2 and B (the default's budget runs give the comparison);
- they track syllable-inventory size, out-of-vocabulary rates or sparse contexts;
- a convention changes counts at different rates in the read texts and in the corpus.

Context span: equal k is not equal material across conventions, so each rung also reports the mean number of segments in its context, per candidate.

## 6. Presentation and uncertainty

- **Curves, not an average.** Candidate-by-candidate curves, plus a labelled envelope across combinations of candidates over languages. The envelope's edges can switch combinations from rung to rung, so an edge need not be any single permissible curve; the write-up says so. No interval averaged over conventions is reported, because that would need weights for the conventions, and none are declared.
- **Differences, not overlapping intervals.** Conventions and rungs are compared by paired differences in R<sub>k</sub> within each bootstrap resample over languages (as spec-review item 5 already does for rungs), not by whether one interval excludes 1 and another doesn't (Gelman & Stern 2006).
- **The calibration itself:** per-text *u* for every candidate, *m*<sub>c</sub>, *e*<sub>c</sub>, their ranges, and whether the default changes when any one text is left out.
- **What each candidate changes, on the corpus:** syllables affected by splitting, by merging and by deletion, reported separately; the signed net change in count; the change in the syllable-type inventory and in out-of-vocabulary rates; and how often each operation applies in the read texts against each corpus.

## 7. Stress and pitch-accent labels

These leave counts unchanged, so *u* gives no correction; they change the syllable alphabet and its sparsity. Both versions (marked and unmarked) get the headline curve. The Stage 4 comparison with the published ShE sets the calibration default and is reported as a replication finding; it doesn't select what the headline uses.

## 8. The headline measure

R<sub>k</sub> = SD<sub>l</sub>(log mean IR<sub>lk</sub>) / SD<sub>l</sub>(log mean SR<sub>l</sub>) over the 17 languages, with v<sub>k</sub> = SD(log ID<sub>k</sub>)/SD(log SR) and r<sub>k</sub> = corr(log ID<sub>k</sub>, log SR) reported beside it (spec-review item 4, adopted 2026-10-08 as a working default and now confirmed by Brett). `SPEC.md`'s CV ratio (Stage 5) is superseded; SPEC.md gets a dated note pointing here rather than a silent edit. For the matched-count version, log IR shifts by each language's log *u*, so the rescaling can raise or lower apparent compression through its covariance with log IR; each language's contribution is reported.

## 9. Training data across candidates

Within a language, every candidate is trained and tested on the same source documents, chosen once for the default at budget B in syllable tokens. A candidate that merges syllables therefore sees the same text in fewer tokens, and one that splits them sees it in more; the token count is reported. Holding the text fixed isolates the effect of the unit from the effect of more or less text. Combining candidates across languages afterwards is then simple arithmetic on stored results.

## 10. Candidate lists (approved changes; the candidate note will be revised to match)

Corrections from the first Sol review, each checked against its source:

- **TUR-B:** ğ between front vowels is "a weak front-velar or palatal approximant" (Zimmer & Orgun 1992: 44) and stays a consonant; it is deleted only between other vowels, and the identical-vowel merger there is labelled as an operationalisation.
- **CMN (corpus side):** er-hua is "suffixation of a rhotacized subsyllabic [ɚ] to a rhyme" (Lee & Zee 2003: 111), so suffixal 儿 doesn't count as a syllable; 儿 as a morpheme of its own (儿子, 女儿) does. The read texts have no 儿.
- **SPA:** non-high vowels in contact reduce to one syllable without a fast-speech condition (*poeta*, *maestro*: Martínez Celdrán et al. 2003: 257). Relabelled: A as the tool transcribes, B maximal pairing.
- **ITA:** a frozen list of words that keep hiatus (starting with *riuscito*, ri.u in the passage, Rogers & d'Arcangeli 2004: 120); phrase-final protection takes precedence over cross-word pairing; the optional supporting schwa after a phrase-final consonant (p. 118) is listed as excluded.
- **EUS:** Markina's optional /e/ deletion (Bedialauneta & Hualde 2022: 1110) is listed as excluded; EUS-B's reach beyond the sources is labelled as ours.
- **FRA:** the free variation between high vowels and glides (Fougeron & Smith 1993: 75) is recorded as an uncovered uncertainty.
- **Shared rules:** one greedy pass over R0 nuclei; runs of three or more identical vowels; tie bars counted only on vowel pairs; precedence of exceptions over pairing. The counters are written and tested on corpus words, and frozen, before the timestamp.

Additions:

- **ITA-C:** every word treated as phrase-final (terminal two-vowel hiatus protected in every word, no cross-word pairing), with the same exception list; a word-isolated proxy for citation forms.
- **EUS-C:** EUS-A with /ui/ as one syllable (Markina, p. 1107), ordinary rising sequences still hiatus.
- **CAT-B:** narrow operations read off the passage transcription (Carbonell & Llisterri 1992: 56), each tied to its documented context: *el* and *es* lose their vowel after a vowel-final word (*que el qui* [kə l ki], *tramuntana es posa* [… s ˈpɔz]); *que* loses its vowel before a vowel-initial word (*que ell* [k eʎ]); *i* next to a vowel is a glide (*tramuntana i el* [… j əl]); a word-final unstressed vowel drops before a vowel-initial word (*cada u* [ˈkaδ u], *posa a* [ˈpɔz ə]). A word left without a vowel has no syllable of its own; its consonant joins the neighbouring syllable (the preceding one for *el*, *es*; the following one for *que*), and that syllable belongs to the host word at the word-aware rungs. Checked against Wheeler (1979) or Hualde (1992), through the UofT library, before freezing.
- **FIN:** A (traditional); B (/eu/, /ou/ split outside the first syllable, labelled ours); C (exact forms *pian*, *tae*, *teos* as one syllable: calibration only, §3); C′ (the combinations /ia, iä/, /ae, äe/, /eo, eö/ tautosyllabic anywhere in the word, labelled ours: the class the book's three examples belong to, Suomi et al. 2008: 50); D (B and C′ together).
- **FRA:** Lexique 3.80's fields, schwa marking and licence are checked; the French route is then settled (Lexique as main lexicon with espeak-ng for words it lacks, or espeak-ng with FRA-B only). If FRA-A depends on a lexicon, it is named "keep the schwas the lexicon writes", with the share of words from the fallback reported.

## 11. Cost

Counting candidates, not runtime: 13 to 14 headline ladders beyond the 17 defaults (about 76–82% more headline computing, Sol's count, which includes the JPN alternative and a possible THA one). The full grid doesn't grow. Languages and conventions differ in cost.

## Choices in this draft that Brett hasn't seen

1. **Denominator (§4):** canonical SR in both versions; the pipeline-rate denominator for the default only.
2. **Same text, not same tokens, across candidates (§9).**
3. **FIN-C as calibration only, no headline curve (§3).**
4. **Settings for non-default candidates' curves (§3):** the first-listed setting of each other fork.
5. **Tie-breaking (§2):** smaller *e*<sub>c</sub>, then the candidate listed first.
6. **CAT-B's operations and the representation of a vowel-less word (§10).**
7. **SPEC.md gets a dated pointer, not an edit (§8).**
