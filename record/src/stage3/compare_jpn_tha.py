"""Compare offline readers with the two explicitly supplied Wiktionary extracts.

No corpus sampling or entropy. Entry/POS records are the main denominator;
unique spelling counts are also reported. Every reference-bearing entry is
attempted, and the same successful set is used for both tools. Dictionary
alternatives match disjunctively. Full entry outcomes and failures go to TSV.
"""
import argparse
from collections import Counter
import csv
import gzip
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('t8_comparison_counters', ROOT / 'src/stage3/counters.py')
C = importlib.util.module_from_spec(spec); sys.modules[spec.name] = C; spec.loader.exec_module(C)
J, T = sys.modules['stage3_japanese'], sys.modules['stage3_thai']


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def long_kana(reading):
    """Comparison heuristic only: identical vowels, /ei/ and /ou/ -> ー.

    These spellings can also represent hiatus. Literal scores are retained and
    this heuristic never changes a counter or reader output.
    """
    out, previous = [], None
    for m in J.morae(reading):
        if m in J.EXTENSIONS:
            out.append(m); previous = None
        elif m in ('ア', 'イ', 'ウ', 'エ', 'オ') and (J.VOWEL[m] == previous or
                (previous, J.VOWEL[m]) in {('e', 'i'), ('o', 'u')}):
            out.append('ー'); previous = None
        else:
            out.append(m); previous = J.VOWEL[m[-1]]
    return ''.join(out)


def references(entry, language, option, normalized=True):
    found = set()
    for sound in entry.get('sounds', ()):
        try:
            if language == 'JPN':
                value = sound.get('other', '')
                if not value or not re.fullmatch(r'[ぁ-ゖァ-ヺー]+', value):
                    continue
                reading = long_kana(value) if normalized else value
                found.add(J.syllables(reading, option)[0])
            else:
                value = sound.get('ipa', '').strip('/[]').strip().strip('.')
                if not value:
                    continue
                # IPA dots are authoritative, whitespace also marks words.
                value = re.sub(r'\s+', '.', value.replace('ˈ', '').replace('ˌ', '').replace('̯', ''))
                found.add(T.parse(value))
        except (ValueError, KeyError):
            continue
    return tuple(sorted(found))


def prediction(word, language, tool, option):
    if language == 'JPN':
        # This diagnostic compares individual readers, rather than the main
        # production route with its fallback. Keep missing readings as failures.
        pairs = J.read_chunk(word, tool)
        return C.COUNTERS['JPN'][option](word, reader=tool,
                    word_tokens=[w for w, _ in pairs], pronunciations=[p for _, p in pairs]).segmentation
    # Dictionary forms are read as a whole, irrespective of internal word cuts.
    return T.transcribe(word, tool)


THAI_NOTATION_MAP = {
    'consonants': {'c': 'tɕ'},
    'diphthongs': {'iːa': 'ia', 'ɯːa': 'ɯa', 'uːa': 'ua'},
    'scope': 'comparison only; applied symmetrically to both tools and references',
    'retained': 'monophthong length, vowel quality, codas, glottal stops, tones and syllable boundaries',
    'qualification': 'diphthong length spelling is treated as notation; consonant-only scores are also reported',
}


def thai_notation(syllables, *, diphthongs=True):
    """Declared common labels, separate from the measured syllable alphabet."""
    result = []
    for syllable in syllables:
        syllable = syllable.replace('c', 'tɕ')
        if diphthongs:
            for source, target in THAI_NOTATION_MAP['diphthongs'].items():
                syllable = syllable.replace(source, target)
        result.append(syllable)
    return tuple(result)


