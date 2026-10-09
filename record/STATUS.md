---
slug: info-rate-context
kind: paper
title: Context-window sensitivity of cross-linguistic information rate
stage: development
external: none
blocked_on: []
updated: 2026-10-09
source:
- STATUS.md
- SPEC.md
claim:
  provenance: not-yet-formulated
  claim_updated: 2026-09-28
---

# Context-window sensitivity of cross-linguistic information rate
<!-- SUMMARY: replication-and-extension of Coupé et al. 2019 info rate across context windows; Stage 1 reproduced, Stage 2 complete; design is now a multiverse over the approved forks, with fake-data checks (F1, F3a, F3b local done; F1 long lines and the F3b stress test running) before any real syllable count · status: development · updated: 2026-10-09 -->

## State

[withheld: from private correspondence with the paper's authors]

Prior-work check (spec review item 6), done 2026-10-08 before any download: none of the 245 indexed works citing the paper, and none of seven web searches, extends its ID across word boundaries (`notes/prior-work-check-2026-10-08.md`). Nearest neighbour: Oh & Pellegrino (2023), on the within-word versus across-word split of information in 47 languages; full text still needed (repository copy is behind a bot check). Stage 2 runs under a disk budget: documents fetched singly by range request, compressed text only, `data/` at most 10 GB, stop if free space would drop below 40 GB (`DECISIONS.md`).

## Next action

**Pre-registration:** the decision record is timestamped and published, with correspondence withheld, at https://github.com/BrettRey/info-rate-context-prereg (r3 anchored in Bitcoin block 970627). The public record is pushed after each batch of decisions and before any step that touches NS: full and public snapshots, both stamped, a diff audit of what changed, then `prereg/publish_public.sh` (`DECISIONS.md`, regular-push entry). No ratio to NS, no syllable count on a read text and no syllable entropy of a real corpus exists in any language.

**Design (2026-10-09): a multiverse** (`notes/multiverse-spec.md`), replacing selection by NS: every reasonable combination of the approved forks is run and the headline is reported as its spread, with NS calibration as a lens. Before any real estimate, fake-data checks with known answers: F1 (the estimator, KenLM, built at commit 4cb443e), F3 (the whole Stage 6 analysis on seventeen fake languages; F3a with true densities, F3b with fitted ones) and F4 (plumbing). Done so far: F1 version 2 short lines and ablation, F1 code checks and an independent rebuild of modified Kneser–Ney, F3a, and F3b's local family; still running: F1 version 2 long lines, F3b's skipped-dependency stress test. Next: F4, the word-boundary rungs (F1c), the counters for the candidate conventions, then the stamp that must precede any real count.

Stage 2 subtitles (`src/stage2_opensubtitles.py`): all 16 languages done 2026-10-09, every sample equal to the output of the final fetcher (`0bf87dd`; provenance in `results/stage2/README.md`), and `src/stage2_check.py` passes on all 34 samples; per-language counts and filter rates in `results/stage2/summary_opensubtitles.tsv`. 200 MB each except EUS (31 MB, whole release), CAT (40 MB, whole release) and JPN (73 MB, the whole usable release). Corpora in `data/raw/` (gitignored; OpenSubtitles text is not redistributable); manifests in `results/stage2/manifest/` rebuild the samples.

Stage 2 Wikipedia (`src/stage2_wikipedia.py`, Hugging Face 20231101): all 17 done 2026-10-08, plus `THA-p150`; per-language counts in `results/stage2/summary_wikipedia.tsv`. Templated share ranges from 2% (JPN, THA, DEU) to 52–61% (EUS, SRP, VIE). Kept text about 180–200 MB per language except YUE (whole wiki, 57 MB) and EUS (152 MB after stub removal). Pass-1 caches in `data/interim/wiki_cache/` are kept: they hold the paragraph structure the Thai paragraph-unit row needs, and let pass 2 be rerun without downloading.

Stage 3 (offline-safe): unit-check scope logged (digit-free texts primary, all texts secondary); tool survey in `notes/stage3-tool-survey.md`; candidate conventions in `notes/stage3-candidate-conventions.md`, to be revised with the approved changes and frozen with their counters.

## Open decisions (Brett)

[withheld: from private correspondence with the paper's authors]

## Blockers

None external.
