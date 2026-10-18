"""Offline syllable comparison; output contains no text or type list.

python -I -B src/stage3/segment_entropy.py SPA A invented.txt --onsets spa-a.tsv
Add --compare-row 51 (optionally --alternative marked) for a paired diagnostic.
Comparisons are counts-only by default; --entropy explicitly adds entropy.
--counts-only never computes entropy and needs no freeze.
Entropy requires --freeze-archive ARCHIVE --freeze-proof PROOF --block-headers
HEADERS, or text read
directly from a file inside tests/. Streams cannot claim the test exemption.
The lock catches mistakes, not deliberate forgery; it trusts the lead's recorded
Bitcoin headers and performs no chain or confirmation check.
CMN/YUE use pinned offline tonal tools unless --pronunciations is supplied.
"""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import subprocess
from types import ModuleType, SimpleNamespace

import importlib.util


def _load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


S = _load("stage3_segment", Path(__file__).with_name("segment.py"))
C, O = S.C, S.O
ROOT = Path(__file__).resolve().parents[2]
F = _load('stage3_freeze', Path(__file__).with_name('freeze.py'))
G = _load('stage3_read_text_guard', Path(__file__).with_name('read_text_guard.py'))


class EntropyGuardError(ValueError):
    pass


def entropy_authorization(input_path=None, freeze_archive=None, freeze_proof=None, block_headers=None):
    """Authorize a file the caller will read directly, or a verified freeze."""
    if freeze_archive is not None or freeze_proof is not None or block_headers is not None:
        try:
            if freeze_archive is None or freeze_proof is None:
                raise ValueError('Both archive and proof are required')
            # Load every listed file before checking retained source (the
            # production closure, P7). This performs no transcription, model
            # fit or entropy calculation, but imports the neural code too.
            F.load_closure()
            # Import-by-spec callers need not register the driver in
            # sys.modules: bind this function's own executing module, with the
            # modules it holds, so the check reaches its dependencies.
            driver = SimpleNamespace(
                __file__=__file__, __freeze_module_code__=__freeze_module_code__,
                __freeze_source__=__freeze_source__,
                **{k: v for k, v in globals().items() if isinstance(v, ModuleType)})
            loaded = {'src/stage3/segment_entropy.py': (driver,)}
            return F.validate_freeze(freeze_archive, freeze_proof, block_headers=block_headers, loaded_modules=loaded)
        except Exception as exc:
            raise EntropyGuardError(f'Entropy requires --freeze-archive ARCHIVE --freeze-proof PROOF --block-headers HEADERS: a SHA-256 proof with a Bitcoin attestation verified against recorded headers, bound to an archive containing FREEZE.json matching the loaded source. {exc}') from exc
    if input_path is not None:
        try:
            path = Path(input_path).resolve(strict=True)
            if path.is_file() and path.is_relative_to((ROOT / 'tests').resolve()):
                return {'kind': 'invented-test-input'}
        except OSError:
            pass
    raise EntropyGuardError('Entropy is blocked until counters are frozen and timestamped. Supply --freeze-archive ARCHIVE --freeze-proof PROOF --block-headers HEADERS or read invented input directly from this worktree\'s tests/. Use counts-only comparisons without entropy.')


def entropy(counts):
    total = sum(counts.values())
    return -sum(n / total * math.log2(n / total) for n in counts.values()) if total else 0.0


