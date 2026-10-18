"""Count-preserving syllable strings from the counters' effective phone trace.

Pass a frozen Inventory (or explicit phone-tuple set in simulations). IPA cuts
require an inventory; an explicitly empty inventory means every medial cluster
is coda. FIN's default spelling cuts and valid Lexique cuts remain authoritative.
"""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
from dataclasses import dataclass, replace
import re
from pathlib import Path
import sys
import importlib.util
import unicodedata as U


def _load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


O = _load("stage3_onsets", Path(__file__).with_name("onsets.py"))
C = O.C
IPA = frozenset(C.COUNTERS) - {"FIN", "CMN", "YUE", "VIE", "KOR", "JPN", "THA"}
DEFAULTS = {"i_attachment": "code", "vietnamese_tone": "code", "ownership": "left",
            "finnish_boundaries": "code", "stress": "unmarked", "korean_g2p": "isolated",
            "turkish_soft_g": "code", "french_cuts": "code"}
# Row 48 describes missing cuts rather than a defined alternative algorithm.
# The maximal-onset decision supplies row 48's missing algorithm, not a new fork.
UNDEFINED_ROWS = {
    48: "The old code returned no cuts; the T6 maximal-onset decision now supplies them. The fixture is not a general alternative rule.",
}
BOUNDARY_ROWS = {
    45: {"setting": "i_attachment", "values": ("code", "backward"), "options": (("CAT", "B"),)},
    46: {"setting": "vietnamese_tone", "values": ("code", "second_vowel_standard"), "options": (("VIE", "A"),)},
    47: {"setting": "french_cuts", "values": ("code", "discard_any_schwa_segmentation"),
         "options": (("FRA", "B"),), "kind": "fixed-row-diagnostic"},
    49: {"setting": "ownership", "values": ("left", "right", "joint"),
         "options": tuple((l, o) for l, opts in C.COUNTERS.items() for o in opts)},
    50: {"setting": "finnish_boundaries", "values": ("code", "maximal_onset", "all_cluster_onset"),
         "options": tuple(("FIN", o) for o in C.COUNTERS["FIN"])},
    51: {"setting": "stress", "values": ("unmarked", "marked"),
         "options": tuple((l, o) for l in sorted(IPA) for o in C.COUNTERS[l])},
    52: {"setting": "korean_g2p", "values": ("isolated", "whole_phrase"), "options": (("KOR", "A"),)},
    53: {"setting": "turkish_soft_g", "values": ("code", "lengthened_phones"),
         "options": (("TUR", "A"), ("TUR", "B"))},
}


def settings_for(language, option, settings=None):
    O.validate_option(language, option)
    provided = dict(settings or {})
    if set(provided) - set(DEFAULTS):
        raise ValueError("Unknown boundary setting")
    for row in BOUNDARY_ROWS.values():
        setting = row["setting"]
        if setting in provided:
            if (language, option) not in row["options"]:
                raise ValueError("Boundary setting does not apply to this language/option")
            if provided[setting] not in row["values"]:
                raise ValueError("Unknown boundary setting value")
    return {row["setting"]: provided.get(row["setting"], DEFAULTS[row["setting"]])
            for row in BOUNDARY_ROWS.values() if (language, option) in row["options"]}


@dataclass(frozen=True)
class Segmented:
    syllables: tuple
    owners: tuple
    members: tuple
    counter: object
    settings: dict

    @property
    def count(self):
        return len(self.syllables)


def legal_onsets(inventory, language, option, result):
    if isinstance(inventory, O.Inventory):
        if (inventory.language, inventory.option) != (language, option):
            raise ValueError("Onset inventory language/option mismatch")
        chain = inventory.metadata.get('counter_configuration', {}).get('counter_settings', {}).get('chained_ties')
        if chain != result.chained_ties:
            raise ValueError("Onset inventory chained-tie setting mismatch")
        recorded = inventory.metadata.get('counter_configuration')
        actual = {'counter_settings': result.counter_settings, 'counter_options': result.counter_options}
        if recorded != actual:
            raise ValueError("Onset inventory counter settings/configuration mismatch; rebuild it")
        if inventory.metadata.get("counter_sha256") != O.provenance()["counter_sha256"]:
            raise ValueError("Onset inventory was built with different counters")
        return inventory.legal
    if inventory is None:
        return None
    # Simulations may explicitly supply atomic phone tuples, never bare strings.
    values = frozenset(inventory)
    if any(not isinstance(onset, tuple) or any(not isinstance(p, str) or not p for p in onset) for onset in values):
        raise ValueError("Legal onsets must be tuples of atomic phone strings")
    return values


