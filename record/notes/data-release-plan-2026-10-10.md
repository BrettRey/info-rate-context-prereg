# Data release plan
<!-- SUMMARY: what the project can release publicly, under which licence, in what form and when; OpenSubtitles text excluded, its rebuild path released; decisions for Brett listed at the end · status: decided; prior-resource check done; first release (benchmarks) after the overnight runs; DOI pending Brett · updated: 2026-10-10 -->

Drafted 2026-10-10 by Claude for Brett's review. Nothing here is released until Brett says so, and nothing touching NS or real-corpus entropy is released before the analysis it belongs to has run.

## What it's for

The study builds, as a by-product, syllabified text and syllable statistics for 17 languages under documented and partly alternative conventions, plus estimator benchmarks with known answers. Released together, they let others reuse the syllable data, rerun the analysis, or test their own estimators. Whether comparable resources already exist hasn't been checked; that check comes before any claim that this one is new (see the last section).

## Components

| # | Component | Contents | Built from | Release licence | When |
|---|---|---|---|---|---|
| 1 | Syllabified Wikipedia text | The Wikipedia part of the Stage 2 sample for the 17 languages, one line per source line, syllables separated, each language under its default conventions | Wikipedia (CC BY-SA 3.0 and GFDL), the main G2P for each language, the lexicons in 3 | CC BY-SA 4.0 | after the freeze |
| 2 | Syllable frequency tables | Unigram and bigram syllable counts per language, for every universe (each fork value) and each one-at-a-time check, from the Wikipedia text | as 1 | CC BY-SA 4.0 | after the analysis |
| 3 | Lexicon resources | Italian hiatus list, Mandarin erhua lexicon, Catalan unstressed words, the French Lexique 4.1 selection, onset inventories per language | English Wiktionary (CC BY-SA 4.0 and GFDL), Lexique 4.1 (CC BY-SA 4.0), the corpus | CC BY-SA 4.0 | after the freeze |
| 4 | Convention tally | How much each counter reading changes syllable counts in real text, per language (`results/stage3/tally-summary-2026-10-10.tsv` and its successors) | the corpus samples; numbers only | CC BY-SA 4.0 | after the freeze |
| 5 | Read-text counts against NS | Per text and language, the pipeline's syllable count under each universe beside the authors' canonical count NS | Coupé et al.'s data (CC BY 4.0, per their repository's README); the read texts are in the paper's SM | CC BY-SA 4.0; counts only, no text | after the analysis |
| 6 | Results | Entropy by context window for every universe, with uncertainty, and the multiverse summaries | 1, 2 and 5 | CC BY-SA 4.0 | after the analysis |
| 7 | Estimator benchmarks | F1, F1c, F3a and F3b on simulated syllable sequences: true values, KenLM and neural estimates, settings and seeds | simulated data only | CC BY 4.0 | now, once the overnight runs finish |
| 8 | OpenSubtitles rebuild kit | Manifests (folder ids, file ids, SHA-256) and the fetch and cleaning code, so anyone can rebuild the identical subtitle sample | OPUS OpenSubtitles v2024 (no licence stated) | manifests CC0, code as 9 | after the freeze |
| 9 | Code | The pipeline, counters, segmentation, estimators, fake-data checks and the tally tools | this project | MIT | with each component it produced |

## Licences

- **Share-alike sets the terms.** Wikipedia's CC BY-SA 3.0 lets an adaptation go out "under … a later version" of the licence with the same elements (CC BY-SA 3.0 legal code, §4(b), read 2026-10-10), so components 1–6 can be CC BY-SA 4.0, matching the Wiktionary and Lexique material. Coupé et al.'s data (CC BY 4.0) can be included under it with attribution.
- **OpenSubtitles text is never released.** OPUS states no licence, and the subtitles belong to third parties (`config/languages.yaml`, terms read 2026-10-08). Component 8 is the substitute. Whether frequency tables from the subtitle sample can be released is an open decision below.
- **The read texts stay in the SM.** The paper is CC BY-NC 4.0 (its licence statement in the PMC copy), so the texts and any syllabified form of them can't go into a CC BY-SA release. Component 5 gives counts only, keyed by the SM's passage labels.
- **Tools.** The CMU Pronouncing Dictionary data carries its own BSD-style licence (`cmudict/data/LICENSE`, copyright Carnegie Mellon 1993–2015); the `cmudict` Python wrapper is GPL-3.0 but isn't redistributed. Epitran is MIT, g2p-en and g2pk2 Apache 2.0, pypinyin and PyCantonese MIT (package metadata). espeak-ng's output carries no licence of its own. Each release names its tools and versions.

