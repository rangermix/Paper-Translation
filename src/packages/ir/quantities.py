"""Exact, bounded localization of explicitly scaled quantities, never source edits."""
from collections import Counter
from decimal import Decimal, localcontext
import re

LITERAL = r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
MAGNITUDE = rf'(?<![A-Za-z0-9_.-]){LITERAL}\s*(?:(?:thousand|million|billion|trillion)(?![A-Za-z])|[MB](?=\s+(?:parameters?|models?)\b))'
_FULL = re.compile(rf'({LITERAL})\s*(thousand|million|billion|trillion|M|B)', re.I)


def localize_quantity(value, locale):
    if locale.split('-')[0] != 'zh' or len(value) > 100:
        return None
    match = _FULL.fullmatch(value.strip())
    if not match:
        return None
    exponent = {'thousand':3, 'million':6, 'billion':9, 'trillion':12, 'm':6, 'b':9}[match[2].lower()]
    with localcontext() as ctx:
        ctx.prec = 120
        number = Decimal(match[1].replace(',', '')) * 10 ** exponent
        scale, unit = (8, '亿') if abs(number) >= 100_000_000 else (4, '万') if abs(number) >= 10_000 else (0, '')
        result = format(number / 10 ** scale, 'f')
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    if locale in {'zh-Hant','zh-TW','zh-HK','zh-MO'} or locale.startswith('zh-Hant-'):
        unit = unit.translate(str.maketrans('亿万', '億萬'))
    return result + unit


def protected_counts(source_nodes, target_nodes, atoms, locale):
    """Account for each exact localized occurrence; all other refs stay strict."""
    source = Counter(n['ref'] for n in source_nodes if n['type'] == 'protected_ref')
    target = Counter(n['ref'] for n in target_nodes if n['type'] == 'protected_ref')
    from packages.editorial.numbers import compare_numbers
    from .validator import flatten_inline
    if not compare_numbers(flatten_inline(source_nodes, atoms), flatten_inline(target_nodes, atoms))['matches']:
        return source, target
    # Only literal target text may replace a quantity, never another protected
    # citation, formula or number. Consume occurrences so duplicates cannot pass.
    literal = ''.join(n['text'] if n['type'] == 'text' else '\0' for n in target_nodes)
    for ref, missing in (source - target).items():
        atom = atoms[ref]
        localized = localize_quantity(atom['value'], locale) if atom['kind'] == 'number' else None
        if localized:
            pattern = re.compile(r'(?<![\d.,+−\-])' + re.escape(localized) + r'(?![\d.亿億万萬])(?!\s*[%‰])')
            literal, count = pattern.subn('\0', literal, count=missing)
            source[ref] -= count
    return +source, +target
