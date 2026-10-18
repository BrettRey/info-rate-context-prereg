"""Compute contrasting readings on hand-made examples, without corpus inputs.

Variants illustrate decisions for review; they do not add candidate options.
Run with python -I -B this_file from the working directory.
"""
import importlib.metadata, importlib.util, json, re, subprocess, sys, unicodedata, warnings
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("counters", ROOT / "src/stage3/counters.py")
C = importlib.util.module_from_spec(spec); sys.modules[spec.name] = C; spec.loader.exec_module(C)
NOTE = "notes/stage3-candidate-conventions.md"
WRITTEN = "VIE, KOR, CMN, YUE (one candidate each)"

def trace(value):
    """Keep counts and segmentation alongside the pronunciations that produced them."""
    if isinstance(value, C.Count):
        return dict(asdict(value), switched_word_count=value.switched_word_count)
    return value

def measured(count, segmentation=None, **kwargs):
    return dict(count=count, segmentation=segmentation, **kwargs)

def sample(text, **readings):
    return dict(text=text, readings={name: trace(value) for name, value in readings.items()})

def safe(call):
    try:
        return trace(call())
    except ValueError as e:
        return dict(error=str(e))

def cat_order(text, prons, order, reverse=False):
    """Run the four CAT operations in a supplied order, retaining the same contexts."""
    tokens = C.tokenize(text); words = [C._phones(p, w) for w, p in enumerate(prons)]
    for w, token in enumerate(tokens):
        if token.word.lower() in C.CAT_FUNCTION_WORDS:
            for phone in words[w]:
                phone.stressed = False
    def linked(w): return w + 1 < len(words) and not tokens[w].phrase_end
    def initial(w): return bool(words[w]) and words[w][0].vowel
    def final(w): return bool(words[w]) and words[w][-1].vowel
    for operation in order:
        for w in reversed(range(len(tokens))) if reverse else range(len(tokens)):
            token = tokens[w]
            if operation == "i" and token.word.lower() == "i":
                if (w and linked(w - 1) and final(w - 1)) or (linked(w) and initial(w + 1)):
                    for p in words[w]:
                        if p.vowel: p.text = p.base = "j"
            elif operation == "el/es" and token.word.lower() in {"el", "es"}:
                if w and linked(w - 1) and final(w - 1): words[w] = [p for p in words[w] if not p.vowel]
            elif operation == "que" and token.word.lower() == "que":
                if linked(w) and initial(w + 1): words[w] = [p for p in words[w] if not p.vowel]
            elif operation == "final" and linked(w) and final(w) and initial(w + 1):
                start = C._unstressed_final_vowel_start(words[w])
                if start is not None: del words[w][start:]
    phones = [p for word in words for p in word]
    return C._result(C._r0(phones), phones, tokens, prons, ("variant",) * len(tokens))

def pair_variant(text, prons, mode):
    """Compare phrase-first pairing with word-first pairing or maximal runs."""
    tokens, prons, sources = C._input(text, "SPA", prons)
    phones = [p for w, pron in enumerate(prons) for p in C._phones(pron, w)]
    groups = C._r0(phones)
    if mode == "word-first":
        slot = {phone: i for i, group in enumerate(groups) for phone in group}
        groups = C._pair(groups, phones, tokens)
        out, i = [], 0
        while i < len(groups):
            a = groups[i]
            if i + 1 < len(groups) and len({slot[p] for p in a + groups[i + 1]}) <= 2 and C._adjacent(a, groups[i + 1], phones, tokens, True):
                out.append(a + groups[i + 1]); i += 2
            else: out.append(a); i += 1
    else:
        out = []
        for group in groups:
            if out and C._adjacent(out[-1], group, phones, tokens, True): out[-1].extend(group)
            else: out.append(list(group))
    return C._result(out, phones, tokens, prons, sources)

def endpoint_pairing(ipa):
    """Alternative excluding consonants between, but not at, nucleus endpoints."""
    phones = C._phones(ipa); groups = C._r0(phones); out, i = [], 0
    while i < len(groups):
        a = groups[i]
        if i + 1 < len(groups) and all(p.vowel for p in phones[a[-1] + 1:groups[i + 1][0]]):
            out.append(a + groups[i + 1]); i += 2
        else:
            out.append(a); i += 1
    return C._result(out, phones, C.tokenize(ipa), (ipa,), ("variant",))

def every_tie_nuclear(ipa):
    phones = C._phones(ipa); n, i = 0, 0
    while i < len(phones):
        if "\u0361" in phones[i].text:
            n += 1; i += 2
        else:
            n += int(phones[i].nucleus); i += 1
    return measured(n, pronunciation=ipa)

def italian_edges(text, prons, exceptions=None, whole_terminal_nuclei=False):
    """Protect hiatus boundaries, allowing their nuclei to pair on the other side."""
    tokens, prons, sources = C._input(text, "ITA", prons)
    phones = [p for w, pron in enumerate(prons) for p in C._phones(pron, w)]
    groups = C._r0(phones); forbidden, blocked = set(), set()
    for w, token in enumerate(tokens):
        local = [g for g in groups if phones[g[0]].word == w]
        for a, b in (C.ITA_HIATUS if exceptions is None else exceptions).get(token.word.lower(), ()):
            forbidden.add((local[a][-1], local[b][0]))
        last = max((i for i, p in enumerate(phones) if p.word == w), default=-1)
        if token.phrase_end and len(local) >= 2 and local[-1][-1] == last and C._adjacent(local[-2], local[-1], phones, tokens, False):
            if whole_terminal_nuclei:
                blocked.update(local[-2] + local[-1])
            else:
                forbidden.add((local[-2][-1], local[-1][0]))
    out, i = [], 0
    while i < len(groups):
        a = groups[i]
        if (i + 1 < len(groups) and (a[-1], groups[i + 1][0]) not in forbidden
                and not blocked.intersection(a + groups[i + 1]) and C._adjacent(a, groups[i + 1], phones, tokens, True)):
            out.append(a + groups[i + 1]); i += 2
        else: out.append(a); i += 1
    return C._result(out, phones, tokens, prons, sources)

def turkish_pair_fusion(word, ipa, strict=False):
    """Delete the same soft g's, then fuse disjoint identical pairs instead of chains."""
    phones = C._phones(ipa); out = []
    for i, p in enumerate(phones):
        if p.base == "ɰ" and i and i + 1 < len(phones) and phones[i - 1].vowel and phones[i + 1].vowel:
            if not all(q.base in set("ieɛyœøɪʏæ") for q in (phones[i - 1], phones[i + 1])): continue
        out.append(p)
    groups = C._r0(out); fused, i = [], 0
    while i < len(groups):
        a = groups[i]
        if i + 1 < len(groups):
            b = groups[i + 1]; p, q = out[a[-1]], out[b[0]]
            same = p.text == q.text if strict else p.base == q.base
            if same and b[0] == a[-1] + 1:
                fused.append(a + b); i += 2; continue
        fused.append(a); i += 1
    return C._result(fused, out, C.tokenize(word), (ipa,), ("variant",))

def finnish_first_run(word):
    """Illustrate a first-vowel-run proxy rather than the counter's first parsed syllable."""
    groups, i = [], 0
    first = next((i for i, c in enumerate(word) if c in C.FIN_VOWELS), len(word))
    while i < len(word):
        if word[i] not in C.FIN_VOWELS: i += 1; continue
        pair = word[i:i + 2]; end = i + 1
        if len(pair) == 2 and pair[1] in C.FIN_VOWELS:
            join = pair[0] == pair[1] or pair in C.FIN_DIPHTHONGS
            if pair in {"eu", "ou"} and any(c not in C.FIN_VOWELS for c in word[first:i]): join = False
            if join: end += 1
        groups.append(word[i:end]); i = end
    return measured(len(groups), nuclei=groups)

