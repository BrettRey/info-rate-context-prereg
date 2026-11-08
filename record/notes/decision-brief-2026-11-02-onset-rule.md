# Decision brief: where syllables split (the onset rule)
<!-- SUMMARY: the pre-registered onset rule misplaces syllable boundaries in Basque, Spanish, Catalan and Turkish; measured in all ten onset languages; one proposed rule, its cost and what it leaves; Brett decides · status: awaiting Brett · updated: 2026-11-02 -->

Status: for Brett. Nothing is settled until you comment. Numbers are from `results/p9/onset-inventories/diagnosis/` and `DECISIONS.md` (2 Nov entries). Everything here is counts on subtitle text: no entropy, no read texts, no NS.
## What the rule does and where it goes wrong
The rule you set on 10 October (pre-registered) splits a word between two vowels by maximal onset: the consonants between them go to the second syllable if, together, they can begin a word, using a list learned from the words of each language's corpus (at least 3 word types, from words Wiktionary lists, since 15 October). A syllable count never depends on this, so speech rate and NS don't move. The syllable _types_ do, and with them the within-word ID that's the replication target and our low rungs.

Three faults:

1. **A consonant that never begins a word can never begin a syllable**, so between two vowels it is pushed into the syllable before. In the pronunciations, Spanish, Catalan and Basque taps and the soft _b d g_ sounds never begin a word, so _nada_ comes out `nað . a`, _para_ `paɾ . a`, Catalan _cada_ `kað . ə`, Basque _hiru_ `iɾ . u`; Turkish _dağı_ `daɰ . ɯ`. This is the big one, and none of the pre-registered checks can see it: floors 1 and 10 and the all-types inventory are all learned from the starts of words.
  
2. **Loanword clusters that Wiktionary lists pass the floor.** Spanish _st_, _sp_, _sm_ and others make _estar_ `e . staɾ` and _mismo_ `mi . smo`.
  
3. **Initialisms are in every language's word list**, lowercased into "words" (_NBE_ gives Basque _nb_; English gets _BW_, _SR_, _VR_).
  

The Basque sources support the diagnosis for the tap: in Markina Basque "coda rhotics are realized as trills, not as taps" (Bedialauneta Txurruka & Hualde 2022, _JIPA_ 53(3), doi:10.1017/S0025100322000032). For the other languages, the principle that one consonant between vowels begins the second syllable is general phonology I haven't checked against a source.
## Proposed rule
- **A lone consonant between two vowels of a word begins the second syllable**, whether or not it ever begins a word. A long (doubled) consonant, Italian _fatto_ `fatː . o`, stays where it is now, closing the first syllable, since splitting it isn't possible with one symbol and the first half belongs there.
  
- **Clusters are learned as now** (from the starts of words, floor 3), but only from listed word types that aren't initialisms (all-capitals headwords and their forms) or that Wiktionary doesn't tag as unadapted borrowings.
  

Share of syllable labels the proposed rule moves, against today's default (5,000 subtitle lines per language, one main-run declaration each):

| Language | Moved | What moves |
| --- | ---: | --- |
| Basque | 39.6% | taps, soft _b d g_, _ts_, _ll_, _ñ_, _y_; _nb_ dropped |
| Spanish | 28.2% | taps, soft _b d g_; seven _s_-clusters dropped |
| Catalan | 20.1% | taps, soft _b d g_ |
| Turkish | 4.4% | soft _g_ (_ğ_); four clusters dropped |
| German | 2.0% | _ch_ (_x_), _ng_, two rare sounds; four clusters dropped |
| Italian | 0.7% | _z_ (_ts_) and two rarities |
| English | 0.6% | ten initialism clusters dropped; _ng_ |
| Serbian | 0.04% | two rarities |
| Hungarian | 0.01% | one rarity, one cluster |
| French | 0   | nothing |
## What it leaves
- Basque _s̺k_ and _ps̺_ aren't tagged as borrowings, so they stay (dropping them too moves about 1.2% more of Basque labels), and Spanish _sk_ stays.
  
- English and German _ng_ would begin a syllable (_si.nger_), where the usual analysis puts it at the end of the first. Small: English _ng_ is 12 cases in 5,000 lines.
  
- Long consonants close the first syllable, as now.
  
## Options
- **A. Keep the rule and report it.** Known errors of 20–40% of syllable labels in three languages, invisible to the planned checks. I don't recommend it.
  
- **B. The proposed rule** (above), recorded as a deviation from the pre-registration made before any entropy is seen. Recommended.
  
- **C. Hand-checked onset lists per language** from published descriptions. Most accurate, least uniform, and needs a phonologist's time per language.
  

