"""Pinned offline tonal adapters; original Han script, one label per character."""

# Retain the executed module code and source snapshot for the offline freeze lock.
# Validation checks the snapshot by compiling it against this actual code object,
# so cached bytecode or a module loaded before a disk edit cannot claim new code.
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import importlib
from importlib.metadata import version
import re

VERSIONS = {'CMN': ('pypinyin', '0.55.0'), 'YUE': ('pycantonese', '5.0.0')}


class Tones:
    def __init__(self, language):
        self.language = language
        package, expected = VERSIONS[language]
        if version(package) != expected:
            raise ValueError('Tonal tool version differs from the frozen adapter')
        self.tool = importlib.import_module(package)

    def transcribe(self, word):
        if self.language == 'CMN':
            def unknown(_):
                raise ValueError('No Mandarin tonal reading for a character')
            labels = self.tool.pinyin(word, style=self.tool.Style.TONE3, heteronym=False,
                                      errors=unknown, strict=True, v_to_u=False,
                                      neutral_tone_with_five=True)
            if any(len(readings) != 1 for readings in labels):
                raise ValueError('Ambiguous Mandarin tonal alignment')
            labels = tuple(readings[0] for readings in labels)
        else:
            words = self.tool.characters_to_jyutping(word)
            if ''.join(chars for chars, _ in words) != word or any(jp is None for _, jp in words):
                raise ValueError('Missing Cantonese tonal reading or character alignment')
            labels = []
            for chars, jp in words:
                syllables = jp.split()
                if len(syllables) != len(chars):
                    raise ValueError('Cantonese syllables do not align to characters')
                labels.extend(syllables)
            labels = tuple(labels)
        tones = '[1-5]' if self.language == 'CMN' else '[1-6]'
        if len(labels) != len(word) or any(not re.fullmatch(r'[^\W\d_]+' + tones, s) for s in labels):
            raise ValueError('Expected one explicitly toned label per Han character')
        return labels

    def join(self, result, word_index, labels):
        """Join only counter-suppressed erhua, retaining the host character's tone."""
        word = result.tokens[word_index].word
        units = [unit for unit, host in zip(result.segmentation, result.hosts) if host == word_index]
        if ''.join(units) != word or len(labels) != len(word):
            raise ValueError('Tonal labels do not align to the counted characters')
        out, cursor = [], 0
        for unit in units:
            label = labels[cursor]
            if len(unit) > 1:
                if self.language != 'CMN' or len(unit) != 2 or unit[1] not in '儿兒':
                    raise ValueError('Unsupported multi-character tonal unit')
                label = label[:-1].rstrip('r') + 'r' + label[-1]
            out.append(label); cursor += len(unit)
        return tuple(out)

    def descriptor(self):
        package, expected = VERSIONS[self.language]
        return {'tool': package, 'version': expected, 'script': 'original; no conversion',
                'settings': ({'style': 'TONE3', 'heteronym': False, 'strict': True,
                              'v_to_u': False, 'neutral_tone_with_five': True,
                              'polyphony': 'default phrase dictionary then first character reading',
                              'erhua': 'counter-aligned r suffix; host tone retained'} if self.language == 'CMN' else
                             {'segmentation': 'default',
                              'polyphony': 'rime-cantonese mapping overrides HKCanCor most-frequent reading; word first then character'}),
                'unknown_reading': 'reject; no untoned or character fallback'}
