# Source verification queue
<!-- SUMMARY: [withheld: from private correspondence with the paper's authors] -->

Checked 2026-09-28 against the sources now in `literature/`:

- **Paper**: `coupe_etal_2019_comparable_information_rates.md`, from the Europe PMC full-text XML (kept alongside as `.xml`). No page numbers; cited by section. The PMC PDF sits behind a bot challenge and wasn't fetched.
- **Supplement**: `coupe_etal_2019_comparable_information_rates_SM.pdf`/`.md`.
- **Authors' compiled analysis report** (supplementary analysis report file S1): `data/ref/aaw2594_Analysis_report_file_S1.html`, gitignored.
- **Other sources**: `pellegrino_etal_2011_cross_language_speech_information_rate`, `pimentel_etal_2021_surprisal_duration_tradeoff`, `coupe_etal_2024_sle57_information_speech_rate_slides`, `bergey_dedeo_2024_information_flow_conversation`, `trott_2020_information_rate_blog`.

The journal's data file S1 and analysis script are byte-identical to the GitHub `InfoRateData.csv` and `InfoRate.Rmd` (SHA-256 `f4dde6de…` and `189caf95…`). Data file S2 is `AutomaticSylDetect.csv` with CRLF line endings.

| # | Claim (SPEC.md) | Status | Evidence |
|---|---|---|---|
| 1 | 17 languages, 9 families; 170 speakers; 15 MULTEXT texts; new translations for 14 languages | **verified, one correction** | Methods, Data: "17 languages from 9 language families"; "speakers (170 in total, 85 females)"; ENG, DEU, ITA texts from MULTEXT, "For the other 14 languages, two of the authors (C.C. or Y.O.) supervised the translation and recording of new datasets". Correction: SM Text S3 says the texts were "translated from British English or French into each target language", not only from English. |
| 2 | SR from canonical transcription; pauses over 150 ms excluded | **verified** | Introduction: "excluding pauses longer than 150 ms"; NS is "the text's 'canonical' pronunciation". Methods: "Pauses longer than 150 ms were identified and discarded through visual inspection". |
| 3 | ID = within-word bigram conditional entropy, null marker word-initially, ML plug-in; restriction forced by word-frequency corpora | **verified** | Methods, Data: "the identity of the previous syllable or a null marker for syllables occurring word initially (thus, no bigrams span across word boundaries)"; "maximum likelihood estimates"; "for several languages, the text corpora only provide word frequencies (and not raw texts), we considered within-word context only". |
| 4 | Tone- or accent-distinct syllables counted as distinct types | **verified** | Methods: "When applicable, syllables bearing specific tone or accent were considered as distinct in the inventory." |
| 5 | Syllabification sources; CMN/YUE character = syllable; word segmentation not described; Oh's 2015 thesis | **verified** | Methods: Oh's rule-based program, except pre-syllabified ENG/FRA/DEU/VIE (multisyllabic words) and G2P for CAT/SPA/THA; "each ideogram corresponds to a single syllable". Nothing on word segmentation in the main text or the supplement (SM searched for `segment`, `word boundar`, `tokeni`: no hits). Ref. 45: "Y. M. Oh, thesis, Université de Lyon, France (2015)". Corpora by language: SM Table S2. |
| [withheld: from private correspondence with the paper's authors] |
| 7 | Stage 1 table | **verified** | `results/stage1/stage1_reference_output.txt`. |
| [withheld: from private correspondence with the paper's authors] |
| 9 | The SR ~ ID model dropped the language random effect | **verified** | Results: "we dropped language as a random effect, since there is, by definition, a single ID value per language, but we did include family". Methods: "language is meaningless as a random effect as there is only one ID value per language". The model keeps text, speaker and family random effects, so it isn't treating readings as independent. What it leaves out is residual variation between languages. |
| 10 | Pellegrino et al. 2011: tone as an extra constituent; ρ ≈ 0.98, N = 7 | **verified, type-based** | p. 549: for Mandarin "the complexity of each of its tone-bearing syllables is thus computed by adding 1 to its number of phonemes". p. 550: type-based complexity with ID, "ρ = 0.98, p < 0.01; r = 0.94"; with SR, type ρ = −0.98, token ρ = −0.89; N = 7. |
| 11 | SLE 2024 follow-up on 36 DoReCo languages | **verified, different measures** | Slide 1: "Trade-offs between information and speech rate in naturalistic speech from 49 non-WEIRD languages", Coupé, Oh, Dediu, Seifart & Pellegrino, SLE 57, 21/08/2024. Slide 13: "Subset of 36 languages" (it includes English). Slide 16: syllabic density = English syllable count / source-language syllable count; information from GPT-2 surprisal of the English translations. |
| 12 | Bibliographic details | **verified** | Coupé et al.: *Science Advances* 5(9), eaaw2594, published 4 Sept 2019 (XML front matter). Pellegrino et al.: *Language* 87(3), 539–558 (running heads). Pimentel et al.: EMNLP 2021, pages 949–962 (p. 1 footer). |

Other checks made along the way:

- **SDIR direction**: Methods: "an SDIRL >1 represents a language L denser than Vietnamese ... (since it requires less syllables than Vietnamese ...)". This matches `NSVR` in the authors' script and `src/stage1_reference.py`.
- **Bergey & DeDeo (2024)**, arXiv:2403.08890v1: "13.21±0.04 bits/second (N = 54,958 sequences)", from continuous conversational English (CANDOR corpus).
- **Trott (2020)**, blog post dated 12 January 2020. It lists three limitations: conditional entropy versus the number of possible syllables, "information" versus meaning, and optimality. It doesn't raise the within-word restriction on context (searched for `word boundar`, `within.word`, `context`, `bigram`, `across word`). Its only mention of context beyond the previous syllable is a footnote about non-linguistic context.

[withheld: from private correspondence with the paper's authors]