"""Explicit reading tables, fixed token expansions and pipeline counts.

Library callers supply invented tables in tests. The file command in ns_lens.py
applies the existing anchored-freeze hold before reading either input table.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage6_reading_adapter_iterables", _BoundaryPath(__file__).resolve().parents[1] / "stage5/iterables.py")
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import csv
import hashlib
import importlib.util
import io
import math
from pathlib import Path
import sys

import regex

ROOT = Path(__file__).resolve().parents[2]


@_boundary
def load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


E = load('p4_entropy_guard', ROOT / 'src/stage3/segment_entropy.py')
# Use the same pipeline instance checked by entropy_authorization.
P = E._load('stage3_entropy_pipeline', ROOT / 'src/stage4/pipeline.py')
M = E._load('stage3_multiverse', ROOT / 'src/stage3/multiverse.py')
A = load('p4_analysis', ROOT / 'src/stage6/analysis.py')
READING_FIELDS = ('Speaker', 'Language', 'Text', 'Sex', 'Duration', 'NS', 'ShE', 'ID', 'Age')
TEXT_FIELDS = ('Language', 'Text', 'text')
NON_LATIN = frozenset(('CMN', 'YUE', 'JPN', 'KOR', 'THA'))
DIGIT_FIELDS = ('id', 'language', 'text', 'offset', 'token', 'reading', 'kind',
                'source', 'confidence', 'note')
DIGIT_READINGS = ROOT / 'resources/digit-readings/readings.tsv'


@_boundary
def table(path, fields):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != list(fields):
            raise ValueError('Unexpected TSV schema: ' + ', '.join(fields))
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError('Malformed TSV row')
    return rows


@_boundary
def validate_tables(readings, texts):
    """Check identifiers, paired text coverage, duplicate readings and constants.

    Paper ID may be constant per language or per language/text; use each
    reading's value rather than silently imposing language-wide constancy.
    """
    readings, texts = [dict(r) for r in readings], [dict(t) for t in texts]
    if not readings or not texts:
        raise ValueError('Nonempty readings and texts required')
    text_keys, reading_keys, constants = set(), set(), {}
    for t in texts:
        if set(t) != set(TEXT_FIELDS) or not all(isinstance(t[k], str) for k in TEXT_FIELDS):
            raise ValueError('Invalid text row')
        key = (t['Language'], t['Text'])
        if not all(key) or t['Language'] not in M.REGISTRY or key in text_keys:
            raise ValueError('Unknown language, empty identifier or duplicate text')
        text_keys.add(key)
    for r in readings:
        if set(r) != set(READING_FIELDS) or any(not isinstance(r[k], str) or not r[k]
                or '\x1f' in r[k] for k in ('Speaker', 'Language', 'Text')):
            raise ValueError('Invalid reading row or identifier')
        key = (r['Language'], r['Text'])
        rk = (r['Language'], r['Speaker'], r['Text'])
        if key not in text_keys or rk in reading_keys:
            raise ValueError('Missing read text or duplicate reading')
        reading_keys.add(rk)
        for k in ('Duration', 'NS', 'ID', 'ShE'):
            r[k] = float(r[k])
            if not math.isfinite(r[k]) or (r[k] <= 0 if k != 'ShE' else r[k] < 0):
                raise ValueError('Invalid reading numeric value')
        if not r['NS'].is_integer():
            raise ValueError('NS must be a positive integer count')
        if key in constants and constants[key] != (r['NS'], r['ID']):
            raise ValueError('NS and ID must be constant within language/text')
        constants[key] = (r['NS'], r['ID'])
    # Unread rows cannot influence calibration or selection of the text subset.
    return readings, [t for t in texts if (t['Language'], t['Text']) in constants]


@_boundary
def primary(text, language):
    """Any Unicode digit excludes a text; Latin letters exclude five languages."""
    return not any(c.isdigit() for c in text) and not (
        language in NON_LATIN and regex.search(r'[\p{Latin}&&\p{L}]', text, regex.V1))


@_boundary
def normalized_text(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


@_boundary
def expansion_text(text):
    """Offsets address characters after physical newline sequences become spaces."""
    return normalized_text(text).replace('\n', ' ')


class DigitExpander:
    """One language's explicit text-ID-specific readings, bound to supplied texts."""
    @_boundary
    def __init__(self, language, texts, rows, table_sha256):
        self.language = language
        self.texts = texts
        self.rows = rows
        self.provenance = dict(scheme='fixed-token-readings-v1', table_sha256=table_sha256,
                               offset_rule='LF replaced by one space after CRLF/CR normalization',
                               newline_rule='CRLF/CR normalized to LF; line breaks preserved')

    @_boundary
    def provenance_for(self, text_id):
        return dict(self.provenance, reading_ids=[r['id'] for r in self.rows[text_id]])

    def __call__(self, text, *, text_id=None):
        text = normalized_text(text)
        if text_id is None:
            matches = [key for key, value in self.texts.items() if value == text]
            if len(matches) != 1:
                raise ValueError('Expansion requires an unambiguous supplied text ID')
            text_id = matches[0]
        if text_id not in self.texts or self.texts[text_id] != text:
            raise ValueError('Expansion text differs from the supplied language/text')
        rows = self.rows[text_id]
        deletions = []
        for row in reversed(rows):
            start, token = row['offset'], row['token']
            end = start + len(token)
            if '\n' in text[start:end]:
                raise ValueError('Reading token spans a line break')
            if expansion_text(text)[start:end] != token:
                raise ValueError('Reading token not found exactly at its offset')
            delta = len(row['reading']) - len(token)
            deletions = [position + delta for position in deletions]
            if not row['reading']:
                deletions.append(start)
            text = text[:start] + row['reading'] + text[end:]
        # Do this after all splices so removing a separator cannot invalidate
        # an earlier token's original span (a token may itself contain spaces).
        for position in sorted(deletions, reverse=True):
            if text[:position].endswith(' ') and text[position:].startswith(' '):
                text = text[:position] + text[position+1:]
            elif position == 0 and text.startswith(' '):
                text = text[1:]
            elif position == len(text) and text.endswith(' '):
                text = text[:-1]
        if not primary(text, self.language):
            raise ValueError('Digit or required Latin letter left unexpanded')
        return text


