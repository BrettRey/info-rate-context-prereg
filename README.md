# info-rate-context: pre-registration record

Dated, verifiable copies of the analysis plan and decision log for a replication and extension of Coupé, Oh, Dediu & Pellegrino (2019), "Different languages, similar encoding efficiency: Comparable information rates across the human communicative niche", *Science Advances* 5(9): eaaw2594, doi:10.1126/sciadv.aaw2594.

The project asks whether languages stay more alike in information rate (bits per second) than in syllable rate as the context used to estimate each syllable's information grows past the word boundary, from the paper's within-word bigram to longer n-grams. The working repository is private while the work is in progress; this repository receives a cleaned copy of its decision record whenever decisions are added, so that what was decided, and when, can be checked against the results that follow.

## What is here

- `record/`: the current decision record, readable as plain files: the plan (`SPEC.md`), the dated decision log (`DECISIONS.md`), project state (`STATUS.md`), per-language settings (`config/`), design notes (`notes/`) and the code that has run so far (`src/`).
- `snapshots/`: each published state as a deterministic archive (`public-snapshot-DATE.tar.gz`) with its SHA-256 and an [OpenTimestamps](https://opentimestamps.org) proof (`.ots`).
- `snapshots/snapshot-DATE.sha256` and `.ots` without an archive: the timestamp of the full private record, correspondence included. It can be shown in confidence to an editor; its hash and proof are public so that it can't be altered afterwards. On 2026-10-09 the full record was stamped at 10:15 UTC; the public archive was built later the same day, after the redacted text had been audited against the correspondence, from a state with further decision-log entries (the timestamps themselves, the withholding, and restatements of withheld decisions).

Passages that record or paraphrase private correspondence with the original paper's authors are replaced by `[withheld: from private correspondence with the paper's authors]`. Withholding works on whole paragraphs, so a paragraph that mixes correspondence with other material is withheld whole; decisions lost that way are restated, without the correspondence, in the decision log's section "Restated for the public record". One explanation from the correspondence, of the paper's 2265 data points, is cited there with the author's permission.

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

A public build stamped earlier that day, at 10:21 UTC, was superseded before publication and isn't published, and so were public builds r4 to r6 between r3 and r7 (`record/DECISIONS.md`). Proofs marked as stamped are complete once `ots upgrade` adds the Bitcoin attestation.

## Licence

CC BY 4.0 (`LICENSE`). The original paper's data and code are the authors' and are not redistributed here.
