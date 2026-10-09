# Prior-work check before Stage 2
<!-- SUMMARY: outward check (spec review item 6) for an existing cross-word or long-context extension of Coupé et al. 2019; none found among 245 citing works or in 7 web searches; four neighbours to adjudicate · status: done · updated: 2026-10-08 -->

Spec review item 6 asked for an outward check, before Stage 2 cost anything, that nobody has already published this extension. The question checked: has anyone recomputed Coupé et al.'s (2019) information density with context that crosses word boundaries (longer n-grams or a language model) and asked whether languages stay more alike in information rate than in syllable rate?

## Searches (2026-10-08)

**Forward citations.** Any such extension would cite Coupé et al. 2019, so every indexed citing work was pulled.

- OpenAlex: `works?filter=cites:W2971775690` (the paper's OpenAlex id, resolved from `doi:10.1126/sciadv.aaw2594`), all pages. 204 works, 174 with abstracts.
- Semantic Scholar: `paper/DOI:10.1126/sciadv.aaw2594/citations`, all pages. 192 works, 165 with abstracts.
- Merged on normalised title: 245 distinct works (`prior-work-check-2026-10-08-citing-works.tsv`, with a flag for each index), 34 without an abstract in either index.
- Screen 1, title plus abstract matching both `information rate|information density|bits per second|bits/s|encoding efficiency|speech rate|syllable rate|speaking rate` and `context|n-gram|ngram|trigram|bigram|language model|neural|transformer|GPT|LLM|surprisal|word boundar|cross-word|conditional entropy|entropy rate|kneser|across words|predictab`: 13 works.
- Screen 2, by eye: every title among the 169 abstract-bearing works that match `entropy|surprisal|information|cross-?linguistic|syllab|languages|typolog|rate`, plus all 34 titles without abstracts. The candidates' abstracts were then read.

**Web searches** (WebSearch, three of them in extended mode):

1. `cross-linguistic information rate syllable context beyond word boundary n-gram language model Coupé 2019 reanalysis`
2. `"information rate" "39 bits" speech languages context length language model surprisal per second cross-linguistic 2025`
3. `Coupé Oh Dediu Pellegrino information rate DoReCo 36 languages surprisal language model 2024 2025`
4. `Oh Pellegrino "Towards robust complexity indices in linguistic typology" word information density across-word pdf hal`
5. `Kilpatrick Bundgaard-Nielsen 2026 Cognition 106406 surprisal syllables information rate`
6. `arXiv 2025 2026 cross-linguistic speech information rate bits per second multilingual language model surprisal syllable rate trade-off replication`
7. `Koplenig Wolfer Meyer "Human languages trade off complexity against efficiency" published journal entropy length trade-off language model`

[withheld: from private correspondence with the paper's authors]

## Result

No work found that recomputes the 17-language ID with cross-word or long-context models and re-evaluates rate compression. That's a claim about the 245 indexed citing works and the searches above. Not covered: preprints and theses that neither index lists yet, and work that doesn't cite the 2019 paper.

## Neighbours to adjudicate

- **Oh & Pellegrino (2023)**, "Towards robust complexity indices in linguistic typology: A corpus-based assessment", *Studies in Language* 47(4): 789–829, doi:10.1075/sl.22034.oh. Read in full 2026-10-08 (`literature/oh_pellegrino_2023_robust_complexity_indices_typology.{pdf,md}`, PDF via Brett's browser). Corpus: 1,150 verses of the Parallel Bible Corpus in 47 languages (§3). Word Information Density is a translation length ratio, English word count over the language's word count per verse (§4.2.1, after Pellegrino et al. 2011), not an entropy. Inter-Word Information is the change in compressed size when word order is randomly permuted (Juola's method), relative to English (§5.1, p. 808). The two trade off at r_median = −0.79, 95% CI [−0.88, −0.67] (p. 810), extending Koplenig et al. (2017, *PLoS ONE* 12(3): e0173614) on more than 1,000 languages; "strictly isolating languages and languages with a non-concatenative morphology" sit at the across-word end (p. 810). Section 6 uses GPT-2 surprisal of the English versions as a proxy for semantic content (p. 815). Text only, no speech rate, no syllable-level conditional entropy, so it doesn't do this project's extension. It does give a directional expectation for the step from rung 1w to 1b: isolating languages should gain more predictability from cross-word context than agglutinative ones.
- **Coupé, Oh, Dediu, Seifart & Pellegrino (SLE 2024 slides)**, already in `literature/`: information from GPT-2 surprisal of the English translations, with syllabic density relative to English (`source-verification.md`, row 11). A long-context measure, but of the translations' content, not each language's own syllable sequence.
- **Koplenig, Wolfer, Rüdiger & Meyer (2025)**, "Human languages trade off complexity against efficiency", *PLOS Complex Systems* 2(1): e0000032, doi:10.1371/journal.pcsy.0000032 (details from the IDS press release via search, not from the article). Entropy rates from models up to neural LMs, over written text in 2,000+ languages; higher entropy rate goes with shorter text. A written-text analogue of the density–rate trade-off with long context, with no speech rate. Not read.
- **Bergey & DeDeo (2024)** and **Pimentel et al. (2021)**, already in `literature/` and noted in the spec review: English conversation with word surprisal at 128-token context (13.21 bits/s), and phone surprisal against duration in 600 languages.

Hits that turned out not to bear on the question (authors from OpenAlex records): Aceves & Evans (2024, *Nature Human Behaviour*, semantic density of words in about 1,000 languages); Bradlow (2020, 2022) on L1 versus L2 information rate; Stelzer (2022), "How fast did Cicero speak?", which applies the 2019 method to Latin; Mansfield (2021) on the word as a unit of internal predictability; Wilcox et al. (2023) on reading times in 11 languages.