class Statistics:
    """H1 uses all tokens; H2 is H(next | previous) over within-line pairs.

    No BOS/EOS, no cross-line pairs, no smoothing. An empty sample has zero
    entropy and zero events. H2's context marginal is taken from pair starts.
    """
    def __init__(self, compute_entropy=True):
        self.single, self.pairs, self.contexts = Counter(), Counter(), Counter()
        self.n_lines = self.nonempty = 0
        self.compute_entropy = compute_entropy

    def add(self, line):
        line = tuple(line); self.n_lines += 1; self.nonempty += bool(line)
        self.single.update(line)
        if self.compute_entropy:
            current = list(zip(line, line[1:]))
            self.pairs.update(current); self.contexts.update(a for a, b in current)

    def report(self):
        counts = {'lines': self.n_lines, 'nonempty_lines': self.nonempty,
                  'syllables': sum(self.single.values()), 'syllable_types': len(self.single)}
        if not self.compute_entropy:
            return counts
        total = sum(self.pairs.values())
        h2 = -sum(n / total * math.log2(n / self.contexts[a]) for (a, b), n in self.pairs.items()) if total else 0.0
        return {**counts, "bigram_events": total, "bigram_types": len(self.pairs),
                "unigram_entropy_bits": entropy(self.single), "bigram_entropy_bits": h2,
                "bigram_joint_entropy_bits": entropy(self.pairs)}


def metrics(lines):
    stats = Statistics()
    for line in lines:
        stats.add(line)
    return stats.report()


class Transcriber:
    """One transcription per unit; Japanese units retain reader context."""
    def __init__(self, language, backend=None, supplied=None, counter_options=None):
        self.language, self.backend, self.supplied = language, backend, supplied
        self.counter_options = dict(counter_options or {})
        self.memory = {}; self.transcriptions = 0
        self.sources = {}; self.word_sources = {}
        self.tones = None

    def get(self, word):
        if self.supplied is not None:
            return self.supplied[word]
        if self.language == "VIE":
            return word
        if word not in self.memory:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                if self.backend is None:
                    if self.language in {'CMN', 'YUE'}:
                        T = _load('stage3_tones', Path(__file__).with_name('tones.py'))
                        self.tones = self.backend = T.Tones(self.language)
                    else:
                        P = _load("stage3_entropy_pipeline", Path(__file__).resolve().parents[1] / "stage4/pipeline.py")
                        P.C = C
                        self.backend = P.main_g2p(self.language, lexicon=self.counter_options.get("lexicon"),
                                                 reader=self.counter_options.get('reader', 'fugashi'),
                                                 tool=self.counter_options.get('tool', 'tltk'),
                                                 japanese_context='word_tokens' not in self.counter_options)
                if self.tones is not None:
                    value = {'pronunciation': self.tones.transcribe(word)}
                else:
                    value = self.backend.transcribe(word)
            pronunciation = value["pronunciation"]
            if not isinstance(pronunciation, (str, list, tuple)):
                raise ValueError("Invalid G2P pronunciation")
            self.memory[word] = pronunciation
            self.sources[word] = value.get('source', 'supplied')
            self.word_sources[word] = value.get('word_sources')
            self.transcriptions += 1
        return self.memory[word]

    def descriptor(self):
        if self.supplied is not None:
            return {"tool": "supplied", "sha256": hashlib.sha256(O.canonical(self.supplied).encode()).hexdigest()}
        return self.backend.descriptor() if self.backend else {"tool": "orthography"}


def analyze(lines, language, option, inventory=None, *, settings=None, counter_options=None,
            pronunciations=None, backend=None, phrase_g2p=None, compare_row=None, alternative=None,
            counts_only=None, compute_entropy=False, input_path=None, freeze_archive=None,
            freeze_proof=None, block_headers=None, alternative_inventory=None):
    """Analyze an iterable, or pass lines=None to read input_path ourselves.

    Only the latter can receive the unstamped tests/ exemption. With a matching
    freeze, ordinary iterables/streams remain available. Comparisons compute
    entropy only on an explicit compute_entropy=True request.
    """
    if counts_only and compute_entropy:
        raise ValueError('counts_only and compute_entropy are mutually exclusive')
    counts_only = bool(counts_only or (compare_row is not None and not compute_entropy))
    path = Path(input_path).resolve(strict=True) if lines is None and input_path is not None else None
    authorization = None if counts_only else entropy_authorization(path, freeze_archive, freeze_proof, block_headers)
    kwargs = dict(settings=settings, counter_options=counter_options, pronunciations=pronunciations,
                  backend=backend, phrase_g2p=phrase_g2p, compare_row=compare_row, alternative=alternative,
                  counts_only=counts_only, authorization=authorization, alternative_inventory=alternative_inventory)
    if lines is None:
        if path is None:
            raise ValueError('lines=None requires input_path')
        with path.open(encoding='utf-8') as stream:
            result = _analyze(stream, language, option, inventory, **kwargs)
    else:
        result = _analyze(lines, language, option, inventory, **kwargs)
    F.unchanged_since(authorization)
    return result


