# Stage 3 candidate syllable conventions: the 15 languages other than JPN and THA
<!-- SUMMARY: closed per-language lists of syllable-grouping candidates (deterministic rules over a fixed main G2P), each with source and page, for NS to choose between under the approved rule; awaiting Brett's approval, then a timestamped snapshot before any read-text run · status: proposal · updated: 2026-10-09 -->

Drafted 2026-10-09 by Claude (Claude Code) for Brett's approval; "I" in this note is the drafting agent. No pipeline has run on the read texts for these languages, and no NS ratio exists for them. Until Brett approves this list and it's in a timestamped snapshot, nothing here runs on the read texts (`DECISIONS.md`, 2026-10-09, r3 entry). Tool test words below are words I chose or corpus words. Two places use the read texts' spelling only, with no syllable count and no NS value: the Serbian *ije* scan (SRP) and the check for 儿 (CMN).

## How the list is used

- The approved rule (`notes/stage3-proposal-units-jpn-tha.md`, §1) chooses between candidates. For each primary text, take the ratio of pipeline syllables to NS. The main candidate is the one whose median ratio is closest to 1, and candidates within 0.01 of it are kept as arms. Every candidate's median and per-text range is reported.
- In a language with one candidate, nothing is chosen. Its NS ratio is reported as a check on the pipeline.
- Approval is of the candidate set. A rule's wording may be tightened while its counter is tested on corpus words, with every change logged. The timestamp covers the final text, before any read-text run.
- Each language's list is closed. No candidate is added or dropped after the first read-text run. An implementation bug found after that run is fixed, the fix is logged **[post hoc]**, and both results are reported.
- The main G2P for each language is fixed here. The second tool's counts are reported beside the main one's but don't take part in the choice (`DECISIONS.md`, correction to the G2P agreement check).
- Syllable boundaries between consonants (maximal onset) change syllable types, not counts, so NS can't decide them. They're fixed before Stage 5, not here.

## Shared definitions

These apply to the main G2P's output, word by word.

- **Word:** a token between spaces, hyphens or phrase-end marks. An apostrophe inside a token doesn't split it (*dell'uomo*, *c'est*, *don't*).
- **Phrase end:** one of . , ; : ? ! … « » " " „ ( ) [ ] – —, or the end of a line.

- **Vowel symbol:** a symbol in the vowel set of `src/stage3_g2p_check.py`, with length marks and combining diacritics attached.
- **Non-syllabic:**
  - a glide symbol (j, w, ɥ);
  - a vowel carrying U+032F;
  - the second member of a tie-bar pair (U+0361).
- **Syllabic consonant:** a consonant carrying U+0329. In SRP, U+0329 is ignored because of the Epitran map bug.

**R0, as transcribed.** Every vowel symbol that isn't non-syllabic is one nucleus. A tie-bar pair is one nucleus, and so is a syllabic consonant.

**Pairing.** Within a word, adjacent R0 nuclei (nuclei with no consonant between them) join greedily from left to right into pairs, so a syllable holds at most two R0 nuclei. A tie-bar pair counts as one nucleus. Identical vowels fuse.

**Cross-word pairing.** The same greedy pass runs over the whole phrase. A pair can then span a word boundary when one word ends in a vowel and the next begins with one, with no phrase-end mark between them.

The counter in the earlier agreement check (`nuclei()`: any run of vowels is one nucleus) is none of these. Each rule above gets its own counter, tested on corpus words before the run.

## Summary

