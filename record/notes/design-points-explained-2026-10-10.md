# The remaining decisions, explained from the start
<!-- SUMMARY: plain-language explanation of the open design points and the counter rows still undecided, for Brett · status: awaiting Brett · updated: 2026-10-10 -->

You asked for more background and a simpler explanation. This replaces Part 3 of the brief, and adds the counter rows you haven't decided yet, now with what the corpus tally showed. Comment anywhere.

* * *
## Background in five steps
1. **What's measured.** For each language, the project measures two things: how fast people speak, in syllables per second; and how much information each syllable carries, in bits. Multiply them and you get the _information rate_ in bits per second.
  
2. **What "information per syllable" depends on.** It depends on how predictable each syllable is. The more of the preceding text you take into account, the more predictable a syllable becomes, so the fewer bits it carries. Each amount of context is called a **rung**:
  
  - rung 0: no context, just how common each syllable is;
    
  - rung **1w**: the previous syllable, but only inside the same word. This is the original paper's measure;
    
  - rung 1: the previous syllable, even across a word boundary;
    
  - rung 1b: the previous syllable, plus knowledge of where words begin;
    
  - rungs 2, 3, 4: the two, three or four previous syllables.
    
3. **The headline number, R.** Languages differ a lot in how fast they're spoken. The paper found they differ much less in information rate, because fast languages pack less into each syllable. R measures this: it compares how much languages vary in information rate with how much they vary in speech rate. R well below 1 means they converge. The project's question is what happens to R as you climb from rung 1w to rung 4. In shorthand, the comparison it turns on is **R₄ minus R₁w**.
  
4. **Why fake data comes first.** The tools that estimate bits per syllable are imperfect, and their errors aren't uniform. They tend to be larger for languages with more distinct syllables, and larger with more context. Errors like that could create or hide a pattern in R by themselves. So before any real data, the whole analysis is rehearsed on made-up languages where the true answer is known, to see whether it comes back right.
  
5. **The rehearsal, F3b.** It builds 17 fake languages, each with a known number of distinct syllables and known true information per syllable, and gives each a speech rate. It runs the estimator on them, computes R, and compares that with the true R.
  

* * *
## Part A. The design questions
### A1. The rehearsal doesn't test the comparison the paper turns on
**What's going on.** The fake languages in F3b are streams of syllables with no words in them. Without words, rung 1w can't be computed, since it means "the previous syllable _inside the same word_". So the rehearsal measures R₄ − R₁ instead of R₄ − R₁w.

**Why it matters.** The real result will be reported as the change from 1w. The rehearsal has checked a neighbouring comparison, not that one. We know from the separate word-boundary check (F1c) that the estimator gets rungs 1w and 1 right on their own. What we haven't checked is whether, across 17 languages, its errors move R₄ − R₁w.

**The choice.** (a) Accept the gap: F1c covers rung 1w and F3b covers the higher rungs. (b) Give F3b's fake languages words, reusing F1c's word-making process, and rerun it. That means a Codex task plus a few hours of computing.

{==**Suggestion: (b).**==}{>>accept<<}{id="c1" by="user" at="2026-10-10T11:21:31.701Z"} It's cheap, and it closes the gap on the one comparison the paper's argument rests on.
### A2. The rehearsal arranged its fake languages by the wrong property
**What's going on.** In real languages, the number of distinct syllables may go with speech rate: languages with many kinds of syllable tend to be spoken more slowly. Because the estimator's errors grow with the number of syllable types, that link is exactly where a false pattern could come from. So the plan (`notes/multiverse-spec.md` §3a) says to build the fake languages three ways: number of syllable types unrelated to speech rate; more types with slower speech; and more types with faster speech.

The code instead arranged the number of types against _information per syllable_, not against speech rate.

**Why it matters.** The two arrangements coincide when a trade-off is built into the fake data, but not when it isn't. So in some of the tested conditions, the rehearsal didn't test the arrangement the plan describes.

**Suggestion:** {==fix the code==}{>>fix it<<}{id="c2" by="user" at="2026-10-10T11:22:03.468Z"} to follow the plan, and rerun the counting-model part (a few hours of computing).
### A3. Eleven rungs or eight
**What's going on.** For rungs 2–4 there are two ways to handle word boundaries, as for rung 1b:

- **"free"**: the model is told where words begin;
  
- **"charged"**: the model has to predict word beginnings too, and those bits count as part of the information.
  

The plan lists eight rungs in all. The code computes both versions of rungs 2–4, giving eleven.

**Why it matters.** The two versions answer slightly different questions: information given the word boundaries, or information including them. For the counting model, both come from one fit, so keeping both costs nothing. For the neural model, each needs its own fit.

{==**Suggestion**==}{>>accepted<<}{id="c3" by="user" at="2026-10-10T11:22:56.520Z"}**:** keep all eleven, and report both versions of rungs 2–4.
### A4. Two small changes to when the neural model stops training
**What's going on.** The neural model checks itself on held-out text as it trains, and keeps its best version. Sol (OpenAI's gpt-6.1-sol, run through Codex) suggested two fixes:

- always keep the best version seen, even if it was only a hair better;
  
- check once more at the very end, since training currently ends a few steps after the last check.
  

**Suggestion:** {==confirm==}{>>confirm<<}{id="c4" by="user" at="2026-10-10T11:23:31.263Z"}. They're already applied to all 13 fits in the comparison now running.
### A5. A tiny correction to one fake process
**What's going on.** One fake process starts its first few syllables from slightly the wrong distribution, so its stated true answer is off by at most 0.0004 bits.