def basque_precedence(word, ipa, mode, option="C"):
    """Contrast original-triple gliding with sequential gliding or pair-first grouping."""
    if option not in {"A", "C"}:
        raise ValueError("Basque precedence variants require A or C")
    phones = C._phones(ipa)
    for p in phones: p.text = p.text.replace("\u0361", "").replace("\u032f", "")
    high = set("iuɪʊ")
    if mode == "sequential":
        for i in range(1, len(phones) - 1):
            a, b, c = phones[i - 1:i + 2]
            if a.vowel and b.base in high and c.vowel: b.text = b.base = "j" if b.base in "iɪ" else "w"
        # Run C's remaining pair rule on the already transformed phones.
        return C._basque(word, option, ["".join(p.text for p in phones)])
    groups = C._r0(phones); paired, locked, i = [], set(), 0
    while i < len(groups):
        a = groups[i]
        if i + 1 < len(groups):
            b = groups[i + 1]; p, q = phones[a[-1]], phones[b[0]]
            if b[0] == a[-1] + 1 and ((p.base not in high and q.base in high) or (option == "C" and p.base == "u" and q.base == "i")):
                paired.append(a + b); locked.update(a + b); i += 2; continue
        paired.append(a); i += 1
    glides = set()
    for i in range(1, len(phones) - 1):
        a, b, c = phones[i - 1:i + 2]
        if not locked.intersection({i - 1, i, i + 1}) and a.vowel and b.base in high and c.vowel: glides.add(i)
    paired = [[i for i in g if i not in glides] for g in paired]; paired = [g for g in paired if g]
    return C._result(paired, phones, C.tokenize(word), (ipa,), ("variant",))

def tone_second(word):
    """Illustrate second-vowel tone placement in open two-vowel syllables."""
    tones = set("\u0300\u0301\u0309\u0303\u0323")
    decomposed = unicodedata.normalize("NFD", word)
    tone = next(c for c in decomposed if c in tones)
    plain = unicodedata.normalize("NFC", "".join(c for c in decomposed if c not in tones))
    vowels = [i for i, c in enumerate(plain) if unicodedata.normalize("NFD", c)[0] in "aeiouy"]
    pos = vowels[-1]
    result = unicodedata.normalize("NFC", plain[:pos + 1] + tone + plain[pos + 1:])
    return measured(C.vie_a(result).count, (result,))

def old_label_count(ipa):
    """Reproduce the reviewed label contamination, including the old vowel-only ties."""
    phones = C._phones(ipa); groups, i = [], 0
    while i < len(phones):
        p = phones[i]
        if p.nucleus:
            g = [i]
            if p.vowel and "\u0361" in p.text and i + 1 < len(phones) and phones[i + 1].vowel:
                g.append(i + 1); i += 1
            groups.append(g)
        i += 1
    return measured(len(groups), nuclei=["".join(phones[i].text for i in g) for g in groups])