@_boundary
def load_digit_expanders(path, texts):
    """Read one TSV snapshot, validate every row, return per-language callables.

    All table rows must refer to supplied (Language, Text) keys. No token search,
    number inference, transliteration or fallback is performed. Ordinary Latin
    letters remain allowed in Latin-script languages; Unicode digits never do.
    """
    supplied = {}
    for t in texts:
        key = (t['Language'], t['Text'])
        if key[0] not in M.REGISTRY or not key[1] or key in supplied or not isinstance(t['text'], str):
            raise ValueError('Invalid or duplicate supplied expansion text')
        supplied[key] = normalized_text(t['text'])
    data = Path(path).read_bytes()
    reader = csv.DictReader(io.StringIO(data.decode('utf-8'), newline=''), delimiter='\t')
    if reader.fieldnames != list(DIGIT_FIELDS):
        raise ValueError('Unexpected digit readings TSV schema')
    grouped = {key: [] for key in supplied}
    ids = set()
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError('Malformed digit readings TSV row')
        key = (row['language'], row['text'])
        if key not in supplied:
            raise ValueError('Reading table row references a text that is not supplied')
        if not row['id'] or row['id'] in ids or not row['token']:
            raise ValueError('Empty token/ID or duplicate reading ID')
        ids.add(row['id'])
        if not regex.fullmatch(r'[0-9]+', row['offset']):
            raise ValueError('Reading offset must be a nonnegative integer')
        row['offset'] = int(row['offset'])
        start, token = row['offset'], row['token']
        if '\n' in supplied[key][start:start+len(token)]:
            raise ValueError('Reading token spans a line break')
        if expansion_text(supplied[key])[start:start+len(token)] != token:
            raise ValueError('Reading token not found exactly at its offset')
        grouped[key].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: r['offset'])
        if any(a['offset']+len(a['token']) > b['offset'] for a, b in zip(rows, rows[1:])):
            raise ValueError('Overlapping or duplicate reading spans')
    sha256 = hashlib.sha256(data).hexdigest()
    expanders = {language: DigitExpander(language,
        {text_id: value for (lang, text_id), value in supplied.items() if lang == language},
        {text_id: rows for (lang, text_id), rows in grouped.items() if lang == language}, sha256)
        for language in sorted({lang for lang, _ in supplied})}
    # Fail before any counting if any supplied text has uncovered tokens.
    for (language, text_id), text in supplied.items():
        expanders[language](text, text_id=text_id)
    return expanders


