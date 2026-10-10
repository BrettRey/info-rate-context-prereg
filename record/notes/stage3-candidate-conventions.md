# Stage 3 candidate syllable conventions: the 15 languages other than JPN and THA
<!-- SUMMARY: closed per-language lists of syllable-grouping options (deterministic rules over a fixed main G2P), each with source and page, entering the multiverse as options; revised with Brett's decisions on the counter readings 2026-10-10; counters written, to be accepted and frozen before the stamp · status: proposal · updated: 2026-10-10 -->

Drafted 2026-10-09 by Claude (Claude Code) for Brett's approval, revised the same day with the changes he approved after Sol's first review (`notes/multiverse-spec.md` §7), and revised again 2026-10-10 with his decisions on the readings the counters had to take where this note was silent (`DECISIONS.md`, 2026-10-10); "I" in this note is the drafting agent. No pipeline has run on the read texts for these languages, and no NS ratio exists for them. Until Brett approves this list and it's in a timestamped snapshot, nothing here runs on the read texts (`DECISIONS.md`, 2026-10-09, r3 entry). Tool test words below are words I chose or corpus words. Two places use the read texts' spelling only, with no syllable count and no NS value: the Serbian *ije* scan (SRP) and the check for 儿 (CMN).

## How the list is used

Under the multiverse design (`notes/multiverse-spec.md`), these are options, not candidates to choose between.

- **Options enter the multiverse if they move the count enough.** A reading whose largest effect in the corpus tally is under 0.05% of syllables in every language is fixed at its default, with the tally as the record; the others are per-language dimensions (§2.2 of the spec). The rule covers only readings the tally measured. Readings with no implemented alternative keep their defaults and are reported as not measured. Readings that move syllable boundaries without changing counts are measured on syllable types (unigram and bigram syllable entropy on the tally sample) once the pipeline segments syllables. Nothing is chosen by matching NS (Brett, 2026-10-10).
- **NS is a lens.** For each option, the per-text ratio of pipeline syllables to NS is reported, with its median, median |log ratio|, range and leave-one-text-out stability (spec §4).
- **Families.** For the shares of universes, each language's source reading (A) is one family and the variants derived from the same ambiguity are another (spec §4).
- **Closed before the stamp.** Each language's list is fixed before the timestamp that precedes any real count, with its counter written, tested on corpus words only and frozen. A bug found after the first read-text run is fixed and logged **[post hoc]**, and both results are reported.
- **The main G2P is fixed here.** The second tool's counts are reported beside the main one's.
- **Syllable boundaries between consonants** (maximal onset) change types, not counts, and are fixed before Stage 5, not here.

## Shared definitions

These apply to the main G2P's output, word by word.

- **Word:** a token between spaces, hyphens or phrase-end marks. An apostrophe inside a token doesn't split it (*dell'uomo*, *c'est*, *don't*). Curly single quotation marks (‘ ’) at a token's edges are stripped; the straight apostrophe stays part of the word, even at an edge (*po'*, *dell'*).
- **Phrase end:** one of . , ; : ? ! … « » " " „ ( ) [ ] – —, their full-width and CJK equivalents (，。；：？！、「」『』（）【】《》), or the end of a line (any line boundary).

- **Vowel symbol:** a symbol in the vowel set of `src/stage3_g2p_check.py`, with length marks and combining diacritics attached.
- **Non-syllabic:**
  - a glide symbol (j, w, ɥ);
  - a vowel carrying U+032F;
  - the second member of a tie-bar pair (U+0361).
- **Syllabic consonant:** a consonant carrying U+0329. In SRP, U+0329 is ignored because of the Epitran map bug.

**R0, as transcribed.** Every vowel symbol that isn't non-syllabic is one nucleus. A tie-bar pair is one nucleus, and so is a syllabic consonant. A chain of tied vowels, which espeak-ng writes for an English triphthong when it switches language for a name or loanword (*O'Brien* in French: ə͡ʊbɹˈa͡ɪ͡ən), is one nucleus too (Brett, 2026-10-10).

