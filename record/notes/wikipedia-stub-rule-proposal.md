# Wikipedia stub rule: proposal
<!-- SUMMARY: proposed prose-line filter and template-share stub filter for the Wikipedia samples, measured on Cantonese; approved by Brett 2026-10-08, window length revised the same evening (8 characters for CMN, YUE, JPN, KOR; 24 elsewhere) · status: settled · updated: 2026-10-08 -->

The Cantonese decision (DECISIONS.md, option B) requires bot stubs to be filtered, with the rule fixed before any YUE entropy; the Wikipedia decision extends that to all 17 languages. Measured on the whole of `20231101.zh-yue` (134,140 articles, `data/interim/wiki-yue-probe/`). No entropy has been computed.

## Proposed rule

1. **Prose lines only.** Keep a line if it ends in sentence-final punctuation (。！？.!?… with any closing quote or bracket). This drops headings (參考, 攷, 睇埋, 出面網頁), category names (日本足球員, 響呢年出世嘅人) and list items. On YUE it keeps 63% of characters; 7,066 articles have no prose line at all. Thai doesn't mark sentence ends with punctuation, so Thai needs its own line rule (a length floor, for instance), to be fixed after looking at Thai data and before any Thai entropy.
2. **Template share.** For each article's prose, take its character 8-grams with digits masked, keep 1 in 4 by a stable hash, and compute the share that occur in at least 20 articles of that language's sample. Drop the article if the share is 0.5 or more. On YUE this drops 28% of articles but 4% of prose characters (the stubs are short), leaving 23.5M prose characters: Japanese performers and footballers, French communes, Thai provinces ("佛丕府係泰國一個府，喺西部地區。"). It spares short human-written articles whose only shared text was boilerplate, once headings are gone.
3. **Second arm (what would Gelman do).** Run every Wikipedia sample at a threshold of 0.3 as well and report both. At 0.3, YUE drops 35% of articles and 6% of prose characters; the extra losses are formulaic but human-written articles (TV schedules, football tournaments).

## Notes for implementation

- Python's built-in `hash()` is salted per process, so the subsampling of 8-grams must use a stable hash (CRC32 or BLAKE2) for the rule to be reproducible. The figures above used `hash()` and will move slightly.
- The "20 articles" floor is relative to sample size. Small Wikipedias are taken whole (YUE: 134,140 articles); large ones are sampled by row group to the 200 MB cap. Report each language's sample size beside its drop rates.
- Character n-grams make the rule script-blind, so the same rule runs on all 17; only the prose-line test needs a Thai variant.

## Revision (approved by Brett, 2026-10-08 evening)

The 8-character window failed outside CJK: in Basque it dropped 97.5% of articles, since 8 characters of an alphabetic script is about a word and a half. Windows are now 8 characters for CMN, YUE, JPN and KOR and 24 for the Latin-script languages and Thai. On the Basque cache that drops 52% of articles and 25% of prose at 0.5, close to what word 4-grams give (DECISIONS.md).