@_boundary
def subset_texts(texts, subset='primary', expanders=None):
    if subset not in {'primary', 'secondary'}:
        raise ValueError('Unknown text subset')
    if subset == 'secondary':
        expanders = expanders or {}
        missing = sorted({t['Language'] for t in texts if not callable(expanders.get(t['Language']))})
        if missing:
            raise ValueError('Secondary expansion unspecified for: ' + ', '.join(missing))
    selected, excluded = [], []
    for t in texts:
        if subset == 'primary' and not primary(t['text'], t['Language']):
            excluded.append({'Language': t['Language'], 'Text': t['Text'], 'reason': 'digits-or-Latin'})
            continue
        expander = expanders[t['Language']] if subset == 'secondary' else None
        value = (expander(t['text'], text_id=t['Text']) if isinstance(expander, DigitExpander)
                 else t['text'] if expander is None else expander(t['text']))
        if not isinstance(value, str):
            raise ValueError('Expansion must return text')
        if subset == 'secondary' and not primary(value, t['Language']):
            raise ValueError('Digit or required Latin letter left unexpanded')
        selected.append(dict(t, text=value))
        if isinstance(expander, DigitExpander):
            selected[-1]['expansion_provenance'] = expander.provenance_for(t['Text'])
    return selected, excluded


@_boundary
def configuration_id(config):
    return hashlib.sha256(P.canonical(config).encode()).hexdigest()


@_boundary
def configurations(languages, include_calibration=False):
    return [dict(u, configuration_id=configuration_id(u)) for language in sorted(languages)
            for u in M.universes(language, include_calibration=include_calibration)]


@_boundary
def main_backend(language, config):
    if language in {'CMN', 'YUE'}:
        # The corpus-side driver supplies these tonal adapters to Stage 4;
        # pipeline.main_g2p itself has no Chinese route.
        tones = E._load('stage3_tones', ROOT / 'src/stage3/tones.py').Tones(language)
        desc = tones.descriptor()
        return P.G2P(desc['tool'], desc['version'], language, desc,
            lambda word: {'pronunciation': list(tones.transcribe(word)),
                          'source': desc['tool'], 'languages': []})
    return P.main_g2p(language, reader=config['counter_options'].get('reader', 'fugashi'),
                     tool=config['counter_options'].get('tool', 'tltk'))