**Suggestion:** {==use the corrected start in future runs==}{>>use the corrected start in future runs<<}{id="c5" by="user" at="2026-10-10T11:23:51.264Z"}. It's an option in the code now.
### A6. The disk guard can't promise everything
**What's going on.** You set a rule that free disk space must never fall below 40 GB. The guard checks before every step and watches during it. But it can't stop other programs writing to the disk, so it can't strictly guarantee the floor. The worst moment so far was 42 GB, when the guard stopped a job as designed.

**Suggestion:** {==accept the guard as it is==}{>>accept the guard as it is<<}{id="c6" by="user" at="2026-10-10T11:24:11.115Z"}, with its margins.
### A7. Syllables never seen in training
**What's going on.** Sometimes a test syllable never appeared in the training text. The counting model then gives it a fixed "unknown" score. In the full fake-data runs this never happened.

**Suggestion:** {==keep the standard treatment, and report how often it happens==}{>>keep the standard treatment, and report how often it happens<<}{id="c7" by="user" at="2026-10-10T11:24:26.593Z"}.

* * *
## Part B. Counter rows not yet decided, with what the tally showed
The tally counted, in 10,000 lines of subtitles and Wikipedia per language, how many syllables each alternative reading would change (`notes/counter-readings-tally-2026-10-10.md`).
### B1. Row 17, Italian phrase-final vowels: the tally points to the other reading
**The rule.** At the end of a phrase, a word ending in two vowels keeps them as two syllables (_mio._ is mi-o). Rogers & d'Arcangeli: "Two-syllable realisations are used where the two-vowel sequence falls at the end of a phrase".

**What the code does.** It protects _both_ of the last two vowels from merging with anything, including a vowel before them.

**What the tally found.** Under option C, which treats every word as phrase-final, the commonest affected words come out wrong:

| Word | Code's count | Expected |
| --- | ---: | --- |
| _suoi_ | 3   | 2 ([ˈswɔ.i]) |
| _gennaio_ | 4   | 3   |

The same goes for _febbraio_, _vuoi_, _puoi_ and _miei_. The alternative protects only the split between the last two vowels and lets an earlier vowel glide as usual, which gives _suoi_ 2 and _gennaio_ 3. That matches the source's wording, since the source is about keeping the final two vowels apart, not about anything before them.

{==**Suggestion**==}{>>accept<<}{id="c8" by="user" at="2026-10-10T11:26:32.928Z"}**:** switch to the alternative (protect only the split between the last two vowels). It changes 0.16% of Italian syllables under option C, and less under A and B.
### B2. Rows 5 and 26: the code is right, and the tally shows why
- **Row 5** (identical vowels). The code pairs vowels two at a time, so Finnish _maailman_ is maa-il-man, 3. The alternative would merge the whole _aai_ run and give 2, which is wrong. Finnish option C′ shows a bigger effect (1.4%), but its affected words (_alkaen_, _takia_, _kilometriä_) have no identical vowels. So that comes from how the alternative's code interacts with C′, not from the rule itself.
  
- **Row 26** (Basque option B). The code splits espeak-ng's diphthongs before pairing. The alternative keeps them and then pairs again, which merges three vowels into one syllable: _hauek_ 1 instead of 2, _gehiago_ 2 instead of 3.
  

**Suggestion:** {==keep the code's readings for both==}{>>keep the code's readings for both<<}{id="c9" by="user" at="2026-10-10T11:27:03.137Z"}.
### B3. Row 23, Turkish ğ chains: the tally's effect is an artefact
The alternative's biggest effects are on words like _saat_ and _faaliyet_, which have no ğ at all. Real chains of deleted ğ are rare.

**Suggestion:** {==keep the code's reading==}{>>keep the code's reading<<}{id="c10" by="user" at="2026-10-10T11:27:19.700Z"}.
### B4. Row 25, Finnish vowel pairs
The book lists its 20 split pairs. The code's 18 extra splits are the pairs that mix front and back vowels, which native words don't have.

**Suggestion:** {==keep, and add the book's list to the note==}{>>keep, and add the book's list to the note<<}{id="c11" by="user" at="2026-10-10T11:27:35.515Z"}.
### B5. The other low-stakes rows
These are rows 3, 4, 6, 7, 11, 19, 20, 21, 24, 27, 28, 29, 34, 36, 37, 39, 40, 42, 43, 44 and 45. In the brief's group C, I suggested keeping the code's reading for each. The tally agrees:

- each changes less than 0.05% of syllables in real text, or nothing at all;
  
- the two large ones, rows 6 and 7, have alternatives nobody is proposing (counting every tie-bar pair as a vowel; one nucleus per vowel run), and the code's readings are the note's intended ones.
  

**Suggestion:** {==accept the code's reading for all of these as a block==}{>>accept<<}{id="c12" by="user" at="2026-10-10T12:34:49.010Z"}, unless you want to look at one.
### B6. Rows about syllable types, not counts
These are rows 46, 48, 50, 51, 52 and 53. They decide what each syllable _is_ (its exact sounds and boundaries), not how many there are. They belong with the code that builds syllable types for the estimators, which hasn't been written yet.

**Suggestion:** {==decide them then==}{>>accept<<}{id="c13" by="user" at="2026-10-10T12:35:08.009Z"}.

**Row 49** is the exception. When two words share a syllable (_la amica_, where the two a's merge), the code gives the syllable to the left-hand word. That matters for rung 1w, which only looks back inside the word. **Suggestion:** treat it as a fork, left and right, so the results show whether it matters.

* * *
## Part C. Still running
The neural settings comparison (13 fits) is on the GPU. When it finishes, the rule fixed in advance decides between 5 and 8 passes, and I'll report the result.