def rows():
    """Build rows in descending potential count exposure, without frequency estimates."""
    result = []
    def add(option, section, quote, reading, alternative, examples, effect, reach):
        result.append(dict(option=option, note=NOTE, section=section, quote=quote, reading=reading,
                           alternative=alternative, examples=examples, effect=effect, reach=reach))

    examples = []
    for text, prons in [("a、e", ["a", "e"]), ("mio。cane", ["mio", "kane"]), ("花儿，女儿", None)]:
        if prons is None:
            current = C.cmn_a(text, {"花儿"})
            # The old tokenizer kept the punctuation in the exact erhua lookup.
            # Explicit old unsplit count, bypassing the now-validated API.
            alt = measured(sum(C._han(c) for c in text))
        elif text.startswith("mio"):
            current = C.ita_b(text, prons); alt = C.ita_b(text.replace("。", " "), prons)
        else:
            current = C.cross_word_pairing(text, prons); alt = C.cross_word_pairing(text.replace("、", " "), prons)
        examples.append(sample(text, code=current, ASCII_only=alt))
    add("Shared: wide punctuation", "Shared definitions", "**Phrase end:** one of . , ; : ? ! … « » \" \" „ ( ) [ ] – —, or the end of a line.",
        "Full-width/CJK equivalents end words and phrases; pending project lead confirmation in the code.",
        "Recognise only the listed narrow marks; wide marks fail to end phrases and may block exact erhua lookup.",
        examples, "counts", "shared boundaries across multiple options")

    examples = [sample(repr("a" + sep + "e"), code=C.cross_word_pairing("a" + sep + "e", ["a", "e"]),
                       LF_CR_only=C.cross_word_pairing("a e", ["a", "e"])) for sep in ("\u2028", "\x85", "\v")]
    add("Shared: line repertoire (fixed)", "Shared definitions", "or the end of a line.",
        "All str.splitlines() boundaries end phrases, including CRLF as one boundary.", "Only LF and CR end phrases (reviewed defect).",
        examples, "counts", "shared boundaries across multiple options")

    examples = [sample(text + (" [supplied IPA a͡ɪ e]" if "͡" in "".join(prons) else ""),
                       code=C.cross_word_pairing(text, prons), word_first=pair_variant(text, prons, "word-first"))
                for text, prons in [("a ea i", ["a", "ea", "i"]), ("a io u", ["a", "io", "u"]), ("a e", ["a͡ɪ", "e"])]]
    add("Shared: phrase pass", "Shared definitions", "The same greedy pass runs over the whole phrase.",
        "Pair original R0 nuclei once over a phrase; a cross-word pair may displace a within-word pair.",
        "First freeze within-word pairs, then pair remaining singletons at boundaries, still respecting the two-nucleus cap. The quoted rule favours the code.",
        examples, "counts", "productive cross-word environments in SPA-B and ITA-B")

    examples = [sample(word, code=C.pairing(word), all_identical_first=C.pairing(re.sub(r"(.)\1+", r"\1", word))) for word in ("aaa", "aaaaa", "aaae")]
    add("Shared: identical-vowel fusion", "Shared definitions", "Identical vowels fuse.",
        "Fusion uses a slot in the two-original-nucleus greedy pair: aaa → aa·a. Grouped strings retain source symbols rather than synthesising a long vowel.",
        "Collapse an entire identical run before pairing, rather than only the chosen pair.", examples, "counts", "identical runs in multiple pairing options")

    examples = [sample(word, code=C.pairing(word), entire_run=pair_variant(word, [word], "all")) for word in ("aei", "aeiou", "aiaia")]
    add("Shared: longer unequal runs", "Shared definitions", "so a syllable holds at most two R0 nuclei.",
        "Take disjoint left-to-right pairs, leaving an odd last nucleus. FIN also caps groups at two spelling vowels.",
        "One group for a whole vowel run; shown as the explicitly excluded earlier-agreement rule, not a candidate fork.",
        examples, "counts", "long vowel sequences across several options")

    examples = []
    for word, voice, counter in [("software", "de", C.deu_a), ("wifi", "fr", C.fra_a), ("weekend", "fr", C.fra_a)]:
        raw = subprocess.run([C.ESPEAK, "-q", "--ipa=3", "-v", voice, "--", word], capture_output=True, text=True, check=True).stdout.strip()
        examples.append(sample(word + " (" + voice + ")", code=counter(word), labels_as_phones=old_label_count(raw.replace("\u200d", "\u0361"))))
    add("Espeak adapters: control labels (fixed)", "Shared definitions", "Every vowel symbol that isn't non-syllabic is one nucleus.",
        "Strip language-switch control labels before phone parsing; preserve the clean switched-language pronunciation and report each affected word token and its language(s).",
        "Reviewed defect: treat label letters as phones. A separate policy could force the original voice, but no such run is a candidate here.",
        examples, "counts", "loanword classes in all espeak-backed options")

    examples = []
    for text, prons in [("la tramuntana i el sol", ["lə", "tɾəmunˈtanə", "i", "əl", "sɔl"]),
                        ("a i el", ["a", "i", "əl"]), ("que el qui", ["kə", "əl", "ki"])]:
        examples.append(sample(text, code=C.cat_b(text, prons), printed_order=cat_order(text, prons, ("el/es", "que", "i", "final")),
                               que_first=cat_order(text, prons, ("que", "el/es", "i", "final"))))
    add("CAT-B: operation order", "CAT", "each tied to its documented context:",
        "Mutate in this order: glide i; delete el/es vowels; delete que vowels; delete unstressed final vowels. Each operation visits tokens left to right and recomputes context after every mutation.",
        "Printed order (el/es, que, i, final), que first, or simultaneous contexts. Order also changes the host in que el qui even when the count stays two.",
        examples, "counts and segmentation/ownership", "productive connected-speech deletions in CAT-B")

    examples = []
    for text in ("la ax", "de ax", "a ax"):
        prons = ('lˈa', 'ˈa')  # invented host and deliberately stressed isolated function word
        code = C.cat_b(text, prons)
        from unittest.mock import patch
        with patch.object(C, 'CAT_FUNCTION_WORDS', frozenset()):
            isolated = C.cat_b(text, prons)
        examples.append(sample(text, code=code, isolation_stress=isolated))
    add("CAT-B: isolated function-word stress", "CAT", "a word-final unstressed vowel drops before a vowel-initial word",
        "Decision 2026-10-10: the frozen English Wiktionary Catalan function-word list overrides isolated stress in CAT-B. Qualifying POS entries require their own IPA and no primary stress in any IPA. Other words retain tool stress.",
        "Historical isolation-stress reading, shown on invented vowel-initial ax and supplied IPA. List, exclusions, hash and provenance are in resources/cat_function_words.tsv and resources/lexicons-provenance.json.",
        examples, "counts", "productive function-word environments in CAT-B")

    examples = []
    for word in ('couvent', 'content', 'préparent'):
        alternative = dict(C._french_module.lowest_entry(C.FRA_ENTRIES[word]))
        examples.append(sample(word, code=C.fra_a(word), lowest_frequency_entry=C.fra_a(word, {word: alternative})))
    add("FRA-A/B: lemma, POS and surface-form selection", "FRA", "Lexique lists forms by part of speech, so verb endings in -ent and -aient come out right",
        "Decision 2026-10-10: frozen Lexique 4.1, highest 10_FreqMot per NFC/lowercase spelling. Frequency ties use ascending POS, phonology, IPA, lemma, syllabification, syllable-number string, original spelling and original frequency string. No contextual tagger or inferred lemma forms.",
        "Contrast the lowest-frequency attested entry using the same deterministic tie rule. These are supplied public Lexique entries; other contextual readings remain possible.",
        examples, "counts", "French inflections and ambiguous lexicon entries")

    examples = [sample(word, code=C.fra_a(word), undecoded_legacy_symbols=C.r0(C.FRA_LEXICON[word]['phon']))
                for word in ('pleuraient', 'enveloppé', 'parvenu')]
    add("FRA-A/B: phonological alphabet", "FRA", "its phonological forms mark schwa two ways:",
        "Lexique 4.1 alphabet checked against every supplied IPA entry: 2 is /ø/ (also nonelidable schwa), ° is elidable /ə/. A keeps all vowels; B deletes only °. Source literal 3 in relish is preserved by the decoder and retained as schwa for counting, explicitly flagged. Supplied legacy overrides keep 3 as schwa.",
        "Compare the supplied IPA column (B removes /ə/) or pass the legacy symbols directly to R0 as an alphabet-mismatch diagnostic. SyllPhono is retained after ° deletion only if its remaining cuts are valid.",
        examples, "counts if the schema is mismatched", "French entries with encoded vowels; release/schema verified on supplied Lexique 4.1")

    examples = []
    for word in ("café", "naïve", "coöperation"):
        raw = tuple(C._english_predictor().predict(word.lower()))
        plain = "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.category(c).startswith("M"))
        examples.append(sample(word, code=C.eng_a(word), raw_predictor=C.eng_a(word, [raw]), normalized_CMU_relookup=C.eng_a(plain)))
    add("ENG-A/B: OOV preprocessing and API", "ENG", "g2p-en 2.1.0 for words CMUdict lacks.",
        "Lowercase and normalise apostrophes before CMU lookup; on a miss, NFKD and drop combining marks, look up CMU again, and only on a second miss call the isolated predictor (decision 2026-10-10).",
        "The old raw predictor, or the historical normalized predictor without a second CMU lookup. The public API also has contextual POS machinery, not measured here.",
        examples, "counts", "English OOV lexical class")

    examples = [sample(word, code=C.spa_b(word, [ipa]), historical_maximal_pairing=C.cross_word_pairing(word, [ipa]))
                for word, ipa in [("día", "dˈia"), ("país", "paˈis"), ("río", "rˈio")]]
    add("SPA-B: stressed close-vowel hiatus", "SPA", "**SPA-B, maximal pairing: SPA-A plus pairing and cross-word pairing.**",
        "Decision 2026-10-10: preserve within-word hiatus containing a stressed close-vowel nucleus. día, país and río each retain two; other within-word and cross-word pairing are unchanged.",
        "Historical maximal pairing without the exemption; or the broader restriction excluding all within-word close-vowel clashes, even unstressed ones.",
        examples, "counts", "Spanish stressed close-vowel hiatus class")

    examples = [sample(text, code=C.ita_b(text, prons, {}), historical_terminal_nuclei=italian_edges(text, prons, {}, whole_terminal_nuclei=True))
                for text, prons in [("suoi", ["suoi"]), ("gennaio", ["d͡ʒennaio"]), ("mio.", ["mio"])]]
    add("ITA-A/B/C: phrase-final protection in longer runs", "ITA", "The phrase-final protection and the exception list take precedence over cross-word pairing.",
        "Decision 2026-10-10: protect only the boundary between the last two adjacent terminal R0 nuclei; an earlier nucleus may pair with the first of them. C does this in every word. Lexical exceptions still protect both named nuclei.",
        "Historical protection of both terminal nuclei, shown with supplied IPA under B; or protection of all nuclei in the terminal run.",
        examples, "counts", "Italian terminal vowel sequences")

    examples = []
    for word in ("riaperto", "riesame", "riavere"):
        _, prons, _ = C._input(word, "ITA")
        exceptions = dict(C.ITA_HIATUS, **{word: ((0, 1),)})
        examples.append(sample(word, code=C.ita_a(word, prons), listed_hiatus=C.ita_a(word, prons, exceptions)))
    add("ITA-A/B/C: exception list beyond riuscito", "ITA", "A frozen list of words that keep a hiatus by lexical prescription, beginning with *riuscito*",
        "Frozen English Wiktionary list: group NFC/lowercase spelling evidence, protect unanimous prescribed pairs only after matching their protected vowels in every minimum-edit phone alignment to the current pronunciation, with consonant anchors. Keep IPA word boundaries and both ties. Skip/report unalignable pairs; main-G2P missing vowels remain limitations. Only forms with own IPA enter; no generated inflections.",
        "Add selected prefix-derived forms or a productive prefix rule. Example additions illustrate potential additions, not new lexical prescriptions; some already occur in the frozen list.",
        examples, "counts", "Italian prefix-derived lexical class and missing inflected forms")

    examples = []
    for word, ipa in [("ea", "ea"), ("ao", "ao")]:
        text = "a " + word + " cane"; prons = ["a", ipa, "kane"]; exceptions = {word: ((0, 1),)}
        examples.append(sample(text, code=C.ita_b(text, prons, exceptions), exception_edge_only=italian_edges(text, prons, exceptions)))
    add("ITA exceptions: protection on both sides", "ITA", "The phrase-final protection and the exception list take precedence over cross-word pairing.",
        "An exception protects both named nuclei, even against cross-word pairing on the opposite side of the listed hiatus.",
        "Forbid only joining the two listed nuclei; allow either to pair with another neighbour. These are artificial exception entries to isolate precedence.",
        examples, "counts", "listed Italian exceptions at vowel boundaries")

    examples = [sample(word, code=C.fin_b(word, ["unused"]), first_vowel_run=finnish_first_run(word)) for word in ("aieus", "aeus", "aous")]
    add("FIN-B/D: first-syllable criterion", "FIN", "**FIN-B: FIN-A, except /eu/ and /ou/ are heterosyllabic outside a word's first syllable.**",
        "First syllable means the first nucleus group in the greedy spelling parse, not the first vowel run or first consonant-delimited chunk.",
        "An independent syllabifier could define position; a first-vowel-run proxy is computed here to expose the difference on invented words. That proxy broadens the literal first-syllable rule.",
        examples, "counts", "Finnish eu/ou in later parsed nuclei")

    examples = [sample(word, code=C.eus_c(word, [word]), pair_first=basque_precedence(word, word, "pairs"),
                       sequential_triples=basque_precedence(word, word, "sequential")) for word in ("uiua", "auia", "iauia")]
    add("EUS-A/C: precedence and overlapping triples", "EUS", "In a sequence of three, a high vowel between two others begins the next syllable.",
        "Find every qualifying middle vowel in the original phone sequence, glide them simultaneously, then apply falling pairs and C's ui merger. Applies inside runs longer than three.",
        "Consume falling/ui pairs before looking for triples, or mutate triples sequentially so the first glide blocks an overlapping triple. Invented runs isolate these choices.",
        examples, "counts", "Basque longer or overlapping vowel sequences")

    examples = [sample(word, code=C.tur_b(word, [ipa]), disjoint_fusion=turkish_pair_fusion(word, ipa))
                for word, ipa in [("ağağa", "aɰaɰa"), ("ağağağa", "aɰaɰaɰa"), ("uğuğu", "uɰuɰu")]]
    add("TUR-B: chains of deleted ɰ", "TUR", "two identical vowels on either side of a deleted ğ fuse into one long vowel.",
        "Fuse cumulatively using the last surviving vowel; a chain of identical back vowels can become one long vowel. Apply the front-vowel exception before any fusion.",
        "Delete qualifying ɰ in parallel, then fuse disjoint original identical pairs; or retain morpheme-boundary hiatus. Examples are invented chains.",
        examples, "counts", "Turkish repeated soft-g chains")

    examples = []
    for word, ipa in [("ağa", "aɰã"), ("uğu", "uːɰu")]:
        examples.append(sample(word + " (marked-vowel fixture)", code=C.tur_b(word, [ipa]), full_symbol_identity=turkish_pair_fusion(word, ipa, True)))
    add("TUR-B: vowel identity", "TUR", "two identical vowels on either side of a deleted ğ fuse into one long vowel.",
        "Identity compares vowel bases, ignoring length and combining diacritics; retain the left vowel's diacritics when extending it.",
        "Require complete symbol identity, so a length or diacritic difference prevents fusion. These supplied markings need not occur in the fixed Epitran map.",
        examples, "counts", "marked vowels around Turkish soft g")

    examples = [sample(word, code=C.fin_a(word, ["unused"]), explicit_class_variant=C.fin_cprime(word, ["unused"])) for word in ("ia", "ae", "eo")]
    add("FIN-A: unenumerated heterosyllabic inventory", "FIN", "double vowels and the 18 diphthongs are tautosyllabic, and the 20 vowel combinations are heterosyllabic.",
        "Join doubles and the listed 18; split every other unequal pair. With eight letters this treats 38 unlisted ordered pairs as hiatus, not an independently verified set of 20.",
        "Verify the book's 20 combinations and domain restrictions. No alternative 20-pair inventory is available here; the approved C′ class supplies a computable contrasting reading for three pairs.",
        examples, "counts; inventory question unresolved", "Finnish unlisted pairs; examples already represented by C′")

    examples = [sample(word + " [supplied IPA " + ipa + "]", code=C.eus_c(word, [ipa]), main_espeak=C.eus_c(word), include_lax_ui=C.eus_c(word, [ipa.replace("ʊ", "u").replace("ɪ", "i")]))
                for word, ipa in [("duin", "dʊɪn"), ("zui", "zʊɪ")]]
    add("EUS-C: literal ui", "EUS", "**EUS-C: EUS-A, except /ui/ is one syllable**",
        "C recognises exactly u followed by i, whereas A's high-vowel set also includes ʊ and ɪ.",
        "Extend C to lax equivalents /ʊɪ/ and mixed forms after a declared phoneme mapping. Supplied IPA differs from the live main G2P; duin is not demonstrated exposure of this lax contrast in that tool.", examples, "counts", "lax ui transcriptions; supplied IPA and main G2P shown separately")

    examples = [sample(word + " [supplied IPA " + ipa + "]", code=C.eus_a(word, [ipa]), main_espeak=C.eus_a(word), recover_high_vowels=C.eus_a(word, [ipa.replace("j", "i").replace("w", "u")]))
                for word, ipa in [("bihar", "bjaɾ"), ("buruan", "burwan"), ("duin", "dwin")]]
    add("EUS-A/C: recovering tool glides", "EUS", "**EUS-A is an explicit rule, not espeak-ng's R0,** so espeak-ng's own diphthong choices don't decide it.",
        "Undo vowel ties and U+032F before the EUS rules, but keep literal j/w/ɥ as consonants; recovery from them is not attempted.",
        "Recover high vowels from selected glide symbols before applying the explicit rule. A universal reverse map would also misread genuine consonantal glides, so it needs lexical/context restrictions. Supplied bjaɾ is not the live main tool's bihar pronunciation.",
        examples, "counts", "tool outputs using literal glides; supplied examples")

    examples = [sample(word, code=C.vie_a(word), spaces_only=measured(len(word.split()), (word,))) for word in ("xin-chào", "Việt-Nam", "hòa-bình")]
    add("VIE-A: spaces versus shared word separators", WRITTEN, "one syllable per space-separated written syllable",
        "Use shared tokenization, so hyphens split written syllables; whitespace beyond ASCII space also separates tokens.",
        "Count only space-delimited units. Hyphenated examples then count as one, despite containing two written syllables.",
        examples, "counts", "hyphenated Vietnamese spellings")

    examples = [sample(word, code=C.cmn_a(word), supplied_list=C.cmn_a(word, {"花儿", "哪儿", "玩儿"})) for word in ("花儿", "哪儿", "玩儿")]
    add("CMN-A: default erhua list", WRITTEN, "a word list giving erhua words their rhotacised reading, to be chosen and its terms checked before the stamp",
        "Frozen English Wiktionary positional erhua list, using generic/Standard Mandarin pinyin. Variable entries choose the erhua reading; provenance and variable words are recorded. No suffixality is inferred for unlisted forms.",
        "Another dictionary or a contextual reading rule. The small caller-supplied list illustrates legacy exact-token overrides, not a competing frozen dictionary.",
        examples, "counts", "Mandarin erhua lexical class; frozen public resource supplied")

    examples = []
    for text, tokens in [("花儿儿子", ["花儿", "儿子"]), ("哪儿女儿", ["哪儿", "女儿"]), ("玩儿儿子", ["玩儿", "儿子"])]:
        erhua = {"花儿", "哪儿", "玩儿"}
        examples.append(sample(text, code=C.cmn_a(text), legacy_exact_tokens=C.cmn_a(text, erhua), supplied_boundaries=C.cmn_a(text, erhua, tokens)))
    add("CMN-A: erhua word boundaries", WRITTEN, "On the corpus side, a dictionary decides which is which",
        "Default/mapping resources use longest nonoverlapping match inside each Han run. Caller subdivisions constrain matching and preserve mandatory separators. Legacy sequence overrides retain exact-token matching.",
        "Another frozen segmenter or exact-token override. Different boundaries can decide which positional suffix matches; examples label legacy overrides explicitly.",
        examples, "counts", "unsegmented Mandarin runs containing erhua words")

    examples = []
    for text in ("花，儿", "花 儿", "花-儿"):
        examples.append(sample(text, code=safe(lambda: C.cmn_a(text, {"花儿"}, ["花儿"])), honour_separators=C.cmn_a(text, {"花儿"})))
    add("CMN-A: supplied-boundary validation (fixed)", "Shared definitions", "a token between spaces, hyphens or phrase-end marks.",
        "Supplied tokens may subdivide a source token but must preserve all NFC source characters, mandatory separators and original phrase-end flags. Reject bridging tokens.",
        "The old Han-sequence-only check erased separators and invented phrase ends (reviewed defect, excluded by the shared definition). Choosing a segmenter inside unbroken runs remains open.",
        examples, "input rejection; prevents invented erhua", "externally supplied Mandarin segmentation; boundary contract fixed")

    examples = [sample(word, code=C.cmn_a(word), legacy_simplified_only=C.cmn_a(word, {"花儿", "哪儿", "玩儿"}))
                for word in ("花兒", "哪兒", "玩兒")]
    add("CMN-A: traditional erhua suffix", WRITTEN, "except the erhua suffix.",
        "Default/mapping lookup normalizes 儿/兒 while retaining positional ownership and supplied script forms. Full simplified/traditional conversion remains outside this rule.",
        "Legacy exact sequence overrides use their literal supplied spellings. The examples contrast the frozen default with a simplified-only override.",
        examples, "counts", "traditional-script Mandarin erhua")

    examples = [sample(word, code=C.cmn_a(word, {"花儿", "哪儿", "玩儿"}), strip_outer_quotes=C.cmn_a(word.strip("'‘’"), {"花儿", "哪儿", "玩儿"}))
                for word in ("'花儿'", "‘哪儿’" )]
    examples.append(sample("u 'el' [supplied IPA ˈu əl]", code=C.cat_b("u 'el'", ["ˈu", "əl"]),
                           strip_outer_quotes=C.cat_b("u el", ["ˈu", "əl"])))
    add("Shared: surrounding single quotes", "Shared definitions", "An apostrophe inside a token doesn't split it",
        "Decision 2026-10-10: strip curly single quotes ‘ ’ at token edges without creating phrase boundaries; retain straight apostrophes at edges and all internal apostrophes. VIE separately removes punctuation before tone normalization.",
        "Historical curly-quote retention; strip straight edge apostrophes too, or treat surrounding quotes as phrase ends. Straight-quote Catalan function-word matching still changes; default Mandarin matches inside Han runs.",
        examples, "counts", "shared quoted tokens; exact-word rules in Mandarin and Catalan")

    examples = [sample(word, code=C.eus_b(word, ["ae"]), broader_hyphen_set=C.eus_b("a-e", ["a", "e"])) for word in ("a－e", "a‒e", "a\u00ade")]
    add("Shared: hyphen repertoire", "Shared definitions", "a token between spaces, hyphens or phrase-end marks.",
        "Split ASCII hyphen, U+2010 and U+2011; en/em dashes end phrases. Full-width hyphen-minus, figure dash and soft hyphen are retained.",
        "Broaden hyphen separators to those characters, with a separate decision on whether each is a word split or a phrase end. Invented EUS-B words show how a word-only pairing option changes.",
        examples, "counts", "less common separator characters")

    examples = []
    for word in ("〇", "⼀", "々"):
        examples.append(sample(word, code=C.yue_a(word), ideographs_only=measured(sum("\u3400" <= c <= "\u9fff" or "\U00020000" <= c <= "\U000323af" for c in word))))
    add("CMN/YUE: Han inventory (fixed)", WRITTEN, "one syllable per Han character.",
        "Use installed regex Script=Han, including radicals, iteration marks and 〇, not merely unified ideographs. All CMN token/list paths use NFC.",
        "Count only ideographs or a hand-written block inventory. D2 explicitly requires Script=Han, settling the implementation; the linguistic treatment of standalone radicals is not separately stated by the note.",
        examples, "counts", "uncommon Han-script characters")

    examples = []
    for word in ("㍻", "㊀"):
        examples.append(sample(word, code=C.yue_a(word), compatibility_normalization=C.yue_a(unicodedata.normalize("NFKC", word))))
    examples.append(sample("ㄱㅏ (supplied KOR output)", code=C.kor_a("가", ["ㄱㅏ"]), compatibility_normalization=C.kor_a("가", [unicodedata.normalize("NFKC", "ㄱㅏ")])))
    add("Written counters: normalization form", WRITTEN, "one syllable per Hangul block of g2pk2's output.",
        "NFC canonical normalization across token paths; it preserves compatibility distinctions not canonically equivalent, and does not compose compatibility jamo.",
        "NFKC would expand compatibility symbols into Han characters and compose compatibility jamo, altering counts. These symbols are artificial edge cases, not observed corpus exposure.",
        examples, "counts", "compatibility symbols and supplied outputs")

    examples = [sample(word, code=C.vie_a(word), every_space_token=measured(len(word.split()), tuple(word.split()))) for word in ("123", "$", "123₫")]
    add("VIE-A: nonalphabetic tokens", WRITTEN, "one syllable per space-separated written syllable",
        "Exclude tokens lacking any alphabetic character; count alphabetic tokens without validating them against a Vietnamese syllable lexicon.",
        "Count every whitespace token, or read digits and symbols into words. Digit/letter conventions for the secondary run remain unfixed; this is not that reader.",
        examples, "counts", "secondary-run digit/symbol inputs")

    examples = [sample("12 (SPA)", code=C.spa_a("12"), ignore_digits=C.spa_a("")),
                sample("42 (VIE)", code=C.vie_a("42"), explicit_number_reading=C.vie_a("bốn mươi hai")),
                sample("7 (CMN)", code=C.cmn_a("7"), explicit_number_reading=C.cmn_a("七"))]
    add("All options: secondary digit/letter readings", "Before the read-text run", "also needs the per-language digit-reading conventions, logged separately,",
        "No common number/letter reader is implemented. Installed G2Ps may read numbers by their defaults; VIE excludes digit-only tokens and CMN/YUE ignore digits. Primary-set exclusion does not settle secondary-run behavior.",
        "Freeze explicit per-language spoken number/letter forms, or exclude these tokens. Examples compare the actual default with dropping or supplying a hand-written number reading; they do not approve a secondary convention.",
        examples, "counts", "secondary run only; digits excluded from the primary set")

    examples = [sample(word, code=C.fin_c(word, ["unused"]), case_sensitive_exact=C.fin_a(word, ["unused"])) for word in ("PIAN", "TAE", "TEOS")]
    add("FIN-C: exact forms and case", "FIN", "the exact word forms *pian*, *tae* and *teos* are one syllable each",
        "Exact membership after NFC and lowercasing, not raw case-sensitive membership. Other inflections remain excluded.",
        "Match only literal lowercase spellings. C is calibration-only under multiverse-spec §2.4, not a full universe dimension.",
        examples, "counts", "case variants of only three calibration forms")

    examples = [sample(word, code=C.fra_a(word), supplied_single_sound=C.fra_a(word, pronunciations={word: ipa})) for word, ipa in [("y", "i"), ("ê", "ɛ")]]
    add("FRA fallback: isolated letters", "FRA", "**Words Lexique lacks** come from espeak-ng",
        "Send an isolated token to fr, which can return a spoken letter/accent name. No special override for y or ê is implemented.",
        "Use intended word/vowel pronunciations or a frozen letter-reading convention. The pre-run French ê fix refers to a separate Epitran issue; these live fallback results remain a limitation.",
        examples, "counts", "isolated French letter tokens")

    examples = []
    for text, prons in [("posa.", ["ˈpɔzə"]), ("la tramuntana es posa.", ["lə", "tɾəmunˈtanə", "əs", "ˈpɔzə"])]:
        passage = list(prons); passage[-1] = "ˈpɔz"
        examples.append(sample(text, code=C.cat_b(text, prons), passage_final_posa=C.cat_b(text, passage)))
    add("CAT-B: final posa in the passage", "CAT", "a word-final unstressed vowel drops before a vowel-initial word",
        "The narrow rules do not delete posa's final schwa without a following vowel. A supplied passage form pɔz is counted as supplied; a main-like pɔzə retains two nuclei.",
        "License additional phrase-final/passage-specific loss, or explain the passage's omitted schwa by a wider source rule. This remains part of the Wheeler/Hualde check, not an added operation.",
        examples, "counts", "one passage-specific deletion; broader class unconfirmed")

    examples = [sample(word, code=C.srp_a(word, [ipa]), isolated_syllabic_r=C.r0("r̩")) for word, ipa in [("r", "r"), ("r̩", "r̩")]]
    add("SRP-A: isolated r", "SRP", "r as a nucleus when it stands between consonants or between a word edge and a consonant.",
        "Strip all U+0329, then derive syllabic r from a neighbouring consonant. A lone r has neither neighbour and counts zero.",
        "Treat an isolated r as a syllabic consonant. The literal contextual rule favours the code; syllabic isolated forms would need an exception.",
        examples, "counts", "isolated r or supplied isolated r̩")

    examples = [sample(ipa, code=C.r0(ipa), syllabic_mark_wins=measured(sum(p.vowel or "\u0329" in p.text for p in C._phones(ipa)))) for ipa in ("j̩", "w̩", "a̯̩")]
    add("Shared: contradictory syllabicity markings", "Shared definitions", "a consonant carrying U+0329.",
        "Glide status or U+032F beats U+0329. Tied second members are suppressed regardless of their two phone classes, as D2 requires.",
        "Let U+0329 override non-syllabic status, or reject contradictory markings. Examples are supplied edge cases, not known adapter output.",
        examples, "counts", "contradictory artificial markings")

    examples = [sample(ipa, code=C.r0(ipa), every_tie_nuclear=every_tie_nuclear(ipa)) for ipa in ("t͡s",)]
    for word, voice in [("Zeit", "de"), ("ciao", "it")]:
        ipa = C.espeak(word, voice)
        examples.append(sample(word + " [espeak " + voice + ": " + ipa + "]", code=C.r0(ipa), every_tie_nuclear=every_tie_nuclear(ipa)))
    add("Shared: nucleus source in a tie", "Shared definitions", "A tie-bar pair is one nucleus",
        "A tie suppresses its second member; the pair contributes a nucleus only if its first member is nuclear. Ordinary consonant affricates remain zero.",
        "Read the quoted sentence literally as making every tied pair nuclear. This is incompatible with the non-syllabic second-member rule and the ordinary affricate examples; the code makes the implicit qualification explicit.",
        examples, "counts", "ordinary tied-affricate lexical classes across languages; Italian espeak is a secondary tool")

    examples = []
    for ipa in ("a͡i͡u", "a͜i͜u͜e"):
        examples.append(sample(ipa, code=safe(lambda ipa=ipa: C.r0(ipa)),
                               one_nucleus=C.r0(ipa, chained_ties="one_nucleus"),
                               disjoint_pairs=C.r0(ipa, chained_ties="disjoint_pairs")))
    ipa = C.espeak("O'Brien", "fr")
    examples.append(sample("O'Brien [espeak fr: " + ipa + "]",
                           code=safe(lambda: C.fra_a("O'Brien")),
                           one_nucleus=C.fra_a("O'Brien", chained_ties="one_nucleus"),
                           disjoint_pairs=C.fra_a("O'Brien", chained_ties="disjoint_pairs")))
    add("Shared: chained ties", "Shared definitions", "the second member of a tie-bar pair (U+0361).",
        "Parameter chained_ties: one_nucleus (default; the lead's decision, row 44), disjoint_pairs, or reject. Accepted chains must contain only vowels; ordinary pairs retain their R0 rule. Both U+0361 and U+035C are ties. Dangling ties, mixed/consonant chains and unattached diacritics still raise ValueError. Results record the setting.",
        "one_nucleus keeps a vowel chain in one group; disjoint_pairs groups left to right, with an odd final vowel independent. Language-specific pairing/deletion follows R0. The tally compares one_nucleus with disjoint_pairs explicitly; rejected chains have no numeric count and fail only their line in other comparisons.",
        examples, "invalid-input policy; alternative changes counts", "English-switched espeak output in French names and German/French English-like invented spellings; finite generated probe only")

    # Equal-count rows follow all count-changing rows.
    examples = []
    for text, prons in [("a i e", ["a", "i", "e"]), ("la i u", ["lə", "i", "u"])]:
        current = C.cat_b(text, prons); segments = list(current.segmentation)
        segments[0] += "j"; segments[1] = segments[1][1:]
        examples.append(sample(text, code=current, i_attaches_backward=measured(current.count, segments)))
    add("CAT-B: hosts of vowel-less i and other words", "CAT", "its consonant joins the neighbouring syllable (the preceding one for *el* and *es*, the following one for *que*)",
        "Vowel-less i attaches forward when a vowel follows, otherwise backward. Other final-vowel deletions attach forward when they leave no nucleus. Follow attachment chains to a surviving host; fail if none exists.",
        "Attach i backward when both neighbours are available; choose another host for a fully elided function word. el/es and que hosts are already specified, so those are not reopened.",
        examples, "segmentation/ownership only", "equal counts; type and word-rung implications")

    examples = []
    for word in ("hòa", "thủy", "khỏe"):
        examples.append(sample(word, code=C.vie_a(word), second_vowel_standard=tone_second(word)))
    add("VIE-A: tone-placement standard", WRITTEN, "after normalising where tone marks sit.",
        "First vowel in ordinary open two-vowel sequences, second before a coda; prefer ê/ơ, middle of triples, discount u/i in qu/gi. Strip punctuation first, so quoted and unquoted forms agree. Preserve case.",
        "A standard placing the tone on the second vowel in open oa/uy/oe sequences: hoà, thuỷ, khoẻ. Both standards count the same written syllables.",
        examples, "segmentation/type spelling only", "zero count changes; tone remains under multiverse-spec §2.2")

    lexicon = {"table": {"phon": "tabl°", "syll": "tabl"}, "porte": {"phon": "pORt°", "syll": "pORt"}, "notre": {"phon": "nOtR°", "syll": "nOtR"}}
    examples = [sample(word, code=C.fra_b(word, lexicon), discard_any_schwa_segmentation=replace(C.fra_b(word, lexicon), segmentation=None)) for word in lexicon]
    add("FRA-B: retained-form syll field (fixed)", "FRA", "syllabification is computed after final schwas are removed",
        "Return syll when its joined segments exactly equal the retained phon form and its segment count matches R0. This includes final-° removal; mismatches stay unsyllabified.",
        "Reviewed defect: discard every segmentation whenever the original phon contains °. No consonant-boundary decision is needed in these three matching fixtures.",
        examples, "segmentation only", "zero count changes; supplied final-schwa entries")

    examples = []
    for word, form, supplied in [("abordera", "abORd°Ra", "a-bOR-d°-Ra"), ("petite", "p°tit", "p°-tit")]:
        current = C.fra_b(word, {word: {"phon": form, "syll": supplied}})
        proposed = ("a", "bOR", "dRa") if word == "abordera" else ("ptit",)
        # Compute the proposed retained-form segmentation through the same API.
        alt = C.fra_b(word, {word: {"phon": form, "syll": "-".join(proposed)}})
        examples.append(sample(word, code=current, resyllabified_fixture=alt))
    add("FRA-B: changed internal-schwa boundaries", "FRA", "**FRA-B: elidable schwas (°) are dropped**, non-elidable ones (3) kept.",
        "Drop every ° for the count. When existing syll no longer segments the retained form, return None instead of assigning consonants to newly adjacent syllables.",
        "Resyllabify the changed form using a frozen consonant-onset policy. The hand-made alternative boundaries are illustrative; no rule is selected here.",
        examples, "segmentation only", "zero count changes; requires Stage 5 boundary policy")

    examples = []
    for text, prons in [("la amica", ["la", "amika"]), ("a e", ["a", "e"])]:
        current = C.cross_word_pairing(text, prons)
        examples.append(sample(text, code=current, right_owner=replace(current, hosts=tuple(m[-1] for m in current.members))))
    add("Shared: cross-word ownership", "Shared definitions", "A pair can then span a word boundary",
        "The merged group belongs to its leftmost contributing word; members records every contributor.",
        "Assign a cross-word group to its rightmost contributor or make a joint word unit. CAT's specified attachment hosts are a separate explicit rule.",
        examples, "ownership/type encoding only", "zero count changes; affects word-aware rungs in multiverse-spec §2.2")

    examples = []
    for word, alt in [("kaksi", ("ka", "ksi")), ("atlas", ("a", "tlas")), ("astra", ("a", "stra"))]:
        # Count the alternative's vowel groups rather than assume it has the same size.
        alt_count = sum(C.fin_a(part, ["unused"]).count for part in alt)
        examples.append(sample(word, code=C.fin_a(word, ["unused"]), all_cluster_onset=measured(alt_count, alt)))
    add("FIN: complete consonant segmentation", "How the list is used", "**Syllable boundaries between consonants** (maximal onset) change types, not counts, and are fixed before Stage 5, not here.",
        "The returned spelling segmentation assigns the last intervening consonant to the next vowel group; the book's hiatus-focused examples do not prescribe all these consonant cuts. IPA alignment is deferred.",
        "Use legal Finnish maximal onsets or keep spelling segmentation incomplete. The all-cluster alternatives here merely demonstrate equal counts; they are not asserted legal onsets.",
        examples, "segmentation only", "zero count changes; all Finnish consonant clusters")

    examples = []
    for word, ipa, segments in [("apa", "apa", ("a", "pa")), ("akta", "akta", ("ak", "ta")), ("aman", "aman", ("a", "man"))]:
        examples.append(sample(word, code=C.r0(ipa), chosen_onsets=measured(sum(C.r0(part).count for part in segments), segments)))
    add("IPA options: full syllable types and stress", "How the list is used", "**Syllable boundaries between consonants** (maximal onset) change types, not counts, and are fixed before Stage 5, not here.",
        "Return nucleus groups and source pronunciations, with segmentation generally None. Nucleus strings omit stress symbols; glides between nuclei can be absent from nucleus strings. Do not treat these as final syllable types.",
        "Build full phone syllables with legal onsets and the marked/unmarked stress fork before Stage 5. Tone stays in tonal types under multiverse-spec §2.2; no syllable-type builder is implemented here.",
        examples, "segmentation/type encoding only", "zero count changes; broad Stage 5 work remains")

    examples = []
    for text in ("신을 신고", "할 수", "할 줄"):
        with C._offline_nltk(): output = C._korean()(text)
        blocks = tuple(c for c in unicodedata.normalize("NFC", output) if "가" <= c <= "힣")
        examples.append(sample(text, code=C.kor_a(text), whole_phrase=measured(len(blocks), blocks, pronunciations=[output])))
    add("KOR-A: isolated versus phrase G2P", WRITTEN, "one syllable per Hangul block of g2pk2's output.",
        "Call g2pk2 word by word with default settings, then NFC and count blocks. Supplied decomposed modern jamo compose before counting.",
        "Call g2pk2 on the whole phrase and freeze contextual settings. Equal counts here do not imply equal pronunciations or types; standalone numbers need a separate reading convention.",
        examples, "segmentation/phones only in these probes", "zero count changes demonstrated; contextual type effects")

    examples = []
    for word, ipa in [("dağ", "daɰ"), ("dağlı", "daɰlɯ"), ("sığ", "sɯɰ")]:
        phones = C._phones(ipa); out = []
        for i, p in enumerate(phones):
            if p.base == "ɰ" and out and out[-1].vowel and (i + 1 == len(phones) or not phones[i + 1].vowel):
                out[-1].text += "ː"
            else: out.append(p)
        changed = "".join(p.text for p in out)
        examples.append(sample(word, code=C.tur_b(word, [ipa]), lengthened_phones=C.tur_b(word, [changed])))
    add("TUR-A/B: final and preconsonantal ɰ", "TUR", "That changes no count in either candidate.",
        "Retain ɰ in the input pronunciation and do not lengthen the nucleus for final/preconsonantal soft g; only intervocalic B grouping is changed.",
        "Remove nonintervocalic ɰ and lengthen the preceding vowel before constructing phonemic types. Counts stay the same; the final type realization remains open.",
        examples, "phones/type encoding only", "zero count changes; Turkish nonintervocalic soft g")

    examples = []
    for word, lower in [("IĞI", "ığı"), ("IĞIĞI", "ığığı"), ("DEĞİL", "değil")]:
        current = C.tur_b(word)
        raw = C._epitran("tur-Latn").transliterate(word)
        label = word + (" (invented suffix chain)" if word.startswith("IĞ") else "")
        examples.append(sample(label, code=current, Epitran_case_handling=C.tur_b(lower, [raw])))
    add("TUR adapters: Turkish casing (fixed)", "TUR", "**Main G2P: Epitran `tur-Latn`**",
        "NFC, map İ→i and I→ı, then lowercase before G2P; uppercase/lowercase inputs now have identical phones and nuclei.",
        "Pass original case to Epitran and let generic lowercasing introduce dotted-i combining marks or wrong dotless-i phones. Turning back ı into front i can incorrectly trigger B's front-vowel exception.",
        examples, "counts and phones/type encoding", "Turkish capital-I soft-g contexts; invented chains isolate the count effect")
    # Capital I can change B's front-vowel exception, so group this fixed reading
    # with the count-changing Turkish rows rather than equal-count type choices.
    casing = result.pop()
    position = next(i for i, row in enumerate(result) if row["option"] == "TUR-B: chains of deleted ɰ")
    result.insert(position, casing)
    examples = [sample(text + " [supplied IPA]", code=C.cat_b(text, text.split()),
                       reverse_token_traversal=cat_order(text, text.split(), ("i", "el/es", "que", "final"), reverse=True))
                for text in ("a e u", "a e u o u")]
    add("CAT-B: traversal within operations", "CAT", "a word-final unstressed vowel drops before a vowel-initial word",
        "Each operation mutates left to right, including its context checks after each token; earlier deletion can alter a later context.",
        "Traverse each operation right to left, or evaluate all its original contexts simultaneously. Simultaneously gliding both original i vowels in i i leaves no surviving nucleus and requires an orphan-host policy; no such policy is implemented.",
        examples, "counts and ownership", "productive connected-speech chains; supplied IPA isolates traversal")
    examples = [sample("x [supplied IPA " + ipa + "]", code=C.eus_b("x", [ipa]), preserve_shared_R0=C.pairing(ipa))
                for ipa in ("a͡ɪe", "aɪ̯e")]
    add("EUS-B: resetting shared R0 slots", "EUS", "pairing on all vowel sequences within a word",
        "B removes vowel tie bars and U+032F, as A/C do, before pairing; originally non-syllabic second members become independent slots.",
        "Keep the shared R0 slots for B, and reset tool diphthong choices only for A/C. Whether B's wording permits the reset needs confirmation.",
        examples, "counts", "Basque tied and non-syllabic vowel transcriptions")
    examples = [sample(ipa, code=C.pairing(ipa), consonants_only_between=endpoint_pairing(ipa)) for ipa in ("n̩a", "an̩a")]
    add("Shared pairing: syllabic-consonant endpoints", "Shared definitions", "adjacent R0 nuclei (nuclei with no consonant between them)",
        "Require vowel symbols at both endpoints as well as throughout the span; syllabic-consonant nuclei never pair.",
        "Exclude consonants strictly between nucleus groups, allowing nuclear consonants themselves to be endpoints. This reading changes supplied n̩a and an̩a.",
        examples, "counts", "shared IPA pairing where syllabic consonants are adjacent to vowels")
    # Broadened reach belongs near the other shared/connected-speech choices.
    for label, before in [("Shared: nucleus source in a tie", "Espeak adapters: control labels (fixed)"),
                          ("Shared: surrounding single quotes", "CAT-B: operation order"),
                          ("CAT-B: traversal within operations", "CAT-B: isolated function-word stress"),
                          ("EUS-B: resetting shared R0 slots", "EUS-C: literal ui"),
                          ("Shared pairing: syllabic-consonant endpoints", "Shared: identical-vowel fusion")]:
        row = result.pop(next(i for i, row in enumerate(result) if row["option"] == label))
        result.insert(next(i for i, row in enumerate(result) if row["option"] == before), row)
    return result + jpn_tha_rows()

