# Stage 3 tool survey
<!-- SUMMARY: candidate G2P, syllabification and segmentation tools per language; existence and Epitran coverage verified, adequacy not yet tested; no tool chosen · status: survey only · updated: 2026-10-08 -->

Existence checked on PyPI (`pip index versions`) and Homebrew on 2026-10-08. Nothing here is a choice. Each language's tool, version, settings and a one-line rationale go in `config/languages.yaml` and `DECISIONS.md` when chosen, and the spec's validation (100 sampled tokens against dictionary syllabifications, or a second independent method) applies to every language.

## Verified to exist

| Package | Version | Registry |
|---|---|---|
| epitran | 1.35.3 | PyPI (installed in `.venv`) |
| pypinyin | 0.55.0 | PyPI (installed) |
| pycantonese | 5.0.0 | PyPI (installed) |
| pythainlp | 5.3.8 | PyPI (installed) |
| espeak-ng | 1.52.0 | Homebrew (not installed) |
| phonemizer | 3.4.0 | PyPI |
| jieba | 0.42.1 | PyPI |
| pkuseg | 0.0.25 | PyPI |
| fugashi, unidic-lite | 1.5.2, 1.0.8 | PyPI |
| pyopenjtalk, pyopenjtalk-plus | 0.4.1, 0.4.1.post9 | PyPI |
| cutlet | 0.5.2 | PyPI |
| g2pk, g2pk2 | 0.9.4, 0.0.3 | PyPI |
| kenlm (Python bindings) | 0.3.0 | PyPI; model building (`lmplz`) needs the C++ build, not checked |
| num2words | 0.5.14 | PyPI (for the secondary unit check's number readings) |
| pyphen | 0.18.1 | PyPI (orthographic hyphenation, a second method for some Latin-script languages) |

## Epitran maps present (from the installed package's `data/map/`)

`vie-Latn`, `cat-Latn`, `deu-Latn` (+ `-nar`, `-np`), `fra-Latn` (+ `-np`, `-p`, `-rev`), `ita-Latn`, `spa-Latn` (+ `-eu`), `srp-Latn`, `srp-Cyrl`, `jpn-Hira`, `jpn-Kana` (+ `-red`), `kor-Hang`, `cmn-Latn`, `yue-Latn`, `tha-Thai`, `tur-Latn` (+ `-bab`, `-red`), `fin-Latn`, `hun-Latn`. None for Basque. English isn't a map; Epitran handles it through an external lexicon. The `cmn-Latn` and `yue-Latn` maps take pinyin and jyutping, not characters, and the Japanese maps take kana, not kanji.

## Per-language decisions still open

- **CMN, YUE:** each character is a syllable (as in the paper); pypinyin and PyCantonese give the toned syllable per character. Open: polyphonic characters (context-sensitive readings) and the word segmenter for the 1w and 1b rungs (jieba or pkuseg; PyCantonese's segmenter). Mandarin Wikipedia mixes traditional and simplified script (`results/stage2/README.md`). Converting to simplified (OpenCC; `opencc` 1.4.2 and `zhconv` 1.4.3 exist on PyPI) would help segmenters trained on simplified text but merges characters with distinct readings (乾/幹/干 → 干). One option: readings from the original characters, word boundaries from a character-aligned simplified copy.
- **JPN:** kanji need a reader (fugashi with UniDic, or pyopenjtalk) before kana can be grouped into syllables. Open: how long vowels, the moraic nasal and geminates group (SPEC.md Stage 3), and whether pitch accent counts as "accent".
- **KOR:** syllabify the phonological form after resyllabification (SPEC.md), so g2pk or g2pk2 output, not Hangul blocks.
- **THA:** needs syllable segmentation and tone; PyThaiNLP has syllable tokenisers and transliteration engines, and Epitran has `tha-Thai`. Adequacy untested.
- **EUS:** no Epitran map. Basque spelling is close to phonemic, so a small rule set is one option, and espeak-ng (which lists Basque) is another.
- **ENG, FRA, DEU:** the paper used the corpus creators' syllabifications (CELEX for ENG and DEU, Lexique for FRA). Spec-review item 9 checks those sources directly for Stage 4; the main pipeline needs its own G2P plus syllabifier.
- **All Latin-script languages:** phonemes from G2P, then syllable boundaries by a stated rule per language (for example, maximal onset over that language's legal onsets). Which rule, and its source, is a per-language entry.

## Test-installed in `.venv` (2026-10-08)

- **fugashi 1.5.2 + unidic-lite 1.0.8:** the `pron` feature is the pronunciation form with long vowels as ー (先生 センセー, 東京 トーキョー, topic は as ワ); `kana` is the spelling-based reading (センセイ). Accent-type fields (`aType`, `aConType`, `aModeType`) are present for a pitch-accent arm.
- **pyopenjtalk-plus 0.4.1.post9:** `g2p(kana=True)` gives the same pronunciation kana (センセーワトーキョーデベンキョーシテイマス); `g2p()` gives phonemes with devoiced vowels in capitals and N for the moraic nasal. ONNX Runtime is absent, so its optional reading predictor for 何 is off.
- **TLTK 1.11:** `g2p` gives syllables with tones (สบายดี → `sa1'baaj0~dii0`) and `th2ipa` gives IPA with tone numbers. Needed scikit-learn 1.9.1: TLTK's dependencies first installed scikit-learn 1.2.2, which failed against numpy 2.5.3 (dtype size mismatch).
- **PyThaiNLP `thaig2p` (torch 2.14.1):** model corpus `thai-g2p` version 0.1 (`~/pythainlp-data/thaig2p-0.1.tar`, 12 MB, outside the project; pin `0.1` in `config/languages.yaml`). Output is IPA syllables with tone letters (สบายดี → `s a ˨˩ . b aː j ˧ . d iː ˧`). First disagreement seen: ตำแหน่ง short /nɛŋ/ (thaig2p) against long /nɛːŋ/ (TLTK).
- `attacut` 1.0.6 exists on PyPI; not yet installed.

## Test-installed in `.venv` (2026-10-09)

- **Environments:** `attacut` 1.0.6 depends on `nptyping`, which requires numpy < 2.0, while SciPy (needed by scikit-learn, TLTK and pyvi) requires numpy ≥ 2.0; installing it pulled numpy to 1.26.4 and broke SciPy. `attacut` now lives in its own `.venv-attacut`; the main `.venv` is back on numpy 2.5.3 with every other tool importing. On the test sentence attacut segments exactly as newmm does.
- **espeak-ng 1.52.0** (Homebrew, already installed): eu ɡelðˈits̻ekˌo es̺ˈan dis̻ˈut (keeps the laminal and apical sibilants apart); de Entkalkungsanlage ɛntkˈalkʊŋsˌanlɑːɡə (right at the compound boundary, where Epitran voiced the s); en-gb button bˈʌtən; fr malheureusement maløʁøzmˈɑ̃ (drops the schwa Epitran keeps); es pjˈano ɣerˈeɾo; ca dəskəlsifikəðˈo (Central Catalan vowel reduction); it ɲˈokːɪ pjˈano; sr prst; tr teşekkürler teʃekːørlˈɛr (ü as ø, which looks wrong next to Epitran's y; to check against a Turkish phonology source); fi kˈiːtoksˌia; hu kˈøsønøm. Stress marks are stripped in the main arm.
- **underthesea 9.5.0 and pyvi 0.1.1** segment Vietnamese differently: "Chúng ta / cần / một / con / ngựa / trị giá / nghìn / đồng / để / làm gì / ?" (underthesea) against "Chúng_ta cần một con ngựa trị_giá nghìn đồng để làm gì ?" (pyvi, which leaves làm gì as two words).
- **g2pk2 0.0.3 with python-mecab-ko 1.3.7:** 먹어 → 머거, 국물 → 궁물, 같이 가요 → 가치 가요, 좋아요 → 조아요, 선릉역 → 설릉역 (resyllabification and assimilation as expected).
- **opencc 1.4.2 (t2s) and jieba 0.42.1:** 這裡是穆德蘭納山脊 → 这里是穆德兰纳山脊 and 我們乾杯吧 → 我们干杯吧, both length-preserving; jieba 这里/是/穆/德兰/纳/山脊, 我们/干杯/吧.
- **pypinyin 0.55.0 reads simplified text better in this case:** 我們乾杯吧 → wo3 men qian2 bei1 ba (乾杯 misread as qián) against 我们干杯吧 → wo3 men gan1 bei1 ba (right). The plan to take readings from the original characters is reversed by this one example; readings from the original and from the converted copy are compared on a sample before one is chosen.
- **pycantonese 5.0.0:** 佢喺旺角出世 → 佢 keoi5 / 喺 hai2 / 旺角 wong6 gok3 / 出世 ceot1 sai3, segmenting as it reads.
- **cmudict 1.1.3:** button B AH1 T AH0 N, problem P R AA1 B L AH0 M. **g2p-en 2.1.0** needs NLTK's `averaged_perceptron_tagger_eng` data before it runs (not yet downloaded).

## More tests (2026-10-09, later)

- **g2p-en 2.1.0** runs once NLTK's `averaged_perceptron_tagger_eng` and `cmudict` data are in `.venv/nltk_data` (set `NLTK_DATA` in the pipeline). Its guesses for words outside CMUdict are rough: Kardashian → K AA1 D AH0 SH EY2 N (three syllables; four is usual); subtitles → S AH1 B T AY2 T AH0 L Z.
- **pkuseg 0.0.25** builds with `--no-build-isolation` once numpy and Cython are installed; numpy stays 2.5.3. It keeps 这里/是/穆德兰纳/山脊, where jieba split the name (穆/德兰/纳). So the CMN segmenter pair is jieba and pkuseg, as planned.
- **Second Cantonese segmenter: cantoseg 0.0.1** (github.com/ayaka14732/cantoseg; jieba with a Cantonese dictionary, so a different algorithm from PyCantonese's longest-match segmenter). On test sentences it agrees on 佢/喺/旺角/出世 and differs elsewhere: it splits 唔該 and 伊利沙伯, where PyCantonese keeps them whole, and joins 做好 and 駁去, where PyCantonese splits them. The YUE pair is PyCantonese and cantoseg.
- **espeak-ng's Turkish ü varies with position:** gül ɟˈøl, üzüm ˈyzøm, kürek kyɾˈɛk, köprü kœprˈø, against Epitran ɡyl, yzym, kyɾek, kœpɾy. ö is œ throughout in both (göl, göz), so ü and ö aren't merged, but espeak-ng would split one Turkish syllable into two types by position. Zimmer & Orgun (1992, *JIPA* 22: 43–45, p. 44; `literature/zimmer_orgun_1992_turkish_ipa_illustration.pdf`, fetched 2026-10-09 at Brett's instruction) give ü as the phoneme /y/ ("y kyl 'ashes'") and ö as /œ/ ("œ gœl 'lake'"), and note that "All vowels except /a, o/ have a lower variant in the final open syllable of a phrase". espeak-ng's lowered ü in köprü (a final open syllable) fits that allophone; its lowered ü in the closed syllables of gül and üzüm isn't described there. Syllable types are built from phonemes, so Epitran (/y/ throughout) is the main Turkish G2P, and espeak-ng serves only for syllable-count agreement. The same page bears on Turkish syllables: long vowels are [iː eː uː aː]; "Dipthongs can be treated as sequences of vowel and /j/"; /ɣ/ (soft g, ğ) is realized "as a lengthening of the preceding vowel" when word-final or before a consonant and is "phonetically zero" between vowels, so how ğ is transcribed changes Turkish syllable counts and has to be checked in Epitran's output.
