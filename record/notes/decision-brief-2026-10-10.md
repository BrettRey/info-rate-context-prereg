# Decisions waiting for Brett
<!-- SUMMARY: brief for Brett's decisions on the neural settings, the 53 counter readings and the design points the overnight reviews raised · status: awaiting Brett · updated: 2026-10-10 -->

Comment on any item in Roughdraft. Each item says what the choice is, why it matters, what the options give, and what I'd do (marked **Lean**). Nothing here is settled until you say so; whatever you decide goes into `DECISIONS.md` with your name on it.

Where an item depends on code, the code is a candidate in the Codex working copy (`~/projects/codex-work/info-rate-context`), not yet in this project.

---

## Part 1. The neural model's settings

### What the model is

For each language the project needs one number per context length k: how many bits of information, on average, a syllable carries once you know the k syllables before it. That's estimated by training a model to predict the next syllable and measuring how surprised it is on text it hasn't seen. A model that predicts badly looks more surprised than a good one, so a badly trained model overstates the bits per syllable.

KenLM, the standard counting model, is one estimator. The second is a small neural network that sees exactly the k previous syllables. It's there because the overnight fake-data checks showed KenLM missing dependencies that skip over intervening syllables: on one built-in pattern KenLM made a trade-off between density and rate vanish or reverse (R₄ estimated at 1.47–1.81 where the truth was 0.61; `DECISIONS.md`, 2026-10-09).

### What "settings" means

The network learns by reading the 10 million training syllables and nudging its internal numbers after each small batch. The settings decide:

- **where it starts**: random numbers, or a head start;
- **how long it reads**: the number of passes over the training text ("epochs");
- **how big each nudge is**: the learning rate, and whether it shrinks as training goes on (a "schedule"; cosine decay shrinks it smoothly to nothing by the last pass);
- **when it stops early**: four times a pass it scores itself on separate validation text, and if a run of checks fails to improve by more than 0.0001 bits, it stops and keeps the best-scoring version. The declared settings allowed two failed checks; the newer candidates allow eight.

These have to be fixed on fake data, where the right answer is known, before any real estimate.

### What happened

The settings declared in advance (3 passes, random start, constant learning rate) stopped too early. Every fake test ran out of passes while still improving, and the estimates came out 0.04–0.19 bits too high, more with longer context and larger syllable inventories. That matters because inventory size varies across real languages: a bias that grows with inventory leaks into the cross-language comparison.

Four candidates were then tried on fresh fake data (80 fits, 10M training syllables each, 20 test conditions per candidate):

| Candidate | What it changes | Worst error (bits) | GPU hours |
|---|---|---:|---:|
| `baseline3` | the declared settings | 0.41 | 1.49 |
| `long4` | one more pass | 0.37 | 2.32 |
| `unigram_cosine3` | starts knowing each syllable's overall frequency; learning rate shrinks | 0.25 | 1.67 |
| `zero_unigram_cosine5` | same, plus context inputs start switched off, the starting point counts as a candidate, and up to 5 passes | 0.18 | 1.68 |

`zero_unigram_cosine5` starts as a plain frequency model and only learns to use context where context helps. It's best in 19 of the 20 conditions and within 0.004 bits of the best in the last. On independent draws it stops early and is essentially exact (0.001 bits or less); where the context it sees carries no information, it's within 0.013. Stopping early there is why it costs no more than the 3-pass candidate.

What it leaves: with 10,000 syllable types, a dependency between different syllables ("mapped") is still 0.14–0.18 bits short, and the conditions with real dependencies all ran to the 5-pass limit while still improving. So more passes would probably help further, at more cost.

