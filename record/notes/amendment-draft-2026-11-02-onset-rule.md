# Amendment draft: syllable boundaries within words
<!-- SUMMARY: draft deviation from the pre-registered onset rule, for the public record; revised after the outside review of 2 Nov (Italian /ʃ/, how the provisions interact, validation chronology, count invariance, source claims, scope of the old-rule comparison); brackets filled 7 Nov (Brett: the 19 words reviewed with an adopted ChatGPT-prepared assessment, validation record in the prereg repo; Fagan 2009 read, point 7 and its citation corrected); approved by Brett 7 Nov and published with public record r13 · status: approved · updated: 2026-11-07 -->

Status: approved by Brett for the public pre-registration, 7 November 2026. Drafted 2 November and final 7 November 2026, before the freeze and before any entropy on real text.

## What was pre-registered

Syllable boundaries within a word are placed by maximal onset: the consonants between two vowels go to the second syllable if, together, they form a legal onset, and legal onsets are the consonant clusters that begin words in the language's own training text, at a frequency floor of three word types (decided 10 October 2026). From 15 October, a word type counts toward an onset only if Wiktionary lists it as a headword or form. The as-built inventory and floors 1 and 10 were pre-registered as one-at-a-time sensitivity checks.

## What was wrong with it

The rule treats three different things as one: whether a consonant or cluster occurs at the start of a word in the sampled vocabulary; whether it occurs there in the pronunciation representation used; and whether it can begin a syllable inside a word. Only the third matters for syllabification, and the first two don't establish it. In consequence:

1. A consonant that never begins a word in the representation can never begin a syllable, so between two vowels it closes the syllable before. Spanish, Catalan and Basque taps, the approximant realisations of /b d g/, Basque affricates and Turkish soft *g* were all affected (Spanish *nada* came out *nað.a*).
2. Clusters that begin words only in loans or initialisms became legal medial onsets (Spanish *estar* came out *e.star*; Basque gained *nb* from the initialism *NBE*).
3. Long consonants were placed whole in the first syllable (Italian *fatt.o*).

No frequency floor can repair the first fault, and the pre-registered checks share its assumption, since every inventory they vary is learned from the starts of words.

## What has and hasn't been seen

Seen before this amendment, all on the training corpora's subtitle and Wikipedia text: the counts phase's line and syllable counts and budget plans; each language's removal masks by reason; the Basque and Finnish onset inventories, and then every onset language's; on samples of 5,000 subtitle lines per language, how many syllable labels the old and amended rules assign differently, and a judged sample of word segmentations. Also the estimators' fake-data checks on simulated text.

Not seen: any entropy, information density or information rate on real text; any read-text count or result; NS.

The amendment moves boundaries between nuclei and never adds or removes one, so it leaves syllable counts unchanged by construction; equal syllable counts were also confirmed on every line of the diagnostic samples. Speech rates and syllable-based budgets are therefore unchanged, provided the same material is retained. On the same samples, no line's reading or segmentation fails under one rule and not the other; the mask checks after the full counts re-run will show whether that holds for the whole corpus.

## The amended rule

Within a word, between two vowels:

