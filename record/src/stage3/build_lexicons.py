"""Derive frozen lists from supplied public Wiktionary sources, offline.

Run with python -I -B src/stage3/build_lexicons.py. No inflection generation,
script converter, corpus, downloads, or pronunciation inference is used.
"""
import csv
import argparse
import gzip
import hashlib
import io
import json
import re
import unicodedata as U
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import regex

ROOT = Path(__file__).resolve().parents[2]
VOWELS = set("iyɨʉɯuɪʏʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒɚɝ")
HAN = regex.compile(r"\p{Han}+")
ER = set("儿兒")
PINYIN = set("""
a ai an ang ao ba bai ban bang bao bei ben beng bi bian biao bie bin bing bo bu
ca cai can cang cao ce cen ceng cha chai chan chang chao che chen cheng chi chong chou chu chua chuai chuan chuang chui chun chuo
ci cong cou cu cuan cui cun cuo da dai dan dang dao de dei den deng di dia dian diao die ding diu dong dou du duan dui dun duo
e ei en eng er fa fan fang fei fen feng fo fou fu ga gai gan gang gao ge gei gen geng gong gou gu gua guai guan guang gui gun guo
ha hai han hang hao he hei hen heng hm hng hong hou hu hua huai huan huang hui hun huo
ji jia jian jiang jiao jie jin jing jiong jiu ju juan jue jun
ka kai kan kang kao ke kei ken keng kong kou ku kua kuai kuan kuang kui kun kuo
la lai lan lang lao le lei leng li lia lian liang liao lie lin ling liu lo long lou lu luan lun luo lv lve
m ma mai man mang mao me mei men meng mi mian miao mie min ming miu mo mou mu
n na nai nan nang nao ne nei nen neng ng ni nia nian niang niao nie nin ning niu nong nou nu nuan nuo nv nve
o ou pa pai pan pang pao pei pen peng pi pian piao pie pin ping po pou pu
qi qia qian qiang qiao qie qin qing qiong qiu qu quan que qun
ran rang rao re ren reng ri rong rou ru rua ruan rui run ruo
sa sai san sang sao se sen seng sha shai shan shang shao she shei shen sheng shi shou shu shua shuai shuan shuang shui shun shuo
si song sou su suan sui sun suo ta tai tan tang tao te teng ti tian tiao tie ting tong tou tu tuan tui tun tuo
wa wai wan wang wei wen weng wo wu xi xia xian xiang xiao xie xin xing xiong xiu xu xuan xue xun
ya yan yang yao ye yi yin ying yo yong you yu yuan yue yun
za zai zan zang zao ze zei zen zeng zha zhai zhan zhang zhao zhe zhei zhen zheng zhi zhong zhou zhu zhua zhuai zhuan zhuang zhui zhun zhuo
zi zong zou zu zuan zui zun zuo
""".split())
SOURCE = {"source": "English Wiktionary, Wiktextract language extracts",
          "dump_date": "2026-09-02", "extract_date": "2026-10-03",
          "license": "CC BY-SA 4.0 and GFDL",
          "citation": "Ylonen, Tatu (2022). Wiktextract: Wiktionary as Machine-Readable Structured Data. LREC 2022, pp. 1317–1325.",
          "citation_url": "https://aclanthology.org/2022.lrec-1.140/",
          "entry_url_template": "https://en.wiktionary.org/wiki/{word}"}
CAT_SOURCE = {
    'source': 'English Wiktionary, Module:ca-IPA, unstressed_words table',
    'source_revision': '91037427',
    'source_revision_date': '2026-06-01',
    'license': 'CC BY-SA 4.0',
    'citation': 'Wiktionary contributors. Module:ca-IPA, revision 91037427 (2026-06-01).',
    'citation_url': 'https://en.wiktionary.org/w/index.php?title=Module:ca-IPA&oldid=91037427',
}


