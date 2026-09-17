"""Language tags and source validation; every language pair is available."""
from copy import deepcopy
import re
import json
from pathlib import Path

NATIVE_NAMES = json.loads(Path(__file__).with_name('language-names.json').read_text(encoding='utf-8'))


def language_name(value):
    if value in {'auto', 'und', None}:
        return '自动识别'
    if value in NATIVE_NAMES:
        return NATIVE_NAMES[value]
    base = value.split('-')[0]
    return f'{NATIVE_NAMES[base]} ({value})' if base in NATIVE_NAMES else value

DERIVED_PROFILE_FIELDS = {'glossary_revision', 'glossary_entries', 'language_authorization'}
LOCALE_PATTERN = r'(?:[a-z]{2,3}(?:-[a-z]{3}){0,3}|[a-z]{4}|[a-z]{5,8})(?:-[a-z]{4})?(?:-(?:[a-z]{2}|[0-9]{3}))?(?:-(?:[a-z0-9]{5,8}|[0-9][a-z0-9]{3}))*(?:-[0-9a-wy-z](?:-[a-z0-9]{2,8})+)*(?:-x(?:-[a-z0-9]{1,8})+)?'


def canonical_locale(value):
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(LOCALE_PATTERN, value, re.IGNORECASE):
        raise ValueError('LOCALE_INVALID')
    parts = value.lower().split('-')
    if parts[0] in {'und', 'auto', 'mul', 'zxx'}:
        raise ValueError('SOURCE_LANGUAGE_REQUIRED')
    extension = False
    for index in range(1, len(parts)):
        part = parts[index]
        if len(part) == 1:
            extension = True
        if not extension:
            if len(part) == 4 and part.isalpha():
                parts[index] = part.title()
            elif len(part) == 2 and part.isalpha():
                parts[index] = part.upper()
    return '-'.join(parts)


def public_profile(profile):
    return {key: value for key, value in profile.items() if key not in DERIVED_PROFILE_FIELDS}


def source_pairs(source, target):
    target = canonical_locale(target)
    def source_locale(value):
        return 'und' if value in ('auto', 'und', None) else canonical_locale(value)
    languages = {source_locale(source['language']), *(source_locale(block.get('language', source['language']))
        for block in source['blocks'] if block['translatable'])}
    return sorted([language, target] for language in languages if language != target)


def translation_profile(profile, source, target):
    source_pairs(source, target)
    return deepcopy(public_profile(profile))


def check_language_policy(profile, source, target):
    # Existing job snapshots remain immutable; their old language flags no longer gate execution.
    source_pairs(source, target)
