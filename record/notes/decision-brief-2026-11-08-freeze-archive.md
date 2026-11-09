# Decision brief: what goes into the freeze archive
<!-- SUMMARY: the freeze lock as built can't open an archive holding the whole counts output; three ways to bind the output, the checks every option needs built (branch freeze-record-checks), Claude recommends B; Brett chose B with the G2P cache bound by digest (06:30 EST 8 Nov; DECISIONS.md 2026-11-08) · status: decided · updated: 2026-11-08 -->

Claude, 8 November 2026, during the counts re-run's checks (job 2625283). Nothing here touches a read text or a result; it decides how the stamp binds the counts output.

## The problem

The freeze-build plan says "the counts phase's outputs go into the freeze archive beside them" (P7, `notes/freeze-build-plan-2026-10-11.md`). The counts phase's own docstring says "`run-record.json` lists every file the freeze needs" (`src/stage7/counts_phase.py`).

The freeze lock as built (`freeze.validate_freeze`) hashes the whole archive and lists its members with `tarfile` each time it runs. It runs in every process that does entropy work: the runner checks it, and each KenLM job is scored in its own fresh interpreter (`entropy_phases._score`). The main run alone has 712 KenLM jobs (`DECISIONS.md` 2026-10-16), and the Wikipedia run and the checks add more, so a real run has well over a thousand such processes.

One validation was measured on the superseded counts output, which has the archive's shape apart from `FREEZE.json` (Fir job 2946694, `private/freeze-rehearsal-2026-11-08/`). The archive is 196 GB with 42.6 million members. Hashing it took 265 s; its SHA-256 matches the one recorded on 2 November. Listing the members took 2,676 s and 32.3 GiB at peak, so one validation took 49 minutes. At that cost, a thousand validations would read about 200 TB and take over 800 hours, and every scoring worker would need 32 GiB for the listing alone. The whole output can't go into the archive as the lock now works.

## What binds the output already

- The run record gives each preparation manifest's digest (`inputs_sha256`, for every preparation and check arm).
- Each manifest checks against its own digest when read (`linguistic_inputs.read_preparation`).
- Each manifest records the digest of every file it made: masks, syllable records, vocabularies and token files.
- The runner refuses a consumed file whose digest doesn't match (`runner._production_provenance`).
- What wasn't checked, under every option, the plan as written included:
  - The entropy phase read each manifest by path without comparing it with the record's `inputs_sha256`.
  - Nothing checked that the counts output it reads is the stamped one: `validate_freeze` reads only `FREEZE.json`.
  - Some counts files the entropy phase reads carry no digest anywhere: each preparation's prepare-arguments file and the provisional mask it names (the NS-closest preparation reads both), and the OOV summaries, which choose escape-coded or pooled scores as the main analysis.

Both checks are now built, on branch `freeze-record-checks` (4067f7e; two outside reviews; `DECISIONS.md` 2026-11-08). First, each manifest must be the one the record names. Second, every archive member besides `FREEZE.json` must equal the project's file at the same path. Alternatively, a member `frozen-files.json` lists files by their SHA-256, and each listed file must match. Either way, the files bound must include the run record, every prepare-arguments file, the provisional masks and the OOV summaries. In the last run those came to 254 argument files (2.7 GB), 92 masks (5.5 GB, the largest 647 MB) and 163 summaries. The tests' stand-in freeze is now made after the counts phase in option B's form, as the real one will be. The check passed on the laptop rehearsal's counts output (129 files). One thing stays unbound under every option short of C: the counts run's G2P cache of readings, which the NS-closest preparation reuses. It is millions of small files, made by the counts run and never edited.

## Options

- **A. The run record, those files and every manifest, carried whole** (about 22 GB). Each validation hashes the archive, about 30 s at the measured rate, so 25 TB of reading or more over the run, shared among the scoring workers. No further code.
- **B. `FREEZE.json`, the run record and `frozen-files.json`**, the digests of the files the record doesn't bind (about 2 MB in all). Each validation reads a few MB; the parent hashes the 8 GB of listed files once per run, about a minute. The code and environment checks cost the same under every option. With the two checks, the stamp fixes every counts file the entropy phases read, apart from the G2P cache: either directly, through the listed digests, or through the chain of run record, manifests, files. The full output stays whole and packed on `/project`, so the chain can be checked from it.
- **C. The whole output, validated once per run.** Child processes would inherit the parent's validation, or a cached digest. This keeps the plan's sentence literally true and binds the G2P cache too. But it weakens the per-process check the lock was built around (T6 rounds 2–5), it's the largest change to `freeze.py` and the runner, and building the archive writes another 190 GB. The new member check would also hash the whole output once per run (about 10 minutes).

## Recommendation

B. Apart from the G2P cache, it commits to the same counts output as A or C. A change to any file the entropy phases read breaks either a digest the stamped record fixes or an archive member. It also costs almost nothing per job and needs no code beyond the checks every option needs, now built. The `DECISIONS.md` entry would say how the P7 sentence is met: the outputs are bound through the archive's members and the run record's digests, with the output kept whole beside the archive.

**Brett:** A, B or C?

**Decided** (Brett, 06:30 EST 8 Nov): "B with the cache digest". The G2P cache is bound too, one tree digest per language folder in `frozen-files.json`, checked at the start of each run and after each language's NS-closest preparation (`DECISIONS.md` 2026-11-08).