1. **Singletons.** The last consonant before the second vowel begins its syllable, whether or not it begins words. Spanish: "intervocalic consonants exceptionlessly syllabify with following vowels" (Ramsammy 2023). Basque: stops and affricates don't close word-internal syllables, although very recent loans keep such codas, as in *doktore* (Hualde 2003: 34); since only the last consonant is moved, such a loan still divides *dok.to.re*.
2. **Longer onsets.** A longer onset is taken only if it passes two tests: it belongs to the learned inventory, and it meets the restrictions in point 3 for its language. In Spanish, Catalan and Basque the approximant realisations of /b d g/ are read as the plosives for both tests (Martínez-Celdrán, Fernández-Planas & Carrera-Sabaté 2003; Carbonell & Llisterri 1992; Bedialauneta Txurruka & Hualde 2023): the inventory test accepts the cluster as transcribed or in that reading, and the restrictions are checked in that reading, so Basque [βɾ] passes as [bɾ]. The labels keep the symbols as transcribed. The longest onset that passes both tests is taken.
3. **Language-specific restrictions.** Basque onsets of more than one consonant are a stop or /f/ followed by a liquid, without /dl tl/ (Hualde 2003: 33). In Spanish, /s/ before a consonant closes the syllable (Ramsammy 2023). In Turkish, a word-internal onset is one consonant, so two consonants between vowels divide VC.CV and three VCC.CV, while clusters at the edges of a word stay together (Myers & Crowhurst).
4. **Long consonants.** A long consonant that begins the consonants between two vowels is split: a coda portion closes the first syllable and an onset portion opens the next (Bertinetto & Loporcaro 2005: 133; Szende 1994). If other consonants follow, the onset portion joins them when the resulting onset passes the tests in point 2, as in Italian *afflitto* af.flit.to, *attrezzo* and *offro* (Bertinetto & Loporcaro 2005: 133–134); otherwise the long consonant stays whole in the first syllable. Italian /ɲ ʃ ʎ ts dz/ are treated as intrinsically geminate between vowels, under the Standard Italian convention adopted here (Rogers & d'Arcangeli 2004: 117; Bertinetto & Loporcaro 2005: 134, who note regional variation and optional degemination of the article *gli* in Florentine), and are split in the same way. For the Italian affricates, the coda portion is the stop and the onset portion the affricate, as in *pizza* pit.tsa, following Rogers & d'Arcangeli's (2004: 117) observation that a geminate affricate doubles only its plosive element. This representation applies to Italian only.
5. **Exceptions.** Two consonants aren't moved into the onset by point 1; they begin a syllable only within an onset that passes the tests in point 2, which in practice leaves them in the coda. English /ŋ/ is "limited to the coda and prohibited in the onset" (Peng 2013), so *singer* is sɪŋ.ə. German [ɾ] between vowels, as transcribed by the pronunciation tool (espeak-ng 1.52.0), is a convention for reading that tool's output. In the diagnostic sample, a lone intervocalic [ɾ] mostly corresponded to the *r* that closes a prefix before a vowel-initial stem (38 of 42 tokens: *ver-*, *er-*, *vor-*), where the prefix keeps its *r* (*Ver|ehrer*); in German pronunciation such a stem begins with a glottal stop (Kohler 1990: 48, *vereisen* against *verreisen*). The other four tokens are names and a loan (*Erich*, *Erika*, *Erickson*, *zero*), where the exception gives the wrong boundary. The sample figure isn't an estimate of corpus-wide accuracy.
6. **Precedence.** Points 4 and 5 take precedence over point 1: a long consonant is split rather than moved whole, and the two exceptions aren't forced into the onset.
7. **German /ŋ/ and /x/.** After a short vowel these begin the next syllable. This is a declared convention, and it follows Fagan's maximal-onset analysis, which takes /ŋ/ as a word-internal onset (*bringen*) and /x/ as an onset (*Kuchen*) and doesn't recognise ambisyllabic consonants (Fagan 2009: 33–35). Many analyses make a consonant after a short vowel ambisyllabic (Fagan 2009: 34 lists them), which a two-way division can't represent.
8. **Initialisms.** A Wiktionary entry whose headword has at least two letters, all of them capitals, no longer counts as evidence for an onset, and neither do the forms listed under it. The capitals test is the operational criterion for an initialism.

The procedure is otherwise unchanged: the same corpora, readers, frequency floor and sensitivity checks. The pre-registered inventory and frequency-floor checks keep the amended provisions (points 1 to 7) and vary only the inventory. The pre-amendment procedure as a whole is the separate comparison declared below.

## How it was checked

**The initial candidate** (points 1 to 4 and 8, without the exceptions, the Turkish restriction or Italian /ʃ/) was checked by a targeted test of every mechanism and of words that shouldn't change; for each of the ten onset languages, the share of syllable labels each provision changes on a 5,000-line sample; and a random sample of 168 word types, 108 changed and 60 unchanged, judged against the sources. Both judgments were made by instances of one AI model (Claude): first by the instance that wrote the rule, then, for the 108 changed words, blind by a second instance that saw each word's two segmentations unlabelled and in random order. The first reading judged 92 changes corrections, 10 wrong, 4 both defensible and 2 (French) artefacts of the pronunciation reader; the second judged 92 corrections, 10 wrong and 6 both defensible. They agree on 100 of the 108 (88 corrections, the same 10 wrong changes, 2 both defensible) and differ on 4 German [x] words (first reading correction, second both defensible), 2 English words (the reverse) and the 2 French artefacts (second reading correction). Their agreement is a consistency check, not an independent estimate of accuracy, and it concerns the initial candidate, not the final rule. The implementation was also reviewed, read-only, by a model from another family (OpenAI's Codex), three times; its findings were fixed and tested.

**The English and German cases.** The 19 English and German words that the readings disputed or judged wrongly changed went to Brett, who reviewed them with a source-based assessment prepared with ChatGPT and adopted its conclusions. That review produced the two exceptions in point 5, the convention in point 7, and the judgment that English medial [nj] is divided defensibly either way.

**Later additions.** The Turkish restriction changes 667 word types in the Turkish sample (4% of syllable labels); the 40 most frequent were checked against the source's divisions (*is.ti.yo.rum*, *fark.lı*, *bek.le*). Italian /ʃ/ was added to the intrinsic geminates after review of a draft of this text; it changes 107 of 50,288 syllable labels in the Italian sample (0.2%), all a split /ʃ/ as in *ascia* aʃ.ʃa. Neither addition was judged on a random sample.

The full validation record, with every count, is published with this amendment, in the same commit of the public pre-registration repository (https://github.com/BrettRey/info-rate-context-prereg).

## What it leaves

- Morpheme boundaries the transcription doesn't mark: the segmenter has no morphology, so a consonant before a vowel-initial stem moves to that stem's syllable under both rules (English *un|earthed*; German prefixes not ending in *r*).
- A long consonant is split only when it begins the consonants between two vowels.
- Apart from the stated exceptions, consonants treated as ambisyllabic in some analyses are assigned to the onset.

## Effect, and what follows

Against the pre-registered rule, the amendment changes about 41% of Basque, 30% of Spanish and 20% of Catalan syllable-token labels, 16% Italian, 9% Hungarian, 8% Turkish, 2% German and under 1% in English, Serbian and French. These are differences between procedures, not error rates, and they bear on syllable types, not counts.

The amended rule is the primary analysis. After the freeze, the pre-registered procedure runs as a declared sensitivity analysis. It restores the complete pre-amendment construction of syllable labels, including its treatment of long consonants (kept whole in the first syllable), with no exceptions, restrictions or licensing equivalents. The corpora, pronunciations, inclusion rules, masks, budgets and estimators are held constant, and so are the onset inventories, which keep the exclusion of initialisms; on the diagnostic samples that exclusion alone changes 0.27% of Basque and 0.54% of English syllable labels and none elsewhere. The comparison covers the within-word ID that replicates Coupé et al. (2019) and the affected low rungs in every onset language, and it is built in the same counts run as the primary analysis. Its purpose is to show how far the conclusions depend on the segmentation convention; the amended rule stays primary whichever gives the more attractive result.

## References

- Bedialauneta Txurruka, Izaro & José Ignacio Hualde. 2023. Markina Basque. *Journal of the International Phonetic Association* 53(3): 1095–1121. doi:10.1017/S0025100322000032.
- Bertinetto, Pier Marco & Michele Loporcaro. 2005. The sound pattern of Standard Italian, as compared with the varieties spoken in Florence, Milan and Rome. *Journal of the International Phonetic Association* 35(2): 131–151. doi:10.1017/S0025100305002148.
- Carbonell, Joan F. & Joaquim Llisterri. 1992. Catalan. *Journal of the International Phonetic Association*, 53–56. doi:10.1017/S0025100300004618.
- Coupé, Christophe, Yoon Mi Oh, Dan Dediu & François Pellegrino. 2019. Different languages, similar encoding efficiency: Comparable information rates across the human communicative niche. *Science Advances* 5(9): eaaw2594. doi:10.1126/sciadv.aaw2594.
- Fagan, Sarah M. B. 2009. *German: A Linguistic Introduction*. Cambridge: Cambridge University Press. Ch. 1, §§1.2.5.1–1.2.5.2, pp. 33–35. doi:10.1017/CBO9780511626821.002.
- Hualde, José Ignacio. 2003. Segmental phonology. In José Ignacio Hualde & Jon Ortiz de Urbina (eds.), *A Grammar of Basque*, §2.1 (pp. 33–34 cited). Berlin: Mouton de Gruyter.
- Kohler, Klaus. 1990. German. *Journal of the International Phonetic Association* 20(1): 48–50. doi:10.1017/S0025100300004084.
- Martínez-Celdrán, Eugenio, Ana Ma. Fernández-Planas & Josefina Carrera-Sabaté. 2003. Castilian Spanish. *Journal of the International Phonetic Association* 33(2): 255–259. doi:10.1017/S0025100303001373.
- Myers, Scott & Megan Crowhurst. n.d. *Phonology: Case Studies*, Turkish, section 5. University of Texas at Austin. https://www.laits.utexas.edu/phonology/turkish/turk_dorsal_pal5.html (accessed 2 November 2026).
- Peng, Long. 2013. *Analyzing Sound Patterns: An Introduction to Phonology*. Cambridge: Cambridge University Press. Ch. 2.
- Ramsammy, Michael. 2023. Contextual reduction of word-final /l/ in Spanish: An EPG study. *Journal of the International Phonetic Association* 53(2): 333–360. doi:10.1017/S0025100321000128.
- Rogers, Derek & Luciana d'Arcangeli. 2004. Italian. *Journal of the International Phonetic Association* 34(1): 117–121. doi:10.1017/S0025100304001628.
- Szende, Tamás. 1994. Hungarian. *Journal of the International Phonetic Association*, 91–94. doi:10.1017/S0025100300005090.
