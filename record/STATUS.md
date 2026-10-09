---
slug: info-rate-context
kind: paper
title: Context-window sensitivity of cross-linguistic information rate
stage: development
external: none
blocked_on: []
updated: 2026-10-08
source:
- STATUS.md
- SPEC.md
claim:
  provenance: not-yet-formulated
  claim_updated: 2026-09-28
---

# Context-window sensitivity of cross-linguistic information rate
<!-- SUMMARY: [withheld: from private correspondence with the paper's authors] -->

## State

[withheld: from private correspondence with the paper's authors]

Prior-work check (spec review item 6), done 2026-10-08 before any download: none of the 245 indexed works citing the paper, and none of seven web searches, extends its ID across word boundaries (`notes/prior-work-check-2026-10-08.md`). Nearest neighbour: Oh & Pellegrino (2023), on the within-word versus across-word split of information in 47 languages; full text still needed (repository copy is behind a bot check). Stage 2 runs under a disk budget: documents fetched singly by range request, compressed text only, `data/` at most 10 GB, stop if free space would drop below 40 GB (`DECISIONS.md`).

## Next action

**Stage 2 is complete.** Next: Stage 3. Test-install and check the tools in `notes/stage3-proposal-other-languages.md` (espeak-ng, underthesea, pyvi, g2pk2, jieba, pkuseg, opencc; a second Cantonese segmenter), then build the syllabification pipeline language by language, starting with the NS unit check on the primary read texts (`DECISIONS.md`, Stage 3 scope and the approved convention rule). Stage 4's exact-source check needs WebCelex (webcelex.ivdnt.org) and Lexique terms checked first.

Stage 2 subtitles (`src/stage2_opensubtitles.py`): all 16 languages done 2026-10-09, every sample equal to the output of the final fetcher (`0bf87dd`; provenance in `results/stage2/README.md`), and `src/stage2_check.py` passes on all 34 samples; per-language counts and filter rates in `results/stage2/summary_opensubtitles.tsv`. 200 MB each except EUS (31 MB, whole release), CAT (40 MB, whole release) and JPN (73 MB, the whole usable release). Corpora in `data/raw/` (gitignored; OpenSubtitles text is not redistributable); manifests in `results/stage2/manifest/` rebuild the samples.

Stage 2 Wikipedia (`src/stage2_wikipedia.py`, Hugging Face 20231101): all 17 done 2026-10-08, plus `THA-p150`; per-language counts in `results/stage2/summary_wikipedia.tsv`. Templated share ranges from 2% (JPN, THA, DEU) to 52–61% (EUS, SRP, VIE). Kept text about 180–200 MB per language except YUE (whole wiki, 57 MB) and EUS (152 MB after stub removal). Pass-1 caches in `data/interim/wiki_cache/` are kept: they hold the paragraph structure the Thai paragraph-unit row needs, and let pass 2 be rerun without downloading.

Stage 3 (offline-safe): unit-check scope logged (digit-free texts primary, all texts secondary); tool survey in `notes/stage3-tool-survey.md`. Per-language tool proposals go to Brett before they're settled.

## Open decisions (Brett)

- Stage 3 plans for the other 15 languages (`notes/stage3-proposal-other-languages.md`): first draft, adequacy mostly untested; VIE added to the segmenter fork.
- Thai Wikipedia prose-line rule, after inspecting Thai Wikipedia.

## Blockers

None external. Stage 2 onward waits on the spec-review decisions.
