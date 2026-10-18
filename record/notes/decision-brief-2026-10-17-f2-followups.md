# F2 follow-ups: four questions for Brett
<!-- SUMMARY: batched decisions after F2's neural subset: the remaining neural fits' cost, a neural pairing for the k = 3–4 reading, the span unit, the definitional forks · status: decided (Brett accepted all four recommendations, 2026-10-17; DECISIONS.md) · updated: 2026-10-17 -->

Claude, 2026-10-17. Numbers come from `results/fakedata/f2/` and the HF job records; each question has a recommendation.

## 1. The remaining 35 neural fits (lag 2's pairs and partial merge)

Measured on the L4:

- **Partial merge:** 666 s per fit, peak 12.7 GB of GPU memory (65,940 units).
- **Pairs:** out of memory at production's evaluation batch of 16,384. One batch's logits need 13.5 GiB, and 8.1 GiB was free. A batch of 4,096 fits. That changes memory only: the loss is summed over batches, so only the order of the sum moves, by about a millionth of a bit. Untimed, but by scaling from the merge fit (3.4 times the vocabulary, 0.58 times the training units), about 21 minutes per fit.

| Option | GPU hours | Cost at $0.80/h |
|---|---:|---:|
| (a) all 35 (17 merge, 18 pairs) | about 9.6 | about $7.70 |
| (b) merge only (17) | about 3.1 | about $2.50 |
| (c) one timed pairs fit first, then decide | 0.35 | about $0.30 |
| (d) stop here | 0 | $0 |

Spent so far: about $0.55.

**Recommendation: (b).** The merge rows pool 2% of test units, and there KenLM's excess is +30% to +41%, so neural values there show whether that excess belongs to KenLM. The pairs rows pool 13%, far beyond the real corpora's under 0.2%, and are already labelled a sparsity stress test.

## 2. Pair the k = 3–4 reading with the neural estimator (amends choice 1)

A side agent pointed out that KenLM's error grows with context in F2 (independent draws: 0% at k = 0, +3.5% at k = 4; lag-2 pairs: +5% to +50–66%), so reading at k = 3–4 trades a convention error for an estimator error. The neural results bear this out. On lag 2:

- fine density at k = 2–4: neural +1.6–2% above the oracle, KenLM +26–32%;
- deletion: neural −3.3% to −4.9% (oracle −5.5% to −6.6%), KenLM +10% to +21%.

One constraint: production fits the neural model at rungs 1w, 1 and 4 only (`runner.NEURAL_RUNGS`), on the first-listed and NS-closest universes. So a neural value exists at k = 4 but not at k = 3.

- **(i)** Pair at k = 4 only. No extra cost; k = 3 is reported for KenLM alone, with a note.
- **(ii)** Add rung 3 to the neural rungs. One more neural fit per job, about a third more neural compute in the real run, and a change to production code before the freeze.

**Recommendation: (i).** At k = 4, report the neural matched-count rate beside KenLM's wherever both exist, with the KenLM-minus-neural difference shown. No threshold: both are reported.

## 3. The span unit (choice 2)

I logged "segments, as the pipeline's syllable labels give them", but the labels aren't phones everywhere:

- **IPA:** CAT, DEU, EUS, FRA, HUN, SPA, TUR, and THA (with tone letters);
- **ARPAbet:** ENG;
- **romanisation:** CMN (pinyin) and YUE (jyutping);
- **kana:** JPN; **hangul:** KOR;
- **orthography:** VIE, FIN, ITA and apparently SRP.

Options:

- **(a) Phones everywhere.** Build segment counts for the non-IPA languages: pinyin and jyutping to phones, kana to phones, hangul to jamo, Vietnamese orthography, the Finnish and Italian digraphs. That's seven or so new phonological choices, each loggable, and about a day.
- **(b) Words covered by the context** (each syllable counts as its share of its word). It needs no phonological choices, and within a language it shows directly when two conventions are compared at unequal spans. Across languages it's coarser.
- **(c) Phones where labels are phonemic** (the IPA languages, ENG, KOR via jamo) **and words elsewhere,** flagged.

**Recommendation: (b), with (c)'s phones as a supplement for the languages where they come free.** F2's problem was unequal spans between conventions of one language, and words answer that without new choices.

## 4. Which forks are definitional (choice 3)

First pass over `notes/stage3-candidate-conventions.md` and the registry:

- FRA-A against FRA-B (FRA-B drops elidable schwas);
- TUR-A against TUR-B (TUR-B deletes intervocalic ğ, fusing identical vowels);
- CAT-A against CAT-B (CAT-B drops vowels in sandhi: *el*, *es*, *que*, and a word-final unstressed vowel before a vowel).

Not on the list:

- **Merges that keep every segment** (EUS-B and EUS-C pairing, glide formation): these are regroupings, not deletions.
- **CMN erhua:** CMN has option A only, so it isn't a fork. I wrongly cited it before; corrected in `DECISIONS.md`.
- **Basque's optional /e/ deletion:** the pipeline doesn't build it.

**Recommendation:** confirm these three.
