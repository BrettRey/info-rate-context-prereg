# Audit: the counts re-run and the path to entropy results
<!-- SUMMARY: audit of counts job 2045998 and the plan from now to entropy results (Claude, with Codex and muse read-only), at Brett's request; per-stage scan workers adopted (about a day saved); checklists, the version guard, what to prepare during the run, Brett's gates · status: for Brett; job 2070732 submitted · updated: 2026-11-02 -->

Brett asked (2 Nov, evening) for "a thorough and careful audit of the job and the plan to avoid future snafus and to proceed as expeditiously and efficiently as possible", with Codex and muse helping. Reviews: Codex on the job and plan (`private/reviews/audit-20261102/`), Codex on the one code change it led to (`private/reviews/review-stage-scan-20261102/`), muse on the job and plan (same folder, `muse-report.md`). Every claim below about the code was checked against the code; the reviewers' estimates are marked as theirs.

## What changed tonight because of the audit

**The run was going to take about 5½–6 days, not 3–3½.** The earlier estimate came from the last run, which reused its main stage. This run starts from nothing, and the scan-worker setting (4) also governs both measures, which last ran at 12 (job 929537: main measured at hour 6.7, Wikipedia at 18.4). Italian, with 36 declarations, takes three times as many scan rounds at 4. At 4 throughout: roughly 35–45 h of measures, 27 h main preparation (Italian's breakdown from the old file listing: 5.4 h of serial per-declaration resources, 3.1 h of scans at 12, a 12.5 h serial per-configuration tail), 55 h Wikipedia preparation, 13 h of 90 checks. Codex independently estimated 5–6 days.

**Fix: each stage at the scan-worker count it has already run at on this node.** Both measures and the main preparation at 12 (929537, 1139836; main peak 253 GB of 768), the Wikipedia preparation and the checks at 4 (1380029; peak 358 GB, checks 134 GB). New optional variable `INFO_RATE_SCAN_WORKERS_BY_STAGE` in `src/stage7/counts_phase.py` (not a version-bound file), set in `sbatch-options` to `prepare:wikipedia=4+check:checks=4` with the base at 12. Parallelism only: it enters no reuse key, result or record. Tests (8), the counts-phase test files, one Codex review (no blocking finding; its three small points fixed), and two probe jobs on Fir: Slurm delivers the value intact (2056738), and an explicit `--export` value wins over a conflicting one in the submitting shell (2062326: shell 99 and "stale", job 12 and the stage setting). Commits 4e599f9 and ff63d5b (the full suite then failed one test, `test_p7_freeze_closure`, which reads a simulated command's first output line; the stage lines moved to stderr, which the driver log also takes, and the seven test files that load the counts or entropy phase pass). **Job 2070732**, submitted about 21:00 EST 2 Nov from ff63d5b in the same run folder (2045998 cancelled before it started). Expected run: about 18 + 21 + 55 + 13 ≈ 107 h, **about 4½ days**: if it starts in the early hours of Tue 3 Nov, DONE about **midday Sat 7 Nov**. Without the change, about Mon 9 Nov.

## Will the job complete? (verdicts)

| Risk | Verdict | Basis |
|---|---|---|
| Staging and setup | Sound | `stage.sh` refuses deleted or renamed files, symlinks, `.gitattributes`; setup checks the checkout file by file, the 47 inputs, then the rebuilt onset lists against their own manifest, then espeak-ng's local copy (Codex agrees) |
| Memory | Within measured peaks | every stage at a measured setting; node 768 GB |
| Local disk | Ample | 7.2 TB TmpDisk; the last work folder packed to 196 GB |
| Time limit | Inside 7 days with margin | about 4½ days; the chain packs and continues if not |
| Scratch quota | Ample | 366 GiB of 19 TiB, 6,875 of 1 M files; the archive is one file |
| Node failure before a pack | **Happened, now mitigated** | job 2070732's node rebooted 2 h 23 min in (3 Nov), and about 130 of Fir's CPU nodes are down. The wrapper packs only at the warning or the end, so planned saves at two stage boundaries (start of the Wikipedia preparation, start of the checks; `private/counts-2026-10-27/save-at-boundaries.sh`) cap what one failure can lose at about 55 h instead of the whole run; the first boundary (after the measures) isn't worth a queue wait. Packing a live folder in the background was rejected as riskier |
| Packing failure at the end | Handled | two tries, else FAILED with the previous archive kept (there is none on a first chunk, so the node's copy is the only one until the pack succeeds) |
| `--export=ALL` precedence | Not a risk here | the Fir login shell sets no `INFO_RATE_*` variable, and probe 2062326 showed the explicit value wins over a conflicting one (Codex had read the documentation the other way) |

## Checklists

**When it starts** (watcher on `chunks.log`): checkout matches the run commit; all 47 inputs match; "onset lists from … all 11 match"; espeak-ng bound; "chunk 1 started" with a successor ID; the driver log's first line shows `INFO_RATE_SCAN_WORKERS=12` and the stage setting; then `measure:main: 12 scan workers`.

**During** (whenever Brett's connection is open): once both `budget-plan.json` files exist (about a day in), B₀ = 7,907,758 set by the same variant as before; stage lines in the driver log (`measure:wikipedia: 12`, `prepare:main: 12`, `prepare:wikipedia: 4`, `check:checks: 4`) at the times expected; worker failures; node memory against the measured peaks; the successor still queued. Low CPU in the serial tails isn't a stall.

**At DONE, before anything uses the output:** `chunks.log` ends "driver finished: phase complete", successor cancelled, no FAILED; the run record read from the archive's tail: 90 check views by registry identity, `versions` equal to the bound files at 4e599f9, and **B₀ = 7,907,758 for both runs** (the amendment can't move counts, so any other value means something else changed); `work.tar` read whole (tar exit 0), its sha256 and member count recorded; a copy on `/project/def-brettrey` checked against that hash. Then the extraction job, the masks by reason (compared with the pre-amendment run's: on the samples no line failed under one rule and not the other) and every onset inventory.

## Not invalidating the run again

`pipeline.version()` hashes 11 source files and four lexicon resources by content (`src/stage4/pipeline.py:112–122`; `src/stage3/counters.py`): pipeline, counters, french_lexicon, native_units, japanese, thai, multiverse, segment, onsets, tones, word_segmenters; `resources/lexicons-provenance.json`, `ita_hiatus.tsv`, `cmn_erhua.tsv`, `cat_function_words.tsv`. Masks and preparations are refused under any other version. So from now until the entropy phase is done with this output:

1. **No edit to those files, comments included, without Brett's decision that a re-run is worth it.** Guard installed at Brett's go (2 Nov): `.git/hooks/pre-commit`, local to this clone and untracked (the portfolio's privacy-gate dispatcher runs a repo's own hook first, found through `git rev-parse --git-common-dir`, so this repo's worktrees are covered too). It refuses a commit that touches any of the 15 files unless `ALLOW_VERSION_BOUND_EDIT=1` is set for that commit. Tested in a throwaway worktree: refused, then allowed with the override; other files unaffected. It doesn't cover other clones (the Codex working copy) or uncommitted edits during a test run. Remove it once the entropy phase is done with this output.
2. **The entropy phase checks the version first.** It should compare `pipeline.version()` with the run record before any read-text work (Codex: `entropy_phases.py` checks schema and mode first). A change to `entropy_phases.py`, which isn't bound; before the freeze.
3. **What could still force a re-run:** Brett choosing the pre-amendment onset lists for row 54 (a `segment.py` change; cheapest before the job starts, about 02:00 EST); an after-counts finding Brett chooses to fix rather than report; any change to preparation rules. On the lists: the rebuilt lists are the old ones minus their initialism entries, nothing added (removed: CAT 79, DEU 608, ENG 13,315, EUS 224, FIN 1,393, FRA 887, HUN 2,212, ITA 211, SPA 643, SRP 47, TUR 401), and on the diagnostic samples that removal changes 0.27% of Basque and 0.54% of English syllable labels and none elsewhere. Claude's recommendation: keep the cleaned lists in row 54, since the comparison tests the boundary convention and the initialism removal is data cleaning whose effect is already measured and stated. Brett's call.

## The path from DONE to entropy results

DONE (about Sat 7 Nov) → verify (1–2 h) → extraction job (minutes, plus queue) → masks by reason and onset inventories (about 2 h) → **Brett: dispositions** → `FREEZE.json` (`src/stage3/freeze.py`) and the freeze archive → **Brett: publish the amendment and the validation record, and stamp** → entropy job → entropy results → report.

**Build during the run, so nothing waits afterwards:**

1. **The entropy-phase job on Fir.** No job scripts exist yet (`scripts/cloud/` has only `counts/`). Its neural part was costed at 34–204 h on one thread for 17–34 fits run one after another (DECISIONS 2026-10-27); run several at once across the node's 192 cores, or on GPUs, sized from the B₀ fake-data neural job 1860554 (ends about Tue 3 Nov morning) and the KenLM B₀ timings already in hand; KenLM concurrency sized for memory. Then a rehearsal on invented text on Fir, as the counts job had, and one review.
2. **A freeze rehearsal** at real size: `freeze.py` over a counts output of this size (hashing about 200 GB and 42 M entries), on the superseded run's archive, so its time and any failure are known before Saturday.
3. **Ready-to-submit job files** for the verification, extraction and after-counts checks, pointed at the new run folder.
4. **The entropy-phase version check** (above).
5. **Brett's items:** the row-54 onset lists (tonight, before the job starts, if at all); the amendment's three bracketed items; the publication location (the public pre-registration repository `BrettRey/info-rate-context-prereg` already exists).
6. **Storage:** copy the container image and inputs to `/project` (the run depends on them on scratch); decide what happens to the superseded 196 GB archive (keep on `/project` or `/nearline`, or let it purge about New Year: Brett's call). Never unpack on `/project` (500 K files) or `/nearline` (5,000).

## Process lessons from this week

- Estimate from measured stage times for the stages a run will actually execute; the 3–3½-day figure assumed a reused stage.
- Check symbol inventories in IPA sources against the PDF, not a text conversion (Italian /ʃ/ was lost to a garbled symbol).
- Don't edit a version-bound file while a test suite or run depends on it (this afternoon's one suite error).
- Check job options against Slurm's parsing before submitting (a comma in an exported value would have been split).
- Compound shell commands with `cd` into a temporary directory must stop if the `cd` fails (one did tonight; nothing was harmed, but the next steps ran in the main checkout).

## Muse's review, and what came of it

Muse agreed the job will probably complete and that the 3–3½-day figure was unsupported (its estimate at 4 throughout: 4.8–5.6 days), recommended the per-stage change as its option A (done), and corrected the stage order as Codex did. Its further points, checked:

- **Near-bound files** (confirmed): a finished preparation is reused only when its manifest matches `pipeline.version()` and the digest of `linguistic_inputs.py` (`counts_phase._finished_preparation`), so editing that file, or the other modules the counts phase loads, would make any restart re-prepare everything, and the freeze would record code that didn't run. The guard now covers them too: `linguistic_inputs.py`, `splits.py`, `budgets.py`, `shared_settings.py`, `corpora.py`, `counts_phase.py`, `resources/onset-lexicons-provenance.json`.
- **Eligibility divergence in the main preparation** (checked, not a risk on the samples): the preparation stops if its learned-inventory mask and the counts pass's empty-inventory mask differ on more than 0.1% of lines (`ELIGIBILITY_TOLERANCE`). Under the amended rule, on the ten 5,000-line samples, the lines that fail are identical with either inventory in every language (0 to 91 lines; `private/reviews/audit-20261102/eligibility-compare.py`).
- **Code first exercised at scale late in the run** (accepted): the amended segmenter meets the full corpora in the measures (first hours), but row 54's views run only in the checks at the end. A fault there stops the chain after the preparations, which a restart reuses, so it would cost hours, not days, unless the fix is to a version-bound file.
- **During the run, check B₀ as soon as both budget plans exist** (adopted into the checklist): the measures finish within about a day, and B₀ must be 7,907,758 with the same text setting it was set by before. A different value means counts moved and needs a decision before two more days of preparation.
- **Fair share** (adopted): a whole node for a week lowers the project's priority for the entropy jobs, so the entropy job should be submitted as soon as the stamp is done, with its scripts finished beforehand.
- **Copy the superseded archive to `/project` now as a rehearsal of the copy** (proposed, Brett's call since it uses 196 of 954 GiB).
- **Not adopted:** making the bound files read-only in the working copy (the guard covers commits, and the run uses staged code); its estimate of the measures at 4 workers (20–26 h) is lower than Claude's (35–45 h), moot now that they run at 12.