def italian_pairs(ipa):
    """Return R0 nucleus ordinals of an unstressed i/u and a following vowel across a syllable break.

    Stress attaches to the next nucleus (through consonants). Non-syllabic
    vowels and tied second phones aren't separate nuclei. A break is a dot, or
    the stress mark that opens a stressed syllable (rione /riˈo.ne/).
    """
    phones, stress_positions = [], set()
    for c in U.normalize("NFD", ipa.strip("/[]")):
        if c in "ˈˌ":
            stress_positions.add(len(phones))
        elif U.combining(c) or c in "ːˑ":
            if phones:
                phones[-1][1] += c
        elif c == ".":
            phones.append([c, c, False])
        else:
            phones.append([c, c, False])
    nuclei = [i for i, (base, symbols, _) in enumerate(phones)
              if base not in "jwɥ" and (base in VOWELS or "̩" in symbols) and "̯" not in symbols
              and not (i and any(t in phones[i - 1][1] for t in "͜͡"))]
    pending = False
    nuclear_indices = set(nuclei)
    for i, phone in enumerate(phones):
        if i in stress_positions:
            pending = True
        if i in nuclear_indices:
            phone[2] = pending
            pending = False
    pairs = []
    for ordinal, (a, b) in enumerate(zip(nuclei, nuclei[1:])):
        between = [p[0] for p in phones[a + 1:b]]
        # A syllable break is written as a dot, or as the stress mark itself before a stressed syllable
        # (rione /riˈo.ne/); glides are written j/w, so a vowel-written i/u beside a vowel across either
        # break is a hiatus (Claude, 2026-10-10, correcting the dot-only brief).
        boundary = between == ["."] or (between == [] and b in stress_positions)
        if phones[a][0] not in VOWELS or phones[b][0] not in VOWELS or not boundary:
            continue
        # Only an unstressed i/u *before* a vowel: that is the case it-IPA marks by hand (the default would
        # write a glide j/w: ri.uscito, bi.ologia, vi.ale). Wiktionary also splits falling sequences
        # (mai /ˈma.i/, auto /ˈa.u.to/), but that is its module's default, not a marked exception
        # (Claude, 2026-10-10, after a side agent's note; an earlier version accepted either order).
        if phones[a][0] in "iu" and not phones[a][2]:
            pairs.append((ordinal, ordinal + 1))
    return tuple(pairs)


def standard_pinyin(entry):
    """Generic Mandarin or Standard tags; explicitly regional readings excluded."""
    regional = {"Sichuanese", "Chengdu", "Beijing", "Taiwan", "Taiwanese",
                "Northeastern-Mandarin", "Xi'an", "Tianjin"}
    out = set()
    for sound in entry.get("sounds", []):
        tags = set(sound.get("tags", []))
        if {"Mandarin", "Pinyin"} <= tags:
            if not tags.intersection(regional) or tags.intersection({"Standard", "Standard-Chinese"}):
                if sound.get("zh_pron"):
                    out.add(sound["zh_pron"])
    return sorted(out)


def align_erhua(form, pinyin):
    """Find a unique positional reading by syllable/character alignment.

    Normal syllables consume one character; a suffixed r consumes a following
    儿/兒. Apostrophes/whitespace/hyphens are hard syllable boundaries. Ambiguous
    position sets and annotated/unsupported pinyin are rejected, never guessed.
    """
    if not HAN.fullmatch(form):
        return None
    # Wiktextract sometimes appends a separate phonetic/sandhi rendering to
    # the head pinyin. Keep the original in the TSV, align only the head.
    head = re.split(r"\s*\[Phonetic:|\^\(→|\s+\(", pinyin)[0]
    chunks = re.split(r"['’\s-]+", U.normalize("NFC", head).lower())
    normalized = []
    tone = []
    for chunk in chunks:
        if not chunk:
            continue
        plain = ""
        marks = []
        for letter in chunk:
            if not letter.isalpha() or not "a" <= U.normalize("NFD", letter)[0] <= "z":
                return None
            decomposed = U.normalize("NFD", letter)
            base = "v" if "̈" in decomposed else decomposed[0]
            plain += base
            marks.append(any(c in "̄́̌̀" for c in decomposed))
        normalized.append(plain)
        tone.extend(marks)
        tone.append(False)  # boundary marker
    raw = "|".join(normalized)
    if not raw:
        return None

    @lru_cache(None)
    def visit(char, start):
        if start < len(raw) and raw[start] == "|":
            start += 1
        if char == len(form):
            return {()} if start == len(raw) else set()
        # Pinyin requires an apostrophe before a non-initial a/e/o syllable.
        # Without it, e.g. jiěr is jie+r, not ji + er; huā'ér is syllabic.
        if start and start < len(raw) and raw[start] in "aeo" and raw[start - 1] != "|":
            return set()
        results = set()
        for stop in range(start + 1, min(len(raw), start + 7) + 1):
            syllable = raw[start:stop]
            if "|" in syllable:
                break
            if sum(tone[start:stop]) > 1:
                continue
            if syllable in PINYIN and (form[char] not in ER or syllable == "er"):
                results.update(visit(char + 1, stop))
            if (syllable.endswith("r") and syllable[:-1] in PINYIN
                    and (form[char] not in ER or syllable[:-1] == "er")):
                if char + 1 < len(form) and form[char + 1] in ER:
                    results.update((char + 1,) + rest for rest in visit(char + 2, stop))
                else:
                    # A rhotacized syllable needn't have a written suffix
                    # (e.g. gērmenr); that r costs no additional character.
                    results.update(visit(char + 1, stop))
        return results

    positions = visit(0, 0)
    return next(iter(positions)) if len(positions) == 1 else None