def jpn_tha_rows():
    """Append T8 without renumbering any of the 53 frozen older row identities."""
    note = 'notes/stage3-proposal-units-jpn-tha.md'
    def row(title, section, quote, reading, alternative, examples, effect):
        return dict(option=title, note=note, section=section, quote=quote, reading=reading,
                    alternative=alternative, examples=examples, effect=effect,
                    reach='T8: main tools selected 2026-10-10; second tools reported separately; G1/G2 tally retained')
    return [
        row('JPN: G1 versus G2', '3. Japanese',
            'G2: G1, plus /ai/, /oi/ and /ui/ as single syllables.',
            'G1 attaches ー, ン and ッ; other vowel morae remain separate. Extension stacks attach to the preceding vowel (parameter: stacked).',
            'G2 greedily joins ai/oi/ui inside a reader word, with an onsetless イ as the second mora; no pitch accent.',
            [sample(s, code=C.COUNTERS['JPN']['G1'](s), G2=C.COUNTERS['JPN']['G2'](s)) for s in ('アイ ノイ ヌイ', 'カイノイ')], 'counts'),
        row('JPN: pronunciation reader', '3. Japanese',
            'Two independent routes: pyopenjtalk (0.4.1, OpenJTalk dictionary) and fugashi (1.5.2) with UniDic',
            'Main fugashi 1.5.2 / unidic-lite 1.0.8: pron field, contextual reader words in counters, pipeline, analysis and tally. Spaces also split words. Pitch accent stays unmarked. Selected by the project lead on 2026-10-10.',
            'Second pyopenjtalk 0.4.1 / OpenJTalk dictionary: pron field and its own words; devoicing annotations omitted from labels. Counts reported beside fugashi with grouping held constant; not a fork.',
            [sample(s, code=C.COUNTERS['JPN']['G1'](s), pyopenjtalk=C.COUNTERS['JPN']['G1'](s, reader='pyopenjtalk')) for s in ('先生 東京', '痛い 重い', '好き です 六本')], 'counts and strings'),
        row('THA: tone-bearing G2P', '4. Thai',
            "Two independent methods: PyThaiNLP 5.3.8's `thaig2p`",
            'Main TLTK 1.11 via PyThaiNLP 5.3.8, selected by the project lead on 2026-10-10; explicit tones retained in tool IPA strings. Cross-tool notation mapping is comparison-only. Pronunciation units fixed to newmm.',
            'Second pinned local thai-g2p 0.1, CPU one thread; reported alternative, not a fork. Tone labels canonicalized to the same five contours, without removing vowel length.',
            [sample(s, code=C.COUNTERS['THA']['A'](s), thaig2p=C.COUNTERS['THA']['A'](s, tool='thaig2p')) for s in ('มหาวิทยาลัย', 'กานู ปาโน')], 'counts and strings'),
        row('THA: word segmentation', '4. Thai',
            '`newmm` (dictionary-based, PyThaiNLP\'s default) and `attacut` (learning-based), both run',
            'newmm word boundaries; the same newmm pronunciation units for either segmenter.',
            'attacut in its own environment. A split pronunciation unit is assigned automatically when fragment readings exactly reproduce its syllable sequence; otherwise require explicit syllable spans and report failure instead of guessing.',
            [sample(s, code=C.COUNTERS['THA']['A'](s), attacut=safe(lambda: C.COUNTERS['THA']['A'](s, segmenter='attacut'))) for s in ('กานู ปาโน', 'กานูปาโน', 'ภาษาไทย')], 'ownership'),
    ]