def _analyze(lines, language, option, inventory, *, settings, counter_options, pronunciations,
             backend, phrase_g2p, compare_row, alternative, counts_only, authorization, alternative_inventory):
    O.validate_option(language, option)
    settings = dict(settings or {}); counter_options = dict(counter_options or {})
    configured = S.settings_for(language, option, settings)
    if alternative is not None and compare_row is None:
        raise ValueError("An alternative requires a comparison row")
    if alternative_inventory is not None and compare_row is None:
        raise ValueError('An alternative onset inventory requires a comparison row')
    row = None
    if compare_row is not None:
        if compare_row in S.UNDEFINED_ROWS:
            raise ValueError(S.UNDEFINED_ROWS[compare_row])
        row = S.BOUNDARY_ROWS.get(compare_row)
        if row is None or (language, option) not in row["options"]:
            raise ValueError("Boundary comparison does not apply to this language/option")
        alternative = alternative or row["values"][1]
        if alternative not in row["values"][1:]:
            raise ValueError("Unknown boundary alternative")
        defaults = S.settings_for(language, option)
        if any(value != defaults[key] for key, value in configured.items() if key != row['setting']):
            raise ValueError('One-at-a-time comparisons require all other boundary settings at default')
        counter_config = C.counter_configuration(language, option, counter_options)
        declared = C.default_counter_configuration(language, option)
        if counter_config['counter_settings'] != declared['counter_settings']:
            raise ValueError('One-at-a-time comparisons require count forks and chained ties at default')
        # Caller-supplied resource tables are simulation fixtures, not policy
        # settings. Native policy switches still must use declared defaults.
        for key, value in counter_config['counter_options'].items():
            if key not in {'lexicon', 'exceptions', 'erhua_words', 'word_tokens'} and value != declared['counter_options'][key]:
                raise ValueError('One-at-a-time comparisons require other native count settings at default')
        settings[row["setting"]] = row["values"][0]
    cache = Transcriber(language, backend, pronunciations, counter_options)
    defaults, alternatives = Statistics(not counts_only), Statistics(not counts_only)
    changed_types = changed_owners = changed_lines = changed_owner_lines = 0
    fallback_tokens = word_tokens = non_syllabic_tokens = 0
    alignment = Counter()
    source_counts = Counter()
    digest = hashlib.sha256()
    for line in lines:
        # Preserve physical line boundaries even if callers retain terminators.
        line = line.rstrip("\r\n")
        if any(c in C.LINE_END for c in line):
            raise ValueError("Supply one physical line per input element")
        digest.update(line.encode("utf-8") + b"\n")
        tokens = (C.cmn_a(line, **counter_options).tokens if language == "CMN" else C.tokenize(line))
        if language in {'JPN', 'THA'}:
            native = sys.modules['stage3_japanese' if language == 'JPN' else 'stage3_thai']
            kwargs = {'reader': counter_options.get('reader', 'fugashi')} if language == 'JPN' else {}
            if language == 'JPN':
                kwargs['word_tokens'] = counter_options.get('word_tokens')
            tokens = native.tokens(C, line, **kwargs)
        contextual = (backend is None or getattr(backend, 'settings', {}).get('pronunciation_units') == 'source chunks')
        if language == 'JPN' and pronunciations is None and contextual and 'word_tokens' not in counter_options:
            tokens, values = native.cached_pronunciations(
                C, line, counter_options.get('reader', 'fugashi'), cache.get)
        else:
            values = {t.word: cache.get(t.word) for t in tokens}
        if cache.tones is not None:
            counted = C.COUNTERS[language][option](line, **counter_options)
            values = {t.word: cache.tones.join(counted, w, values[t.word]) for w, t in enumerate(counted.tokens)}
        line_options = dict(counter_options)
        if language in {'JPN', 'THA'} and pronunciations is None:
            if language == 'JPN' and contextual and 'word_tokens' not in counter_options:
                line_options['pronunciation_sources'] = [source for chunk in C.tokenize(line)
                    for source in (cache.word_sources[chunk.word] or
                                   [cache.sources[chunk.word]] * len(cache.memory[chunk.word]))]
            elif language == 'JPN':
                line_options['pronunciation_sources'] = [cache.sources[t.word] for t in tokens]
            else:
                line_options['pronunciation_sources'] = {t.word: cache.sources[t.word] for t in tokens}
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            base = S.segment_text(line, language, option, inventory, settings=settings,
                                  counter_options=line_options, pronunciations=values,
                                  phrase_g2p=phrase_g2p)
            defaults.add(base.syllables)
            word_tokens += len(base.counter.tokens)
            fallback_tokens += sum(any(s.endswith('-fallback') for s in source.split('+'))
                                   for source in base.counter.sources)
            source_counts.update(base.counter.sources)
            non_syllabic_tokens += len((base.counter.resource_provenance or {}).get('non_syllabic_words', []))
            alignment.update((base.counter.resource_provenance or {}).get('split_unit_alignment', {}))
            if row:
                changed = S.segment_text(line, language, option,
                                         inventory if alternative_inventory is None else alternative_inventory,
                                         settings={**settings, row["setting"]: alternative},
                                         counter_options=line_options, pronunciations=values,
                                         phrase_g2p=phrase_g2p)
                if changed.count != base.count:
                    raise ValueError("Boundary comparison unexpectedly changed syllable counts")
                alternatives.add(changed.syllables)
                n_changed = sum(a != b for a, b in zip(base.syllables, changed.syllables))
                n_owners = sum(a != b for a, b in zip(base.owners, changed.owners))
                changed_types += n_changed; changed_owners += n_owners
                changed_lines += bool(n_changed); changed_owner_lines += bool(n_owners)
    inventory_descriptor = (inventory.descriptor() if isinstance(inventory, O.Inventory) else
                            {"kind": "explicit-simulation-onsets", "sha256": hashlib.sha256(O.canonical(sorted(inventory)).encode()).hexdigest()}
                            if inventory is not None else None)
    report = {"schema": "segment-entropy-v2", "language": language, "option": option,
              "fallback_share": fallback_tokens / word_tokens if word_tokens else 0.,
              "non_syllabic_word_tokens": non_syllabic_tokens,
              "split_unit_alignment": dict(alignment),
              "word_readers": dict(source_counts), "fallback_word_tokens": fallback_tokens,
              "mode": "counts-only" if counts_only else "entropy", "entropy_authorization": authorization,
              "status": "complete", "default": defaults.report(),
              "settings": S.settings_for(language, option, settings),
              "provenance": {**O.provenance(), "segment_sha256": hashlib.sha256(Path(S.__file__).read_bytes()).hexdigest(),
                             "entropy_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                             "tones_sha256": hashlib.sha256(Path(__file__).with_name('tones.py').read_bytes()).hexdigest(),
                             "input_sha256": digest.hexdigest(), "onsets": inventory_descriptor,
                             "counter_options_sha256": hashlib.sha256(O.canonical(C._configuration_value(counter_options)).encode()).hexdigest(),
                             "chained_ties": counter_options.get("chained_ties", C.DEFAULT_CHAINED_TIES),
                             "g2p": cache.descriptor(), "transcriptions": cache.transcriptions,
                             "phrase_g2p": "caller-supplied" if phrase_g2p else "g2pk2-defaults" if
                             language == "KOR" and (row and compare_row == 52 or settings.get("korean_g2p") == "whole_phrase") else None},
              "estimator": None if counts_only else {"unigram": "ML H(S)", "bigram": "ML H(next|previous), within-line pairs",
                            "boundaries": "no BOS/EOS; no pairs across lines; punctuation does not reset pairs",
                            "empty_sample": "zero bits with zero events"}}
    if row:
        alternate = alternatives.report()
        report["comparison"] = {"row": compare_row, "setting": row["setting"], "alternative": alternative,
                                "kind": row.get('kind', 'fork' if compare_row == 49 else 'one-at-a-time-check'),
                                "result": alternate,
                                "changed_syllable_positions": changed_types,
                                "changed_owner_positions": changed_owners,
                                "changed_syllable_share": changed_types / sum(defaults.single.values()) if defaults.single else 0.0,
                                "changed_owner_share": changed_owners / sum(defaults.single.values()) if defaults.single else 0.0,
                                "changed_lines": changed_lines, "changed_owner_lines": changed_owner_lines,
                                "difference": {key: alternate[key] - report["default"][key] for key in alternate}}
        if alternative_inventory is not None:
            report['comparison']['onsets'] = (alternative_inventory.descriptor() if isinstance(alternative_inventory, O.Inventory)
                                              else {'kind': 'explicit-simulation-onsets',
                                                    'sha256': hashlib.sha256(O.canonical(sorted(alternative_inventory)).encode()).hexdigest()})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language"); parser.add_argument("option"); parser.add_argument("input", type=Path)
    parser.add_argument("--onsets", type=Path)
    parser.add_argument("--alternative-onsets", type=Path,
                        help='Inventory built with an alternative counter setting, e.g. CAT row 45 attachment')
    parser.add_argument("--settings", type=json.loads, default={})
    parser.add_argument("--counter-options", type=json.loads, default={})
    parser.add_argument("--pronunciations", type=Path)
    parser.add_argument("--compare-row", type=int); parser.add_argument("--alternative")
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--counts-only", action='store_true')
    mode.add_argument("--entropy", action='store_true', help='Explicitly compute entropy in a comparison')
    parser.add_argument("--freeze-archive", type=Path)
    parser.add_argument("--freeze-proof", type=Path)
    parser.add_argument("--block-headers", type=Path, help="Lead's recorded Bitcoin headers JSON (trusted offline input)")
    args = parser.parse_args()
    try:
        authorization = None
        if not args.counts_only and (args.compare_row is None or args.entropy):
            authorization = entropy_authorization(args.input, args.freeze_archive, args.freeze_proof, args.block_headers)
        # Counts on the read texts only through the production command, after the stamp.
        G.check(args.input, authorized=bool(authorization) and authorization.get('kind') != 'invented-test-input')
        inventory = O.read(args.onsets) if args.onsets else None
        alternative_inventory = O.read(args.alternative_onsets) if args.alternative_onsets else None
        supplied = json.loads(args.pronunciations.read_text(encoding="utf-8")) if args.pronunciations else None
        report = analyze(None, args.language, args.option, inventory, settings=args.settings,
                         counter_options=args.counter_options, pronunciations=supplied,
                         compare_row=args.compare_row, alternative=args.alternative,
                         counts_only=args.counts_only, compute_entropy=args.entropy, input_path=args.input,
                         freeze_archive=args.freeze_archive, freeze_proof=args.freeze_proof,
                         block_headers=args.block_headers,
                         alternative_inventory=alternative_inventory)
    except EntropyGuardError as exc:
        print(O.canonical({'status': 'failed', 'reason': 'entropy-guard', 'message': str(exc)}), file=sys.stderr)
        return 1
    except G.ReadTextRefused as exc:
        print(O.canonical({'status': 'failed', 'reason': 'read-text-guard', 'message': str(exc)}), file=sys.stderr)
        return 1
    except (ValueError, TypeError, RuntimeError, LookupError, OSError, subprocess.SubprocessError):
        # Adapter errors can contain source words. Never echo them in a CLI run.
        print('{"status":"failed","reason":"segmentation-or-resource-error"}', file=sys.stderr)
        return 1
    output = O.canonical(report) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
