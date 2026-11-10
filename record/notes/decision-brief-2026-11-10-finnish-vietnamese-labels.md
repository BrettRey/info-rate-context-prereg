# Decision brief: Finnish and Vietnamese syllable labels
<!-- SUMMARY: two label questions found on 10 Nov, before any production result was read: Vietnamese labels keep capital letters; Finnish labels are spelling where the plan says Epitran's segments; options and Claude's recommendation for each · status: both decided by Brett on 10 Nov (Finnish A, Vietnamese B2) · updated: 2026-11-10 -->

Drafted by Claude (Claude Code), 10 Nov 2026, for Brett's decision. Decided the same day: Finnish, option A; Vietnamese, option B2 (`DECISIONS.md` 2026-11-10). The production entropy job is running and nothing from it has been read. Neither question can change that run. Every figure below is a count of labels in the counts run's syllable records (`results/p9/label-scan-2026-11-10/`, `DECISIONS.md` 2026-11-10); no entropy has been computed for either question, so the choice is made without sight of results.

## 1. Vietnamese labels keep capital letters

**What happens.** A Vietnamese syllable is labelled with its written form. The code moves the tone mark to a standard place and leaves case alone, so a syllable at the start of a sentence and the same syllable inside one are two labels. From the first-listed Wikipedia record: *và* 178,393 tokens and *Và* 859; *một* 123,169 and *Một* 9,715; *các* 113,616 and *Các* 15,222 (`results/p9/label-scan-2026-11-10/brief-examples.json`).

**How much.**
- Wikipedia record (9.5 million syllables): 16% hold a capital. A quarter of those begin a line; the rest stand inside one. 12% of all syllables would take an existing lowercase label if lowercased; 3.7% are capitalised with no lowercase twin.
- Main (subtitle) run: 18% hold a capital, and lowercasing would merge 21% of the label types.

**What it touches.** Every other language's labels are pronunciations, lowercased spelling (Finnish) or a script without case, so case enters only here (apart from a handful of French label types). Vietnamese has one convention, so its labels are case-sensitive in every universe of both runs; unlike the split-gap defect, this can't be handled by leaving universes out. Capitals aren't spoken, so the labels carry distinctions the speech doesn't have. With no context, splitting a label in two can only raise the measured information per syllable. With context the direction isn't certain, because the preceding syllables are labelled more finely too. The size isn't known either way. The plan's wording ("one syllable per space-separated written syllable, after normalising where tone marks sit") doesn't mention case.

**Options.**
- **A. Leave it and report it as a limit.** No cost. The paper states that Vietnamese labels are case-sensitive and gives these counts.
- **B. Add a lowercased Vietnamese run after the 17 Nov outage**, and decide now which version the headline uses. Syllable counts, splits and budgets don't change with case, so B₀ stands; Vietnamese goes through the counts and entropy steps again under a new declared option (a small code change, reviewed). It is one of the three smallest languages by record size.
  - **B1.** The headline keeps the run as registered; the lowercased version is reported beside it.
  - **B2.** The headline uses lowercased Vietnamese; the registered version is reported beside it. Until the rerun exists, a 17-language headline is provisional.
- **C. Make case a fork of the multiverse.** Not advised: a fork is a choice that could reasonably go either way, and case-sensitive syllables aren't one.

**Recommendation: B2.** It applies the rule of the split-gap decision (a defective arm stays out of the headline), and it is decided before any result is read.

## 2. Finnish labels are spelling, where the plan says Epitran's segments

**What happens.** The plan cuts Finnish words by their spelling and labels each syllable with Epitran's transcription. The code labels each syllable with its lowercase spelling: *käsi* gives *kä* · *si*, where the plan would give *kæ* · *si*. Counts and boundaries are as planned.

**How the two differ**, measured on the first-listed Wikipedia record (26.9 million syllables; the main run wasn't compared):
1. The spelling keeps apart loan spellings that Epitran writes alike: *ca* (10,111 tokens) beside *ka* (250,221), *wa* beside *va*. 0.5% of syllables are in the rarer spelling of such a pair.
2. Epitran writes a velar nasal where the spelling has *n* before *k* (*jon.ka* as *joŋkɑ*): 0.4% of syllables.
3. Epitran also marks sounds by what follows: a dental *n* or *l* before *t*, two variants of *h*, a doubled consonant as one long one. 38% of words transcribe differently as a whole than syllable by syllable, so labels taken from Epitran would say something about the next syllable.

**What it touches.** Finnish in every universe; all of Finnish's conventions share the spelled labels.

**Options.**
- **A. Keep the spelled labels and state the departure from the plan**, with these counts, in the report and the next public record. No cost.
- **B. Also run Finnish with Epitran's labels after the outage.** This needs new code to align each transcription with the spelled syllables, a choice about the context marks in point 3, a review, and Finnish through the counts and entropy steps again.

**Recommendation: A.** The two real differences are each about half a percent of syllables and pull in opposite directions, and the plan's wording, followed literally, would have put next-syllable information into the labels.
