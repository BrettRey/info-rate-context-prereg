# info-rate-context: pre-registration record

Dated, verifiable copies of the analysis plan and decision log for a replication and extension of Coupé, Oh, Dediu & Pellegrino (2019), "Different languages, similar encoding efficiency: Comparable information rates across the human communicative niche", *Science Advances* 5(9): eaaw2594, doi:10.1126/sciadv.aaw2594.

The project asks whether languages stay more alike in information rate (bits per second) than in syllable rate as the context used to estimate each syllable's information grows past the word boundary, from the paper's within-word bigram to longer n-grams. The working repository is private while the work is in progress; this repository receives a cleaned copy of its decision record whenever decisions are added, so that what was decided, and when, can be checked against the results that follow.

**Current record: r16** (2026-11-10), in `record/` and `snapshots/public-snapshot-2026-11-10-r16.tar.gz`. The plan is also registered on OSF: https://osf.io/m4cjp (Open-Ended Registration, registered 2026-11-09 17:36 UTC), with public r14 as its registered copy. The production entropy job started at 06:09:49 UTC on 2026-11-10; no result from it had been read when r16 was published.

## What is here

- `record/`: the current decision record, readable as plain files: the plan (`SPEC.md`), the dated decision log (`DECISIONS.md`), project state (`STATUS.md`), per-language settings (`config/`), design notes (`notes/`) and the code that has run so far (`src/`).
- `snapshots/`: each published state as a deterministic archive (`public-snapshot-DATE.tar.gz`) with its SHA-256 and an [OpenTimestamps](https://opentimestamps.org) proof (`.ots`).
- `snapshots/superseded/`: public r15, a build that was timestamped and then failed a last check before publication, released afterwards marked as superseded because its timestamp falls before the production job started. Its `README.md` says how it differs from r16. Cite r16.
- `snapshots/snapshot-DATE.sha256` and `.ots` without an archive: the timestamp of the full private record, correspondence included. It can be shown in confidence to an editor; its hash and proof are public so that it can't be altered afterwards. On 2026-10-09 the full record was stamped at 10:15 UTC; the public archive was built later the same day, after the redacted text had been audited against the correspondence, from a state with further decision-log entries (the timestamps themselves, the withholding, and restatements of withheld decisions).

Passages that record or paraphrase private correspondence with the original paper's authors are replaced by `[withheld: from private correspondence with the paper's authors]`. Withholding works on whole paragraphs, so a paragraph that mixes correspondence with other material is withheld whole; decisions lost that way are restated, without the correspondence, in the decision log's section "Restated for the public record". One explanation from the correspondence, of the paper's 2265 data points, is cited there with the author's permission.

## Data

The Wikipedia text the study counts, with each row's syllables, in all 17 languages, is published separately: Reynolds, B. (2026), *Syllabified Wikipedia text in 17 languages, as counted for a study of cross-linguistic information rate* [Data set], Zenodo, https://doi.org/10.5281/zenodo.24134212 (CC BY-SA 4.0). A mirror is at https://huggingface.co/datasets/BrettRey/syllabified-wikipedia.

## Checking a date

Two independent records:

1. The OpenTimestamps proof. With the client (`pip install opentimestamps-client`): `ots verify snapshots/public-snapshot-DATE.tar.gz.ots` checks that the archive's hash was committed to the Bitcoin blockchain no later than the block it names. A proof is complete once `ots upgrade` has added the Bitcoin attestation.
2. GitHub's record of when each commit to this repository was pushed. Commit dates themselves are set by the author's machine and prove nothing on their own.

Each archive lists its files; `tar -tzf` shows them, and unpacking it should reproduce `record/` as it stood in that commit.

## Snapshots

| Date | Public archive | Full record SHA-256 | Milestone |
|---|---|---|---|
| 2026-10-09 | `public-snapshot-2026-10-09-r3`, SHA-256 `e18281aace6501b54a72ce87f9f06440ce4de4ac713a2884771965173b4f6d0f` (anchored in Bitcoin block 970627, 12:21:03 UTC) | `38ee5150dee1ff71e13a9f1c3a66446944809b54b4df3444fb9f3765bb3b0d34` (anchored in Bitcoin block 970616, 10:17:51 UTC) | Stages 1–2 done; before any syllable count, ratio to the authors' syllable counts, or entropy |
| 2026-10-09 | `public-snapshot-2026-10-09-r7`, SHA-256 `e602c2b83bd3b8fd2a4a724a29f7ca889e9a2c7762a5c4e2c6597826df2afb93` | `fc7a619452dbdd5e5e762cc71984199b3d2a94f12b89de5c4453e990f6129ca3` (both anchored in Bitcoin block 970662, 17:21:20 UTC) | Stage 3 candidate syllable conventions proposed for 15 languages, not yet approved; Japanese and Thai comparison with the authors' syllable counts paused while the selection rule is settled; still no syllable count on a read text, no ratio to the authors' counts and no entropy in any language |
| 2026-10-09 | `public-snapshot-2026-10-09-r8`, SHA-256 `f7751f1428b0b1b58bfde0499f434653d65e26282ab7323056c64189f6b59a1a` | `efa430c8b81799c97540131922b8f11ffd48432d17e77c822c520509a25b1510` (stamped 23:05 UTC) | The design becomes a multiverse over the approved forks, replacing selection by the authors' syllable counts; fake-data checks with known answers (estimator, code, whole analysis) before any real estimate; candidate options revised; still no syllable count on a read text, no ratio to the authors' counts and no syllable entropy of a real corpus |
| 2026-10-10 | `public-snapshot-2026-10-10-r11`, SHA-256 `d8b2b3a6efd30687cc0ab802aee4addc8d5069c128d4f497946e2303d07d40cf` | `9e4a449fbe71b9301f4d378087ccdddd3b88a082794d4823c3a2d8145f3ab0a8` (both anchored in Bitcoin block 970794, 16:54:16 UTC) | Counter readings cut by a corpus tally; the rows that move syllable boundaries chosen by a count; still no syllable count on a read text, no ratio to the authors' counts and no syllable entropy of a real corpus |
| 2026-10-18 | `public-snapshot-2026-10-18-r12`, SHA-256 `3f1883e5eeb6f76d19ca7c736627723b652aa372968b656567b511c3ee0d39bd` | `469f9c934bdc5aae691253d04a849423e569cddd2f3e87dbaafa268773d4979b` (both anchored in Bitcoin block 971986, 11:33:38 UTC) | The production steps built and rehearsed on invented text; reporting choices fixed; same hold |
| 2026-11-08 | `public-snapshot-2026-11-08-r13`, SHA-256 `0fd2ffd4eb891bf8ba487c301bec628cf1de743a43825b02555062b2d6af7322` | `1d8ea343219f71c543f7f20080183152bd8f2ba30e5dfe59d678b6c4f5176840` (both anchored in Bitcoin block 975020, 04:43:25 UTC) | The counts phase on the Alliance's Fir cluster; the onset-rule amendment, with its validation record; the fake-data check at the real training budget; same hold |
| 2026-11-09 | `public-snapshot-2026-11-09-r14`, SHA-256 `add8c58dd3affa2c5cd2353f987e27f2b8400867b691b624d78d47c69ff14e6c` | `1f67950aa742f4df5f0fc8be6a65aa4f1dbe5c1225b97e30824dbb1d821c56ca` (both anchored in Bitcoin blocks 975172, 12:07:47 UTC, and 975173, 12:10:32 UTC) | Counts done and checked; the freeze archive that locks the entropy code built, stamped and anchored (block 975165); before any entropy. The copy registered on OSF |
| 2026-11-09 | Superseded: `superseded/public-snapshot-2026-11-09-r15`, SHA-256 `8e7961a633ea4cc5d640ec1b290676acc2a8448471ba97b29cd16e20a33f84c5` | `3f5999f0b106592b7f6cb6b9395066a8e9e0f5e927082ec12b5acda4ee122814` (both anchored in Bitcoin blocks 975224, 23:28:26 UTC 9 Nov, and 975226, 00:06:47 UTC 10 Nov) | The review of the frozen entropy code and the decision to compute the headline over the gap-dropping universes, recorded before the production job started (06:09:49 UTC 10 Nov). Failed a last check (a false sentence and two miscounts in a correction entry); superseded by r16 |
| 2026-11-10 | `public-snapshot-2026-11-10-r16`, SHA-256 `d7e8c5dc9b6bb4253a3dee32d70f302ff8e798ebf94bd8bb385d46894f905749` | `5a2e584a9ab89b1358b8136f69530480ec9a27e6a6633819d55375e1ded5684a` (both anchored in Bitcoin blocks 975324, 16:57:06 UTC, 975325 and 975342) | Reviews of the syllable-count code and their findings, logged before any result is read; Finnish keeps its spelled labels; Vietnamese labels to be lowercased and recomputed; the production job running, no result read |

A public build stamped earlier on 2026-10-09, at 10:21 UTC, was superseded before publication and isn't published, and so were public builds r4 to r6 between r3 and r7, and r9 and r10 before r11; public r15 was superseded before publication and later released for its timestamp (`snapshots/superseded/`). The record's own list of every snapshot, published or not, is in the decision log (`record/DECISIONS.md`). Proofs marked as stamped are complete once `ots upgrade` adds the Bitcoin attestation.

## Licence

CC BY 4.0 (`LICENSE`). The original paper's data and code are the authors' and are not redistributed here.