The part of B that a reader could fairly question is the cluster filter's reliance on Wiktionary's borrowing tags, which are uneven (it catches Spanish _st_, misses Basque _s̺k_). The lone-consonant part is the one that matters most and is the least controversial.
## Cost if B
- **Compute:** re-prepare the ten languages on Fir. The original preparations took Italian 21 h (main) and 52 h (Wikipedia), the longest, so about 3 days, perhaps 2 split over two nodes. Syllable counts don't change, so B₀, the budget plans and the masks stay. A fresh run folder is needed (the reuse check covers only one module).
  
- **Code:** the segmenter's cut and the onset-list builder; tests; one outside review.
  
- **Record:** a dated deviation in the public pre-registration (publication needs your go).
  
- **Storage:** a second archive of about 200 GB on scratch while the project-space request is open.
  
- **Then:** the after-counts checks again (masks by reason, the inventories), then the freeze.
  
## Decision needed
1. A, B or C?
  
2. If B: also drop Basque _s̺k_ and _ps̺_ by hand (about 1.2% of Basque labels), or leave them as the general rule finds them?
  
3. If B: go ahead with the code, the review and the Fir re-preparation now, with the public-record entry drafted for your approval?

*Note added 8 November 2026:* Brett's decision on this brief (comment c1, below) likely adopts an assessment prepared with ChatGPT; its links carry ChatGPT's referral tag. The same holds for his review of the 19 English and German words (see the amendment).

---
comments:
  c1:
    body: |-
      I’d choose B with a small amount of C: keep the general procedure, but add a few explicit, sourced linguistic constraints. I’d authorize the code, review, and amendment draft now. I’d launch the full Fir re-preparation once a short validation pass has settled those constraints.

      The brief’s central diagnosis is convincing. But B as written understates two remaining problems: the same allophonic mismatch can affect clusters, and the treatment of geminates is a substantive representational choice. Both deserve attention before a three-day rerun.

      I’m taking the numerical results from your brief; I’ve checked the linguistic evidence, not the underlying diagnosis files.

      ## 1. The original rule needs changing

      The rule conflates three things:

      - Whether a segment or cluster occurs word-initially in the sampled vocabulary.
      - Whether it occurs there in the particular pronunciation representation.
      - Whether it can begin a word-internal syllable.

      The first two don’t establish the third. Changing the frequency floor can’t repair a systematically missing class of legitimate onsets. The brief is right that the preregistered inventory checks share the assumption that causes the problem.

      For Spanish, there’s good published support for assigning a single intervocalic consonant to the following syllable. Ramsammy and colleagues’ discussion of Spanish syllabification explicitly identifies this as the descriptive consensus, including word-internal VCV sequences. So the motivating correction doesn’t have to rest on unsourced general phonology. [Cambridge Core](https://www.cambridge.org/core/journals/journal-of-the-international-phonetic-association/article/contextual-reduction-of-wordfinal-l-in-spanish-an-epg-study/CFBE280941AF6D2C0E75392A26BD968C?utm_source=chatgpt.com)

      One wording correction matters: the approximants don’t literally *never begin a word*. Spanish word-initial /b d g/ can have approximant realizations in connected speech—for example, *mi bola* with [β]. Their absence here is from the word-initial representations used to build this inventory. That makes the underlying problem more precise: the procedure is transferring restrictions from citation-form realizations to other phonological environments. [Cambridge Core](https://www.cambridge.org/core/journals/studies-in-second-language-acquisition/article/crosslanguage-interactions-of-phonetic-and-phonological-processes/803196DEA17B80CCCA7FA090D185FCE1?utm_source=chatgpt.com)

      I wouldn’t retain A as the primary measurement procedure just because it was preregistered. The independent linguistic evidence provides a reason to amend it before examining the target results.

      ## 2. The singleton correction may leave the same error inside clusters

      This is the first thing I’d check in the candidate implementation.

      Consider Spanish *padre* [ˈpa.ðɾe] and *libro* [ˈli.βɾo]. These dotted transcriptions occur explicitly in Cabrelli Amaro’s dissertation; the standard account licenses the corresponding obstruent–liquid clusters both word-initially and word-medially. [ufdcimages.uflib.ufl.edu](https://ufdcimages.uflib.ufl.edu/UF/E0/04/52/25/00001/CABRELLI_AMARO_J.pdf?utm_source=chatgpt.com)

      If the learned inventory contains word-initial [bɾ] but lacks [βɾ], a special rule for a lone intervocalic consonant won’t establish the correct onset in *libro*. Even adding [ɾ] to the singleton onset inventory can produce [liβ.ɾo], which still splits the cluster incorrectly.

      That’s a prediction from the brief’s description, not a finding about the code. The implementation might already handle the relevant equivalences. But it needs an explicit check.

      I’d distinguish:

      - The pronunciation symbols retained in the syllable labels.
      - The equivalences used to decide whether an onset is licensed.

      A small, language-specific mapping could allow evidence for [bɾ] to license [βɾ], while preserving [βɾ] in the output. That would repair the syllabification without also changing the project’s phonetic distinctions.
    by: user
    at: 2026-11-02T18:36:06.494Z