def _cut(texts, start, stop, legal):
    if start == stop:
        return stop
    if legal is None:
        raise ValueError("An explicit onset inventory is required for consonant cuts")
    units, begins = O.tied_units(texts, start, stop)
    for i, beginning in enumerate(begins):
        if units[i:] in legal:
            return beginning
    return stop


def _phone_segments(result, language, legal, settings):
    texts, words, groups = O.effective_trace(result, language)
    texts = list(texts)
    if len(groups) != result.count:
        raise ValueError("Nucleus trace disagrees with the count")
    if language == "TUR" and settings["turkish_soft_g"] == "lengthened_phones":
        # Only final/preconsonantal ɰ: A/B's intervocalic decision is unchanged.
        for i, text in enumerate(tuple(texts)):
            if text != "ɰ" or i == 0 or words[i - 1] != words[i]:
                continue
            nxt = i + 1 < len(texts) and words[i + 1] == words[i]
            if nxt and C._phones(texts[i + 1])[0].vowel:
                continue
            if not texts[i - 1]:
                continue
            previous = C._phones(texts[i - 1])[0]
            if previous.vowel:
                texts[i - 1] = texts[i - 1].rstrip(":ːˑ") + "ː"
                texts[i] = ""
    assignment = [None] * len(texts)
    attached = {a.word: a.nucleus for a in result.attachments}
    for w in range(len(result.tokens)):
        positions = [i for i, owner in enumerate(words) if owner == w]
        local = [(s, min(gp), max(gp)) for s, g in enumerate(groups)
                 if (gp := [i for i in g if words[i] == w])]
        if not local:
            if w in attached:
                for i in positions:
                    assignment[i] = attached[w]
                continue
            raise ValueError("Word has no counted nucleus or attachment")
        if language == "FRA":
            valid = (result.resource_provenance or {}).get("word_segments", ())
            parts = valid[w] if w < len(valid) else None
            if parts:
                legacy = result.resource_provenance.get("nonstandard_3_policy") == "retain-as-schwa"
                cursor = positions[0]
                for (s, _, _), part in zip(local, parts):
                    length = len(C._phones(C.decode_lexique(part, legacy=legacy)))
                    for i in range(cursor, cursor + length):
                        assignment[i] = s
                    cursor += length
                if cursor != positions[-1] + 1:
                    raise ValueError("Lexique syllables disagree with effective phones")
                continue
        cuts = [positions[0]]
        for (_, _, last), (_, first, _) in zip(local, local[1:]):
            start, stop = last + 1, first
            if language == "FIN" and settings["finnish_boundaries"] == "all_cluster_onset":
                cut = start
            else:
                cut = _cut(texts, start, stop, legal)
            cuts.append(cut)
        cuts.append(positions[-1] + 1)
        for (s, _, _), start, stop in zip(local, cuts, cuts[1:]):
            for i in range(start, stop):
                assignment[i] = s
    bodies = [[] for _ in groups]
    marks = [[] for _ in groups]
    for i, (text, s) in enumerate(zip(texts, assignment)):
        if s is None:
            raise ValueError("Unassigned phone")
        if language == "ENG":
            text = text if settings["stress"] == "marked" else re.sub(r"[012]$", "", text)
        elif language != "FIN" and settings["stress"] == "marked" and result.phone_stress[i]:
            marks[s].append(result.phone_stress[i])
        if (result.chained_ties == 'disjoint_pairs' and i + 1 < len(assignment)
                and s != assignment[i + 1]):
            # The trace retains source ties; a syllable cannot tie to a phone
            # that is assigned to another syllable.
            text = text.replace('͡', '').replace('͜', '')
        bodies[s].append(text)
    sep = " " if language == "ENG" else ""
    return tuple("".join(mark) + sep.join(body) for mark, body in zip(marks, bodies))


def vietnamese_second(word):
    normalized = C.normalize_vietnamese(word)
    decomposed = U.normalize("NFD", normalized)
    tones = set("\u0300\u0301\u0309\u0303\u0323")
    tone = "".join(c for c in decomposed if c in tones)
    plain = U.normalize("NFC", "".join(c for c in decomposed if c not in tones))
    lower = plain.lower()
    vowels = [i for i, c in enumerate(plain) if U.normalize("NFD", c.lower())[0] in "aeiouy"]
    if len(vowels) > 1 and lower.startswith(("qu", "gi")):
        vowels = [i for i in vowels if i != 1]
    # Discount onset u/i without excluding the remaining open rhyme.
    if (tone and len(vowels) == 2 and vowels[-1] == len(plain) - 1
            and "".join(lower[i] for i in vowels) in {"oa", "uy", "oe"}):
        return U.normalize("NFC", plain + tone)
    return normalized