def entries(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def form_kind(entry):
    cats = entry.get("categories", [])
    return "form" if any("non-lemma" in c or c.endswith(" forms") for c in cats) else "lemma"


def derive_italian(records):
    candidates = defaultdict(set)
    own_ipa = set()
    verbs = defaultdict(set)
    scanned = 0
    for e in records:
        scanned += 1
        word = U.normalize("NFC", e["word"])
        for s in e.get("sounds", []):
            if "ipa" in s:
                own_ipa.add(word)
                candidates[(word, e.get("pos", ""), form_kind(e))].add(s["ipa"])
        if word in {"riaprire", "riunire", "riuscire"}:
            for f in e.get("forms", []):
                tags = set(f.get("tags", []))
                if tags.intersection({"auxiliary", "table-tags", "inflection-template", "canonical", "infinitive"}):
                    continue
                if not tags:
                    continue
                links = f.get("links", [])
                target = links[0][1].split("#")[0] if links else f["form"]
                if " " not in target and target.startswith("ri"):
                    verbs[word].add(target)
    word_readings = defaultdict(set)
    for (word, _, _), ipas in candidates.items():
        word_readings[word.lower()].update(italian_pairs(ipa) for ipa in ipas)
    selected = {word for word, readings in word_readings.items() if any(readings)}
    rows = []
    for (word, pos, kind), ipas in sorted(candidates.items()):
        if word.lower() in selected:
            for ipa in sorted(ipas):
                rows.append(dict(word=word, pos=pos, kind=kind, ipa=ipa,
                                 protected_pairs=json.dumps(italian_pairs(ipa), separators=(",", ":")),
                                 variable=int(len(word_readings[word.lower()]) > 1)))
    summary = {"scanned_records": scanned, "rows": len(rows), "words": len(selected),
               "lemma_words": len({r['word'].lower() for r in rows if r['kind'] == 'lemma'}),
               "form_words": len({r['word'].lower() for r in rows if r['kind'] == 'form'}),
               "variable_words": sum(len(word_readings[w]) > 1 for w in selected),
               "lemma_form_overlap": len({r['word'].lower() for r in rows if r['kind'] == 'lemma'} &
                                         {r['word'] for r in rows if r['kind'] == 'form'}),
               "non_single_token_entries": sorted(w for w in selected if any(c.isspace() or c in '-‐‑' for c in w)),
               "missing_verb_forms_without_own_ipa": {v: sorted(fs - own_ipa) for v, fs in sorted(verbs.items())},
               "verb_forms_with_own_ipa_but_no_qualifying_dot": {v: sorted(fs & own_ipa - selected) for v, fs in sorted(verbs.items())},
               "policy": "syllable break (dot or stress mark) after an unstressed i/u before a vowel; no generated inflections; counters protect a pair only if every pronunciation of the spelling has it"}
    return rows, summary


def align_italian_rows(rows):
    """Audit selected spellings against the installed main G2P, retaining evidence.

    Row-level mappings make the alignment reviewable; runtime realigns supplied
    pronunciations with the same routine instead of reusing main-G2P ordinals.
    """
    import importlib.util
    import importlib.metadata
    import sys
    spec = importlib.util.spec_from_file_location('builder_alignment_counters', ROOT / 'src/stage3/counters.py')
    counter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = counter
    spec.loader.exec_module(counter)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['word'].lower()].append(row)
    audit = []
    for word, evidence in sorted(grouped.items()):
        agreed = set.intersection(*(set(tuple(p) for p in json.loads(r['protected_pairs'])) for r in evidence))
        if not agreed:
            status, main, pairs = 'no-unanimous-exception', '', ()
        elif tuple(t.word for t in counter.tokenize(word)) != (word,):
            status, main, pairs = 'not-an-exact-token', '', ()
        else:
            main = counter.epitran_word(word, 'ita-Latn')
            aligned = [counter.align_italian_pairs(r['ipa'], main, json.loads(r['protected_pairs'])) for r in evidence]
            status = next((st for _, st in aligned if st != 'aligned'), 'aligned')
            pairs = tuple(sorted(set.intersection(*(set(ps) for ps, _ in aligned)))) if status == 'aligned' else ()
        for row in evidence:
            if main:
                ps, st = counter.align_italian_pairs(row['ipa'], main, json.loads(row['protected_pairs']))
            else:
                ps, st = (), status
            row.update(main_ipa=main, main_protected_pairs=json.dumps(ps, separators=(',', ':')), alignment_status=st)
        audit.append(dict(word=word, main_ipa=main, status=status, protected_pairs=pairs))
    summary = dict(alignment_policy='unique protected-vowel projection across all minimum-edit base-phone alignments; consonant anchors and e/ɛ, o/ɔ neutralization; reject ambiguity, missing vowels and nonadjacent nuclei',
                   main_g2p=dict(tool='epitran', version=importlib.metadata.version('epitran'), voice='ita-Latn', settings={}),
                   unanimous_spellings=sum(a['status'] != 'no-unanimous-exception' for a in audit),
                   aligned_spellings=sum(a['status'] == 'aligned' for a in audit),
                   alignment_skips=[a for a in audit if a['status'] not in {'aligned', 'no-unanimous-exception'}])
    limitations = {}
    for row in rows:
        if row['main_ipa'] and counter.r0(row['ipa'].strip('/[]')).count > counter.r0(row['main_ipa']).count:
            record = limitations.setdefault(row['word'].lower(), dict(word=row['word'].lower(), main_ipa=row['main_ipa'], wiktionary_ipa=[]))
            record['wiktionary_ipa'].append(row['ipa'])
    summary.update(g2p_missing_nucleus_limitations=sorted(limitations.values(), key=lambda r: r['word']),
                   previous_unanimous_spellings=2039, removed_boundary_inclusions=['agli occhi di', 'ti amo'])
    return rows, summary


