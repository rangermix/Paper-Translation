"""Conservative script diagnostics, never a language gate or text replacement.

Hangul and kana are distinctive enough to identify accidental language mixing.
Latin names, Han characters shared by several languages, and scientific Greek
are intentionally outside this check. Source literals and selected glossary
terms may legitimately retain a script different from the target language.
"""
from collections import Counter
import unicodedata


def _tokens(text):
    tokens = {'Hangul': [], 'Kana': []}
    active, word = None, ''
    for char in unicodedata.normalize('NFC', text) + '\0':
        name = unicodedata.name(char, '')
        script = ('Hangul' if name.startswith('HANGUL ') else
                  'Kana' if name.startswith(('HIRAGANA ', 'KATAKANA ', 'KATAKANA-HIRAGANA ',
                                             'HALFWIDTH KATAKANA ')) else None)
        if script != active:
            if active:
                tokens[active].append(word)
            active, word = script, ''
        if active:
            word += char
    return tokens


def unexpected_scripts(source, target, target_locale, *, allowed_literals=()):
    parts = target_locale.split('-')
    explicit_script = None
    for part in parts[1:]:
        if len(part) == 1:
            break
        if len(part) == 4 and part.isalpha():
            explicit_script = part.title()
            break
    if explicit_script:
        expected = {'Hangul'} if explicit_script in {'Hang', 'Kore'} else (
            {'Kana'} if explicit_script in {'Hira', 'Kana', 'Jpan'} else set())
    else:
        expected = {'Hangul'} if parts[0] == 'ko' else {'Kana'} if parts[0] == 'ja' else set()
    allowed = _tokens(source)
    for literal in allowed_literals:
        for script, words in _tokens(literal).items():
            allowed[script].extend(words)
    findings = []
    for script, words in _tokens(target).items():
        if script in expected:
            continue
        known = set(allowed[script])
        introduced = Counter(word for word in words if word not in known)
        if introduced:
            findings.append({'script': script, 'unexpected': [
                {'text': word, 'count': count} for word, count in introduced.items()]})
    return findings
