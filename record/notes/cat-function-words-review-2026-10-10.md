# Catalan function words treated as unstressed: for Brett's review
<!-- SUMMARY: the 50-spelling list CAT-B treats as unstressed (row 12), drawn from English Wiktionary, with the entries that look doubtful flagged · status: awaiting Brett · updated: 2026-10-10 -->

**What the list is for.** CAT-B drops a word-final unstressed vowel before a vowel-initial word (*cada u* [ˈkaδ u]). espeak-ng transcribes words one at a time and stresses every monosyllable, so without a list the rule never fires on function words. You decided that a frozen list of function words counts as unstressed. Only vowel-final words are affected, since the rule deletes a final vowel; the glide rule for *i* is separate.

**How it was drawn.** From English Wiktionary's Catalan entries (Wiktextract, dump of 2026-09-02): entries whose part of speech is article, determiner, preposition, conjunction or pronoun, and whose every IPA lacks a primary stress mark. The result is 50 spellings; 300 candidates were excluded (`resources/cat_function_words-excluded.tsv` on branch `codex/t4-stage4-pipeline`).

**The caveat.** Wiktionary marks stress on some monosyllables (*mi* [ˈmi], *tu* [ˈtu], *ell* [ˈeʎ], all rightly excluded) but not consistently. So "no stress mark" lets in at least one stressed word. Please mark any entry to drop, or any word to add.

## Flagged

| Word | Wiktionary IPA | Why it's doubtful | Suggestion |
|---|---|---|---|
| *jo* | [d͡ʒo], [jo], [jɔ], [ʒɔ] | the stressed subject pronoun; [ɔ] can't be unstressed in Eastern Catalan, where "unstressed syllables will only contain one of the three vowel qualities [i], [u] or [ə]" (Carbonell & Llisterri 1992: 55) | drop (on the list, *jo estic* counts 2 syllables, against 3 with *jo* stressed) |
| *si* | [si] | listed as conjunction ('if', unstressed) and pronoun; the reflexive pronoun *si* (after a preposition) is stressed, and matching is by spelling only | keep: the conjunction is far commoner, and the count is the same either way (the rule drops its vowel, *si ell* [seʎ], one syllable; a glide, [sjeʎ], would also be one) |
| *un*, *uns* | [un], [uns] | indefinite article, but the same spelling is the numeral | keep (consonant-final, so the deletion rule never applies to them) |
| *per a que* | [pər ə kə] | multiword; can't match a single token | harmless (its parts are on the list) |

## Excluded, for comparison

- *o* ('or'): excluded because Wiktionary gives [ˈo] and [ˈu], with a stress mark. **Do you want it on the list?**
- *mi*, *tu*, *ell*, *ella*, *nosaltres*: stressed pronouns, rightly excluded.
- *al*, *del*, *als*, *dels*: contractions, not under the parts of speech searched. They end in a consonant, so the rule doesn't apply to them either way.

## The list as drawn (50 spellings)

- **Articles:** *el*, *la*, *els*, *les*, *lo*, *los*, *es*, *ses*, *na*, *en*, *un*, *uns*, *l'*
- **Prepositions:** *a*, *de*, *d'*, *en*, *per*, *pel*, *pels*, *des*, *amb*, *ab*
- **Conjunctions:** *i*, *ni*, *que*, *si*, *per a que*
- **Clitic pronouns:** *em*, *et*, *es*, *se*, *me*, *te*, *ne*, *ens*, *us*, *vos*, *hi*, *ho*, *li*, *la*, *les*, *lo*, *los*, *el*, *els*
- **Unstressed possessives:** *ma*, *mes*, *mon*, *mons*, *mos*, *son*, *ton*, *tons*, *tos*, *tes*
- **Pronoun, flagged:** *jo*

The vowel-final ones the rule can affect are *a*, *de*, *la*, *que*, *me*, *te*, *se*, *ne*, *ma*, *na*, *lo*, *ho*, *li*, *hi*, *si*, *ni*, *i* and *jo*.

