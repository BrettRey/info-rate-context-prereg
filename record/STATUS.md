---
slug: info-rate-context
kind: paper
title: Context-window sensitivity of cross-linguistic information rate
stage: development
external: none
blocked_on: []
updated: 2026-10-10
source:
- STATUS.md
- SPEC.md
claim:
  provenance: not-yet-formulated
  claim_updated: 2026-09-28
---

# Context-window sensitivity of cross-linguistic information rate
<!-- SUMMARY: replication-and-extension of Coupé et al. 2019 info rate across context windows; Stage 1 reproduced, Stage 2 complete; multiverse design; fake-data checks F1, F3a, F3b (KenLM) and neural F1 done; Codex branches for runner, counters, pipeline and F1c reviewed and awaiting acceptance; neural settings fixed, neural F1 (seed 1, then seeds 2 and 3) and the F3b words-and-rates grid running; counter readings cut by the corpus tally (under 0.05% frozen, five forks: rows 16, 26, 12, 17, 5), boundary rows to be measured on entropy once segmentation exists · status: development · updated: 2026-10-10 -->

## State

[withheld: from private correspondence with the paper's authors]

Prior-work check (spec review item 6), done 2026-10-08 before any download: none of the 245 indexed works citing the paper, and none of seven web searches, extends its ID across word boundaries (`notes/prior-work-check-2026-10-08.md`). Nearest neighbour: Oh & Pellegrino (2023), on the within-word versus across-word split of information in 47 languages; full text still needed (repository copy is behind a bot check). Stage 2 runs under a disk budget: documents fetched singly by range request, compressed text only, `data/` at most 10 GB, stop if free space would drop below 40 GB (`DECISIONS.md`).

## Next action

**Pre-registration:** the decision record is timestamped and published, with correspondence withheld, at https://github.com/BrettRey/info-rate-context-prereg (r3 anchored in Bitcoin block 970627). The public record is pushed after each batch of decisions and before any step that touches NS: full and public snapshots, both stamped, a diff audit of what changed, then `prereg/publish_public.sh` (`DECISIONS.md`, regular-push entry). No ratio to NS, no syllable count on a read text and no syllable entropy of a real corpus exists in any language.

**Design (2026-10-09): a multiverse** (`notes/multiverse-spec.md`), replacing selection by NS: every reasonable combination of the approved forks is run and the headline is reported as its spread, with NS calibration as a lens. Before any real estimate, fake-data checks with known answers: F1 (the estimator, KenLM, built at commit 4cb443e), F3 (the whole Stage 6 analysis on seventeen fake languages; F3a with true densities, F3b with fitted ones) and F4 (plumbing). Done: F1 (short and long lines, code checks, independent rebuild of modified Kneser–Ney, mapped process with KenLM), F3a, F3b (local and skipped families, copy and mapped, KenLM), and the neural estimator's F1 under its declared settings (it recovers skipped dependencies KenLM misses, with a floor of 0.04–0.19 bits). Second estimator: option B (Brett). The neural settings sweep runs on the GPU from task F's copy; its four candidates go to Brett, then the neural F1 (copy and mapped) and neural F3b are rerun.

**Codex work (2026-10-09/10, at Brett's request):** code tasks run in a history-free working copy, `~/projects/codex-work/info-rate-context` (`DECISIONS.md`, 2026-10-09), each in its own worktree and branch, each reviewed independently by a read-only Codex run until the reviews came back clean or with named limits: `codex/t1-tuning-fixes`, `t2-f3b-fixes`, `t3-neural-runner` (runner and assembly after their fix rounds, plus the neural backend), `t4-stage4-pipeline` (counters after their fix rounds, the readings table, the Stage 4 pipeline on generated text), `t5-f1c-fixes` (word-boundary rungs; F1c with KenLM recovers rungs 0–1b within 0.04 bits, and I(S; B) where syllables carry it). None is in this project yet: each enters by review here (diff, tests rerun, log entry). Runs, reviews and manifests: `private/reviews/codex-runs-20261009/`.

Next: Brett's decisions (below), then accept the branches, freeze the counters with Brett's readings, and make the stamp that must precede any real count.

Stage 2 subtitles (`src/stage2_opensubtitles.py`): all 16 languages done 2026-10-09, every sample equal to the output of the final fetcher (`0bf87dd`; provenance in `results/stage2/README.md`), and `src/stage2_check.py` passes on all 34 samples; per-language counts and filter rates in `results/stage2/summary_opensubtitles.tsv`. 200 MB each except EUS (31 MB, whole release), CAT (40 MB, whole release) and JPN (73 MB, the whole usable release). Corpora in `data/raw/` (gitignored; OpenSubtitles text is not redistributable); manifests in `results/stage2/manifest/` rebuild the samples.

Stage 2 Wikipedia (`src/stage2_wikipedia.py`, Hugging Face 20231101): all 17 done 2026-10-08, plus `THA-p150`; per-language counts in `results/stage2/summary_wikipedia.tsv`. Templated share ranges from 2% (JPN, THA, DEU) to 52–61% (EUS, SRP, VIE). Kept text about 180–200 MB per language except YUE (whole wiki, 57 MB) and EUS (152 MB after stub removal). Pass-1 caches in `data/interim/wiki_cache/` are kept: they hold the paragraph structure the Thai paragraph-unit row needs, and let pass 2 be rerun without downloading.

Stage 3 (offline-safe): unit-check scope logged (digit-free texts primary, all texts secondary); tool survey in `notes/stage3-tool-survey.md`; candidate conventions in `notes/stage3-candidate-conventions.md`, to be revised with the approved changes and frozen with their counters.

## Open decisions (Brett)

[withheld: from private correspondence with the paper's authors]

Settled 2026-10-10: neural settings (`zero_unigram_cosine5`); the design points (A1–A7, B1–B6); the syllabification scope cut, which drops the CELEX and PhonItalia questions; the rows the cut can't judge (boundary rows measured on syllable entropy once segmentation exists, unmeasured rows reported as such, row 13 frozen with its bound reported; row 5 a fork on its genuine effects, row 23 unmeasured, rows 29 and 37 fixed defects); neural F1 on seeds 2 and 3, queued after seed 1 (`.worktrees/f1seeds-run` in the Codex working copy).

## Blockers

None external.