def derive_mandarin(records):
    readings = defaultdict(set)
    evidence_sources = defaultdict(set)
    categories, usable_categories = set(), set()
    category_tagged, category_eligible = set(), set()
    rejected = set()
    scanned = 0
    for e in records:
        scanned += 1
        word = U.normalize("NFC", e["word"])
        category = "Mandarin erhua terms" in e.get("categories", [])
        if category:
            categories.add(word)
            if any({'Mandarin', 'Pinyin'} <= set(s.get('tags', [])) and s.get('zh_pron') for s in e.get('sounds', [])):
                category_tagged.add(word)
        if not any(c in ER for c in word):
            continue
        forms = {word}
        forms.update(U.normalize("NFC", f["form"]) for f in e.get("forms", [])
                     if set(f.get("tags", [])).intersection({"Simplified-Chinese", "Traditional-Chinese"}))
        pinyins = standard_pinyin(e)
        if category and pinyins:
            category_eligible.add(word)
        for pinyin in pinyins:
            positions = align_erhua(word, pinyin)
            if positions is None:
                rejected.add((word, pinyin))
                continue
            if category:
                usable_categories.add(word)
            for form in forms:
                # Script equivalents must retain the character alignment and 儿 positions.
                if (HAN.fullmatch(form) and len(form) == len(word)
                        and tuple(i for i, c in enumerate(form) if c in ER) == tuple(i for i, c in enumerate(word) if c in ER)):
                    readings[form].add((pinyin, positions))
                    evidence_sources[(form, pinyin, positions)].add(word)
    selected = {w for w, rs in readings.items() if any(pos for _, pos in rs)}
    # Merge positional evidence across 儿/兒-normalized forms and POS homographs.
    normalized = defaultdict(set)
    for word, rs in readings.items():
        normalized[word.replace("兒", "儿")].update(pos for _, pos in rs)
    rows = []
    for word in sorted(selected):
        variable = int(len(normalized[word.replace("兒", "儿")]) > 1)
        for pinyin, pos in sorted(readings[word]):
            rows.append(dict(form=word, pinyin=pinyin, erhua_positions=json.dumps(pos, separators=(",", ":")),
                             variable=variable, source_words=json.dumps(sorted(evidence_sources[(word, pinyin, pos)]), ensure_ascii=False, separators=(",", ":"))))
    missing = sorted(categories - usable_categories)
    summary = {"scanned_records": scanned, "rows": len(rows), "forms": len(selected),
               "normalized_forms": len({w.replace('兒', '儿') for w in selected}),
               "variable_forms": sum(len(normalized[w.replace('兒', '儿')]) > 1 for w in selected),
               "category_members": len(categories), "category_members_without_usable_pinyin": len(missing),
               "category_members_without_tagged_pinyin": len(categories - category_tagged),
               "category_members_only_excluded_regional_pinyin": len(category_tagged - category_eligible),
               "category_members_with_unalignable_pinyin": len(category_eligible - usable_categories),
               "category_members_with_unalignable_pinyin_words": sorted(category_eligible - usable_categories),
               "category_members_without_usable_pinyin_words": missing,
               "forms_with_multiple_positive_position_sets": sum(len({p for p in ps if p}) > 1 for ps in normalized.values()),
               "rejected_alignments": [dict(form=w, pinyin=p) for w, p in sorted(rejected)],
               "policy": "generic/Standard Mandarin Pinyin; align characters; longest nonoverlapping match; variable default erhua (most positions, lexicographic tie-break)"}
    return rows, summary


