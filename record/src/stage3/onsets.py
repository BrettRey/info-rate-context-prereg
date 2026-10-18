"""Freeze onset counts from explicitly supplied word/G2P records; never store words.

CLI records are JSONL objects: word, pronunciation (or counter_result), tokens.
Use --provenance to identify the source and G2P tool/version/voice/settings.
No corpus discovery, G2P downloads, or training is performed here.
"""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unicodedata


def load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


C = load("stage3_segmentation_counters", Path(__file__).with_name("counters.py"))
SCHEMA = "onsets-v2"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def provenance():
    return {"counter_sha256": hashlib.sha256(Path(C.__file__).read_bytes()).hexdigest(),
            "onsets_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "resources": C.LEXICON_PROVENANCE, "unicode": unicodedata.unidata_version}


def validate_option(language, option):
    if language not in C.COUNTERS or option not in C.COUNTERS[language]:
        raise ValueError("Unknown language/option")


def tied_units(texts, start, stop):
    """Consonant ties are indivisible when matching an onset suffix."""
    units, begins, i = [], [], start
    while i < stop:
        begins.append(i)
        unit = texts[i]
        while any(t in texts[i] for t in "͜͡"):
            i += 1
            if i >= stop:
                raise ValueError("Boundary splits a tied phone")
            unit += texts[i]
        units.append(unit)
        i += 1
    return tuple(units), tuple(begins)


def spelling_trace(result):
    """Use FIN's counted vowel groups, including calibration-only mergers."""
    texts, words, groups = [], [], []
    for w, token in enumerate(result.tokens):
        spelling = unicodedata.normalize("NFC", token.word.lower())
        start = len(texts)
        texts.extend(spelling); words.extend([w] * len(spelling))
        cursor = 0
        for nucleus, host in zip(result.nuclei, result.hosts):
            if host != w:
                continue
            indices = []
            for vowel in nucleus:
                pos = spelling.find(vowel, cursor)
                if pos < 0:
                    raise ValueError("Cannot align Finnish counted nuclei to spelling")
                indices.append(start + pos); cursor = pos + 1
            groups.append(tuple(indices))
    return tuple(texts), tuple(words), tuple(groups)


def effective_trace(result, language):
    if language == "FIN":
        return spelling_trace(result)
    if not result.group_indices and result.count:
        raise ValueError("Counter result has no effective phone trace; rerun the updated counter")
    if not (len(result.phone_texts) == len(result.phone_words) == len(result.phone_stress)):
        raise ValueError("Invalid counter phone trace")
    if len(result.group_indices) != result.count or any(
            not g or any(type(i) is not int or not 0 <= i < len(result.phone_texts) for i in g)
            or list(g) != sorted(set(g)) for g in result.group_indices):
        raise ValueError("Invalid counter nucleus trace")
    return result.phone_texts, result.phone_words, result.group_indices


@dataclass(frozen=True)
class Inventory:
    language: str
    option: str
    floor: int
    rows: tuple
    metadata: dict

    @property
    def legal(self):
        return frozenset(onset for onset, types, tokens in self.rows if types >= self.floor)

    def descriptor(self):
        return {"language": self.language, "option": self.option, "floor": self.floor,
                "sha256": hashlib.sha256(canonical([self.metadata, self.rows]).encode()).hexdigest(),
                "legal_sequences": len(self.legal),
                "floor_counts": {str(f): sum(types >= f for _, types, _ in self.rows) for f in (1, 3, 10)}}


def collect(records, language, option, *, floor=3, counter_options=None, source=None):
    """A type is an NFC, lowercased spelling; repeat records add token frequency.

    Records can be triples (word, pronunciation or Count, tokens), or JSON objects.
    Count records must describe exactly that one word. Contextual phrase records
    are rejected: they do not define isolated initial onsets.
    """
    validate_option(language, option)
    if language in {"CMN", "YUE", "VIE", "KOR"}:
        raise ValueError("Block/character/written-syllable languages do not use onset inventories")
    if not isinstance(floor, int) or isinstance(floor, bool) or floor < 1:
        raise ValueError("Onset floor must be a positive integer")
    kwargs = dict(counter_options or {})
    configuration = C.counter_configuration(language, option, kwargs)
    seen, counts, no_nucleus = {}, defaultdict(lambda: [set(), 0]), set()
    for record in records:
        if isinstance(record, dict):
            word = record["word"]
            pron = record.get("counter_result", record.get("pronunciation"))
            tokens = record["tokens"]
        else:
            word, pron, tokens = record
        if not isinstance(word, str) or not word:
            raise ValueError("A record must contain one nonempty word")
        key = unicodedata.normalize("NFC", word).lower()
        parsed = C.tokenize(word)
        if len(parsed) != 1 or parsed[0].word != unicodedata.normalize("NFC", word):
            raise ValueError("Onset records must be isolated words without separators")
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 1:
            raise ValueError("Token counts must be positive integers")
        if isinstance(pron, dict):
            fields = {k: pron[k] for k in C.Count.__dataclass_fields__ if k in pron}
            fields["tokens"] = tuple(C.Token(**t) for t in fields["tokens"])
            result = C.Count(**fields)
        elif hasattr(pron, "group_indices"):
            result = pron
        else:
            if pron is None:
                raise ValueError("A pronunciation or counter result is required")
            result = C.COUNTERS[language][option](word, pronunciations={word: pron}, **kwargs)
        if len(result.tokens) != 1 or result.tokens[0].word != unicodedata.normalize("NFC", word):
            raise ValueError("Counter result must describe exactly the record's word")
        if result.chained_ties != configuration['counter_settings']['chained_ties']:
            raise ValueError("Counter result uses different chained-tie settings")
        if {'counter_settings': result.counter_settings, 'counter_options': result.counter_options} != configuration:
            raise ValueError("Counter result uses different counter settings/configuration")
        texts, owners, groups = effective_trace(result, language)
        onset = tied_units(texts, 0, groups[0][0])[0] if groups else None
        if key in seen and seen[key] != onset:
            raise ValueError("A word type has conflicting initial onsets")
        seen[key] = onset
        if onset is None:
            no_nucleus.add(key)
        else:
            counts[onset][0].add(key); counts[onset][1] += tokens
    rows = tuple((onset, len(types), tokens) for onset, (types, tokens) in sorted(counts.items()))
    metadata = {"schema": SCHEMA, "language": language, "option": option, "floor": floor,
                "type_normalization": "NFC-lowercase",
                "counter_options": {key: value for key, value in kwargs.items()
                                    if value is None or isinstance(value, (str, int, float, bool))},
                "counter_options_sha256": hashlib.sha256(canonical(C._configuration_value(kwargs)).encode()).hexdigest(),
                "counter_configuration": configuration,
                "source": source or {"kind": "caller-supplied-records"}, **provenance(),
                "rows_sha256": hashlib.sha256(canonical(rows).encode()).hexdigest(),
                "types_without_nucleus": len(no_nucleus)}
    return Inventory(language, option, floor, rows, metadata)


def write(inventory, path):
    out = io.StringIO()
    out.write("# " + canonical(inventory.metadata) + "\n")
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow(["onset", "word_types", "word_tokens", "legal_selected", "legal_1", "legal_3", "legal_10"])
    for onset, types, tokens in inventory.rows:
        writer.writerow([canonical(onset), types, tokens, int(types >= inventory.floor),
                         *(int(types >= f) for f in (1, 3, 10))])
    data = out.getvalue().encode("utf-8")
    if len(data) > 100 * 1024 ** 2:
        raise ValueError("Onset output exceeds the small-scale write limit")
    path = Path(path)
    # Frozen means never replace a conflicting inventory accidentally.
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Refusing to overwrite a different frozen onset inventory")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".onsets-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.link(temporary, path)  # Atomic publication, refusing replacement.
    finally:
        Path(temporary).unlink(missing_ok=True)


def read(path):
    with Path(path).open(encoding="utf-8") as f:
        first = f.readline()
        if not first.startswith("# "):
            raise ValueError("Missing onset provenance")
        meta = json.loads(first[2:])
        if meta.get("schema") != SCHEMA:
            raise ValueError("Unsupported onset inventory schema")
        if set(meta.get('counter_configuration', {})) != {'counter_settings', 'counter_options'}:
            raise ValueError("Missing onset counter configuration")
        validate_option(meta["language"], meta["option"])
        floor = meta["floor"]
        if type(floor) is not int or floor < 1:
            raise ValueError("Invalid onset floor")
        rows, seen = [], set()
        for row in csv.DictReader(f, delimiter="\t"):
            raw = json.loads(row["onset"])
            if not isinstance(raw, list) or any(not isinstance(p, str) or not p for p in raw):
                raise ValueError("Invalid onset sequence")
            onset = tuple(raw); types, tokens = int(row["word_types"]), int(row["word_tokens"])
            if onset in seen or types < 1 or tokens < types:
                raise ValueError("Invalid onset counts")
            for field, threshold in (("legal_selected", floor), ("legal_1", 1), ("legal_3", 3), ("legal_10", 10)):
                if int(row[field]) != int(types >= threshold):
                    raise ValueError("Inconsistent onset floor flags")
            seen.add(onset); rows.append((onset, types, tokens))
    if meta.get("rows_sha256") != hashlib.sha256(canonical(rows).encode()).hexdigest():
        raise ValueError("Onset inventory checksum mismatch")
    return Inventory(meta["language"], meta["option"], floor, tuple(rows), meta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language"); parser.add_argument("option"); parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--floor", type=int, default=3)
    parser.add_argument("--counter-options", type=json.loads, default={})
    parser.add_argument("--provenance", type=json.loads, required=True)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8") as f:
        inventory = collect((json.loads(line) for line in f if line.strip()), args.language, args.option,
                            floor=args.floor, counter_options=args.counter_options, source=args.provenance)
    write(inventory, args.output)
    print(canonical(inventory.descriptor()))


if __name__ == "__main__":
    main()