**Pairing.** Within a word, adjacent R0 nuclei (nuclei with no consonant between them) join greedily from left to right into pairs, so a syllable holds at most two R0 nuclei. A tie-bar pair counts as one nucleus. Identical vowels fuse.

**Cross-word pairing.** The same greedy pass runs over the whole phrase. A pair can then span a word boundary when one word ends in a vowel and the next begins with one, with no phrase-end mark between them. At the word-aware rungs, a syllable formed across a word boundary belongs to the left-hand word in one option and to the right-hand word in the other: a fork (Brett, 2026-10-10).

The counter in the earlier agreement check (`nuclei()`: any run of vowels is one nucleus) is none of these. Each rule above gets its own counter, tested on corpus words before the run.

**Readings the note leaves open.** Where these rules don't settle a case (runs of three or more vowels, the order of overlapping operations, Unicode details), the counters take a reading recorded in the readings table frozen with them (`notes-draft/counter-readings.md` on the counters' branch, 53 rows, each with the note's words, the reading, its alternatives and examples), as Brett decided it on 2026-10-10; a tally on 10,000 corpus lines per language measured how much text each reading touches (`notes/counter-readings-tally-2026-10-10.md`).

## Summary

| Lang | Main G2P | Candidates | Source |
|---|---|---|---|
| SPA | espeak-ng `es` | A as the tool transcribes, B maximal pairing | Martínez Celdrán et al. 2003: 256–257 |
| CAT | espeak-ng `ca` | A, B (function-word vowel loss, from the passage) | Carbonell & Llisterri 1992: 54, 56 |
| ITA | Epitran `ita-Latn` | A within word, B also across words, C each word phrase-final; lexical hiatus from English Wiktionary | Rogers & d'Arcangeli 2004: 118–120 |
| DEU | espeak-ng `de` | A only | Kohler 1990: 49 |
| ENG | CMUdict (+ g2p-en) | A as listed, B triphthongs single | Roach 2004: 241 |
| FRA | Lexique 4.1, espeak-ng for words it lacks | A every schwa kept, B elidable schwas dropped | New et al. 2026; Fougeron & Smith 1993: 75 |
| SRP | Epitran `srp-Latn` | A only | Landau et al. 1995: 83–84 |
| TUR | Epitran `tur-Latn` | A ğ as consonant, B coalescence except between front vowels | Zimmer & Orgun 1992: 44 |
| FIN | Epitran `fin-Latn` | A traditional, B /eu, ou/ split, C′ /ia, ae, eo/ merged, D both; C (three words) for calibration | Suomi et al. 2008: 49–51 |
| HUN | Epitran `hun-Latn` | A only | Szende 1994 (no diphthong described) |
| EUS | espeak-ng `eu` | A falling diphthongs, B all pairs (our extension), C A with /ui/ | Hualde et al. 2010: 121–122; Bedialauneta & Hualde 2022: 1107 |
| VIE | none (orthography) | A only | |
| KOR | g2pk2 | A only | Lee 1993: 30 |
| CMN | pypinyin | A only (erhua from an English Wiktionary lexicon) | Lee & Zee 2003: 111 |
| YUE | PyCantonese | A only | |

That makes 8 languages with more than one option (SPA, CAT, ENG, FRA and TUR with two; ITA and EUS with three; FIN with four plus a calibration-only fifth) and 7 with one.

**Second tool,** reported beside the main one and not used to choose:

- espeak-ng for ITA, ENG (`en-gb`), SRP, TUR, FIN and HUN;
- Epitran for SPA and DEU, and for CAT with its broken segments noted;
- none for EUS, VIE, KOR, CMN and YUE in this list. The segmenter forks are a separate matter (`notes/stage3-proposal-other-languages.md`).

## Per language

### SPA