@_boundary
def count_texts(texts, configs, cache_dir, *, backends=None):
    """Count every selected text/configuration using Stage 4's exact line path.

    Boundary settings from the registry preserve counts; validate and retain
    them, while counter_options control the counter. Missing full syllable cuts
    do not invalidate P; every other pipeline problem invalidates the text.
    No partial count is ever supplied to the lens or matched rates.
    """
    records = []
    for config in configs:
        cfg = {k: config[k] for k in ('language', 'option', 'counter_options', 'settings')}
        language, option = cfg['language'], cfg['option']
        if cfg not in M.universes(language, include_calibration=True):
            raise ValueError('Configuration must be declared by multiverse.universes')
        cid = configuration_id(cfg)
        if config.get('configuration_id', cid) != cid:
            raise ValueError('Configuration ID mismatch')
        backend = (backends or {}).get(language)
        try:
            backend = backend or main_backend(language, cfg)
            cache = P.PronunciationCache(cache_dir, language, backend, producer=cfg)
            descriptor = backend.descriptor()
        except (ValueError, RuntimeError, LookupError, OSError, ImportError) as error:
            for t in texts:
                if t['Language'] == language:
                    records.append(dict(Language=language, Text=t['Text'], configuration_id=cid,
                        configuration=cfg, status='failed', P=None, problems=[{'reason': 'reader-unavailable',
                        'kind': type(error).__name__}],
                        **({'provenance': {'expansion': t['expansion_provenance']}}
                           if 'expansion_provenance' in t else {})))
            continue
        for t in texts:
            if t['Language'] != language:
                continue
            problems, total = [], 0
            normalizations, repairs = {}, {}
            # Match physical LF/CR lines; other separators remain for counters.
            lines = t['text'].replace('\r\n', '\n').replace('\r', '\n').split('\n')
            for i, line in enumerate(lines):
                try:
                    result = P.segment_line(line, language, option, cache,
                        counter_options=cfg['counter_options'], segment_mode='require', ownership='counter',
                        segmenter=None, segmenter_version=None, counter=P.C.COUNTERS[language][option])
                    # Every firing of a normalisation or named G2P repair is kept in provenance.
                    for tally, fired in ((normalizations, result.get('normalizations', {})),
                                         (repairs, P.g2p_repairs([result]))):
                        for name, n in fired.items():
                            tally[name] = tally.get(name, 0) + n
                    errors = [p for p in result['problems'] if p['reason'] != 'full-segmentation-unfixed']
                    if result['counter_count'] is None or errors:
                        problems.extend({'line': i, 'reason': p['reason']} for p in errors)
                        if not errors:
                            problems.append({'line': i, 'reason': 'incomplete-count'})
                    else:
                        total += result['counter_count']
                except (ValueError, RuntimeError, LookupError, OSError, ImportError) as error:
                    problems.append({'line': i, 'reason': 'pipeline-failed', 'kind': type(error).__name__})
            if not problems and total <= 0:
                problems.append({'reason': 'nonpositive-count'})
            records.append(dict(Language=language, Text=t['Text'], configuration_id=cid, configuration=cfg,
                status='failed' if problems else 'complete', P=None if problems else total, problems=problems,
                provenance={'pipeline': P.version(), 'g2p': descriptor,
                            'text_sha256': hashlib.sha256(t['text'].encode()).hexdigest(),
                            **({'normalizations': dict(sorted(normalizations.items()))} if normalizations else {}),
                            **({'g2p_repairs': repairs} if repairs else {}),
                            **({'expansion': t['expansion_provenance']}
                               if 'expansion_provenance' in t else {})}))
    return records


@_boundary
def mean(rows, key):
    languages, values = A.language_means([r['Language'] for r in rows],
                                        [r['Speaker'] for r in rows], [r[key] for r in rows])
    return dict(zip(languages.tolist(), values.tolist()))


@_boundary
def validate_selected_counts(readings, counts, selected_texts, configs):
    """Require declared configurations and a subset, including failed counts."""
    selected = set(selected_texts)
    available = {(r['Language'],r['Text']) for r in readings}
    if not selected or not selected.issubset(available):
        raise ValueError('Invalid selected text set or missing reading')
    declared = {}
    for config in configs:
        cfg = {k: config[k] for k in ('language', 'option', 'counter_options', 'settings')}
        cid = configuration_id(cfg)
        if config.get('configuration_id', cid) != cid:
            raise ValueError('Declared configuration ID mismatch')
        if cid in declared:
            raise ValueError('Duplicate declared configuration')
        declared[cid] = cfg
    if not declared or {c['language'] for c in declared.values()} != {l for l,_ in selected}:
        raise ValueError('Declared configurations must cover the selected languages')
    groups, seen = {}, set()
    for c in counts:
        key = (c['Language'],c['Text']); cid = c['configuration_id']
        if key not in selected:
            raise ValueError('Count outside selected text set; options must cover identical selected texts')
        if (cid,key) in seen:
            raise ValueError('Duplicate count')
        seen.add((cid,key))
        cfg = c['configuration']
        if cfg['language'] != c['Language'] or configuration_id(cfg) != cid:
            raise ValueError('Count configuration mismatch')
        if cid not in declared or cfg != declared[cid]:
            raise ValueError('Count outside declared configurations')
        groups.setdefault(cid, set()).add(key)
    if set(groups) != set(declared):
        raise ValueError('Missing declared configuration count records')
    if not groups or {c['Language'] for c in counts} != {l for l,_ in selected}:
        raise ValueError('Missing selected text counts for a language')
    for keys in groups.values():
        language = next(iter(keys))[0]
        if keys != {key for key in selected if key[0]==language}:
            raise ValueError('Missing selected text count records; options must cover identical selected texts')
    return selected


