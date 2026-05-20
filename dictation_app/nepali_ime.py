"""Nepali IME — offline roman-to-Devanagari transliteration with word suggestions."""

import os
import unicodedata

CONSONANTS = {
  'k': '\u0915', 'kh': '\u0916', 'g': '\u0917', 'gh': '\u0918', 'ng': '\u0919',
  'ch': '\u091a', 'chh': '\u091b', 'j': '\u091c', 'jh': '\u091d', 'ny': '\u091e',
  'tt': '\u091f', 'tth': '\u0920', 'dd': '\u0921', 'ddh': '\u0922', 'nn': '\u0923',
  't': '\u0924', 'th': '\u0925', 'd': '\u0926', 'dh': '\u0927', 'n': '\u0928',
  'p': '\u092a', 'ph': '\u092b', 'b': '\u092c', 'bh': '\u092d', 'm': '\u092e',
  'y': '\u092f', 'r': '\u0930', 'l': '\u0932', 'v': '\u0935', 'w': '\u0935',
  'sh': '\u0936', 'shh': '\u0937', 's': '\u0938', 'h': '\u0939',
  'ksh': '\u0915\u094d\u0937', 'tr': '\u0924\u094d\u0930', 'gy': '\u091c\u094d\u091e',
}

VOWELS = {
  'a': '\u0905', 'aa': '\u0906', 'i': '\u0907', 'ee': '\u0908',
  'u': '\u0909', 'oo': '\u090a', 'e': '\u090f', 'ai': '\u0910',
  'o': '\u0913', 'au': '\u0914', 'ri': '\u090b',
}

MATRAS = {
  'a': '', 'aa': '\u093e', 'i': '\u093f', 'ee': '\u0940',
  'u': '\u0941', 'oo': '\u0942', 'e': '\u0947', 'ai': '\u0948',
  'o': '\u094b', 'au': '\u094c', 'ri': '\u0943',
}

HALANT = '\u094d'
ANUSVARA = '\u0902'
VISARGA = '\u0903'
CHANDRABINDU = '\u0901'

ENGLISH_TO_NEPALI_DIGITS = str.maketrans('0123456789', '०१२३४५६७८९')

def to_nepali_digits(text):
  return text.translate(ENGLISH_TO_NEPALI_DIGITS)

SINGLE_VOWEL_MAP = {
  'a': 'a', 'i': 'i', 'u': 'u', 'e': 'e', 'o': 'o',
}

CONSONANT_PREFIXES = sorted([k for k in CONSONANTS if len(k) > 1], key=len, reverse=True)
VOWEL_KEYS = sorted(VOWELS.keys(), key=len, reverse=True)


def _is_vowel_char(ch):
  return ch in 'aeiou'


def _split_roman(word):
  tokens = []
  i = 0
  while i < len(word):
    matched = False
    for p in CONSONANT_PREFIXES:
      if word[i:i+len(p)] == p:
        tokens.append(('c', p))
        i += len(p)
        matched = True
        break
    if matched:
      continue
    if word[i] in 'aeiou':
      for vk in VOWEL_KEYS:
        if word[i:i+len(vk)] == vk:
          tokens.append(('v', vk))
          i += len(vk)
          matched = True
          break
    if matched:
      continue
    if word[i] in 'abcdefghijklmnopqrstuvwxyz':
      tokens.append(('c', word[i]))
    else:
      tokens.append(('o', word[i]))
    i += 1
  return tokens


def roman_to_devanagari(text):
  words = text.split()
  result_words = []
  for word in words:
    result_words.append(_word_to_devanagari(word))
  return ' '.join(result_words)


def _word_to_devanagari(word):
  if not word:
    return ''
  tokens = _split_roman(word)
  output = []
  i = 0
  while i < len(tokens):
    ttype, tval = tokens[i]
    if ttype == 'v':
      output.append(VOWELS.get(tval, tval))
      i += 1
    elif ttype == 'c':
      cons = CONSONANTS.get(tval)
      if cons is None:
        output.append(tval)
        i += 1
        continue
      if i + 1 < len(tokens):
        next_type, next_val = tokens[i + 1]
        if next_type == 'c':
          output.append(cons + HALANT)
        elif next_type == 'v':
          matra = MATRAS.get(next_val)
          if matra:
            output.append(cons + matra)
          else:
            output.append(cons)
          i += 1
        else:
          output.append(cons)
      else:
        output.append(cons)
      i += 1
    else:
      output.append(tval)
      i += 1
  if output and output[-1] == '\u094d':
    output[-1] = ''
  return ''.join(output).replace('\u094d\u093e', '\u094b')


_WORD_LIST = None

def _load_word_list():
  global _WORD_LIST
  if _WORD_LIST is not None:
    return _WORD_LIST
  _WORD_LIST = []
  path = os.path.join(os.path.dirname(__file__), 'nepali_words.txt')
  try:
    with open(path, 'r', encoding='utf-8') as f:
      seen = set()
      for line in f:
        w = unicodedata.normalize('NFC', line.strip())
        if w and len(w) >= 2 and w not in seen:
          seen.add(w)
          _WORD_LIST.append(w)
  except FileNotFoundError:
    _WORD_LIST = []
  return _WORD_LIST


def _levenshtein(a, b):
  if len(a) < len(b):
    a, b = b, a
  if len(b) == 0:
    return len(a)
  prev = list(range(len(b) + 1))
  for i, ca in enumerate(a):
    curr = [i + 1]
    for j, cb in enumerate(b):
      cost = 0 if ca == cb else 1
      curr.append(min(
        curr[j] + 1,
        prev[j + 1] + 1,
        prev[j] + cost
      ))
    prev = curr
  return prev[-1]


def get_suggestions(prefix, max_suggestions=4):
  if not prefix:
    return []
  prefix = prefix.lower().strip()
  if not prefix:
    return []

  dev_input = unicodedata.normalize('NFC', roman_to_devanagari(prefix))
  if not dev_input:
    return []

  words = _load_word_list()
  if not words:
    return []

  input_len = len(dev_input)
  results = []
  seen = set()

  for word in words:
    if word.startswith(dev_input):
      if word not in seen:
        seen.add(word)
        results.append((0, len(word), word))
        if len(results) >= max_suggestions:
          break

  if len(results) < max_suggestions:
    candidates = []
    for word in words:
      if word in seen:
        continue
      wlen = len(word)
      if abs(wlen - input_len) > 3:
        continue
      if input_len >= 2 and word[0] != dev_input[0]:
        continue
      dist = _levenshtein(word, dev_input)
      if dist <= min(3, input_len):
        candidates.append((dist, word))
    candidates.sort(key=lambda x: x[0])
    for _, w in candidates:
      if w not in seen:
        seen.add(w)
        results.append((1, 0, w))
        if len(results) >= max_suggestions:
          break

  return [(w, w) for _, _, w in results[:max_suggestions]]
