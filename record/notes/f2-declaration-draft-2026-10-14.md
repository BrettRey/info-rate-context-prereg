# F2, conventions: declaration
<!-- SUMMARY: declared design for the F2 fake-data check (does the matched-count correction cancel regrouping?); Brett's decisions of 2026-10-15 folded in, remaining details logged as defaults before any code or result · status: declared · updated: 2026-10-17 -->

Drafted by Claude 2026-10-14; declared 2026-10-17 with Brett's decisions of 2026-10-15 (`DECISIONS.md`: batch item 3, "keep and add neural subset, costed first"; and "1 yes, 2 yes"). The details those decisions left open are defaults, logged in `DECISIONS.md` on 2026-10-17 before any F2 code ran. Anything changed after seeing a result is marked post hoc.

The spec's line (§3a): "A fine-unit process with known entropy, regrouped losslessly (pairs, as in Sol's counterexample) and lossily (merging chosen adjacent pairs, deleting a class of units, as the real conventions do); estimated at the same k and at matched spans. Reported: how far the matched-count correction is from cancellation in cases where the true answer is known, which sets how the matched-count rate (§6) is read."

## What it checks

The matched-count rate (§6) multiplies bits per pipeline syllable by pipeline syllables per second. If two conventions cut the same speech into different units, the hope is that the unit count cancels: more, smaller units with fewer bits each, the same bits per second. Sol's counterexample (`private/reviews/sol-gelman-20261009-131804/`) shows that at the same nominal context k it needn't: grouping a binary process into pairs gives 1 bit per symbol fine and 0.469 corrected, because one previous pair spans two symbols. F2 measures how far from cancellation the correction is, with the project's estimator, where the true answer is known, and separates the convention's own effect (exact) from the estimator's (KenLM against the oracle).

## Processes (fine units)

Every process is a set of lag-m copy chains: token t copies token t − m with probability 1 − ε and is otherwise a fresh draw from p (m = 0 is independent draws). The chains are stationary from the first token, as in F1.

1. **Sol's process**: binary, X<sub>i</sub> = X<sub>i−2</sub> ⊕ E<sub>i</sub>, E<sub>i</sub> ~ Bernoulli(0.1). This is the lag-2 copy chain on a uniform binary inventory with ε = 0.2. True rates: 1 bit at k ≤ 1, h(0.1) ≈ 0.469 bits at k ≥ 2.
2. **Independent Zipf draws**, 2,000 types, exponent 1.1 (F1's).
3. **Lag-1 copy**, the same inventory, ε = 0.3 (F1's).
4. **Lag-2 copy**, the same inventory, ε = 0.3.

Budgets: 4M and 8M fine units of training text (the real B₀ is likely near 8M syllables and B₀/2 near 4M). One test set of 1M fine units per process and line length, the same for every budget, seed and regrouping. Lines of 16 fine units (subtitle-like; even, so pairs tile each line) and of 1,000. Three seeds for the training text.

## Regroupings

Every regrouping is applied to the same fine-unit training and test material, inside each line.

- **R0, fine**: the fine units themselves.
- **R1, lossless pairs**: every two consecutive fine units of a line become one unit (count ratio 1/2).
- **R2, lossless partial merge**: a unit of class A absorbs the unit after it in its line (as diphthong and hiatus conventions join a vowel to what follows). A is the types ranked 5, 10, 15, … (400 types, 14.7% of the Zipf mass); for Sol's process, A = {1}. The coarse stream determines the fine one, so nothing is lost.
- **R3, lossy deletion**: units of class D are removed (as schwa deletion and erhua do). D is the types ranked 10, 20, 30, … (200 types, 6.3% of the mass). Not run on Sol's process, where deleting either symbol leaves a constant stream.

## Oracle

The exact probability of each test unit under the source process, given exactly the context KenLM sees: the previous min(k, j) coarse units of its line, and the line start when j < k. Units before that window are unseen and marginalised, at their stationary distribution (for R2, conditioned on the window starting at a unit boundary; at a line start, not). Deleted units between survivors (R3) are marginalised by a forward pass over the hidden fine positions. For R0 the oracle is F1's reference evaluated on the test realization. Two approximations, each checked by simulation on a small inventory before the grid runs: at k = 0 the oracle uses the stationary distribution at every line position, and for R3 it ignores the line end (the chance that a line's remaining positions are all deleted).

## Estimator and comparisons

KenLM at orders 1–9 on fine units (k = 0–8) and 1–5 on coarse units (k = 0–4), scored as in production: held-out, each unit's probability normalised over unit outcomes (leaving out end of line and the unknown symbol), with the raw score beside it. For each regrouping the corrected density is (bits per coarse unit) × (coarse units ÷ fine units) on the test set. It is compared with the fine-unit density:

- (a) at the same nominal k;
- (b) at matched spans: for each coarse k, the number of fine positions its context covers on the test set (deleted positions included for R3), with its distribution reported; the fine comparison is at the k nearest the mean span.

The neural estimator on a subset of cells, costed for Brett before anything launches.

## Reported

Per process, regrouping, k, budget, line length and seed, in bits per fine unit and as a percentage of the fine oracle:

- the convention's effect: oracle-corrected coarse density minus fine oracle (exact, no estimator);
- the estimator's effect on each stream: KenLM minus oracle;
- the total: KenLM-corrected coarse density minus fine oracle;
- for R3, the deleted process's own oracle beside the fine one, since its true rate isn't the fine rate.

Monte Carlo spread over the three seeds. No pass/fail bar, as for F3: the result says how the matched-count rate is read, and anything that changes the design because of it is logged before any real estimate. The draft's comparison with F3's S1–S2 gap is dropped: F3's contrasts are on R<sub>k</sub>'s scale, not bits per unit, so the percentage of the true density is reported instead.