@_boundary
def matched_rates(readings, counts, densities=None, *, selected_texts, configs):
    """Assembly rate records plus per-reading/aggregate IR on matched texts.

    configs is the complete declared configuration list, never inferred from counts.
    densities maps configuration IDs to {rung: bits per pipeline syllable}.
    Full canonical SR remains the assembly denominator; paper_subset_sr and
    both paper IR computations use exactly the matched subset beside P/D.
    """
    validate_selected_counts(readings, counts, selected_texts, configs)
    full = [dict(r, sr=r['NS']/r['Duration']) for r in readings]
    canonical = mean(full, 'sr')
    groups = {}
    for c in counts:
        groups.setdefault(c['configuration_id'], []).append(c)
    output = []
    for cid, group in groups.items():
        language = group[0]['Language']
        record = dict(configuration_id=cid, configuration=group[0]['configuration'], Language=language,
                      status='failed', rates={'mean_sr': canonical[language]}, readings=[], language_ir={},
                      ir_status='unavailable', ir_reason='incomplete-text-counts')
        if any(c['status'] != 'complete' for c in group):
            record['reason'] = 'incomplete-text-counts'
            output.append(record)
            continue
        selected = {c['Text']: c['P'] for c in group}
        rows = [dict(r, P=selected[r['Text']], matched_sr=selected[r['Text']]/r['Duration'],
                     paper_subset_sr=r['NS']/r['Duration'], paper_original_ir=r['ID']*r['NS']/r['Duration'])
                for r in readings if r['Language'] == language and r['Text'] in selected]
        if not rows:
            raise ValueError('Matched subset has no readings')
        ids = (densities or {}).get(cid, {})
        if any(not math.isfinite(float(v)) or float(v) <= 0 for v in ids.values()):
            raise ValueError('Information density must be positive and finite')
        record.update(ir_status='complete' if ids else 'unavailable',
                      ir_reason=None if ids else 'corpus-density-not-supplied')
        for r in rows:
            r['IR'] = {k: float(v)*r['matched_sr'] for k, v in ids.items()}
            r['paper_IR'] = {k: float(v)*r['paper_subset_sr'] for k, v in ids.items()}
        record['status'] = 'complete'
        record['rates'].update({k: mean(rows, k)[language]
                               for k in ('matched_sr', 'paper_subset_sr', 'paper_original_ir')})
        record['language_ir'] = {k: dict(matched=float(v)*record['rates']['matched_sr'],
            paper=float(v)*record['rates']['paper_subset_sr']) for k, v in ids.items()}
        record['readings'] = rows
        # Full canonical support plus explicit subset fields for named intervals.
        record['interval_readings'] = [dict(language=r['Language'],speaker=r['Speaker'],text=r['Text'],
            sr=r['NS']/r['Duration'], **(dict(matched_sr=selected[r['Text']]/r['Duration'],
            paper_subset_sr=r['NS']/r['Duration']) if r['Text'] in selected else {}))
            for r in readings if r['Language']==language]
        record['selected_texts'] = sorted(selected)
        output.append(record)
    return output
