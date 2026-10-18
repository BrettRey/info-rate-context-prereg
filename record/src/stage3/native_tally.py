"""T8 adapters for the existing tally schema; all ownership is source-span based."""
from collections import Counter
import hashlib
from pathlib import Path
import sys

TITLES = {54: 'JPN: G1 versus G2', 55: 'JPN: pronunciation reader',
          56: 'THA: tone-bearing G2P', 57: 'THA: word segmentation'}
ALTERNATIVES = {54: ('G2',), 55: ('pyopenjtalk',), 56: ('thaig2p',), 57: ('attacut',)}


def failure_message(error, language):
    """Never publish tool exceptions, cause strings or source text."""
    native = sys.modules['stage3_japanese' if language == 'JPN' else 'stage3_thai']
    value = str(error)
    return value if value in native.FAILURE_MESSAGES else 'Unclassified native failure'


def count(tally_module, line, language, option, cache, row=None):
    C = tally_module.C
    native = sys.modules['stage3_japanese' if language == 'JPN' else 'stage3_thai']
    route = 'second' if row in {55, 56} else 'main'
    if language == 'JPN':
        reader = 'pyopenjtalk' if row == 55 else 'fugashi'
        words, prons, sources = [], [], []
        for chunk in C.tokenize(line):
            value = cache.get(chunk.word, route)
            words.extend(value['tokens']); prons.extend(value['pronunciation'])
            sources.extend(value.get('word_sources', [value['source']] * len(value['tokens'])))
        return C.COUNTERS[language]['G2' if row == 54 else option](
            line, pronunciations=prons, word_tokens=words, reader=reader, pronunciation_sources=sources)
    base = native.tokens(C, line, 'newmm')
    prons = {token.word: cache.get(token.word, route)['pronunciation'] for token in base}
    sources = {token.word: cache.get(token.word, route)['source'] for token in base}
    return C.COUNTERS[language][option](line, pronunciations=prons,
                  tool='thaig2p' if row == 56 else 'tltk', segmenter='attacut' if row == 57 else 'newmm',
                  pronunciation_sources=sources)


def mapped(T, line, reference, variant):
    source = T.spans(line, reference.tokens)
    changed = T.spans(line, variant.tokens)
    out = [0] * len(source)
    for w, (a, b) in enumerate(changed):
        host = next((i for i, (x, y) in enumerate(source) if a < y and b > x), None)
        n = variant.hosts.count(w)
        if host is None and n:
            raise ValueError('Native syllables have no source token')
        if host is not None:
            out[host] += n
    return out


