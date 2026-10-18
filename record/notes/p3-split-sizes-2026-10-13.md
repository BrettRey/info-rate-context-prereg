# P3: two open choices, held-out sizes and budget-invariant resources
<!-- SUMMARY: decision brief for Brett on P3: held-out sizes, and whether masks and onset inventories vary with the training budget; recommendations given, nothing settled · status: decided (Brett accepted both, 2026-10-13) · updated: 2026-10-13 -->

Settled already: the split is by document group (a film's folder; every episode of a series in one group; `DECISIONS.md` 2026-10-08), chosen once per language; B is set by the smallest language from training material after cleaning and the split, under first-listed options, YUE included; B/2 is nested in B with validation and test fixed; 3B on the languages that reach it, with B recomputed on that subset; the plateau is Δ<sub>k</sub> = H<sub>k</sub>(B/2) − H<sub>k</sub>(B), reported continuously, 0.05 bits a warning only (Brett, 2026-10-11).

Not settled anywhere: **how large the validation and test sets are.**

**Recommendation: the same fixed sizes in every language, in syllables: test 1,000,000 and validation 500,000**, filled by whole groups in one seeded shuffle per language (test first, then validation, the rest training), realised sizes reported. Reasons: equal held-out sizes keep each language's estimation error comparable; these are the sizes the fake-data checks (F1, F3b) used, where both estimators were shown to work; and held-out size is then independent of corpus size, so it doesn't feed into B differently by language.

The alternative is proportions (for example 80/10/10 of each language's corpus). That gives the large languages much bigger test sets than the small ones, so precision would differ across the panel.

What it costs: B shrinks by the held-out amount in the smallest language. YUE's whole Wikipedia under the drop rule is about 10.9M characters, about one syllable each (`DECISIONS.md` 2026-10-08), so B would land near 9M, close to the 10M at which the fake-data checks ran. The counts phase computes the real figure; this one is rough.

P3 is being built with the sizes as parameters, defaulting to the recommendation, so either answer only changes a setting.

## A second question, for the budget pieces

When the training budget changes (B, B/2, 3B), should the line mask and the onset inventories change with it?

**Recommendation: no. Learn them once per language from the whole training split, and let the budget forks cut only the text the models train on.** B/2 then differs from B only in how much training text the estimators see, not in where syllables are cut or which lines are scored, which is what a budget comparison is meant to isolate. It also keeps one frozen mask per language across budgets, which Stage 5 and 6 now require. The vocabulary would still be learned from the text each budget actually trains on, so a held-out syllable unseen in the B/2 training text is caught there (the open OOV question gates the B/2 run as well as B).

The alternative is to relearn the onset inventories on each budget's own training text. That keeps "training material only" in the narrowest sense, but syllable cuts, and possibly line eligibility, could then differ between B and B/2, and a different mask per budget would have to be allowed.