def _tonal_segments(result, pronunciations):
    out = []
    for w, token in enumerate(result.tokens):
        value = pronunciations[token.word] if hasattr(pronunciations, "keys") else pronunciations[w]
        labels = value.split() if isinstance(value, str) else tuple(value)
        if len(labels) != result.hosts.count(w):
            raise ValueError("Supply one tonal label per counted Han unit, with erhua already joined")
        for label in labels:
            if not isinstance(label, str) or not label or any(c.isspace() for c in label):
                raise ValueError("Invalid tonal syllable label")
            if not (re.search(r"[0-9˥˦˧˨˩]", label) or any(c in "\u0300\u0301\u0304\u030c" for c in U.normalize("NFD", label))):
                raise ValueError("A Han syllable label must retain an explicit tone")
            out.append(U.normalize("NFC", label))
    return tuple(out)


def _french_clitic_attachments(result, legal):
    """FRA-B: place the consonants of words whose only vowel was a deleted schwa (je, de, le, que...).

    They join the consonant stretch between the neighbouring nuclei and are cut
    there by the onset rule (Brett, 2026-10-14): from the cut on they belong to
    the next nucleus's syllable, before it to the previous one's; at a line edge
    the one neighbour takes them. The word becomes a member of that syllable, so
    the ownership fork decides a syllable that spans words. Counts are unchanged.
    A line of such words alone has no nucleus and stays uncut.
    """
    texts, words, groups = O.effective_trace(result, 'FRA')
    voiced = {words[i] for g in groups for i in g}
    attached = {a.word for a in result.attachments}
    stray = [w for w in range(len(result.tokens))
             if w not in voiced and w not in attached and w in words]
    if not stray or not groups:
        return result
    firsts, lasts = [min(g) for g in groups], [max(g) for g in groups]
    members = [set(m) for m in result.members]
    added = []
    for w in stray:
        positions = [i for i, owner in enumerate(words) if owner == w]
        before = [s for s in range(len(groups)) if lasts[s] < positions[0]]
        after = [s for s in range(len(groups)) if firsts[s] > positions[-1]]
        if not before:
            nucleus, side = after[0], 'before'
        elif not after:
            nucleus, side = before[-1], 'after'
        else:
            cut = _cut(texts, lasts[before[-1]] + 1, firsts[after[0]], legal)
            nucleus, side = (after[0], 'before') if positions[0] >= cut else (before[-1], 'after')
        added.append(C.Attachment(w, result.hosts[nucleus], nucleus, ''.join(texts[i] for i in positions), side))
        members[nucleus].add(w)
    return replace(result, attachments=tuple(result.attachments) + tuple(added),
                   members=tuple(tuple(sorted(m)) for m in members))