| Lang | Main G2P | Candidates | Source |
|---|---|---|---|
| SPA | espeak-ng `es` | A citation, B fast speech | Martínez Celdrán et al. 2003: 256 |
| CAT | espeak-ng `ca` | A only | Carbonell & Llisterri 1992: 54 |
| ITA | Epitran `ita-Latn` | A within word, B also across words | Rogers & d'Arcangeli 2004: 119 |
| DEU | espeak-ng `de` | A only | Kohler 1990: 49 |
| ENG | CMUdict (+ g2p-en) | A as listed, B triphthongs single | Roach 2004: 241 |
| FRA | open (see FRA) | A schwa kept, B medial schwa dropped | Fougeron & Smith 1993: 75 |
| SRP | Epitran `srp-Latn` | A only | Landau et al. 1995: 83–84 |
| TUR | Epitran `tur-Latn` | A ğ as consonant, B coalescence | Zimmer & Orgun 1992: 44 |
| FIN | Epitran `fin-Latn` | A traditional, B /eu, ou/ split | Suomi et al. 2008: 49–51 |
| HUN | Epitran `hun-Latn` | A only | Szende 1994 (no diphthong described) |
| EUS | espeak-ng `eu` | A falling diphthongs, B fast speech | Hualde et al. 2010: 121–122 |
| VIE | none (orthography) | A only | |
| KOR | g2pk2 | A only | Lee 1993: 30 |
| CMN | pypinyin | A only | |
| YUE | PyCantonese | A only | |