def compare(language, source, prefix, *, predict=None, progress_every=2000, saved_predictions=None):
    source, prefix = Path(source), Path(prefix)
    tools = J.READERS if language == 'JPN' else T.TOOLS
    options = ('G1', 'G2') if language == 'JPN' else ('A',)
    descriptors = {tool: J.descriptor(tool) if language == 'JPN' else T.descriptor(tool) for tool in tools}
    predict = prediction if predict is None else predict
    signature = {'language': language, 'tools': descriptors, 'code_sha256': J.N.sha256(__file__),
                 'source_sha256': J.N.sha256(source)}
    cache_path = prefix.with_suffix('.cache.json')
    memory = {}
    if saved_predictions is not None:
        if language != 'THA' or predict is not prediction:
            raise ValueError('Saved replay is restricted to native Thai predictions')
        saved = json.loads(Path(saved_predictions).read_text(encoding='utf-8'))
        old = saved['signature']
        if old['language'] != language or old['source_sha256'] != signature['source_sha256']:
            raise ValueError('Saved prediction source differs')
        for tool in tools:
            if ({k: v for k, v in old['tools'][tool].items() if k != 'code_sha256'} !=
                    {k: v for k, v in descriptors[tool].items() if k != 'code_sha256'}):
                raise ValueError('Saved prediction tool/model settings differ')
        memory = saved['records']
        signature['prediction_origin'] = {'mode': 'saved only; no inference or failed-record retry',
                                          'cache_sha256': J.N.sha256(saved_predictions),
                                          'original_signature': old}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
        if cache['signature'] != signature:
            raise ValueError('Comparison cache configuration differs; choose a new output prefix')
        memory = cache['records']
    def save():
        temp = cache_path.with_suffix('.tmp')
        temp.write_text(canon({'signature': signature, 'records': memory}) + '\n', encoding='utf-8')
        temp.replace(cache_path)
    start = time.monotonic()
    totals = Counter(); stats = {}; disagreements = {}; common_words = {o: set() for o in options}
    tool_disagreements = {o: Counter() for o in options}
    modes = ('literal', 'normalized') if language == 'JPN' else ('normalized', 'phonemic-consonants', 'phonemic')
    notation_resolved = {tool: Counter() for tool in tools}
    residual_pairs = {tool: Counter() for tool in tools}
    for option in options:
        for mode in modes:
            for tool in tools:
                stats[option, mode, tool] = Counter()
                disagreements[option, mode, tool] = Counter()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    fields = ('entry', 'word', 'pos', 'option', 'status', 'references_literal', 'references_normalized', *tools)
    if language == 'THA':
        fields += ('references_phonemic', *(tool + '_phonemic' for tool in tools))
    with prefix.with_suffix('.tsv').open('w', encoding='utf-8', newline='') as out, gzip.open(source, 'rt', encoding='utf-8') as stream:
        writer = csv.DictWriter(out, fields, delimiter='\t', lineterminator='\n'); writer.writeheader()
        for index, line in enumerate(stream, 1):
            entry = json.loads(line); totals['entries'] += 1
            word = entry['word']
            for option in options:
                ref = references(entry, language, option)
                literal = references(entry, language, option, False)
                row = {'entry': index, 'word': word, 'pos': entry.get('pos', ''), 'option': option,
                       'references_literal': canon(literal), 'references_normalized': canon(ref)}
                if not ref:
                    totals['no_usable_reference_' + option] += 1
                    row['status'] = 'no-usable-reference'; writer.writerow(row); continue
                predictions, errors = {}, {}
                for tool in tools:
                    key = canon([word, option, tool])
                    if key not in memory:
                        if saved_predictions is not None:
                            raise ValueError('Saved replay lacks an eligible prediction; inference forbidden')
                        try:
                            memory[key] = {'syllables': list(predict(word, language, tool, option))}
                        except (ValueError, RuntimeError, LookupError, OSError, KeyError) as error:
                            memory[key] = {'error': type(error).__name__}
                    value = memory[key]; row[tool] = canon(value)
                    if 'error' in value:
                        errors[tool] = value['error']; totals['failure_' + option + '_' + tool] += 1
                    else:
                        predictions[tool] = tuple(value['syllables'])
                if errors:
                    row['status'] = 'tool-failure'; totals['not_common_' + option] += 1
                    writer.writerow(row); continue
                totals['common_' + option] += 1; common_words[option].add(word)
                row['status'] = 'common'
                if predictions[tools[0]] != predictions[tools[1]]:
                    tool_disagreements[option][(word, predictions[tools[0]], predictions[tools[1]])] += 1
                if language == 'THA':
                    mapped_refs = tuple(thai_notation(r) for r in ref)
                    row['references_phonemic'] = canon(mapped_refs)
                    for tool in tools:
                        raw = predictions[tool]; mapped = thai_notation(raw)
                        row[tool + '_phonemic'] = canon({'syllables': mapped,
                            'count_agreement': any(len(mapped) == len(r) for r in mapped_refs),
                            'string_agreement': mapped in mapped_refs})
                        if raw not in ref and mapped in mapped_refs:
                            notation_resolved[tool][(word, raw, ref)] += 1
                        if mapped not in mapped_refs:
                            nearest = min(mapped_refs, key=lambda r: (abs(len(r)-len(mapped)),
                                          sum(a != b for a, b in zip(mapped, r)), r))
                            if len(mapped) != len(nearest):
                                residual_pairs[tool][('syllable count', str(len(mapped)), str(len(nearest)))] += 1
                            else:
                                residual_pairs[tool].update(('syllable string', a, b)
                                                           for a, b in zip(mapped, nearest) if a != b)
                writer.writerow(row)
                for mode in modes:
                    current_ref = literal if mode == 'literal' else ref
                    for tool in tools:
                        s = stats[option, mode, tool]; pred = predictions[tool]
                        if mode.startswith('phonemic'):
                            pred = thai_notation(pred, diphthongs=mode == 'phonemic')
                            current_ref = tuple(thai_notation(r, diphthongs=mode == 'phonemic') for r in ref)
                        s['entries'] += 1
                        count_match = any(len(pred) == len(r) for r in current_ref)
                        string_match = pred in current_ref
                        s['count_agreements'] += count_match; s['string_agreements'] += string_match
                        if not string_match:
                            disagreements[option, mode, tool][(word, pred, current_ref)] += 1
            if index % progress_every == 0:
                save()
                print(f'{language}: {index} entries; {totals["common_" + options[0]]} common; {time.monotonic()-start:.1f}s', flush=True)
    save()
    results = []
    for (option, mode, tool), s in stats.items():
        results.append({'option': option, 'reference_mode': mode, 'tool': tool, **s,
                        'unique_common_spellings': len(common_words[option]),
                        'count_agreement_share': s['count_agreements'] / s['entries'] if s['entries'] else None,
                        'string_agreement_share': s['string_agreements'] / s['entries'] if s['entries'] else None,
                        'commonest_disagreements': [{'word': w, 'frequency': n, 'prediction': p, 'references': r}
                          for (w, p, r), n in sorted(disagreements[option, mode, tool].items(), key=lambda x: (-x[1], x[0]))[:20]]})
    report = {'schema': 't8-tool-comparison-v2', 'language': language, 'totals': dict(totals),
              'results': results, 'provenance': signature, 'elapsed_seconds': time.monotonic() - start,
              'dictionary': {'source': 'English Wiktionary / Wiktextract', 'dump_date': '2026-09-02',
                             'extract_date': '2026-10-03', 'license': 'CC BY-SA 4.0 and GFDL',
                             'citation': 'Ylonen, Wiktextract'},
              'tool_disagreements': {o: [{'word': w, 'frequency': n, tools[0]: a, tools[1]: b}
                   for (w, a, b), n in sorted(ds.items(), key=lambda x: (-x[1], x[0]))[:20]] for o, ds in tool_disagreements.items()},
              'policies': {'denominator': 'entry/POS records with usable reference and success from both tools',
                           'alternatives': 'agreement with any dictionary reading',
                           'Japanese_normalized': 'heuristic identical vowel /ei ou/ length folding; literal also reported',
                           'Thai': 'explicit dotted IPA; canonical lexical tone; remove unreleased-stop marks and ties',
                           'failures': 'explicit TSV rows and per-tool totals; not silently treated as disagreements',
                           'no_reference': 'all extract records retained in TSV; no pronunciation inferred from spelling'}}
    if language == 'THA':
        report['thai_notation_map'] = THAI_NOTATION_MAP
        report['notation_resolved'] = {tool: {'entries': sum(ds.values()), 'commonest': [
            {'word': w, 'frequency': n, 'prediction': p, 'references': r}
            for (w, p, r), n in sorted(ds.items(), key=lambda x: (-x[1], x[0]))[:20]]}
            for tool, ds in notation_resolved.items()}
        report['remaining_differences'] = {tool: [
            {'kind': kind, 'prediction': a, 'reference': b, 'frequency': n}
            for (kind, a, b), n in sorted(ds.items(), key=lambda x: (-x[1], x[0]))]
            for tool, ds in residual_pairs.items()}
        report['policies']['remaining_differences'] = 'nearest explicit alternative for descriptive mismatch pairs; not a gold adjudication'
    prefix.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'language': language, 'totals': report['totals'], 'elapsed_seconds': report['elapsed_seconds'],
                      'scores': [{k: r[k] for k in ('option','reference_mode','tool','entries','count_agreement_share','string_agreement_share')} for r in results]}, ensure_ascii=False), flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('language', choices=('JPN', 'THA')); p.add_argument('source', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--saved-predictions', type=Path, help='Thai saved cache replay; missing records refuse inference')
    a = p.parse_args(); compare(a.language, a.source, a.output, saved_predictions=a.saved_predictions)

if __name__ == '__main__':
    main()
