# Stage 3 proposal: the other 15 languages
<!-- SUMMARY: per-language G2P, syllabification, segmentation and tone plans for the 15 languages other than JPN and THA; package existence and Epitran behaviour verified, adequacy mostly untested; awaiting Brett · status: proposal · updated: 2026-10-08 -->

Written 2026-10-08, before any pipeline syllable count. The approved rule (`notes/stage3-proposal-units-jpn-tha.md`, §1–2) governs every choice below: NS decides grouping conventions, Stage 4 ShE decides accent and stress labels, research-question forks run at every rung. Each section separates what has been checked from what still has to be tested before a tool is named main in `config/languages.yaml`.

Checked 2026-10-08: every package named exists on PyPI or Homebrew (epitran 1.35.3, pyphen 0.18.1, cmudict 1.1.3, g2p-en 2.1.0, underthesea 9.5.0, pyvi 0.1.1, g2pk2 0.0.3, opencc 1.4.2, jieba 0.42.1, pkuseg 0.0.25, pycantonese 5.0.0, phonemizer 3.4.0, num2words 0.5.14, espeak-ng 1.52.0). Installed and run so far: epitran, pyphen, pypinyin, pycantonese (installed, not yet run on text).

## Shared machinery for the Latin-script languages (EUS CAT DEU ENG FRA ITA SPA SRP TUR FIN HUN)

- **G2P:** Epitran where it has a map (all but EUS and ENG), espeak-ng as the second, independent G2P. Epitran outputs on test words (2026-10-08): `cat-Latn` descalcificador → dɛskalsifikadɔɾ (no Central Catalan vowel reduction); `deu-Latn` Entkalkungsanlage → ɛntkalkʊŋzanlaːɡə (voices the s at a compound boundary); `fra-Latn` malheureusement → malœʀœzəmɑ̃ (keeps schwa); `ita-Latn` gnocchi → ɲokːi; `spa-Latn` guerrero → ɡereɾo; `srp-Latn` prst → prst; `tur-Latn` teşekkürler → teʃekkyɾleɾ; `fin-Latn` kiitoksia → ki:toksiɑ; `hun-Latn` köszönöm → køsønøm.
- **Syllabification:** maximal onset over each language's legal onsets, the legal onsets being the word-initial clusters attested in that language's own transcribed corpus (a data-driven version of the legality principle; the threshold for "attested" to be fixed in config). Language-specific nuclei: syllabic r in SRP (prst is one syllable). Candidate groupings for NS to decide (§1): vowel sequences as diphthong or hiatus where the languages allow both (SPA, ITA, CAT: piano as pia.no or pi.a.no); English syllabic consonants (button as one or two syllables); French schwa kept (canonical full forms, as the spec asks) or dropped.
- **Second method for boundaries:** pyphen hyphenation, compared as syllables per word, where a dictionary exists (eu, ca, de, en, fr, it, es, sr, hu; checked). TUR and FIN have none; their orthographic syllabification rules are short and well documented, so a rule-based second method, with the source cited when written.
- **Stress:** labelling, so unmarked in the main arm; Stage 4 decides from WebCelex (now at webcelex.ivdnt.org; access terms not yet checked).

## Per language

- **ENG:** CMUdict (stress-marked) as the lexicon, g2p-en for words it lacks; espeak-ng second. The Stage 4 exact-source check uses WebCelex.
- **DEU:** Epitran, but compound boundaries need handling (see Entkalkungsanlage); espeak-ng second and possibly better here. Stage 4 exact source: WebCelex.
- **FRA:** Epitran keeps schwa; Lexique (the paper's source, now version 4.10) is a candidate lexicon if it carries syllabified transcriptions. Not yet checked: its fields, the right download link (a guessed URL returned 404), and its licence, which the site states as CC BY-SA 4.0 while linking to CC BY-NC 4.0.
- **SPA, ITA, CAT:** Epitran plus maximal onset; NS decides diphthong against hiatus. Catalan vowel reduction changes types, not counts.
- **SRP:** Epitran `srp-Latn` on the transliterated text; syllabic r as a nucleus.
- **TUR, FIN, HUN:** Epitran plus maximal onset; phonemic spellings make the second method straightforward. Finnish long segments are marked with ":" in Epitran's output.
- **EUS:** no Epitran map. espeak-ng (lists Basque) as one route; a rule set written from a cited grammar of Basque as the other, since the spelling is close to phonemic. Not tested.
- **VIE:** Epitran drops tones (tiếng Việt → tiəŋ viət), so no G2P. A written syllable is a syllable, with tone in its diacritics; syllable types are lower-cased written syllables after normalising tone-mark placement (hoà and hòa as one type). **Word segmentation joins the segmenter fork:** the paper's Vietnamese corpus had multisyllabic words (Methods), so the 1w and 1b rungs need word boundaries. Two segmenters: underthesea and pyvi.
- **CMN:** pypinyin with tone numbers per character, using its phrase dictionary for polyphonic characters; word boundaries from a character-aligned simplified copy made with OpenCC (length-preserving in tests). Readings: pypinyin misread traditional 乾杯 as qián bēi and read simplified 干杯 right (`notes/stage3-tool-survey.md`), so readings from the original and from the simplified copy are compared on a sample before one is chosen. Second segmenter: pkuseg 0.0.25 fails to build on Python 3.12 (it wants numpy at build time); try a build with numpy preinstalled, or substitute another segmenter.
- **YUE:** PyCantonese jyutping per character; word boundaries from PyCantonese's segmenter. A second Cantonese segmenter is still to be found; without one, YUE runs a single segmenter and says so.
- **KOR:** g2pk2 gives the pronunciation after sound changes and resyllabification, written in Hangul; each Hangul block of that output is a syllable. Words are the space-separated units (eojeol). g2pk (0.9.4) is the second method.

## Still to do before any of this is settled

Install and test espeak-ng, underthesea, pyvi, g2pk2, jieba, pkuseg and opencc; run each Latin-script pipeline on its read texts' primary set and on 100 sampled corpus words; find a second Cantonese segmenter; check Lexique's fields and terms and WebCelex's terms.