- **Main G2P: espeak-ng 1.52.0, voice `es`.** Epitran `spa-Latn` has no stress and turns a stressed high vowel into a glide: *día* comes out as dja (one syllable), *país* as pais. espeak-ng writes the glides, joins falling diphthongs with a tie bar, and keeps stressed hiatus vowels separate. Test words: *día* dˈia, *país* paˈis, *piano* pjˈano, *aire* ˈa͡ɪɾe, *poeta* poˈeta, *muy* mˈuj.
- **SPA-A, as the tool transcribes: R0.** "Spanish has rising diphthongs, formed by the glides [j] or [w] plus a syllabic nucleus, and falling diphthongs, formed by a syllabic nucleus plus the glides [i̯] or [u̯]" (Martínez Celdrán et al. 2003: 256). espeak-ng keeps clashing non-high vowels as hiatus (*poeta* poˈeta, three syllables).
- **SPA-B, maximal pairing: SPA-A plus pairing and cross-word pairing.** The source attests the reduction without a fast-speech condition: "when two non-close vowels clash in the string, one of them becomes non-syllabic. In the following examples, theoretical three-syllable words become two-syllable words: poeta 'poet' [ˈpoe̯ta], maestro" (p. 257); and, for fast speech, "sequences of vowels in hiatus reduce so that one becomes [–syllabic]. If both vowels have the same timbre they fuse: la Alhambra [la ˈlambɾa]" (p. 256), an example that crosses a word boundary. Fast speech is the motivation for the cross-word part, not a partition the source sets out. **Exempt:** a hiatus with a stressed close vowel (*día*, *país*, *río*) stays two syllables in SPA-B too (Brett, 2026-10-10), since the within-word evidence quoted concerns non-close vowels only. In the corpus tally this choice moves 0.75% of Spanish syllables (2% of tokens; *había*, *día*, *país*, *tenía*).

### CAT