def tally(T, lines, language, selected=None, cache=None, chained_ties='one_nucleus'):
    titles, table_hash = T.table()
    if chained_ties not in T.C.CHAINED_TIES:
        raise ValueError('Unknown chained-tie policy')
    rows = sorted(set(selected)) if selected is not None else [r for r in TITLES if T.options(r, language)]
    if any(r not in titles for r in rows):
        raise ValueError('Unknown reading row')
    cache = cache or T.Cache(language)
    if cache.language != language:
        raise ValueError('Cache language does not match tally language')
    lines = list(lines)
    results, baselines = [], {}
    for row in rows:
        opts = T.options(row, language)
        if not opts:
            results.append(dict(row=row, title=titles[row], language=language, option='', alternative='',
                                status='skipped', reason='Row does not apply to this language.', lines=len(lines), word_tokens=0))
            continue
        for option in opts:
            record = dict(row=row, title=titles[row], language=language, option=option,
                          alternative=ALTERNATIVES[row][0], lines=len(lines))
            totals = Counter(); affected = Counter(); frequencies = Counter(); failures = Counter()
            messages, base_alignment, alternative_alignment = Counter(), Counter(), Counter()
            for index, line in enumerate(lines):
                base = None
                try:
                    if (index, option) not in baselines:
                        baselines[index, option] = count(T, line, language, option, cache)
                    base = baselines[index, option]
                    totals['word_tokens'] += len(base.tokens)
                    variant = count(T, line, language, option, cache, row)
                    before, after = mapped(T, line, base, base), mapped(T, line, base, variant)
                except T.FAILURES as error:
                    totals['failed_lines'] += 1
                    totals['failed_tokens'] += len(base.tokens) if base is not None else 0
                    totals['unattributed_failed_lines'] += 1
                    failures[type(error).__name__] += 1
                    messages[failure_message(error, language)] += 1
                    continue
                totals['successful_lines'] += 1; totals['successful_word_tokens'] += len(base.tokens)
                for result, prefix, alignment in ((base, 'code', base_alignment),
                                                  (variant, 'alternative', alternative_alignment)):
                    provenance = result.resource_provenance or {}
                    totals[prefix + '_non_syllabic_word_tokens'] += len(provenance.get('non_syllabic_words', []))
                    alignment.update(provenance.get('split_unit_alignment', {}))
                totals['code_syllables'] += sum(before); totals['alternative_syllables'] += sum(after)
                changed = 0
                for token, a, b in zip(base.tokens, before, after):
                    frequencies[token.word] += 1
                    if a != b:
                        affected[token.word, a, b] += 1; changed += 1
                totals['changed_word_tokens'] += changed
                totals['changed_lines'] += sum(before) != sum(after)
                totals['lines_with_changed_tokens'] += bool(changed)
            top = Counter()
            for (word, a, b), n in affected.items():
                top[word] += n
            record.update({k: totals[k] for k in ('word_tokens', 'successful_lines', 'successful_word_tokens',
                           'failed_lines', 'failed_tokens', 'unattributed_failed_lines', 'code_syllables', 'alternative_syllables', 'changed_word_tokens',
                           'changed_lines', 'lines_with_changed_tokens')})
            record.update(status='partial' if totals['failed_lines'] and totals['successful_lines'] else
                          'skipped' if totals['failed_lines'] else 'covered',
                          reason='Native syllable/word alignment or G2P failed; inspect explicit failures.' if totals['failed_lines'] else '',
                          failure_kinds=dict(failures), failure_messages=dict(sorted(messages.items())),
                          code_non_syllabic_word_tokens=totals['code_non_syllabic_word_tokens'],
                          alternative_non_syllabic_word_tokens=totals['alternative_non_syllabic_word_tokens'],
                          baseline_split_unit_alignment=dict(base_alignment),
                          alternative_split_unit_alignment=dict(alternative_alignment),
                          difference=totals['alternative_syllables']-totals['code_syllables'],
                          failing_types=[],
                          changed_token_share=totals['changed_word_tokens']/totals['successful_word_tokens'] if totals['successful_word_tokens'] else 0.,
                          changed_line_share=totals['changed_lines']/totals['successful_lines'] if totals['successful_lines'] else 0.,
                          code_unattributed_syllables=0, alternative_unattributed_syllables=0,
                          baseline_chained_ties=chained_ties, alternative_chained_ties=chained_ties,
                          top_types=[{'word': word, 'frequency': frequencies[word], 'affected_frequency': top[word],
                                      'count_pairs': [{'code': a, 'alternative': b, 'frequency': n} for (w, a, b), n in sorted(affected.items()) if w == word]}
                                     for word in sorted(top, key=lambda w: (-top[w], w))[:20]])
            if record['status'] == 'skipped':
                for key in ('code_syllables', 'alternative_syllables', 'difference', 'changed_word_tokens',
                            'changed_lines', 'lines_with_changed_tokens', 'changed_token_share',
                            'changed_line_share', 'code_unattributed_syllables', 'alternative_unattributed_syllables', 'top_types'):
                    record.pop(key, None)
            results.append(record)
    cache.save()
    fallback, alignment_by_option = {}, {}
    for option in sorted({o for _, o in baselines}):
        own = [r for (_, o), r in baselines.items() if o == option]
        n = sum(len(r.tokens) for r in own)
        fallback[option] = dict(word_tokens=n, fallback_word_tokens=sum(
            any(s.endswith('-fallback') for s in source.split('+')) for r in own for source in r.sources),
            non_syllabic_word_tokens=sum(len((r.resource_provenance or {}).get('non_syllabic_words', [])) for r in own),
            sources=dict(Counter(source for r in own for source in r.sources)))
        fallback[option]['share'] = fallback[option]['fallback_word_tokens'] / n if n else 0.
    if language == 'THA':
        keys = sys.modules['stage3_thai'].alignment_counts()
        for option in sorted({r['option'] for r in results if r['option']}):
            own = [r for (_, o), r in baselines.items() if o == option]
            alignment_by_option[option] = {'newmm': {
                **{k: sum((r.resource_provenance or {}).get('split_unit_alignment', {}).get(k, 0)
                          for r in own) for k in keys},
                'failed_lines': len(lines) - len(own)}}
            for record in results:
                if record['option'] == option:
                    counts = record.get('alternative_split_unit_alignment', {})
                    alignment_by_option[option][record['alternative']] = {
                        **{k: counts.get(k, 0) for k in keys}, 'failed_lines': record['failed_lines']}
    return {'schema': 'reading-tally-v2', 'language': language, 'lines': len(lines),
            'word_tokens': next((r['word_tokens'] for r in results if r['option']), 0),
            'fallback_share': next(iter(fallback.values()))['share'] if fallback else 0.,
            'fallback_by_option': fallback,
            'non_syllabic_word_tokens': next(iter(fallback.values()))['non_syllabic_word_tokens'] if fallback else 0,
            'split_unit_alignment_by_option': alignment_by_option,
            'provenance': {'table_sha256': table_hash, 'tally_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           'word_segmenters': ({s: sys.modules['stage3_thai'].descriptor('tltk', s)
                                                for s in (('newmm', 'attacut') if 57 in rows else ('newmm',))}
                                               if language == 'THA' else {}),
                           'token_accounting': 'native reader words; alternative merged words assigned leftmost overlapping baseline token',
                           'Japanese_cache': 'whole source chunks preserve contextual token readings',
                           'failure_messages': 'allowlisted fixed native counter messages; unknown errors redacted',
                           'Thai_pronunciation_units': 'fixed newmm; exact fragments then checked TLTK spelling pieces; inside-piece cuts owned by first character',
                           'adapters': {route: backend.descriptor() for route, backend in sorted(cache.adapters.items())}},
            'rows': results}
