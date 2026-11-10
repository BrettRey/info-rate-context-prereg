# Superseded snapshot: cite r16

`public-snapshot-2026-11-09-r15.tar.gz` (SHA-256 `8e7961a633ea4cc5d640ec1b290676acc2a8448471ba97b29cd16e20a33f84c5`) is a public build of the decision record that was timestamped at 23:15 UTC on 9 Nov 2026 and then failed a last check before publication. It was not published then, and `public-snapshot-2026-11-10-r16` supersedes it. `record/` in this repository is r16, not this copy.

It is released here, marked as superseded, on the project lead's decision of 10 Nov 2026 (`record/DECISIONS.md`), for one purpose: its timestamp. The proof beside it (`.ots`) is anchored in Bitcoin blocks 975224 (mined 23:28:26 UTC, 9 Nov 2026) and 975226 (00:06:47 UTC, 10 Nov). The production entropy job started at 06:09:49 UTC on 10 Nov, by the cluster's accounting. This copy holds the 9 Nov entries on the review of the entropy code and on the headline decision as they read before the job began; r16, timestamped after the job started, holds them unchanged.

How this copy differs from r16, in `DECISIONS.md` (every other entry it holds is unchanged in r16):
- the entry "Correction to the entry above on Codex reviews" says that no review of F2's code had run with reasoning on. One had, on 17 Oct. It counts the other review logs as 80 and 59; they were 79 and 58 files. It says "Counted today", which r16 dates to 9 Nov;
- the entry "Public record r15: the diff audit" words its sentence on what the two verifiers found differently from r16, which follows the wording of earlier audit entries. Its ending says that no existing entry was reworded and that the rebuild was compared with the audited build before stamping; r16 replaces that ending and doesn't state an order;
- r16 also has an entry dated 9 Nov that this copy lacks: the start forecast for the production job, logged on 10 Nov. It is the source of the forecast in this copy's `STATUS.md`.

r16 corrects the errors in the first entry, rewords the second, and records what was reworded in each. This copy's `STATUS.md` is the state on the evening of 9 Nov.

Also here: `public-snapshot-2026-11-09-r15.sha256`, and `snapshot-2026-11-09-r15.sha256` with `snapshot-2026-11-09-r15.tar.gz.ots`, the hash and proof of the full private record stamped at the same moment.