---
comments:
  c1:
    body: |-
      I’d revise the list, and I’d also correct the phonological justification. **Drop *jo*, add *ta* and *sa*, and leave *o* outside the core list for now.** The larger issue is that an unstressed final vowel isn’t automatically deletable: the literature distinguishes vowel deletion, gliding, and retained hiatus. [CPNL](https://www.cpnl.cat/gramatica/64/36-els-pronoms-personals-forts/nivell/tots)

      ## Changes to the inventory

      | Entry | My recommendation | Reason |
      |---|---|---|
      | *jo* | **Drop.** | It’s a strong personal pronoun, with lexical stress. That classification directly supports exclusion; the argument from [ɔ] is unnecessary. [CPNL](https://www.cpnl.cat/gramatica/64/36-els-pronoms-personals-forts/nivell/tots) |
      | *ta*, *sa* | **Add their unstressed possessive uses.** | The IEC explicitly lists the singular paradigm *mon, ton, son; ma, ta, sa*. Their absence is a real omission. *Sa* needs a homograph warning, below. [Acadèmia Oberta als Ensenyants](https://aoe.iec.cat/els-possessius/) |
      | *o* | **Leave outside an unqualified unstressed list; mark it as variable.** | Lloret lists *i, ni, si, que* as unstressed, then explicitly identifies *o* as showing variation. Including it would be a chosen weak-form default, rather than a straightforward correction of Wiktionary’s stress marking. [diposit.ub.edu](https://diposit.ub.edu/server/api/core/bitstreams/6b265697-7d5d-4d62-a723-ab24b0688e42/content) |
      | *si* | **Keep as a conjunction default, with an explicit limitation.** | Conjunction *si* is unstressed; reflexive *si* is a strong pronoun. The note’s claim that the ambiguity makes no difference to syllable counts doesn’t establish that. [diposit.ub.edu](https://diposit.ub.edu/server/api/core/bitstreams/6b265697-7d5d-4d62-a723-ab24b0688e42/content) |
      | *un*, *uns* | **No change needed for CAT-B.** | Their consonant endings make them irrelevant to the stated deletion rule. But their stress also varies, so their presence shouldn’t be taken as an independently validated lexical classification. [diposit.ub.edu](https://diposit.ub.edu/server/api/core/bitstreams/6b265697-7d5d-4d62-a723-ab24b0688e42/content) |
      | *per a que* | **Remove from the operational list.** | Given the stated single-token matching, it contributes nothing. Its components are already covered. |
      | *sos* | **Add if you’re maintaining the broader inventory.** | It’s missing from the unstressed possessive paradigm, though it won’t affect CAT-B. *Ses*, already present under articles, also belongs under possessives. [Acadèmia Oberta als Ensenyants](https://aoe.iec.cat/els-possessius/) |

      The homograph limitation extends beyond *si*. In particular:

      - *te* is also the stressed noun meaning ‘tea’.
      - *sa* is also the stressed adjective meaning ‘healthy’.
      - *si* also names a musical note, in addition to its conjunction and reflexive uses.

      These aren’t distinctions that preserving written accents will resolve: the modern spellings are genuinely identical. The affirmative *sí* is separately accented, but the reflexive *si* isn’t. [iec.cat](https://www.iec.cat/llengua/documents/ortografia_catalana_versio_digital.pdf)

      That doesn’t make a spelling-based default unusable. It means the note should describe it as an approximation that assigns the function-word reading. Whether its errors are negligible depends on the corpus; it can’t be established by comparing two proposed pronunciations of one conjunction example.

      ## There’s a more direct Wiktionary source

      English Wiktionary’s [Catalan pronunciation module](https://en.wiktionary.org/w/index.php?title=Module:ca-IPA&oldid=91037427) already contains an explicit `unstressed_words` table. It includes *ta, sa,* and *sos*, and excludes *jo*. That’s a more direct candidate source than reconstructing unstressedness from the absence of IPA stress marks.
    by: user
    at: 2026-10-10T13:07:23.360Z