def segment_result(result, language, option, inventory=None, *, settings=None, tonal_pronunciations=None):
    """Use with a versioned Stage 4 segmenter callback via `.syllables`.

    CAT row 45 and KOR row 52 alter counting inputs/attachments, so use
    segment_text for those settings. A result already computed with them is fine.
    """
    configured = settings_for(language, option, settings)
    legal = legal_onsets(inventory, language, option, result)
    if language == 'FRA' and option == 'B' and configured['french_cuts'] == 'discard_any_schwa_segmentation':
        resource = dict(result.resource_provenance or {})
        resource['word_segments'] = [None if source == 'lexique' and '°' in pron else parts
                                    for source, pron, parts in zip(result.sources, result.pronunciations,
                                                                   resource.get('word_segments', ()))]
        result = replace(result, resource_provenance=resource)
    if language == 'FRA' and option == 'B':
        result = _french_clitic_attachments(result, legal)
    if language == "CAT" and option == "B" and configured["i_attachment"] != (
            result.resource_provenance or {}).get("i_attachment", "code"):
        raise ValueError("Compute the counter with the requested Catalan attachment setting first")
    covered = {w for members in result.members for w in members}
    provenance = result.resource_provenance or {}
    if language == 'JPN':
        covered.update(provenance.get('dropped_extension_words', []))
        covered.update(provenance.get('non_syllabic_words', []))
    if language == 'THA':
        covered.update(provenance.get('spelling_piece_unowned_words', []))
    if covered != set(range(len(result.tokens))):
        raise ValueError("Words without counted nuclei must not be silently dropped")
    if language in {"CMN", "YUE"}:
        if any(not C._han(c) for token in result.tokens for c in token.word):
            raise ValueError("Unhandled non-Han characters")
        if tonal_pronunciations is None:
            T = _load('stage3_tones', Path(__file__).with_name('tones.py'))
            adapter = T.Tones(language)
            tonal_pronunciations = {t.word: adapter.join(result, w, adapter.transcribe(t.word))
                                    for w, t in enumerate(result.tokens)}
        syllables = _tonal_segments(result, tonal_pronunciations)
    elif language == "VIE":
        syllables = result.segmentation
        if configured["vietnamese_tone"] == "second_vowel_standard":
            syllables = tuple(vietnamese_second(s) for s in syllables)
    elif language in {"KOR", "JPN", "THA"} or language == "FIN" and configured["finnish_boundaries"] == "code":
        syllables = result.segmentation
        if language == "KOR" and any(not ("가" <= c <= "힣") for pron in result.pronunciations
                                     for c in U.normalize("NFC", pron)):
            raise ValueError("Unhandled non-Hangul G2P output")
    elif not result.count:
        if result.tokens:
            raise ValueError("Words without counted nuclei must not be silently dropped")
        syllables = ()
    else:
        syllables = _phone_segments(result, language, legal, configured)
        if language == "FRA":
            # Lexique alphabet and fallback IPA must share one type alphabet.
            valid = (result.resource_provenance or {}).get("word_segments", ())
            legacy = (result.resource_provenance or {}).get("nonstandard_3_policy", "retain-as-schwa") == "retain-as-schwa"
            syllables = list(syllables)
            replaced = set()
            for w, parts in enumerate(valid):
                if parts:
                    indices = [s for s, host in enumerate(result.hosts) if host == w]
                    for s, part in zip(indices, parts):
                        syllables[s] = C.decode_lexique(part, legacy=legacy)
                        replaced.add(s)
            # An attached clitic's consonants (FRA-B) stay in a syllable whose type
            # Lexique's cut replaced, on their side and in word order.
            for s in replaced:
                attached = sorted((a for a in result.attachments if a.nucleus == s), key=lambda a: a.word)
                syllables[s] = (''.join(a.segments for a in attached if a.side == 'before') + syllables[s]
                                + ''.join(a.segments for a in attached if a.side == 'after'))
            syllables = tuple(syllables)
    if syllables is None or len(syllables) != result.count or any(not s for s in syllables):
        raise ValueError("Segmentation must supply exactly one nonempty type per counted nucleus")
    # CAT's explicitly documented hosts take priority over row 49 ownership.
    owners = []
    for host, members in zip(result.hosts, result.members):
        if language == "CAT" or configured["ownership"] == "left":
            owners.append(host)
        elif configured["ownership"] == "right":
            owners.append(max(members))
        else:
            owners.append(tuple(members) if len(members) > 1 else host)
    return Segmented(tuple(syllables), tuple(owners), result.members, result, configured)


def segment_text(text, language, option, inventory=None, *, settings=None,
                 counter_options=None, pronunciations=None, phrase_g2p=None):
    configured = settings_for(language, option, settings)
    kwargs = dict(counter_options or {})
    if language == "CAT" and option == "B":
        if "i_attachment" in kwargs:
            raise ValueError("Set i_attachment through boundary settings")
        kwargs["i_attachment"] = configured["i_attachment"]
    if language not in {"CMN", "YUE", "VIE"} and pronunciations is not None:
        if language == "FRA" and not hasattr(pronunciations, "keys"):
            tokens = C.tokenize(text)
            if len(tokens) != len(pronunciations):
                raise ValueError("Supply one pronunciation per word token")
            pronunciations = {t.word: p for t, p in zip(tokens, pronunciations)}
        kwargs["pronunciations"] = pronunciations
    result = C.COUNTERS[language][option](text, **kwargs)
    if language == "KOR" and configured["korean_g2p"] == "whole_phrase" and result.tokens:
        if phrase_g2p is None:
            with C._offline_nltk():
                output = C._korean()(text)
        else:
            output = phrase_g2p(text)
        # Source separators must survive for unambiguous word ownership.
        before, after = C.tokenize(text), C.tokenize(output)
        if len(before) != len(after) or [t.phrase_end for t in before] != [t.phrase_end for t in after]:
            raise ValueError("Phrase G2P changed word boundaries; explicit alignment is required")
        altered = C.kor_a(text, pronunciations=[t.word for t in after],
                          chained_ties=result.chained_ties)
        if [altered.hosts.count(w) for w in range(len(before))] != [result.hosts.count(w) for w in range(len(before))]:
            raise ValueError("Phrase G2P changed per-word counts; outside the boundary-only comparison")
        result = altered
    return segment_result(result, language, option, inventory, settings=settings,
                          tonal_pronunciations=pronunciations)