def tsv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def derive_catalan(records):
    """Historical stress-criterion builder, retained for its existing regression tests.

    Aggregate duplicate word/POS entries; require IPA rather than admitting a
    missing pronunciation vacuously. Other POS homographs do not veto a
    qualifying function-word entry. No forms are inferred from inflection tables.
    Frozen CAT-B defaults now come from derive_catalan_module instead.
    """
    parts = {'article': 'article', 'det': 'determiner', 'prep': 'preposition',
             'conj': 'conjunction', 'pron': 'pronoun'}
    candidates = defaultdict(set)
    source_words = defaultdict(set)
    scanned = 0
    for entry in records:
        scanned += 1
        if entry.get('pos') in parts:
            source_word = U.normalize('NFC', entry['word'])
            canonical = {U.normalize('NFC', f['form']) for f in entry.get('forms', []) if 'canonical' in f.get('tags', [])}
            # A Wiktionary language subpage can hold the spelling in a canonical
            # form field (i/languages A to L -> i). Never infer alternative forms.
            word = next(iter(canonical)) if '/' in source_word and len(canonical) == 1 else source_word
            key = (word, parts[entry['pos']])
            source_words[key].add(source_word)
            candidates[key].update(s['ipa'] for s in entry.get('sounds', []) if s.get('ipa'))
    rows, excluded = [], []
    for (word, pos), ipas in sorted(candidates.items()):
        reason = 'no IPA' if not ipas else ('primary stress in at least one IPA' if any('ˈ' in p for p in ipas) else None)
        if reason:
            excluded.append(dict(word=word, pos=pos, ipas=sorted(ipas), reason=reason))
        else:
            for ipa in sorted(ipas):
                rows.append(dict(word=word, pos=pos, ipa=ipa,
                                 source_words=json.dumps(sorted(source_words[word, pos]), ensure_ascii=False, separators=(',', ':')),
                                 **SOURCE))
    return rows, dict(scanned_records=scanned, candidate_entries=len(candidates),
                      selected_entries=len({(r['word'], r['pos']) for r in rows}),
                      words=len({r['word'].lower() for r in rows}), rows=len(rows),
                      excluded_entries=excluded,
                      policy='qualifying word/POS entries with own IPA and no primary stress in any IPA; unique supplied canonical spelling for language subpages; no generated forms; override isolation stress in CAT-B only')


