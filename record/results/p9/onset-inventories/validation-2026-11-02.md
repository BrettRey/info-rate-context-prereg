# Onset amendment: validation pass
<!-- SUMMARY: the validation Brett asked for before the Fir re-preparation (2026-11-02): the amended rule, its sources, a targeted check of every mechanism, each change's contribution, a judged sample of changed and unchanged boundaries with the two readings cross-tabulated, the invariants, Brett's spot-check and the two exceptions it led to, the Turkish limit and Italian /ʃ/ added later, and what remains open (morpheme boundaries); Brett's review method and the Fagan citation settled 7 Nov · status: to be published with the amendment · updated: 2026-11-07 -->

Counts and segmentations on subtitle text only: no entropy, no read texts, no NS. Code: branch `onset-rule-amendment` (`src/stage3/segment.py`, `src/stage3/build_onset_lexicons.py`); tests `tests/test_p10_onset_amendment.py`.

## The amended rule

Between two nuclei of one word:

1. **The last consonant before the second vowel always begins its syllable**, whether or not it begins words. A lone consonant is the simplest case. Spanish: "intervocalic consonants exceptionlessly syllabify with following vowels" (Ramsammy 2023, §1.2). Basque: "Stops or affricates are not allowed in word-internal codas", though "word-internal coda stops are kept in very recent loanwords; e.g. dok-tore 'doctor, PhD', obsesio 'obsession'" (Hualde 2003: 34), so *an.tsa*, not *ants.a*; only the last consonant moves, so such loans still divide *dok.to.re*. espeak-ng's Basque *y*, written `jj`, counts as one segment.
2. **A longer onset must be legal** (learned from the starts of words, as before), **or legal once Spanish, Catalan and Basque approximants are read as their plosives** (β ð ɣ as b d g; only for licensing, the labels keep the symbols). /b d g/ are approximants between vowels and after most consonants: Martínez-Celdrán, Fernández-Planas & Carrera-Sabaté (2003) for Spanish; "in onset positions" after a vowel or liquid, Carbonell & Llisterri (1992) for Catalan; Bedialauneta Txurruka & Hualde (2023) for Basque. The longest such onset is taken. A longer onset must pass both this inventory test and the language's limits in point 3, and the limits too are checked on the plosive reading (Basque [βɾ] as [bɾ]).
3. **Sourced cluster limits.** Basque: "The only onset groups allowed in Basque are those of the muta-cum-liquida type (including fl-, fr- and excluding dl-, tl-)" (Hualde 2003: 33), so *s̺k* and *ps̺* don't license medial onsets. Spanish: /s/ before a consonant closes the syllable (Ramsammy 2023, §1.2: *tɾans.pa.ɾen.te*). Turkish (added after Brett's spot-check): a word-internal onset is one consonant, "In an intervocalic cluster of two consonants, a syllable boundary divides the consonants, VC.CV", three give VCC.CV, and "A cluster at either edge of the word is parsed tautosyllabically" (Myers & Crowhurst, *Phonology: Case Studies*, University of Texas at Austin); in the sample it changes 667 word types (`private/onset-validation/tur-limit-affected.tsv`), and the 40 most frequent all divide as the source has it (*is.ti.yo.rum*, *as.lın.da*, *bek.le*, *fark.lı*, *kont.rol*).
4. **Long consonants are split**, the first half closing the first syllable and the second opening the next: geminates are "phonologically parsed into two subsequent syllables" (Bertinetto & Loporcaro 2005: 133, with *fatto*); Hungarian long consonants "are commonly analyzed as clusters of identical consonants" (Szende 1994). Italian /ɲ ʃ ʎ ts dz/ "are always geminate when intervocalic", and "Geminate affricates double only the plosive element" (Rogers & d'Arcangeli 2004: 117), so for an affricate the coda portion is the stop and the onset portion the affricate: *pit.tsa*. These are Bertinetto & Loporcaro's (2005: 134) intrinsic geminates (*ascia* [ˈaʃːa]), with regional variation and optional degemination of *gli* in Florentine, so they are treated as geminate under the Standard Italian convention adopted here. /ʃ/ was added on 2 Nov after the outside review of the amendment draft (below); espeak-ng 1.52.0 writes it short (*pesce* pˈeʃe), as it does ʎ, ts and dz, and doubles ɲ itself (*bagno* bˈaɲɲo). Before a liquid the onset portion joins the liquid's onset if that onset passes the tests in point 2 (*af.flit.to*, *attrezzo*, *offro*, Bertinetto & Loporcaro 2005: 133–134); otherwise the long consonant stays whole in the first syllable. The split and the exceptions in point 6 take precedence over point 1.
5. **Initialisms leave the onset word lists**: an entry whose headword has two or more letters, all capitals, contributes neither its headword nor any form listed under it (the capitals test is the operational criterion for an initialism), so *NBE* no longer gives Basque *nb*; a lowercase word another entry lists stays. Wiktionary's borrowing tags are not used: their coverage varies by language.

Turkish soft *g* now begins the syllable (*da.ɰɯ*), as Ünal-Logacev, Żygis & Fuchs (2019) represent it ("intervocalically V.ğV"); the project's transcription writes it ɰ.

6. **Two exceptions to point 1, after Brett's spot-check of the English and German cases** (2 Nov). English [ŋ] stays in the coda: it "is limited to the coda and prohibited in the onset", and "engma is always syllabified as sɪŋ.ə" (Peng 2013, ch. 2). German [ɾ] stays in the coda, a convention for reading espeak-ng's output: in the sample, espeak-ng 1.52.0 writes *r* between vowels inside a morpheme as [r] (*Ware* vɑː.rə, *Ehre*), and a lone [ɾ] between vowels mostly corresponds to an *r* closing a prefix before a vowel-initial stem (the association observed, not a mechanism read from espeak's code); in German pronunciation such a stem begins with a glottal stop (Kohler 1990: 48, *vereisen* against *verreisen*): *fɛɾ.eː.rɜ*, *ɛɾ.ɪ.nɜn* keep the old boundary. The exceptions aren't forced into the onset; they begin a syllable only within an onset that passes point 2. (It also writes [ɾ] after a consonant, *drei* dɾaɪ; legal clusters handle those.) In the German sample this affects 42 tokens (32 word types): 38 are the prefixes *ver-*, *er-*, *vor-* before a vowel-initial stem, where it's right; 4 are names or a loan espeak reads as prefixed (*Erich*, *Erika*, *Erickson*, *zero*), where it's wrong, as the old rule was (`private/onset-validation/deu-tap-before-vowel.tsv`). An espeak-based convention, not a published one. German [ŋ] and [x] after a short vowel stay in the onset (*ju.ŋə*, *za.xə*) as a declared maximal-onset convention: Fagan (2009: 33–35) gives word-internal [ŋ] as an onset (*bringen*); analyses that make these consonants ambisyllabic are the alternative, and a two-way split can't show ambisyllabicity.

## Targeted check

Every mechanism, the exceptions and unchanged cases, in `tests/test_p10_onset_amendment.py` with supplied pronunciations: Spanish *na.ða*, *pa.ɾa*, *pa.ðɾe*, *li.βɾo*, *es.taɾ*, *nwes.tɾo*; Catalan *ka.ðə*; Basque *i.ɾu*, *a.t͡s̻o*, *po.βɾe*, *eʊs̺.ka.ɾa*, *ma.jja*, *an.t͡s̻es̻.te.ɾa*, *aɾ.t͡s̻en*; Italian *fat.to* against *fa.to*, *pit.t͡sa*, *aʃ.ʃa*, *fiʎ.ʎo*, *baɲ.ɲo*, *af.flit.to*, and *kon.ʃo* (not split after a consonant); Hungarian *kɛt.tøː*; Turkish *da.ɰɯ*. Syllable counts equal the old rule's in every case. On the production readers, also *a.βɾiɾ*, *sa.ɣɾa.ðo*, *tɾans.pa.ɾɛn.te*, *at.las*, *s̻en.bat*, *an.dɾe*, *baɲ.ɲo*, *ak.klu.de.re*; French unchanged.

## What each change contributes

Share of syllable tokens whose label differs from the old rule's (5,000 Stage 1 subtitle lines per language, one main-run declaration; `decomposition/`). These are disagreements between two procedures, not error rates; moving one boundary changes both neighbours' labels. A high share needn't mean a large change in ID: a one-to-one renaming of types leaves entropy alone.

| Language | Last consonant | Approximants licensed | Initialisms out | Cluster limits | Geminates split | All | Tokens in a split geminate |
|---|---:|---:|---:|---:|---:|---:|---:|
| Basque | 39.4% | 16.3% | 0.27% | 1.5% | 0 | 40.7% | 0 |
| Spanish | 22.5% | 16.5% | 0 | 6.9% | 0 | 30.3% | 0 |
| Catalan | 20.2% | 12.0% | 0 | 0 | 0 | 20.3% | 0 |
| Italian | (15.2%) | 0 | 0 | 0 | 16.4% | 16.5% | 18.0% |
| Hungarian | (8.7%) | 0 | 0 | 0 | 8.8% | 8.8% | 8.8% |
| Turkish | 4.3% | 0 | 0 | 4.1% | 0 | 8.3% | 0 |
| German | 1.65% | 0 | 0 | 0 | 0 | 1.65% | 0 |
| English | 0 | 0 | 0.54% | 0 | 0 | 0.54% | 0 |
| Serbian | 0.04% | 0 | 0 | 0 | 0 | 0.04% | 0 |
| French | 0.02% | 0 | 0 | 0 | 0 | 0.02% | 0 |

The bracketed Italian and Hungarian figures move long consonants whole into the second syllable; the full rule splits them instead. Every line was segmented by a re-implementation with each change behind a switch and checked to give the production cut's labels with all switches on and the old cut's with all off.

## Judged sample

From the same lines, 12 word types whose segmentation changes and 6 whose segmentation doesn't, per language (fewer where fewer exist), drawn at random and judged against the sources above (`sample_boundaries.py`; the full lists of words, judgements and bases are in `private/onset-validation/`, since they come from the corpus; the words named in this record are illustrative).

Who judged: the first reading is Claude's, the author of the amended rule, word by word but with one basis per language. A second reading of the 108 changed words was done blind: a fresh Claude subagent (same model family, separate context) saw each word's two segmentations as A and B in random order, not labelled old and new, with the same source notes, and not the first verdicts. The two readings agree on 100 of 108; both find the same ten old-right, new-wrong cases (below). They differ on four German *x* after a short vowel (*Drachen*, *Sache*: first reading new right, second both defensible, since the consonant is ambisyllabic in standard accounts and a two-way split can't show that), two English words (first both defensible, second new right) and the two French reader artifacts. A reader outside the model family was tried and failed: a local model (qwen3.8:27b, on the laptop, so the words stayed private), given the same pairs and notes, chose A 82 times and B 24 though the pairs were shuffled, often against its own stated reason; asked instead to copy out the right segmentation, it still answered with letters, mostly A. Its readings aren't used. No phonologist has checked the sample. (The first 24 pairs the second reader saw were typed in a different A/B order from the stored key, so its verdicts are scored by matching the chosen segmentation to the old and new ones, not by the key.)

| | Old wrong, new right | Old right, new wrong | Both defensible | Both wrong |
|---|---:|---:|---:|---:|
| Changed (108), first reading | 92 | 10 | 4 | (2 reader artifacts) |
| Changed (108), blind second reading | 92 | 10 | 6 | 0 |
| Unchanged (60), first reading | n/a | n/a | 3 | 1 |

The two readings of the 108 changed words against each other (second reading scored by matching the chosen segmentation, as above):

| First reading | Second reading | Words |
|---|---|---:|
| old wrong, new right | old wrong, new right | 88 |
| old right, new wrong | old right, new wrong | 10 |
| both defensible | both defensible | 2 |
| old wrong, new right | both defensible | 4 (German [x]) |
| both defensible | old wrong, new right | 2 (English) |
| reader artifact | old wrong, new right | 2 (French) |

Agreement is 100 of 108, the first three rows. Both readings are instances of one model, so their agreement is a consistency check, not an independent estimate of accuracy. They judged the initial candidate (points 1 to 5, before the exceptions in point 6, the Turkish limit in point 3 and Italian /ʃ/ in point 4), so the ten old-right, new-wrong cases describe that candidate, not the final rule.

All changed Spanish, Catalan, Basque, Italian, Hungarian, Turkish and Serbian words are old wrong, new right. The ten old-right, new-wrong cases were German (7) and English (3): nine *ŋ* beginning a syllable (*ju.ŋə*, *bri.ŋɪŋ*) and one German prefix before a vowel-initial stem (*Ver|ehrer*, where "word and stem initial vowels are always prefixed by glottal stop", Kohler 1990). The unchanged words judged both wrong or defensible are a morpheme boundary (*un|earthed*) and *s* + consonant in Italian and Serbian.

**Brett's spot-check** of the 19 English and German words in dispute (`private/onset-validation/spot-check-for-brett.md`, 2 Nov; he reviewed them with a source-based assessment prepared with ChatGPT and adopted its conclusions): English *bringing*, *singers* and *Yongye*, old right (Peng 2013), now kept by the English [ŋ] exception (*Yongye* weak evidence, a name of unknown pronunciation); *Verehrer*, old preferred, now kept by the German [ɾ] exception; the six German [ŋ] words and the four German [x] words after a short vowel, both defensible, the new split kept as the declared maximal-onset convention (Fagan 2009: 33–35), not counted as corrections; *suche*, new preferred; English *continue* and *menu*, new preferred; *California* and *senior*, both defensible (dictionaries differ). He also noted an upstream transcription problem both rules inherit: *Hitzewallungen* has [t͡seː] where [t͡sə] is expected. With the two exceptions, no changed word in the sample is judged wrong by Brett; the corrections are the Spanish, Catalan, Basque, Italian, Hungarian, Turkish and Serbian changes and English *continue*, *menu*, *always*, *blasphemous*, *Fenris*, *transformed*, *Everyone's*.

A first draw of the sample, under the rule before point 1 was generalised from lone consonants, showed two errors the old and new rules shared: Basque affricates after a consonant (*ant͡s̻.e*), now fixed by point 1, and a Turkish loan cluster across a morpheme boundary (*o.da.klan*, *odak + lan*), since fixed by the Turkish limit in point 3 (*o.dak.lan*).

## Italian /ʃ/ (added 2 Nov, after the outside review)

The outside review of the amendment draft (pasted by Brett, 2 Nov) noted that Rogers & d'Arcangeli (2004: 117) list five intrinsic geminates, /ɲ ʃ ʎ ts dz/, where the code had four, and asked whether the general long-consonant rule already covered /ʃ/. It didn't: espeak-ng 1.52.0 writes intervocalic /ʃ/ short (*pesce* pˈeʃe, *ascia* ˈaʃa), so the rule left *pe.ʃe*. (The earlier reading of the source missed /ʃ/, whose symbol the PDF-to-text conversion garbled.) With /ʃ/ added, 107 of 50,288 syllable tokens in the Italian sample (0.21%) change, every one a coda gaining the first portion of a split /ʃ/ (*aʃ.ʃol*, *piʃ.ʃo*, *naʃ.ʃo*; 44 label pairs in `private/onset-validation/ita-sh-affected.tsv`); no line fails that didn't before (53 skipped either way). The Italian row of the table above is re-measured with it (`decomposition/ITA.json`); the other nine languages' files still record the earlier `segment.py` hash, and weren't re-run because the intrinsic geminates are Italian only. Counts job 2030570 was held on Fir before it started, and the code restaged.

## Invariants

- **Masks.** A mask records the lines whose reading or segmentation fails. On the ten samples, no line fails under one rule and not the other (failures identical: 0 to 91 per language). The masks' content wouldn't change; they must be rebuilt anyway, because a mask and a preparation are bound to the code version, which covers `segment.py` and `onsets.py` (`pipeline.version()`), and both the mask reader and the preparation-reuse check refuse another version.
- **Corpus.** The onset word lists are read only to learn onsets (`linguistic_inputs.onset_lexicon_listed`); excluding initialisms from them removes nothing from the analysed text.
- **Counts.** The amendment moves boundaries between nuclei and never adds or removes one, so counts are unchanged by construction; and no syllable count moved on any line of any sample. B₀ and the budget plans stay as they are, provided the same material is retained, which the masks rebuilt by the full re-run will show.
- **Scope of the failure check.** The no-differential-failure result above covers the ten diagnostic samples only; the full corpus is checked when the re-run's masks are compared by reason.

## Cost

Because the version binding covers every language's masks and preparations, the re-run is the whole counts phase, not the ten onset languages alone: about 2 days 20 hours as on 30 October–2 November (Italian's preparations are the long pole, 21 h main and 52 h Wikipedia). The pronunciation cache can't shorten it much, since segmentation dominates. A restart from the old archive would be refused by the version check.

## Open

- **Morpheme boundaries** the transcription doesn't mark (English *un|earthed*): the segmenter has no morphology. German prefixes ending in *r* are kept by the [ɾ] exception; other German prefix-final consonants before vowel-initial stems aren't.
- **German [ŋ] and [x] after short vowels** are ambisyllabic in some analyses; the rule puts them in the onset by convention, following Fagan (2009: 33–35), whose analysis doesn't recognise ambisyllabic consonants.
- **Upstream transcriptions** (German *Hitzewallungen* [t͡seː] for [t͡sə]): outside syllabification.

## Sources

- Bedialauneta Txurruka, Izaro & José Ignacio Hualde. 2023. Markina Basque. *Journal of the International Phonetic Association* 53(3): 1095–1121. doi:10.1017/S0025100322000032.
- Bertinetto, Pier Marco & Michele Loporcaro. 2005. The sound pattern of Standard Italian, as compared with the varieties spoken in Florence, Milan and Rome. *Journal of the International Phonetic Association* 35(2): 131–151. doi:10.1017/S0025100305002148.
- Cabrelli Amaro, Jennifer Lauren. 2013. *The Phonological Permeability Hypothesis: Measuring regressive L3 influence to test L1 and L2 phonological representations*. PhD dissertation, University of Florida. (Spanish *pa.dɾe*, *li.bɾo*, p. 74; nonce *fas.pɾa*.)
- Carbonell, Joan F. & Joaquim Llisterri. 1992. Catalan. *Journal of the International Phonetic Association*, 53–56. doi:10.1017/S0025100300004618.
- Hualde, José Ignacio. 2003. Segmental phonology. In José Ignacio Hualde & Jon Ortiz de Urbina (eds.), *A Grammar of Basque*, §2.1. Berlin: Mouton de Gruyter. (§2.1.3.1, p. 33; §2.1.3.3, p. 34, including the loanword qualification.)
- Fagan, Sarah M. B. 2009. *German: A Linguistic Introduction*, ch. 1, Phonetics and phonology. Cambridge: Cambridge University Press. doi:10.1017/CBO9780511626821.002. (§§1.2.5.1–1.2.5.2, pp. 33–35.)
- Kohler, Klaus. 1990. German. *Journal of the International Phonetic Association* 20(1): 48–50. doi:10.1017/S0025100300004084.
- Myers, Scott & Megan Crowhurst. *Phonology: Case Studies*, Turkish (dorsal palatalization), section 5. University of Texas at Austin, Liberal Arts ITS. https://www.laits.utexas.edu/phonology/turkish/turk_dorsal_pal5.html (read 2 Nov 2026).
- Peng, Long. 2013. *Analyzing Sound Patterns: An Introduction to Phonology*. Cambridge: Cambridge University Press. Ch. 2 (*singer* sɪŋ.ə; p. 39 per Brett, page not visible in the preview read here).
- Martínez-Celdrán, Eugenio, Ana Ma. Fernández-Planas & Josefina Carrera-Sabaté. 2003. Castilian Spanish. *Journal of the International Phonetic Association* 33(2): 255–259. doi:10.1017/S0025100303001373.
- Ramsammy, M. 2023. Contextual reduction of word-final /l/ in Spanish: An EPG study. *Journal of the International Phonetic Association* 53(2): 333–360. doi:10.1017/S0025100321000128.
- Rogers, Derek & Luciana d'Arcangeli. 2004. Italian. *Journal of the International Phonetic Association* 34(1): 117–121. doi:10.1017/S0025100304001628.
- Szende, Tamás. 1994. Hungarian. *Journal of the International Phonetic Association*, 91–94. doi:10.1017/S0025100300005090.
- Ünal-Logacev, Ö., M. Żygis & S. Fuchs. 2019. Phonetics and phonology of soft 'g' in Turkish. *Journal of the International Phonetic Association* 49(2): 183–206. doi:10.1017/S0025100317000317.
