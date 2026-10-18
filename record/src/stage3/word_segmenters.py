"""Pinned, offline word boundaries over fixed counter units; no syllable refit.

Resources are checked and hashed before initialization. Jieba-derived adapters
build their private prefix tables in memory (no global dictionary or disk cache).
All package calls run with networking disabled, including lazy initialization.
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
import importlib
import importlib.metadata as metadata
import hashlib
from contextlib import contextmanager
from pathlib import Path
import socket
from unittest.mock import patch

VERSIONS = {'jieba': '0.42.1', 'pkuseg': '0.0.25', 'pycantonese': '5.0.0',
            'cantoseg': '0.0.1', 'underthesea': '9.5.0', 'pyvi': '0.1.1'}
FORKS = {'CMN': ('jieba', 'pkuseg'), 'YUE': ('pycantonese', 'cantoseg'),
         'VIE': ('underthesea', 'pyvi')}
ALIGNMENT_FAILURE = 'Word segmentation does not align with fixed syllable units'


@contextmanager
def offline():
    def refuse(*args, **kwargs):
        raise RuntimeError('Word segmenter downloads/network disabled')
    with patch.object(socket, 'create_connection', refuse), patch.object(socket.socket, 'connect', refuse), \
            patch.object(socket.socket, 'connect_ex', refuse):
        yield


def resource_manifest(package, files):
    distribution = metadata.distribution(package)
    actual = distribution.version
    if actual != VERSIONS[package]:
        raise RuntimeError(f'Pinned {package} version required: {VERSIONS[package]}, installed {actual}')
    out = {}
    for name in files:
        path = Path(distribution.locate_file(name))
        if not path.is_file():
            raise FileNotFoundError(f'{package} resource missing; downloads disabled: {name}')
        h = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                h.update(block)
        out[name] = {'sha256': h.hexdigest(), 'bytes': path.stat().st_size}
    return {'package': package, 'version': actual, 'resources': out}


def _jieba_resources(pos=False):
    files = ['jieba/finalseg/prob_' + x + '.py' for x in ('start', 'trans', 'emit')]
    if pos:
        files += ['jieba/posseg/' + x + '.py' for x in
                  ('prob_start', 'prob_trans', 'prob_emit', 'char_state_tab')]
    return files


# The data files each segmenter reads, hashed at use and in the freeze's environment.
RESOURCES = {
    'jieba': ['jieba/dict.txt', *_jieba_resources()],
    'pkuseg': ['pkuseg/models/default/features.pkl', 'pkuseg/models/default/weights.npz',
               'pkuseg/dicts/default.pkl'],
    'pycantonese': ['pycantonese/word_segmentation/segmenter.fb.zst',
                   'pycantonese/data/rime_cantonese/chars_to_jyutping.json',
                   'pycantonese/data/rime_cantonese/phrase_fragments.json'],
    'cantoseg': ['cantoseg/merged_dict.txt'],
    'underthesea': ['underthesea/pipeline/text_normalize/tn_rules_2023_07_14.bin',
                   *['underthesea/pipeline/word_tokenize/models/ws_crf_vlsp2013_20230727/' + f
                     for f in ('models.bin', 'features.bin', 'dictionary.bin')],
                   # Also read when the tokenizer loads (R8: every data file opened is hashed).
                   'underthesea/corpus/data/Viet74K.txt', 'underthesea/models.yaml'],
    'pyvi': ['pyvi/models/words.txt', 'pyvi/models/pyvi3.pkl'],
}
# cantoseg's jieba.posseg import also reads jieba's own dictionary (R8).
DEPENDENCIES = {'cantoseg': ('jieba', ['jieba/dict.txt', *_jieba_resources(True)])}


class Segmenter:
    def __init__(self, language, name):
        if name not in FORKS.get(language, ()):
            raise ValueError('Unknown word segmenter for language')
        self.language, self.name = language, name
        files = RESOURCES[name]
        self.provenance = resource_manifest(name, files)
        if name in DEPENDENCIES:
            self.provenance['dependency'] = resource_manifest(*DEPENDENCIES[name])
        self.provenance['settings'] = {'offline': True, 'word_boundaries_only': True}
        with offline():
            if name in {'jieba', 'cantoseg'}:
                jieba = importlib.import_module('jieba')
                dictionary = Path(metadata.distribution(name).locate_file(files[0]))
                tokenizer = jieba.Tokenizer(str(dictionary))
                # Bypass initialize's uncontrolled, unhashed prefix cache.
                tokenizer.FREQ, tokenizer.total = tokenizer.gen_pfdict(dictionary.open('rb'))
                tokenizer.initialized = True
                if name == 'cantoseg':
                    pos = importlib.import_module('jieba.posseg').POSTokenizer(tokenizer)
                    self.cut = lambda text: [p.word for p in pos.cut(text, HMM=True)]
                else:
                    self.cut = lambda text: list(tokenizer.cut(text, HMM=True))
                self.provenance['settings'].update(HMM=True, cut_all=False, prefix_cache='disabled')
            elif name == 'pkuseg':
                tool = importlib.import_module(name).pkuseg(model_name='default', user_dict='default', postag=False)
                self.cut = tool.cut
                self.provenance['settings'].update(model_name='default', user_dict='default', postag=False)
            elif name == 'pycantonese':
                self.cut = importlib.import_module(name).segment
            elif name == 'underthesea':
                tool = importlib.import_module(name)
                self.cut = lambda text: tool.word_tokenize(text, use_token_normalize=False)
                self.provenance['settings']['use_token_normalize'] = False
            else:
                tool = importlib.import_module('pyvi.ViTokenizer')
                self.cut = lambda text: [w.replace('_', ' ') for w in tool.tokenize(text).split()]
            # Force lazy model loads while offline, before provenance is published.
            self.cut({'CMN': '木林', 'YUE': '木林', 'VIE': 'mùa nắng'}[language])

    def descriptor(self):
        return self.provenance

    def words(self, text):
        with offline():
            result = tuple(self.cut(text))
        if any(not isinstance(w, str) or not w for w in result):
            raise ValueError(ALIGNMENT_FAILURE)
        return result


def align(result, language, adapter, core):
    """Return selected words and one owner per ORIGINAL counted syllable.

    Han source chunks keep mandatory separators. Vietnamese whitespace units
    may merge, but phrase punctuation remains a boundary. Cuts inside a written
    syllable or joined erhua unit fail rather than changing the syllable stream.
    """
    words, owners = [], []
    if language in {'CMN', 'YUE'}:
        for old, token in enumerate(result.tokens):
            units = [s for s, host in zip(result.segmentation, result.hosts) if host == old]
            pieces = adapter.words(token.word)
            if ''.join(pieces) != token.word or ''.join(units) != token.word:
                raise ValueError(ALIGNMENT_FAILURE)
            cursor = 0
            for j, piece in enumerate(pieces):
                accumulated = ''
                index = len(words)
                while cursor < len(units) and len(accumulated) < len(piece):
                    accumulated += units[cursor]; owners.append(index); cursor += 1
                if accumulated != piece:
                    raise ValueError(ALIGNMENT_FAILURE)
                words.append(core.Token(piece, j == len(pieces)-1 and token.phrase_end))
    else:
        chunks, chunk = [], []
        for token in result.tokens:
            chunk.append(token)
            if token.phrase_end:
                chunks.append(chunk); chunk = []
        if chunk:
            chunks.append(chunk)
        for tokens in chunks:
            source = [t.word for t in tokens]
            pieces = adapter.words(' '.join(source))
            cursor = 0
            for j, piece in enumerate(pieces):
                parts = piece.split()
                if not parts or source[cursor:cursor+len(parts)] != parts:
                    raise ValueError(ALIGNMENT_FAILURE)
                words.append(core.Token(piece, j == len(pieces)-1 and tokens[-1].phrase_end))
                owners.extend([len(words)-1] * len(parts)); cursor += len(parts)
            if cursor != len(source):
                raise ValueError(ALIGNMENT_FAILURE)
    if len(owners) != result.count:
        raise ValueError(ALIGNMENT_FAILURE)
    return tuple(words), tuple(owners)