def derive_catalan_module(source):
    """Read the supplied literal table without executing Lua; retain its category comments."""
    tables = re.findall(r'^local unstressed_words = list_to_set\{\s*\n(.*?)^\}', source, re.M | re.S)
    if len(tables) != 1:
        raise ValueError('Expected exactly one literal unstressed_words table')
    checksum = hashlib.sha256(source.encode('utf-8')).hexdigest()
    category = None
    selected, excluded, seen = [], [], set()
    for line in tables[0].splitlines():
        code, _, comment = line.partition('--')
        if not code.strip():
            if comment.strip():
                category = comment.strip()
            continue
        # Only literal comma-separated words are accepted, never Lua expressions.
        if not re.fullmatch(r'\s*(?:"[^"\\]+"\s*,\s*)+', code) or not category:
            raise ValueError('Unsupported unstressed_words table syntax or missing category')
        for word in re.findall(r'"([^"\\]+)"', code):
            if word in seen:
                raise ValueError('Duplicate unstressed_words spelling: ' + word)
            seen.add(word)
            if word == 'o':
                excluded.append(dict(word=word, category=category,
                                     reason='variable stress; project-lead decision 2026-10-10'))
            else:
                selected.append(dict(word=word, category=category,
                                     source_revision=CAT_SOURCE['source_revision'], source_sha256=checksum))
    if not any(row['word'] == 'o' for row in excluded):
        raise ValueError('Expected the variable conjunction o in the source table')
    return sorted(selected, key=lambda row: row['word']), dict(
        table_words=len(seen), words=len(selected), rows=len(selected), excluded_entries=excluded,
        provenance=dict(CAT_SOURCE, source_sha256=checksum),
        policy='Module:ca-IPA unstressed_words table minus o; NFC-lowercase spelling match; '
               'homographs take the function-word reading; override isolation stress in CAT-B only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=['it', 'zh', 'ca'], help='Rebuild just one list, retaining other metadata')
    args = parser.parse_args()
    manifest = ROOT / 'resources/lexicons-provenance.json'
    meta = json.loads(manifest.read_text(encoding='utf-8')) if args.language else dict(SOURCE, index_base=0, resources={})
    for lang, name, derive, fields in (
        ("it", "ita_hiatus.tsv", derive_italian, ["word", "pos", "kind", "ipa", "protected_pairs", "variable", "main_ipa", "main_protected_pairs", "alignment_status"]),
        ("zh", "cmn_erhua.tsv", derive_mandarin, ["form", "pinyin", "erhua_positions", "variable", "source_words"]),
        ('ca', 'cat_function_words.tsv', derive_catalan_module, ['word', 'category', 'source_revision', 'source_sha256']),
    ):
        if args.language and lang != args.language:
            continue
        source = ROOT / "resources/wiktionary" / ('ca-IPA-91037427.lua' if lang == 'ca' else lang + '.jsonl.gz')
        rows, summary = derive(source.read_bytes().decode('utf-8') if lang == 'ca' else entries(source))
        if lang == "it":
            rows, alignment = align_italian_rows(rows)
            summary.update(alignment)
        data = tsv_bytes(rows, fields)
        (ROOT / "resources" / name).write_bytes(data)
        # The earlier Catalan stress-criterion exclusion file is historical; do not overwrite it.
        with source.open("rb") as source_stream:
            input_checksum = hashlib.file_digest(source_stream, "sha256").hexdigest()
        meta["resources"][name] = dict(summary, sha256=hashlib.sha256(data).hexdigest(), input_sha256=input_checksum,
                                       builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        print(name + ": " + json.dumps({k: v for k, v in summary.items() if not isinstance(v, (list, dict))}, sort_keys=True))
    meta["builder_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (ROOT / "resources/lexicons-provenance.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