## Form

- **Formats.** UTF-8, tab-separated, gzipped; one folder per language; a manifest of every file with its SHA-256; the code commit and settings that produced each file.
- **Size.** Only the default conventions go out as text (component 1; the Wikipedia samples hold about 180–200 MB of text per language, YUE 57 MB and EUS 152 MB, before syllabification and compression); the variants are released as frequency tables (component 2) and as code that regenerates their text. This keeps the deposit small and still covers every universe.
- **Documentation.** A datasheet: sources, sampling (evenly spaced lines, gap handling), the conventions per language with their sources and pages (from `notes/stage3-candidate-conventions.md`), the forks and checks with their measured effects, known limits (G2P language switching, Vietnamese lines rejected, the uncovered rows), and the AI-use disclosure.
- **Hosting.** Zenodo for the data (a versioned DOI), GitHub for the code, both cited from the paper and the OSF registration. The pre-registration record stays where it is.

## Order

Brett, 2026-10-10: release as soon as possible, each component when it's ready, versioned, rather than all with the paper. The hold still sets the earliest point for anything built from real text.

1. **Now, once the overnight runs finish:** component 7 (the benchmarks; no real data), with the code that produced it (9, for those scripts).
2. **Once the counters are frozen and stamped:** components 3 and 4, then 1 and 8 (syllabified text and the rebuild kit need only the frozen counters and segmentation, not entropy or NS).
3. **Once the analysis has run:** components 2, 5 and 6, since frequency tables are one step from entropy and component 5 holds NS. Each later release is a new version of the same deposit.

## Decided (Brett, 2026-10-10)

1. **Code licence:** MIT.
2. **Subtitle frequency tables:** not released until the OpenSubtitles terms are checked more closely; the rebuild kit (component 8) covers reproducibility.
3. **Title and authorship:** Brett as sole author; working title "Syllable data and estimator benchmarks for cross-linguistic information rate, 17 languages". Brett links the deposit to Zenodo for a DOI later.

## What already exists (searched 2026-10-10)

An inward check (Brett's literature folder: filenames and three content searches) and an outward one (35 web searches, plus Zenodo, Hugging Face, GitHub, OSF, OpenAlex, ELRA and LDC; every resource listed was opened; `private/reviews/resource-check-20261010/REPORT.md`) found the following. These are claims about those searches, not about everything that exists; Google Scholar and sources in Chinese, Japanese or Korean weren't searched, and seven of the 17 languages weren't searched one by one.

- **Not found:** a corpus of syllabified running text in many languages under stated conventions; a consistent multi-language set of syllable frequency tables, or tables with variants by convention; any measurement of how much syllable-counting conventions change counts in real text (component 4).
- **Nearest neighbours:** syllabified text for about 20 languages in Oncevay & Rivas Rojas (2020) and Oncevay et al. (2022), mostly by orthographic hyphenation and not released; phonemic running text without syllables (IPA-CHILDES, 31 languages; Phonemized-UD; XPhoneBERT's Wikipedia data, unreleased).
- **Already exists:** single-language syllable frequency tables for about ten of the 17, from different sources under different conventions (for German, Samlowski, Möbius & Wagner, deposited on Zenodo on 2026-10-08); Wiktionary pronunciation lexicons (WikiPron, released without syllable boundaries); estimator benchmarks with known truth on simpler processes (independent draws, small-alphabet automata, binary Markov chains).
- **So:** components 1, 2 and 4 look new as described; component 3 is curated extracts of what Wiktionary already holds, and should be described that way; component 7 is new in its target (syllable-like sequences with large Zipfian inventories and word boundaries, KenLM beside a neural estimator), not in kind.
- **Licence to settle before release:** Lexique's web page says CC BY-SA 4.0 in its text but links to CC BY-NC 4.0 (found again in this search, and in the multiverse spec's §8 on 2026-10-09). The release follows the README distributed with Lexique 4.1 (CC BY-SA 4.0) (Brett, 2026-10-10).