- **Main G2P: espeak-ng `ca`.** Epitran `cat-Latn` writes the high vowel of a diphthong as a consonant: *aigua* aʒɡwa, *noi* nɔʒ, *diu* dib, *cauen* kabɛn. Its counts can match while its segments are wrong. espeak-ng writes the glides (*aigua* ˈajɣwə, *feina* fˈɛjnə, *diu* dˈiw, *cauen* kˈawən) and keeps hiatus vowels separate (*piano* piˈanu, *Maria* məɾˈiə, *veïna* bəˈinə, *teatre* teˈatɾə).
- **CAT-A: R0.** "It is best to consider /j/ and /w/ as underlying non-syllabic elements… Diphthongs are formed with a vowel and /j/ and /w/ either preceding (rising diphthong) or following (falling diphthong)" (Carbonell & Llisterri 1992: 54). Whether a high vocoid is a glide is a lexical fact, so the lexical transcription decides it.
- **CAT-B: narrow operations read off the passage transcription** (Carbonell & Llisterri 1992: 56), each tied to its documented context:
  - *el* and *es* lose their vowel after a vowel-final word (*que el qui* [kə l ki]; *la tramuntana es posa* [lə trəmunˈtanə s ˈpɔz]);
  - *que* loses its vowel before a vowel-initial word (*que ell* [k eʎ]);
  - *i* next to a vowel is a glide (*la tramuntana i el sol* [… j əl sɔl]);
  - a word-final unstressed vowel drops before a vowel-initial word (*cada u* [ˈkaδ u]; *posa a* [ˈpɔz ə]).

  The four apply in this order, each left to right: the glide *i*; *el* and *es*; *que*; final vowels. That order reproduces the passage's *la tramuntana i el sol*, where *el* keeps its vowel after the glided *i* (Brett, 2026-10-10). Function words count as unstressed for the last operation, whatever stress espeak-ng gives them in isolation: the `unstressed_words` table of English Wiktionary's `Module:ca-IPA` (revision 91037427), less *o* (Brett, 2026-10-10), since Lloret lists "les conjuncions i, ni, si, que" among the unstressed elements and adds "Hi ha més variació en altres casos, com ara en la conjunció o, la partícula negativa no, l'indefinit un(s)" (Lloret 2011: 16; *un(s)* stays on the list, harmlessly, since it ends in a consonant): clitic pronouns, unstressed possessives ("Els possessius àtons (mon, ton, son i ma, ta, sa en singular; mos, tos, sos i mes, tes, ses en plural)", IEC, Acadèmia Oberta als Ensenyants, "Els possessius", read 2026-10-10), prepositions and their contractions, articles including the personal and Balearic ones, and the conjunctions *i, si, ni, que*. Matching is by spelling, so homographs take the function-word reading (*te* 'tea', *sa* 'healthy', reflexive *si*), a stated approximation. Whether a final unstressed vowel is deleted, glided or kept in hiatus varies (Brett's comment, citing the literature on Catalan vowel sandhi), and CAT-B's deletion is part of the check below. The passage's phrase-final *posa* [pɔz], with no following vowel, is not licensed by these operations and nothing is added for it; it stays with the check below.

  A word left without a vowel has no syllable of its own: its consonant joins the neighbouring syllable (the preceding one for *el* and *es*, the following one for *que*), and at the word-aware rungs that syllable belongs to the host word. The illustration's prose describes none of this (searches for "hiatus", "synal", "elision", "fast", "connected", "reduc": every hit concerned vowel reduction or consonant clusters), so CAT-B is an operationalisation of one speaker's passage. A check against Wheeler (1979) or Hualde (1992) was planned and dropped with the scope cut (Brett, 2026-10-10); CAT-B is reported as that operationalisation.

### ITA

- **Main G2P: Epitran `ita-Latn`.** espeak-ng `it` doesn't mark glides consistently. It writes *buono* bʊˈɔno and *paura* paˈʊra with the same ʊ, and *sei* sˈɛi without a tie, so R0 on its output has no stable meaning. Epitran writes every vowel letter as a vowel (*piano*, *buono*, *sei*), which is the input the source's rule needs.
- **ITA-A: pairing within words, with exceptions.**
  - When the last word before a phrase end ends in two vowels (*mio.*, *Italia,*), those two vowels stay two syllables; a vowel sequence earlier in that word (*paura.*) pairs as usual. "Two-syllable realisations are used where the two-vowel sequence falls at the end of a phrase, and also in some lexically prescribed cases – typically where the sequence arises from adding a prefix to a stem; one-syllable realisations are used in other cases" (Rogers & d'Arcangeli 2004: 119). Only the split between the last two vowels is protected: an earlier vowel may still pair with the first of them (*suoi.* [ˈswɔ.i], 2; *gennaio.*, 3), since the source concerns keeping the final two apart (Brett, 2026-10-10, after the tally showed the stricter reading overcounting *suoi*, *gennaio*, *febbraio*, *vuoi*, *puoi*, *miei*).
  - A frozen list of words that keep a hiatus by lexical prescription, beginning with *riuscito*, transcribed ri.u in the passage (p. 120), taken from English Wiktionary (Brett, 2026-10-10). Wiktionary's `it-IPA` says such a hiatus "must be indicated explicitly by placing a `.` between the vowels, e.g. `{{it-IPA|bi.ologìa}}`" (template documentation, read 2026-10-10), so the list takes a spelling when its IPA has an unstressed *i* or *u* before another vowel across a syllable break, the break written as a dot or as the stress mark that opens a stressed syllable (*rione* /riˈo.ne/), and only if every Wiktionary pronunciation of the spelling has that pair (homographs: *piano* is /ˈpja.no/ beside a rare /piˈa.no/). Falling sequences such as *mai* /ˈma.i/ and *auto* /ˈa.u.to/ are Wiktionary's default syllabification, not marked exceptions, and are not taken; nor are non-high sequences such as *paese*. Result: 2,039 spellings (Wiktextract extract of the 2026-09-02 dump), 0.26% of the Italian tally sample's tokens, the commonest *riesce*, *costruire*, *Luigi*, *influenza*, *statua*, *inviato*, *cliente*. Inflected forms enter only where Wiktionary gives them their own IPA; forms such as *riaperto*, *riunisco* and *riuscendo* lack it, a stated limitation.
  - The optional supporting schwa after a phrase-final consonant ("Phrase-final consonants … can be supported by a following schwa", p. 118) is listed as excluded: no option adds it.
- **ITA-B: ITA-A plus cross-word pairing within a phrase.** "Since most words in Italian end with a vowel and many begin with one, two-vowel sequences arise frequently at word boundaries" (p. 119). The phrase-final protection and the exception list take precedence over cross-word pairing.
- **ITA-C: every word treated as phrase-final.** The split between a word's last two vowels is protected in every word, with no cross-word pairing and the same exception list: a word-isolated proxy for citation forms, my reading of how the rule applies to words said alone, not something the source states.

### DEU

- **Main G2P: espeak-ng `de`.** Epitran `deu-Latn` misreads vowel letters in hiatus: *Museum* muːzɔɪ̯m, *Ruine* ryːnə. espeak-ng gives *Museum* muːzˈeːʊm, *Ruine* ruːˈiːnə, *Theater* teːˈɑːtɜ, *Bauer* bˈa͡ʊɜ. Its one deviation from the source is that it writes postvocalic r as ɾ (*Ohr* ˈoːɾ) instead of a vocalised [ɐ̯]. That changes syllable types, not counts, and goes to the Stage 4 comparison.
- **DEU-A: R0.** Postvocalic r before a consonant or word-final "is vocalized to [ɐ], which results in diphthongs (… hart, Ohr…); the ending -er is realised as [ɐ]" (Kohler 1990: 49). So vocalised r adds no syllable, and -er is one syllable. *Leiten* has two syllables in either transcription: the source writes [ˈlaɪtn̩], with a syllabic nasal and [aɪ], one of the three diphthongs its vowel table lists (p. 49); espeak-ng writes lˈa͡ɪtən, with a schwa. The source marks no diphthong as non-syllabic, so R0 would count its [aɪ] twice; the counter runs on the tool's output, where the tie makes the diphthong one nucleus. The source has no other variant of grouping.

### ENG

- **Main G2P: CMUdict** (cmudict 1.1.3), first-listed pronunciation; g2p-en 2.1.0 for words CMUdict lacks. A word CMUdict lacks has its accents stripped and is looked up in CMUdict again before it goes to g2p-en, so *café* takes CMUdict's *cafe* (Brett, 2026-10-10). A syllable is a vowel carrying a stress digit. CMUdict is a General American lexicon, while Roach describes RP. That gap is part of what the NS check measures.
- **ENG-A: CMUdict as listed.** *fire* F AY1 ER0 (2), *hour* AW1 ER0 (2), *science* S AY1 AH0 N S (2).
- **ENG-B: a closing diphthong (AY, AW, EY, OW, OY) followed directly within a word by ER0 or AH0 counts as one syllable.** "A closing diphthong can have a /ə/ vowel attached to it (e.g. fire /faɪə/); the resulting complex vowel unit may be classed as a TRIPHTHONG if it is pronounced as a single syllable" (Roach 2004: 241).
- **Syllabic consonants aren't a candidate.** They are pronounced "in place of a weak syllable containing a vowel" (p. 241), so the count doesn't change.

### FRA

- **Main source: Lexique 4.1** (New, Pallier, Schalchli, Bourgin & Gimenes 2026; CC BY-SA 4.0 per its README; Brett chose 4.1 on 2026-10-10), the successor of the paper's French lexicon (SM Table S2), with espeak-ng for words it lacks. Lexique 3.80, the paper's version, is no longer available, so the original's French pronunciations can't be matched exactly. Fields used: `2_Phono` (the Lexique alphabet), `3_Phono_IPA` (used to check the alphabet mapping entry by entry), `10_FreqMot` and `25_SyllPhono` (the syllabified form). In Lexique 4.1, "°" marks an elidable schwa (30,910 of 189,863 entries; *petite* p°tit, *abordera* abORd°Ra), while a non-elidable schwa is written "2", the symbol for /ø/ (*premier* pR2mje); the "3" of earlier manuals occurs once. Lexique lists forms by part of speech, so verb endings in -ent and -aient come out right, which Epitran's French map doesn't (64 frequent subtitle words probed: *préparent* pʀepaʀɑ̃, three syllables against two; *pleuraient* plœʀeɛ̃).
- **Homographs:** a spelling with several Lexique entries takes the pronunciation of the most frequent one by `10_FreqMot`, Lexique's frequency per entry in a 316-million-word subtitle corpus (Brett, 2026-10-10: a rule by prevalence). *Couvent* takes the noun [kuvɑ̃] (5.237 against the verb's 0.082), *content* the adjective [kɔ̃tɑ̃] (102.794 against 0.291).
- **FRA-A: every schwa the lexicon writes is kept** (° and the "2" of a non-elidable schwa).
- **FRA-B: elidable schwas (°) are dropped**, everything else kept, with the syllabification of `25_SyllPhono` where dropping ° leaves it valid.
- **Words Lexique lacks** come from espeak-ng, which applies its own schwa deletion; so FRA-A is precisely "keep the schwas the lexicon writes", and the share of corpus words supplied by the fallback is reported. On the probe words, espeak-ng's deletions matched the pattern of the passage transcription (Fougeron & Smith 1993: 75: dropped in *enveloppé* [ɑ̃vlope] and *arriverait* [aʁivʁe], kept in first syllables and monosyllables), which serves as a check on the fallback, not as a candidate.
- **Recorded, not covered:** the free variation between high vowels and glides ("there are also many cases where they are in free variation", p. 75), which also changes counts.

### SRP

- **Main G2P: Epitran `srp-Latn`** on the Latin text that Stage 2 transliterated from Cyrillic. Its U+0329 on l and n is ignored (map bug, `DECISIONS.md`).
- **SRP-A: R0, plus r as a nucleus when it stands between consonants or between a word edge and a consonant.** Landau et al. (1995: 84) describe "a syllabic trill /r/" for Croatian. Standard Croatian is based on Štokavian, "as is Standard Serbian" (p. 83).
- **The Croatian diphthong /ie/ isn't a candidate.** It's ijekavian, and the two standards "are based on different subdialects, Ijekavian and Ekavian respectively" (p. 83). In the SRP read texts, the only *ije* spellings are i + consonant j + e: *nije*, *najkasnije*, *dobijem*, *egzotičnije*, *informacije*. That comes from a scan of `data/ref/texts.tsv`, with no syllable count.

### TUR

- **Main G2P: Epitran `tur-Latn`**, because Zimmer & Orgun (1992: 44) give ü as /y/ throughout (`notes/stage3-tool-survey.md`). Epitran writes ğ as ɰ.
- **TUR-A: R0 on Epitran's output.** Intervocalic ğ is a consonant, so the vowels on either side are separate syllables: *ağaç* aɰatʃ (2), *soğuk* soɰuk (2).
- **TUR-B: intervocalic ğ is deleted except between front vowels, and two identical vowels on either side of a deleted ğ fuse into one long vowel.** Between front vowels ğ "is pronounced as a weak front-velar or palatal approximant" and stays a consonant (*değil* keeps two syllables); "elsewhere when intervocalic, it is phonetically zero" (p. 44). Dissimilar vowels stay separate syllables, so *ağaç* has 1 and *soğuk* 2. The source doesn't say whether the vowels merge once ğ is zero; limiting the merger to identical vowels is my operationalisation.
- **Word-final and preconsonantal ğ** realise "as a lengthening of the preceding vowel" (p. 44). That changes no count in either candidate. "Dipthongs [sic] can be treated as sequences of vowel and /j/" (p. 44), and /j/ is a consonant.

### FIN

- **Main G2P: Epitran `fin-Latn`.** It marks long vowels with ":" and writes every vowel letter as a vowel.
- **The FIN counter reads the spelling, not the IPA.** "A given vowel phoneme is always written with the same grapheme" (Suomi, Toivanen & Ylitalo 2008: 20). So the rules below apply to the orthographic word, and Epitran's output supplies the segments for syllable types.
- **FIN-A: the traditional classification** (Suomi, Toivanen & Ylitalo 2008: 49–50). Within a word, double vowels and the 18 diphthongs are tautosyllabic, and the 20 vowel combinations are heterosyllabic. The 18 diphthongs are /ei, yi, öi, äi, ai, oi, ui; iu, eu, au, ou; ey, iy, öy, äy; ie, yö, uo/. The 20 combinations, in spelling, are *iö, iä, ia, io; eö, eä, eo, ea; ye, yä; öe, öä; äe, äö; ae, ao; oe, oa; ue, ua*, three of them marginal (*yä, öä, ua*) ("According to the traditional classification, there are 20 vowel combinations, all with a syllable boundary between the two vowels", p. 50). The counter also splits the 18 remaining ordered pairs, which are exactly those mixing a back vowel (*a, o, u*) with a front one (*ä, ö, y*): vowel harmony keeps them out of native simple words, so they arise in loans and compounds, where a split is the natural reading (Brett, 2026-10-10).
- **Longer sequences in FIN-A** are parsed left to right, taking a double vowel or listed diphthong where one starts. "At most two of the vowels can be tautosyllabic" (p. 23). The parse reproduces the book's examples *ai.e*, *kaa.os*, *ai.oin* (p. 23) and *ai.emmin*, *hau.is*, *vaa.oissa*, *tai.oit* (p. 51).
- **FIN-B: FIN-A, except /eu/ and /ou/ are heterosyllabic outside a word's first syllable.** The book reports that speakers disagree on "whether oikeus 'justice' or talous 'economy' are di- or trisyllabic… /eu/ and /ou/ can be judged to be heterosyllabic sequences in some words by some speakers, while they are unquestionably tautosyllabic for all speakers in words like leuka 'chin' and koulu 'school'" (p. 50). The condition about position generalises from the book's examples and is my operationalisation.
- **FIN-C (calibration only): FIN-A, except the exact word forms *pian*, *tae* and *teos* are one syllable each**, the book's own examples of the opposite judgement ("speakers disagree among themselves as to whether words like pian 'soon', tae 'guarantee' or teos 'work' are mono- or disyllabic", p. 50). It changes three word types, so it is reported for its NS ratio and affected share only (spec §2.4).
- **FIN-C′: FIN-A, except the combinations /ia, iä/, /ae, äe/ and /eo, eö/ are tautosyllabic anywhere in the word**: the class the book's three examples belong to, including their harmonic counterparts; my operationalisation.
- **FIN-D: FIN-B and FIN-C′ together**, since the two ambiguities are independent and only their combination shows the joint effect.

### HUN

- **Main G2P: Epitran `hun-Latn`.** It writes no glides.
- **HUN-A: R0, so each vowel symbol is a nucleus** and every vowel sequence is a hiatus: *fiú* 2, *kalauz* 3, *koreográfia* 6. The ground is a narrow claim: searches of Szende (1994) for "diphthong", "hiatus" and "glide" return no hits, so the illustration describes no diphthong.

### EUS

- **Main G2P: espeak-ng `eu`.** Epitran has no Basque map.
- **EUS-A rule:**
  - Within a word, two adjacent vowel symbols form one syllable when the second is high (i, u, ɪ, ʊ) and the first is not.
  - Rising sequences (high then non-high) and sequences of two high vowels are separate syllables.
  - In a sequence of three, a high vowel between two others begins the next syllable.
- **EUS-A sources** (Hualde, Lujanbio & Zubiri 2010):
  - "Sequences where a high vocoid immediately follows another vowel are generally syllabified as diphthongs" (p. 121).
  - "Sequences of rising sonority, on the other hand, are most usually realized as hiatus, as are sequences of two high vocoids" (p. 122).
  - In sequences of three, "the high vocoid is resyllabified as a syllable-initial approximant consonant" (p. 122).
  - Bedialauneta & Hualde (2022: 1107) agree on falling diphthongs for Markina, though there /ui/ is one of them.
- **EUS-A is an explicit rule, not espeak-ng's R0,** so espeak-ng's own diphthong choices don't decide it. On test words they agree anyway: *aita* ˈa͡ɪta, *bihar* biˈaɾ, *buruan* buɾˈuˌan, *duin* duˈin.
- **EUS-B: pairing on all vowel sequences within a word.** "Hiatus sequences may be reduced to diphthongs in fast speech" (p. 122). Extending this to every vowel sequence, non-high ones and longer runs included, is our extension of the statement, labelled as such.
- **EUS-C: EUS-A, except /ui/ is one syllable**, with ordinary rising sequences still hiatus: Markina's falling diphthongs include [ui̯] (*duin* 'decent', Bedialauneta & Hualde 2022: 1107). A source-motivated alternative, not a Markina grammar.
- **Limitations:**
  - Both sources describe local dialects (Goizueta and Markina), not the standard language.
  - The lexical exceptions (loans keeping Spanish diphthongs, hiatus where a consonant was lost) aren't applied.
  - Markina's optional deletion of /e/ in hiatus after another vowel, in inflected forms ("/e/ is optionally deleted in hiatus after another vowel", p. 1110), is excluded: the pipeline doesn't build those dialect forms.

### VIE, KOR, CMN, YUE (one candidate each)

- **VIE:** one syllable per space-separated written syllable, after normalising where tone marks sit. No phonological source is cited for this; it's the orthography's own convention.
- **KOR:** one syllable per Hangul block of g2pk2's output. "[j, w] are considered to be components of diphthongs rather than separate consonants" (Lee 1993: 30), so glide plus vowel is one syllable, as the block structure writes it. Resyllabification moves consonants between blocks without changing their number. Checked on 300 corpus lines (1,080 eojeol): the block count of g2pk2's output equalled the input's in every line. Digits would be read out as extra blocks, but Stage 2 drops lines containing digits, and the primary texts have none.
- **CMN:** one syllable per Han character, except the erhua suffix. "er-hua refers to suffixation of a rhotacized subsyllabic [ɚ] to a rhyme, or to rhotacization of a vowel or a sequence of two vowels in a rhyme" (Lee & Zee 2003: 111), so suffixal 儿 is not a syllable of its own; 儿 as a morpheme in its own right (儿子, 女儿) is. On the corpus side, a lexicon decides which is which: built from English Wiktionary (Brett, 2026-10-10; CC BY-SA 4.0), from Standard Mandarin pinyin and the "Mandarin erhua terms" category (920 members in the extract, 47 of them without usable Standard pinyin), it records the position of each 儿/兒 that has no syllable of its own (兒媳婦兒 keeps its first 兒: 3 syllables; 哥兒們: 2), for 2,538 forms in both scripts, matched as one form. Running text has no spaces, so forms are found by longest match inside runs of Han characters (花儿女儿: 3). Where Wiktionary gives both readings (花儿 huār and huā'ér), the erhua reading is used and recorded with the result. In the tally sample 儿/兒 is 0.1% of Han characters. 儿 doesn't occur in the CMN read texts (scan of `data/ref/texts.tsv`), so NS can't bear on it.
- **YUE:** one syllable per Han character. The Latin letters in some texts already keep those texts out of the primary set.

## Before the read-text run

1. Done 2026-10-09: Brett approved the options as revised here (`DECISIONS.md`); the four quotations whose IPA I rebuilt from garbled PDF text match the page images, as checked by the r4 leak auditor, the Martínez Celdrán page also by the r5 auditor (r and ɾ in *la Alhambra* can't be told apart at the rendered resolution; the glyph fits ɾ).
2. Each rule's counter is written, tested on corpus words only and frozen, with the French ê fix, the SRP U+0329 strip, the ITA exception list, the CMN erhua lexicon and the CAT function-word list. Written 2026-10-09/10 by Codex in the Codex working copy, reviewed independently in several rounds (`DECISIONS.md`), tallied on the corpus sample; to be accepted into this project, with Brett's review of the CAT list, before the freeze.
3. Lexique 4.1 downloaded (done 2026-10-10). The CAT-B check against Wheeler or Hualde was dropped with the scope cut (Brett, 2026-10-10).
4. A full snapshot and a public snapshot are made, audited, stamped and published, and the proof anchored, before any read-text count.

The secondary run (all 15 texts) also needs the per-language digit-reading conventions, logged separately, as the Stage 3 scope entry requires. Postponed (Brett, 2026-10-10); English Wiktionary is to be considered as a source for writing numbers out. No digits survive in the Stage 2 corpora, so the conventions bear on the read texts only.
