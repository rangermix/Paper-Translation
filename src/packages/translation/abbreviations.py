"""Preserve source-defined abbreviation spellings without rewriting source IR."""
import re


DEFINITION = re.compile(r'([A-Za-z][A-Za-z\s-]{3,120})\s*\(([A-Z][A-Za-z0-9-]{1,12})\)')
INSTRUCTIONS = ('Follow the source usage of abbreviations exactly: preserve their spelling, case, '
    'and singular/plural form. Translate a full expression only where the source writes it out; '
    'keep its parenthesized abbreviation unchanged. Never expand an abbreviation-only occurrence '
    'or add a definition from context or terminology suggestions.')


def expansion(match):
    """Accept an exact initialism, including a printed lowercase plural s."""
    acronym = match[2]
    initials = acronym[:-1] if acronym.endswith('s') and acronym[:-1].isupper() else acronym
    words = list(re.finditer(r'[A-Za-z]+', match[1]))
    for width in range(2, min(len(words), 12) + 1):
        suffix = words[-width:]
        letters = ''.join(word[0][0] for word in suffix if word[0].casefold() not in {'of', 'the', 'and'})
        if letters.casefold() == initials.casefold():
            return match[1][suffix[0].start():suffix[-1].end()]
    return None


def source_literals(blocks):
    """A source definition supports its exact acronym and observed plural forms.

    Arbitrary capitalized prose, unknown parentheses and substrings of longer
    identifiers are not enough evidence for retaining a word untranslated.
    """
    forms = set()
    for block in blocks:
        for match in DEFINITION.finditer(block['normalized_text']):
            if expansion(match):
                acronym = match[2]
                forms.add(acronym)
                if acronym.endswith('s') and acronym[:-1].isupper():
                    forms.add(acronym[:-1])
                elif acronym.isupper():
                    forms.add(acronym + 's')
    return sorted(forms, key=lambda value: (-len(value), value))
