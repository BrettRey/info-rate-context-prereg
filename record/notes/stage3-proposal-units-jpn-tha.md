# Stage 3 proposal: how unit conventions are chosen, and Japanese and Thai
<!-- SUMMARY: proposed pre-registered rule for choosing syllable conventions (NS for grouping, Stage 4 ShE for labelling), triage of forks, and the Japanese and Thai tool plans; approved by Brett 2026-10-08 · status: settled · updated: 2026-10-08 -->

Written 2026-10-08, before any pipeline syllable count or NS ratio exists. Nothing here is settled until Brett approves it; the git commit date is the pre-registration timestamp.

## 1. Choosing a convention where the syllable is ambiguous

Two kinds of ambiguity need different evidence.

[withheld: from private correspondence with the paper's authors]

- For each language with two or more candidate groupings, compute the ratio of pipeline syllables to NS on each primary text (no digits or Latin intrusions; 7 to 15 texts per language, `DECISIONS.md`, Stage 3 scope).
- The main convention is the one whose median ratio is closest to 1. Report every candidate's median and per-text range.
- Candidates within 0.01 of the best median are both kept as arms.
- For a language where NS chose the convention, its NS ratio is a calibration, not an independent check of unit consistency, and the write-up says so.

**Labelling** (whether pitch accent or lexical stress makes syllables distinct types) leaves the count unchanged, so NS can't decide it. It changes the type inventory and the unigram entropy, so the evidence is Stage 4's comparison with the published ShE. Where Stage 4 has an exact source (WebCelex with its stress marks for ENG and DEU, spec-review item 9), compute ShE with and without stress; whichever matches the published value sets the default for the other stress languages. Japanese pitch accent rests on the Stage 4 ShE comparison alone, since its corpus differs from the paper's. Tone in CMN, YUE, THA and VIE is part of the syllable in every arm, as in the paper.

## 2. Which forks run everywhere (triage)

- **Forks that bear on the research question run at every rung and are reported as curves:** boundary treatment (rung 1, 1b-free, 1b-charged); line treatment (bounded, cross-line); training budget (B, B/2, and 3B if approved); Wikipedia stub threshold (0.5, 0.3); and, for CMN, YUE and THA, the word segmenter, since the word boundary defines the 1w and 1b rungs.
- **Unit conventions get one main convention per language under §1;** the runner-up is recomputed only for the headline R_k, as a sensitivity row.

## 3. Japanese

- **What the sources say.** The paper syllabified Japanese with Oh's rule-based program, from the Japanese Internet Corpus (SM Table S2), and gives 643 distinct syllables from LAPSyD (SM Table S1). Pellegrino et al. (2011, Table 2) give 416 syllable types for Japanese, with complexity 2.65 by type and 1.93 by token. Both are far above a mora inventory, so the paper's unit is the syllable, with heavy syllables as single units. Oh's thesis (2015, Lyon 2, theses.fr 2015LYO20072) is where the paper defers details. It's marked accessible on theses.fr, but no full text was found on HAL, theses.fr or the Lyon 2 server (2026-10-08).
- **Readings.** Kanji need a reader before kana can be grouped. Two independent routes: pyopenjtalk (0.4.1, OpenJTalk dictionary) and fugashi (1.5.2) with UniDic (unidic-lite 1.0.8 or full unidic 1.1.0). Neither is test-installed yet. Before naming one main, confirm that the installed dictionary gives a pronunciation form with long vowels written ー (先生 → センセー, 東京 → トーキョー), not the spelling form.
- **Candidate groupings** (decided by §1):
  - G1: a syllable is (C)(y)V plus one of ー, ン or ッ; any other vowel sequence is two syllables.
  - G2: G1, plus /ai/, /oi/ and /ui/ as single syllables.
  - Inventory check: our syllable inventory on the subtitles should land in the hundreds, near the 416 and 643 references, not near the roughly 100 of a mora inventory.
- **Pitch accent:** labelling, settled in Stage 4 (§1). Main arm unmarked.
- **Word segmentation** for the 1w and 1b rungs: the reader's own tokens (MeCab via fugashi, or OpenJTalk). Subtitle lines also use spaces as phrase breaks ("なあ なんで謝ってるんだ?"); those count as word boundaries.
- **Validation:** agreement between the two readers on 100 sampled word tokens (spec), and the NS ratio.

## 4. Thai

- **G2P with syllables and tones.** Two independent methods: PyThaiNLP 5.3.8's `thaig2p` (neural, model downloaded from Hugging Face at first use, so the model revision gets pinned in `config/languages.yaml`) and TLTK (1.11 on PyPI, through PyThaiNLP's `tltk_g2p` engine or directly). Both segment syllables as part of transcription (to be confirmed on install). The main method is chosen by §1 if their counts differ, and agreement on 100 sampled words is reported.
- **Word segmentation** for the 1w and 1b rungs: `newmm` (dictionary-based, PyThaiNLP's default) and `attacut` (learning-based), both run (§2); existence of the `attacut` package to be checked before install. Rung 1 and the unflagged higher rungs don't depend on either.
- **Line rule for Thai Wikipedia:** Thai doesn't end sentences with punctuation, so the prose-line test needs its own form, fixed after inspecting Thai Wikipedia and before any Thai entropy (stub-rule entry, `DECISIONS.md`).
- **Corpus quirks already handled in Stage 2:** sara am recomposed after NFKC; legacy private-use tone-mark characters drop the line.