def display(value):
    if "error" in value: return "error (" + value["error"] + ")"
    text = str(value["count"])
    if value.get("segmentation") is not None: text += " [" + " · ".join(value["segmentation"]) + "]"
    if value.get("switched_word_count"): text += "; switched=" + str(value["switched_word_count"])
    return text

def main():
    """Write the draft table and its computed traces; verify every note quotation locally."""
    warnings.simplefilter("ignore", FutureWarning)
    warnings.simplefilter("ignore", UserWarning)
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--t8-only', action='store_true')
    args = parser.parse_args()
    if args.t8_only:
        saved = json.loads((ROOT / 'results/d2-reading-examples.json').read_text())
        entries = saved['rows'][:53] + jpn_tha_rows()
    else:
        entries = rows()
    note = (ROOT / NOTE).read_text()
    for entry in entries[53:] if args.t8_only else entries:
        note = (ROOT / entry['note']).read_text()
        if entry['note'] != NOTE:
            if entry['quote'] not in note: raise ValueError('T8 quotation mismatch')
            continue
        heading = "## " + entry["section"] if entry["section"] in {"Shared definitions", "How the list is used", "Before the read-text run"} else "### " + entry["section"]
        section = note.split(heading + "\n", 1)[1].split("\n##", 1)[0]
        if entry["quote"] not in section: raise ValueError("Quote/heading mismatch: " + entry["option"])
        if not 2 <= len(entry["examples"]) <= 3: raise ValueError("Need two or three examples per row")
    versions = {name: importlib.metadata.version(name) for name in ("regex", "epitran", "cmudict", "g2p-en", "g2pk2")}
    metadata = dict(python=sys.version.split()[0], unicode=unicodedata.unidata_version, packages=versions,
                    espeak=subprocess.run([C.ESPEAK, "--version"], capture_output=True, text=True, check=True).stdout.strip())
    loanwords = []
    for lang in (() if args.t8_only else ("DEU", "FRA", "SPA", "CAT")):
        for option, counter in C.COUNTERS[lang].items():
            value = counter("software wifi weekend")
            loanwords.append(dict(language=lang, option=option, result=trace(value)))
    if args.t8_only:
        loanwords = saved['loanword_calls']
    (ROOT / "results/d2-reading-examples.json").write_text(json.dumps(dict(environment=metadata, rows=entries, loanword_calls=loanwords), ensure_ascii=False, indent=2) + "\n")
    lines = ["# Counter readings for project-lead review", "",
             "Draft only. No candidate list or decision log is changed. All numbers below come from this working copy on hand-made words, supplied phone strings, supplied public Lexique/Wiktionary entries, hand-made Lexique entries, or installed offline G2P resources. Invented chains and markings are labelled; they are not claims about lexical validity. No corpus, read text, NS value, network or GPU was used.", "",
             "Rows are ordered by qualitative potential count exposure: shared rules across languages first, then productive connected-speech or lexical classes in one language, then narrower inventories, rare symbols and isolated supplied forms. Equal-count segmentation/phone/ownership choices follow. This is not a ranking of measured frequencies, probabilities, or effect on information rate; there is no corpus evidence for exact counts of affected tokens. Relative order within a class is uncertain. The reach stated in each option cell explains the judgement.", "",
             "Each example gives `code` and named contrasting readings as **counts**, with available full segmentation in brackets. A rejected input is reported as an error, not given a fictitious count. For rows about segmentation only, equal counts are intentional. The JSON trace preserves each input, pronunciation, nucleus group, segmentation, source, ownership and switched-word record. Most IPA counters return no full syllable segmentation because consonant boundaries are deferred.", "",
             "Recompute from the working directory (one CPU process; no downloads):", "",
             "```bash", "OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \\",
             "  /Users/brettreynolds/projects/LLM-CLI-projects/papers/development/info-rate-context/.venv/bin/python \\",
             "  -I -B src/stage3/reading_examples.py", "```", "",
             "The command writes this draft and `results/d2-reading-examples.json`; rerun before annotating, or save review comments separately so they are not overwritten.", "",
             "| Option / potential reach | Note's exact words and section | Reading in the code | Main alternative(s) | Computed examples | Effect |",
             "|---|---|---|---|---|---|"]
    for n, entry in enumerate(entries, 1):
        example_text = []
        for ex in entry["examples"]:
            example_text.append("`" + ex["text"] + "`: " + "; ".join(name + "=" + display(value) for name, value in ex["readings"].items()))
        cells = [str(n) + ". **" + entry["option"] + "**<br>" + entry["reach"],
                 "“" + entry["quote"] + "”<br>[" + entry['note'] + "](../" + entry['note'] + "), §" + entry["section"],
                 entry["reading"], entry["alternative"], "<br>".join(example_text), entry["effect"]]
        lines.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    lines.extend(["", "The remaining implementation gates are in `notes/stage3-candidate-conventions.md` §Before the read-text run. Frozen public ITA, CMN and CAT resources are now available in this candidate worktree for lead review. Lexique 4.1 selection, alphabet and provenance are now frozen in this worktree; review the literal-3 source anomaly and the strict segmentation policy. Verify CAT-B against Wheeler or Hualde; fix secondary-run digit/letter readings; and snapshot/stamp before real counts. The table does not complete those gates. FRA high-vowel/glide free variation remains explicitly excluded (§FRA); EUS lexical/dialect exclusions remain explicit (§EUS); HUN's narrow source basis remains as stated (§HUN). No unstated grouping reading was found for HUN or YUE beyond the shared/character issues above.", "",
                  "`notes/stage3-tool-survey.md` §Per-language decisions still open retains CMN/YUE polyphony, script conversion and word-segmenter questions; §More tests (2026-10-09, later) explains the English predictor limitations and Turkish phonemic-type rationale. `notes/multiverse-spec.md` §2.2 requires stress/tone/type and word-rung alignment; §2.4 keeps FIN-C calibration-only. None is settled by these count probes. The secondary French Epitran ê repair mentioned in the candidate note is separate from the main Lexique/espeak counter.", "",
                  "DEU §DEU is settled by the updated note: the main counter runs on espeak's tied diphthong, so leiten has two syllables. Literal R0 on an untied source-style [aɪ] would count that sequence twice, but it is not the main counter's input. This is not reopened as a design question.", "",
                  "Installed environment for these runs: `" + json.dumps(metadata, ensure_ascii=False) + "`.", ""])
    draft = ROOT / "notes-draft/counter-readings.md"; draft.parent.mkdir(exist_ok=True)
    draft.write_text("\n".join(lines))
    print(str(len(entries)) + (" rows; T8 quotations checked; prior 53 saved rows preserved; 2–3 new examples per T8 row"
                             if args.t8_only else " rows; all quotations and section headings checked; 2–3 computed examples per row"))
    if args.t8_only:
        print('Prior loanword traces below are saved results, not new probes')
    for call in loanwords:
        value = call["result"]
        print(call["language"] + "-" + call["option"] + ": count=" + str(value["count"]) + "; switched_word_count=" + str(value["switched_word_count"]))
    print("Wrote notes-draft/counter-readings.md and results/d2-reading-examples.json")

if __name__ == "__main__":
    main()
