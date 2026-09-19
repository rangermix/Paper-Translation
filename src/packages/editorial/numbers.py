"""Conservative numeric formatting equivalence for QA; never rewrites source/target.

Only explicit Arabic-number scales are converted. Spaced decimals must have
horizontal whitespace on both sides of the dot (a PDF extraction convention),
not a sentence-ending dot/newline. Commas are removed only in groups of three.
Percentages remain a separate unit, and occurrences are compared as a multiset.
"""
from collections import Counter
import re


_SPACE = r'[ \t\u00a0\u202f]'
_SCALES = {
    'thousand': 3, 'million': 6, 'billion': 9, 'trillion': 12,
    '万亿': 12, '萬億': 12, '十亿': 9, '十億': 9, '亿': 8, '億': 8,
    '千万': 7, '千萬': 7, '百万': 6, '百萬': 6, '十万': 5, '十萬': 5,
    '万': 4, '萬': 4, 'b': 9, 'm': 6,
}
_SCALE_PATTERN = '|'.join(re.escape(s) for s in _SCALES if s not in {'b', 'm'}) + r'|[BM](?=\s+(?:parameters?|models?)\b)'
_NUMBER = re.compile(
    rf'(?<![A-Za-z0-9_])(?P<number>[+\-−]?(?:\d{{1,3}}(?:,\d{{3}})+(?!\d)|\d+)'
    rf'(?:(?:\.|{_SPACE}+\.{_SPACE}+)\d+)?(?:[eE][+\-]?\d+)?)'
    rf'(?:{_SPACE}*(?P<scale>{_SCALE_PATTERN})(?![A-Za-z]))?'
    rf'(?:{_SPACE}*(?P<percent>%))?', re.IGNORECASE)
_WIDTH = str.maketrans('０１２３４５６７８９．％＋－', '0123456789.%+-')


def _canonical(literal, scale):
    # Decimal arithmetic contexts can round or overflow. Canonicalize the exact
    # coefficient/exponent instead; never allocate padding for huge exponents.
    mantissa, _, exponent = literal.lower().partition('e')
    if len(exponent.lstrip('+-')) > 6:
        return f'literal:{literal.lower()}*1e{scale}'  # conservative exact match only
    negative = mantissa.startswith('-')
    whole, _, fraction = mantissa.lstrip('+-').partition('.')
    digits = (whole + fraction).lstrip('0')
    if not digits:
        return '0'
    power = int(exponent or '0') - len(fraction) + scale
    trimmed = digits.rstrip('0')
    power += len(digits) - len(trimmed)
    digits = trimmed
    adjusted = len(digits) + power - 1
    if -20 <= adjusted <= 30:
        point = len(digits) + power
        if point <= 0:
            result = '0.' + '0' * -point + digits
        elif point >= len(digits):
            result = digits + '0' * (point - len(digits))
        else:
            result = digits[:point] + '.' + digits[point:]
    else:
        result = digits[0] + ('.' + digits[1:] if len(digits) > 1 else '') + f'e{adjusted}'
    return ('-' if negative else '') + result


def _tokens(text):
    # Width folding is deliberately limited to numeric characters, not NFKC of prose.
    folded = text.translate(_WIDTH)
    result = []
    for match in _NUMBER.finditer(folded):
        literal = re.sub(_SPACE, '', match['number']).replace(',', '').replace('−', '-')
        scale = _SCALES.get((match['scale'] or '').lower(), 0)
        result.append({'text': text[match.start():match.end()], 'value': _canonical(literal, scale),
            'unit': '%' if match['percent'] else ''})
    return result


def compare_numbers(source, target):
    source_numbers, target_numbers = _tokens(source), _tokens(target)
    def counts(tokens):
        return Counter((token['value'], token['unit']) for token in tokens)
    left, right = counts(source_numbers), counts(target_numbers)
    def difference(before, after):
        return [{'value': value, 'unit': unit, 'count': count}
            for (value, unit), count in (before - after).items()]
    return {'matches': left == right, 'source_numbers': source_numbers, 'target_numbers': target_numbers,
        'missing_from_target': difference(left, right), 'extra_in_target': difference(right, left)}