That makes 7 languages with two candidates (FRA's main G2P still open) and 8 with one. Under FRA option 1, French would have one.

**Second tool,** reported beside the main one and not used to choose:

- espeak-ng for ITA, ENG (`en-gb`), SRP, TUR, FIN and HUN;
- Epitran for SPA and DEU, and for CAT with its broken segments noted;
- none for EUS, VIE, KOR, CMN and YUE in this list. The segmenter forks are a separate matter (`notes/stage3-proposal-other-languages.md`).

## Per language

### SPA

- **Main G2P: espeak-ng 1.52.0, voice `es`.** Epitran `spa-Latn` has no stress and turns a stressed high vowel into a glide: *día* comes out as dja (one syllable), *país* as pais. espeak-ng writes the glides, joins falling diphthongs with a tie bar, and keeps stressed hiatus vowels separate. Test words: *día* dˈia, *país* paˈis, *piano* pjˈano, *aire* ˈa͡ɪɾe, *poeta* poˈeta, *muy* mˈuj.
- **SPA-A (citation): R0.** "Spanish has rising diphthongs, formed by the glides [j] or [w] plus a syllabic nucleus, and falling diphthongs, formed by a syllabic nucleus plus the glides [i̯] or [u̯]" (Martínez Celdrán et al. 2003: 256).
- **SPA-B (fast speech): SPA-A plus pairing and cross-word pairing.** "In fast speech, sequences of vowels in hiatus reduce so that one becomes [–syllabic]. If both vowels have the same timbre they fuse: la Alhambra [la ˈlambɾa]" (p. 256). The source's example crosses a word boundary, so B applies across words as well as within them.

### CAT

- **Main G2P: espeak-ng `ca`.** Epitran `cat-Latn` writes the high vowel of a diphthong as a consonant: *aigua* aʒɡwa, *noi* nɔʒ, *diu* dib, *cauen* kabɛn. Its counts can match while its segments are wrong. espeak-ng writes the glides (*aigua* ˈajɣwə, *feina* fˈɛjnə, *diu* dˈiw, *cauen* kˈawən) and keeps hiatus vowels separate (*piano* piˈanu, *Maria* məɾˈiə, *veïna* bəˈinə, *teatre* teˈatɾə).
- **CAT-A: R0.** "It is best to consider /j/ and /w/ as underlying non-syllabic elements… Diphthongs are formed with a vowel and /j/ and /w/ either preceding (rising diphthong) or following (falling diphthong)" (Carbonell & Llisterri 1992: 54). Whether a high vocoid is a glide is a lexical fact, so the lexical transcription decides it.
- **No second candidate.** I searched the illustration for "hiatus", "synal", "elision", "fast", "connected" and "reduc". Every hit concerned vowel reduction or consonant clusters, and none mentioned reducing vowel sequences. A fast-speech or cross-word candidate would need a source, such as a Catalan phonology from the UofT library.

### ITA

- **Main G2P: Epitran `ita-Latn`.** espeak-ng `it` doesn't mark glides consistently. It writes *buono* bʊˈɔno and *paura* paˈʊra with the same ʊ, and *sei* sˈɛi without a tie, so R0 on its output has no stable meaning. Epitran writes every vowel letter as a vowel (*piano*, *buono*, *sei*), which is the input the source's rule needs.
- **ITA-A: pairing within words, with one exception.** When the last word before a phrase end ends in two vowels (*mio.*, *Italia,*), those two vowels stay two syllables. A vowel sequence earlier in that word (*paura.*) pairs as usual. "Two-syllable realisations are used where the two-vowel sequence falls at the end of a phrase, and also in some lexically prescribed cases – typically where the sequence arises from adding a prefix to a stem; one-syllable realisations are used in other cases" (Rogers & d'Arcangeli 2004: 119). Prefix cases can't be identified without a morphological lexicon, so that part of the rule isn't applied. This is a limitation.
- **ITA-B: ITA-A plus cross-word pairing within a phrase.** "Since most words in Italian end with a vowel and many begin with one, two-vowel sequences arise frequently at word boundaries" (p. 119).
- **Considered, not listed:** each word treated as phrase-final, which is how the same rule would apply to citation forms. It's my inference, not something the source states.

### DEU

- **Main G2P: espeak-ng `de`.** Epitran `deu-Latn` misreads vowel letters in hiatus: *Museum* muːzɔɪ̯m, *Ruine* ryːnə. espeak-ng gives *Museum* muːzˈeːʊm, *Ruine* ruːˈiːnə, *Theater* teːˈɑːtɜ, *Bauer* bˈa͡ʊɜ. Its one deviation from the source is that it writes postvocalic r as ɾ (*Ohr* ˈoːɾ) instead of a vocalised [ɐ̯]. That changes syllable types, not counts, and goes to the Stage 4 comparison.
- **DEU-A: R0.** Postvocalic r before a consonant or word-final "is vocalized to [ɐ], which results in diphthongs (… hart, Ohr…); the ending -er is realised as [ɐ]" (Kohler 1990: 49). So vocalised r adds no syllable, and -er is one syllable. A syllabic nasal (*leiten* [ˈlaitn̩], p. 49) gives two syllables in either transcription. The source has no other variant of grouping.

### ENG

- **Main G2P: CMUdict** (cmudict 1.1.3), first-listed pronunciation; g2p-en 2.1.0 for words CMUdict lacks. A syllable is a vowel carrying a stress digit. CMUdict is a General American lexicon, while Roach describes RP. That gap is part of what the NS check measures.
- **ENG-A: CMUdict as listed.** *fire* F AY1 ER0 (2), *hour* AW1 ER0 (2), *science* S AY1 AH0 N S (2).
- **ENG-B: a closing diphthong (AY, AW, EY, OW, OY) followed directly within a word by ER0 or AH0 counts as one syllable.** "A closing diphthong can have a /ə/ vowel attached to it (e.g. fire /faɪə/); the resulting complex vowel unit may be classed as a TRIPHTHONG if it is pronounced as a single syllable" (Roach 2004: 241).
- **Syllabic consonants aren't a candidate.** They are pronounced "in place of a weak syllable containing a vowel" (p. 241), so the count doesn't change.

### FRA (not approvable as written: a question for Brett)

**The two candidates, defined over a G2P that writes every schwa:**

- **FRA-A: every schwa kept; word-final e silent.** The passage transcription has *toutes* [tut] and *forces* [fɔʁs] (Fougeron & Smith 1993: 75).
- **FRA-B: within a word, a schwa outside the first syllable is dropped when exactly one consonant separates it from the preceding vowel and a consonant follows it.** The rule applies left to right, each schwa judged on the string as it stands after earlier drops. Schwas in first syllables and in monosyllables are kept.

**FRA-B comes from the passage (p. 75):**

- dropped: *enveloppé* [ɑ̃vlope], *arriverait* [aʁivʁe];
- kept: *le premier* [lə pʁəmje], *renonça* [ʁənɔ̃sa], *regardé* [ʁəgaʁde], *celui* [səlɥi], and *de*, *que*, *le*.

It rests on one speaker and a handful of tokens, so it's an operationalisation of the passage, not a rule the source states.

**Neither tool can serve as main for both candidates.** I probed 64 frequent subtitle words, 8 from each of eight endings or vowels (corpus words, not read texts).

**Epitran `fra-Latn` writes every schwa but gets counts wrong:**

- It reads -ent in verbs as ɑ̃: *préparent* pʀepaʀɑ̃ (3, against 2), *dépendent* depɑ̃dɑ̃. Telling verbs from nouns and adverbs (*moment*, *paisiblement*) needs part-of-speech information.
- -aient gets an extra nucleus: *pleuraient* plœʀeɛ̃ (3, against 2).
- *quatrième* katʀjə̀m loses one, and *soucies* susj has one.
- Infinitive -er comes out as əʀ (*voler* vɔləʀ), and ê and è come out as schwas with accents (*même* mə̂m, *père* pə̀ʀ). Under FRA-B, these vowels would be dropped as schwas.

**espeak-ng `fr` gets these right** (*préparent* pʁepˈaʁ, *pleuraient* pløʁˈɛ, *voler* volˈe, *même* mˈɛm). But it applies its own schwa deletion, so FRA-A can't be built from it. On every probe word its deletions match the FRA-B rule:

- dropped: *relevez* ʁəlvˈe, *bêtement* bɛtmˈɑ̃, *spécifiquement* spesifikmˈɑ̃, *samedi* samdˈi;
- kept: *petite* pətˈit, *paisiblement* pɛzibləmˈɑ̃, *débarquement* debaʁkəmˈɑ̃.

**Options:**

1. **espeak-ng as main, FRA-B only.** Its deletions get checked against the stated rule on corpus words. FRA would then be a language with one candidate.
2. **Lexique 3.80, the paper's own French corpus (SM Table S2), as main lexicon, with espeak-ng for words Lexique lacks.** Lexique lists forms by part of speech, so the verb endings come out right. If it marks schwa, both candidates can be built. This waits on Lexique's fields, download link and licence, none of them checked yet.
3. **Epitran with a patch list.** The verb-ending error needs part-of-speech tagging, so the patch wouldn't be small.

**My recommendation is 2, with 1 as the fallback if Lexique doesn't mark schwa.** Lexique 3.80 is also the Stage 4 exact-source check.

### SRP

- **Main G2P: Epitran `srp-Latn`** on the Latin text that Stage 2 transliterated from Cyrillic. Its U+0329 on l and n is ignored (map bug, `DECISIONS.md`).
- **SRP-A: R0, plus r as a nucleus when it stands between consonants or between a word edge and a consonant.** Landau et al. (1995: 84) describe "a syllabic trill /r/" for Croatian. Standard Croatian is based on Štokavian, "as is Standard Serbian" (p. 83).
- **The Croatian diphthong /ie/ isn't a candidate.** It's ijekavian, and the two standards "are based on different subdialects, Ijekavian and Ekavian respectively" (p. 83). In the SRP read texts, the only *ije* spellings are i + consonant j + e: *nije*, *najkasnije*, *dobijem*, *egzotičnije*, *informacije*. That comes from a scan of `data/ref/texts.tsv`, with no syllable count.

### TUR

- **Main G2P: Epitran `tur-Latn`**, because Zimmer & Orgun (1992: 44) give ü as /y/ throughout (`notes/stage3-tool-survey.md`). Epitran writes ğ as ɰ.
- **TUR-A: R0 on Epitran's output.** Intervocalic ğ is a consonant, so the vowels on either side are separate syllables: *ağaç* aɰatʃ (2), *soğuk* soɰuk (2).
- **TUR-B: intervocalic ğ is deleted, and two identical vowels on either side of it fuse into one long vowel.** Dissimilar vowels stay separate syllables, so *ağaç* has 1 and *soğuk* 2. The source says ğ is "phonetically zero" between vowels (p. 44) but not whether the vowels then merge. Limiting the merger to identical vowels is my operationalisation.
- **Word-final and preconsonantal ğ** realise "as a lengthening of the preceding vowel" (p. 44). That changes no count in either candidate. "Dipthongs [sic] can be treated as sequences of vowel and /j/" (p. 44), and /j/ is a consonant.

### FIN

- **Main G2P: Epitran `fin-Latn`.** It marks long vowels with ":" and writes every vowel letter as a vowel.
- **The FIN counter reads the spelling, not the IPA.** "A given vowel phoneme is always written with the same grapheme" (Suomi, Toivanen & Ylitalo 2008: 20). So the rules below apply to the orthographic word, and Epitran's output supplies the segments for syllable types.
- **FIN-A: the traditional classification** (Suomi, Toivanen & Ylitalo 2008: 49–50). Within a word, double vowels and the 18 diphthongs are tautosyllabic, and the 20 vowel combinations are heterosyllabic. The 18 diphthongs are /ei, yi, öi, äi, ai, oi, ui; iu, eu, au, ou; ey, iy, öy, äy; ie, yö, uo/.
- **Longer sequences in FIN-A** are parsed left to right, taking a double vowel or listed diphthong where one starts. "At most two of the vowels can be tautosyllabic" (p. 23). The parse reproduces the book's examples *ai.e*, *kaa.os*, *ai.oin* (p. 23) and *ai.emmin*, *hau.is*, *vaa.oissa*, *tai.oit* (p. 51).
- **FIN-B: FIN-A, except /eu/ and /ou/ are heterosyllabic outside a word's first syllable.** The book reports that speakers disagree on "whether oikeus 'justice' or talous 'economy' are di- or trisyllabic… /eu/ and /ou/ can be judged to be heterosyllabic sequences in some words by some speakers, while they are unquestionably tautosyllabic for all speakers in words like leuka 'chin' and koulu 'school'" (p. 50). The condition about position generalises from the book's examples and is my operationalisation.
- **Considered, not listed:** the opposite ambivalence. Some speakers judge *pian*, *tae* and *teos* monosyllabic (p. 50), but the book doesn't delimit that class.

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
- **EUS-B: pairing on all vowel sequences within a word.** "Hiatus sequences may be reduced to diphthongs in fast speech" (p. 122).
- **Limitations:**
  - Both sources describe local dialects (Goizueta and Markina), not the standard language.
  - The lexical exceptions (loans keeping Spanish diphthongs, hiatus where a consonant was lost) aren't applied.

### VIE, KOR, CMN, YUE (one candidate each)

- **VIE:** one syllable per space-separated written syllable, after normalising where tone marks sit. No phonological source is cited for this; it's the orthography's own convention.
- **KOR:** one syllable per Hangul block of g2pk2's output. "[j, w] are considered to be components of diphthongs rather than separate consonants" (Lee 1993: 30), so glide plus vowel is one syllable, as the block structure writes it. Resyllabification moves consonants between blocks without changing their number. Checked on 300 corpus lines (1,080 eojeol): the block count of g2pk2's output equalled the input's in every line. Digits would be read out as extra blocks, but Stage 2 drops lines containing digits, and the primary texts have none.
- **CMN:** one syllable per Han character. The suffix 儿 (erhua) would be the exception, but it doesn't occur in the CMN read texts (scan of `data/ref/texts.tsv`), so NS can't decide it. In the corpora 儿 counts as a syllable. Lee & Zee (2003) don't cover erhua, and no source on it is in hand.
- **YUE:** one syllable per Han character. The Latin letters in some texts already keep those texts out of the primary set.

## Before the read-text run

1. Brett approves or amends this list. The approval goes into `DECISIONS.md`.
2. Each rule's counter is written and tested on corpus words only. The French ê fix and the SRP U+0329 strip go in with them.
3. Done 2026-10-09: the four quotations whose IPA I rebuilt from garbled PDF text (Roach /faɪə/, Martínez Celdrán [i̯ u̯] and [la ˈlambɾa], Kohler [ɐ]) match the page images, as checked by the r4 leak auditor, the Martínez Celdrán page also by the r5 auditor (r and ɾ in *la Alhambra* can't be told apart at the rendered resolution; the glyph fits ɾ); the *la Alhambra* example had lost its space.
4. A full snapshot and a public snapshot are made, audited, stamped and published. The NS comparison waits until the proof is anchored in a block.

The secondary run (all 15 texts) also needs the per-language digit-reading conventions, logged separately, as the Stage 3 scope entry requires. This list doesn't cover them.