**My lean before asking Sol (OpenAI's gpt-6.1-sol, run through Codex):** adopt `zero_unigram_cosine5`, possibly with a longer limit (say 8 passes) after one short confirming run, then rerun the neural model's fake-data checks with it before it enters the analysis.

**Sol's view** (asked independently, with the same results and without my lean; `private/reviews/codex-runs-20261009/sol-settings-20261010/`):

- **Same base:** `zero_unigram_cosine5`. On Sol's recomputation it wins 19 of 20 conditions, including 11 of the 12 where a dependency is visible, so its advantage isn't only that it starts as a frequency model.
- **Test 8 passes before fixing it.** All 12 dependency fits used the full 5 passes and picked their last checkpoint. The hardest ones were still improving by 0.02–0.03 bits over the last pass, far more than the 0.0001 threshold.
- **A specific follow-up:** 13 fits, about 1.2–2.4 GPU hours (allow 2.5). It compares 5 and 8 passes on six conditions at 10,000 types, re-tests the one condition where `unigram_cosine3` was slightly better, and uses a fresh replicate. If 8 passes doesn't help the hard cells, keep 5.
- **Two small changes to the stopping code:** always keep the best checkpoint, using the 0.0001 threshold only to decide when to stop; and check validation after the final update, which the code currently skips.
- **A tolerance miss:** the chosen candidate's bias on the simplest dependency (lag-1 copy, 10,000 types, one syllable of context) is +0.054 bits, just over the F1 check's declared 0.05 tolerance (I confirmed the number). So it can't yet be said to pass F1.
- **What the remaining error means:** the neural model recovers about 98% of the skipped mapped dependency (7.03 bits of information gained between k = 1 and 4; it estimates 6.87), which is what it's for. But its error grows with inventory and context. Where the true curve is flat, its estimate rises by 0.02–0.04 bits from k = 1 to 4, so part of any curve's shape can be estimation error. A 0.18-bit error doesn't translate into a bound on R_k, which only F3b can measure.
- **Reporting:** both estimators side by side in the named universes, with F3b's distortions next to the real results and never subtracted from them.
- **Limits of the ranking:** one replicate; the 20 conditions share samples, so "19 wins" isn't 19 independent results; the candidates bundle several changes, so the sweep can't say which change helped.

**Do we agree?** Yes on the candidate, and Sol's follow-up is a sharper version of my "one short confirming run". **Lean now:** run Sol's 13-fit comparison with its two stopping-code changes, choose 5 or 8 passes on the result, then rerun the neural F1 and F3b checks, which must also clear the copy-1 tolerance.

---

## Part 2. The syllable-counting readings

### What these are

The candidate conventions note (`notes/stage3-candidate-conventions.md`) gives rules for counting and grouping syllables in each language's transcriptions. Codex turned the rules into code. Wherever the note's wording leaves a choice open, the code had to take one reading, and each such reading is a row in `notes-draft/counter-readings.md` (branch `codex/t4-stage4-pipeline`). Once the counters are frozen and stamped, those readings become the rules, so each needs your decision first.

There are now 53 rows (the table grew during review). Every quotation in it was checked verbatim against the note, and every example was recomputed. Row numbers below match the table. They fall into five groups:

- **A**, 12 rows that change counts on real text and need a real decision;
- **B**, 3 rows a source can settle;
- **C**, 25 rows that are artificial or low-stakes, where the code's reading is fine;
- **D**, 6 rows that were defects and are already fixed;
- **E**, 7 rows that change syllable types but not counts, which belong to the Stage 5 type builder.

### A. Decisions that change counts on real text

**Row 1. Chinese and Japanese punctuation as phrase ends.** The note's list of phrase-end marks is ASCII and European (. , ; : ? ! … « » " „ ( ) [ ] – —). Chinese text uses full-width marks (，。、！？「」). Without them, a word is never seen to end at a Chinese comma, which also stops the erhua word list from matching (`花儿，女儿` counts 4 instead of 3). The code already treats the full-width equivalents as phrase ends, marked as pending your confirmation.
**Lean:** confirm. The list was written with European scripts in view.

**Row 9. Quotation marks around a word.** The note only says an apostrophe *inside* a word doesn't split it. The code keeps single quotation marks stuck to a word, so `‘哪儿’` doesn't match the erhua list, and a quoted Catalan `'el'` isn't recognised as the article. Stripping outer quotation marks fixes both, but a straight apostrophe at a word edge can belong to the word (Italian *po'*, English *'tis*).
**Lean:** strip curly single quotation marks (‘ ’) at token edges; keep the straight apostrophe as part of the word.

**Rows 10, 11, 12 and 41. Catalan option B's connected-speech rules.** CAT-B has four operations read off one speaker's passage (Carbonell & Llisterri 1992: 56):
- *el* and *es* lose their vowel after a vowel;
- *que* loses its vowel before a vowel;
- *i* next to a vowel becomes a glide;
- a word-final unstressed vowel drops before a vowel.

The note doesn't say in what order they apply, and order matters where contexts overlap.

- *Order (row 10).* The code applies the glide first, then *el*/*es*, then *que*, then final vowels. That order reproduces the passage: *la tramuntana i el sol* comes out as 7 syllables, matching the transcription the note quotes ([… j əl sɔl], where *el* keeps its vowel). The printed order gives 6. **Lean:** keep the code's order, because the passage decides it.
- *Direction (row 11).* Each operation goes left to right, and an earlier deletion can change a later context. Only invented strings separate the readings. **Lean:** keep.
- *Stress on function words (row 12).* The rule deletes a word-final *unstressed* vowel. But espeak-ng transcribes words one at a time, and in isolation it stresses monosyllables like *a* and *u*, so the rule never fires on them: *a u* stays 2, where connected speech gives 1. **Lean:** treat a frozen list of Catalan function words as unstressed. The rule is about connected speech, and isolation stress is an artefact of transcribing word by word.
- *Final* posa *(row 41).* The passage writes phrase-final *posa* as [pɔz], with no following vowel, which none of the four rules licenses. **Lean:** add nothing now. It belongs to the Wheeler or Hualde check the note already requires before CAT-B is frozen.

**Row 13. French words with two pronunciations.** Lexique lists each spelling once per part of speech. *Couvent* is a noun ('convent', 2 syllables) and a verb ('they brood', 1); *content* is an adjective (2) and a verb (1). The note says Lexique gets the *-ent* verb endings right, but that holds only if something picks the right entry, and nothing does yet.
**Options:** (a) the more frequent entry for the spelling, from Lexique's frequency columns (to confirm on download); (b) a part-of-speech tagger run on each sentence; (c) both, as a fork.
**Lean:** (a). It's simple and deterministic, and a tagger adds another tool to verify. The cost is that a homograph always gets its commoner reading.

**Row 15. English words CMUdict lacks.** For *café*, *naïve* or *coöperation*, the code strips the accent and asks the g2p-en predictor, which gives 1, 1 and 4 syllables. But *cafe*, *naive* and *cooperation* are in CMUdict, which gives 2, 2 and 5. Looking the stripped form up in CMUdict again first gets these right.
**Lean:** change to that (strip the accent, look up in CMUdict again, and only then predict).

**Row 16. Spanish option B and stressed high vowels (*día*, *país*, *río*).** SPA-B is "maximal pairing": every pair of adjacent vowels merges into one syllable, so *día* counts 1. The note grounds B in two quotations from Martínez Celdrán et al. (2003). The within-word one (p. 257) is about two *non-close* vowels clashing (*poeta*, *maestro*). The fast-speech one (p. 256) covers "sequences of vowels in hiatus" generally.
**Options:** (a) keep B maximal, as an upper bound on merging; (b) exempt hiatus with a stressed close vowel; (c) both, as two options.
**Lean:** (b). The within-word evidence the note cites concerns non-close vowels only, so merging *día* goes beyond it. The fast-speech quotation is the only support, and B already uses that for its cross-word part.

**Row 18. Italian words that keep a hiatus.** ITA-A protects lexically prescribed hiatus, which the note's source says arises "typically where the sequence arises from adding a prefix to a stem" (Rogers & d'Arcangeli 2004: 119). The list holds only *riuscito*, the one example in the passage.
**Options:** (a) keep the list at *riuscito* and state the limitation; (b) a prefix rule (*ri-*, *re-*, *pre-* before a vowel-initial stem), which would also misfire on unprefixed words like *reale*; (c) a list from an Italian pronouncing dictionary, which we don't have.
**Lean:** (a), unless you know a citable list.

**Rows 30, 31 and 33. Mandarin erhua.** The suffix 儿 usually merges with the syllable before it (花儿 *huār*, one syllable), but not in every word: 儿子 and 女儿 keep it as a syllable. The note says a word list decides, but three things are missing:
- *the list* (row 30): currently empty, so every 儿 counts as a syllable;
- *finding words in running text* (row 31): Chinese text has no spaces, so a list can't match inside an unbroken run of characters without a segmenter or longest-match lookup;
- *the traditional form 兒* (row 33).

**Lean:**
- a frozen list taken from a dictionary, with its licence checked;
- longest-match lookup inside character runs, rather than a full segmenter;
- 兒 handled the same as 儿.

**Row 38. Numbers in the secondary run.** The primary set uses only texts without digits. The secondary run uses all 15 texts, so it needs a rule for how each language reads digits aloud, and none exists. Some tools read digits their own way, while others drop them.
**Lean:** postpone the secondary run until its number readings are written and frozen. Nothing in the primary analysis depends on it.

### B. Rows a source can settle

**Row 25. Finnish vowel pairs.** FIN-A treats doubles and the 18 listed diphthongs as one syllable and every other pair as two. The note cites "the 20 vowel combinations" as heterosyllabic. With eight vowel letters, the code splits 38 pairs, not 20. The book (Suomi et al. 2008, vowel phonotactics section) does enumerate its 20 and calls three of them marginal. The other 18 pairs the code splits are exactly those mixing back and front vowels (*a*, *o*, *u* with *ä*, *ö*, *y*), which vowel harmony keeps out of native simple words. They turn up only in loans and compounds, where splitting is the natural reading anyway.
**Lean:** keep the code's reading, and add the book's list to the note.

**Row 14. Lexique's phonetic alphabet.** The code assumes the older Lexique symbol set. It has to be checked against whichever release you choose (3.83 or 4.1), so it's part of that decision, not a separate one.

**Row 41.** Above, under Catalan; it waits for the Wheeler or Hualde check.

### C. Low-stakes or artificial; the code's reading is fine

These either follow the note's wording or arise only in invented strings or malformed input. **Lean** for all: keep the code's reading.

- **3.** Cross-word pairing is one left-to-right pass over the phrase, as the note says. The alternative pairs within words first.
- **4.** A syllabic consonant beside a vowel doesn't pair with it (n̩a counts 2). This only arises in options that pair, and only with supplied transcriptions.
- **5.** A run of identical vowels pairs two at a time (aaa → 2), consistent with "at most two" per syllable.
- **6.** Longer runs of different vowels pair two at a time, as the note states.
- **7.** A tied affricate such as t͡s has no vowel, so it adds no syllable. The note's "a tie-bar pair is one nucleus" means vowel pairs.
- **11.** Catalan direction; see above.
- **17.** Italian phrase-final protection covers both of the last two vowels, which only matters in invented runs.
- **19.** An Italian listed exception protects both of its vowels; tested only on artificial entries.
- **20.** Finnish "first syllable" means the first group in the left-to-right parse; only invented words differ.
- **21, 26, 27, 28.** Basque:
  - how overlapping triple-vowel rules apply (21);
  - whether option B starts from the tool's diphthongs (26);
  - whether /ui/ includes lax vowels (27);
  - whether glides written as j or w are turned back into vowels (28).

  The live tool's output gives the same counts under either reading in the examples tested.
- **23, 24.** Turkish chains of deleted ğ, and whether vowel identity ignores diacritics. The examples are invented, and Epitran doesn't produce the marked forms.
- **29.** Vietnamese hyphenated spellings (*Việt-Nam*) count each written syllable.
- **34.** Unusual hyphen characters: the full-width hyphen-minus, the figure dash and the soft hyphen. I'd treat the soft hyphen as invisible (join the word), the full-width hyphen-minus as a hyphen, and the figure dash as a dash. These are rare.
- **36.** Unicode normalisation stays canonical (NFC). Compatibility symbols such as ㍻ aren't expanded.
- **37.** Vietnamese tokens with no letters (digits, currency signs) are excluded in the primary run.
- **39.** FIN-C's three exact words match whatever their capitalisation.
- **40.** A lone French letter can come back as its spoken name. Single-letter words such as *y* are in Lexique, so this is rare.
- **42.** A Serbian *r* standing alone isn't syllabic.
- **43, 44.** Contradictory or chained diacritics in malformed input: the code either takes the non-syllabic reading or rejects the input.
- **45.** In Catalan, a vowel-less *i* attaches to the following syllable when there is one. This changes segmentation, not counts.

### D. Defects already fixed (for information)

- **Row 2:** every kind of line break ends a phrase.
- **Row 8:** espeak-ng's language-switch labels, which counted *software* as 4 syllables, are stripped.
- **Row 22:** Turkish capital İ and I are lowercased correctly.
- **Row 32:** supplied Mandarin word boundaries can't erase separators.
- **Row 35:** every Han character counts.
- **Row 47:** French option B keeps Lexique's syllabification where it still applies.

### E. Types, not counts: for the Stage 5 type builder

These don't change how many syllables there are, only what each syllable *is* (its phones, its boundaries, which word owns it). They matter because the estimators predict syllable *types*. The type builder doesn't exist yet, so these are best decided together when it's written:
- 46: Vietnamese tone-mark placement;
- 48: French syllable boundaries after a dropped schwa;
- 50: Finnish consonant boundaries;
- 51: full syllable types and the stress fork;
- 52: Korean transcription word by word or by phrase;
- 53: Turkish ğ lengthening before a consonant.

One of them reaches further. **Row 49:** when two words share a syllable (Spanish or Italian *la amica*, where the two a's merge), the code gives that syllable to the left-hand word. That affects rung 1w, the paper's own measure, which only looks back within the word. **Lean:** keep the left-hand rule but treat it as a fork, so the analysis shows whether it matters.

---

## Part 3. Design points the reviews raised

1. **What F3b compares.** The paper's measure is rung 1w, which uses context within the word only. The project's headline is how R changes from 1w to longer contexts. F3b's fake languages have no words, so it measures the change from rung 1 instead.
   **Lean:** give F3b's fake languages word structure (the F1c process has it) and rerun it, so the check covers the contrast the paper turns on. This is a Codex task plus a few hours of KenLM.
2. **How F3b pairs inventories.** The spec says fake inventories are to be assigned "independently of syllable rate, larger inventories with slower rates, and the reverse" (`notes/multiverse-spec.md` §3a). The code pairs inventory with *density* instead. When the trade-off is built in, the two coincide roughly; when it isn't, they don't.
   **Lean:** make the code match the spec and rerun the KenLM grid.
3. **How many rungs.** Rungs 2–4 can each be computed two ways: with word boundaries known in advance, or with the model also predicting them. That gives 11 rungs where the spec lists 8. One fitted model gives both versions, so keeping both costs nothing extra.
   **Lean:** keep all 11 and report both versions of rungs 2–4. For KenLM this is free; the neural model needs a separate fit for each version, so for it the cost roughly doubles at those rungs.
4. **The stopping threshold** (0.0001 bits, inherited; see also Sol's two changes in Part 1). Under the recommended candidate, no condition with a real dependency stopped early: all ran to the limit, and only conditions where context adds nothing stopped early, which is correct. Under the original settings a few dependency conditions did stop early, at errors of 0.05–0.19 bits, so the threshold can bite when training plateaus.
   **Lean:** keep the threshold for deciding when to stop, but always keep the best checkpoint, and check validation after the last update (Sol's two changes).
5. **Where the mapped fake process starts.** It begins each chain from the overall syllable frequencies rather than its long-run mix, so the stated truth is very slightly off: at most 0.0004 bits on short tests, 0.00002 on long ones.
   **Lean:** start future runs from the long-run mix (the option now exists), and keep the old start only to reproduce past results.
6. **The disk guard's limit.** It checks free space before each step and watches during it, but it can't stop another program's writes, so it can't guarantee staying above 40 GB.
   **Lean:** accept, with the margins it has. The worst moment was in the evening, when free space reached 42 GB and task E's guard stopped its grid as designed; from then on it was 63–76 GB.
7. **Unseen syllables in fake tests.** A test syllable never seen in training gets KenLM's "unknown word" score. The code keeps the established handling and reports how many there were (none in the full runs).
   **Lean:** keep.
8. **Line length in F1c.** This is answered. Lines of 40 against 1,000 syllables change the bias by at most 0.06 bits, so future checks can use 1,000 to match the rest.

---

## Part 4. Other open items

[withheld: from private correspondence with the paper's authors]

Once you've decided, I'll merge the branches into the project, freeze the counters with your readings, and prepare the timestamped snapshot that has to come before any real count.

---
comments:
  c1:
    body: >-
      Row 1: confirm

      Row 9: strip curly single quotation marks (‘ ’) at token edges; keep the
      straight apostrophe as part of the word.

      Row 10: keep the order

      Row 11: keep

      Row 12: treat a frozen list of Catalan function words as unstressed

      Row 41: add nothing now

      Row 13: what about a rule that looks at the prevalence of each in the
      world and assigns one of the two based on that?

      row 15: strip the accent, look up in CMUdict again, and only then predict

      Row 16: b

      Row 18: already sent

      Rows 30, 31, & 33: also sent

      Row 38: postpone, but also consider English Wiktionary as a source for
      writing the numbers


      You'll have to explain the design choices more completely. I don't
      understand what I'm being asked. Provide more background and be simpler
    by: user
    at: 2026-10-10T11:14:32.603Z
