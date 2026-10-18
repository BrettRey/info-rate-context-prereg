"""Frozen subtitle mojibake rule (Brett, 2026-10-11; DECISIONS.md, "Mojibake rule amended").

The detector is the one used in the 2026-10-11 scan of the subtitle corpora,
unchanged. A line is flagged when, after NFC, it contains either
  - UTF-8 read as Windows-1252 or Latin-1: Ã, Â, Ð or Ñ followed by a
    character in U+0080-U+00BF, or â€ followed by one of those, ™, œ or ";
  - Thai UTF-8 read as Windows-874: three or more consecutive pairs เธ or เน,
    each followed by one character.
It is applied to every extracted nonempty subtitle line before Stage 2's own
cleaning and filters. The denominator is all those nonempty lines, each
flagged line counted once. A file is dropped whole when its flagged lines are
10% or more of that denominator; otherwise the flagged lines are dropped and
the remaining lines go through the other filters. Lines are never repaired.
"""
import re
import unicodedata

LATIN = re.compile(r'[ÃÂ][\u0080-¿]|â€[\u0080-¿™œ"]|Ð[\u0080-¿]|Ñ[\u0080-¿]')
THAI = re.compile(r'(?:เ[ธน].){3,}')
RULE = ('mojibake-v2 (scan detector of 2026-10-11): NFC; flag a line matching '
        + LATIN.pattern + ' or ' + THAI.pattern + '; denominator all nonempty extracted lines; '
        'drop the file when 10*flagged >= nonempty and flagged > 0, else drop the flagged lines')


def text(line):
    return unicodedata.normalize('NFC', line)


def flagged(line):
    """True if the NFC form of one extracted line matches the frozen detector."""
    value = text(line)
    return bool(LATIN.search(value) or THAI.search(value))


def document(lines):
    """Apply the rule to one file's extracted lines; indices are positions in `lines`."""
    lines = tuple(lines)
    if any(not isinstance(line, str) for line in lines):
        raise ValueError('Mojibake filter takes extracted text lines')
    nonempty = [i for i, line in enumerate(lines) if text(line).strip()]
    bad = [i for i in nonempty if flagged(lines[i])]
    dropped = bool(bad) and 10 * len(bad) >= len(nonempty)
    return {'rule': RULE, 'flagged': len(bad), 'nonempty': len(nonempty),
            'file_dropped': dropped, 'flagged_lines': bad}
