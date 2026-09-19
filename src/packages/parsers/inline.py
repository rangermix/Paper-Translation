"""Lossless academic inline spans, ordered before scalar numeric protection."""
import re
from packages.ir.quantities import MAGNITUDE

_NAME = r'[A-ZÀ-Ž][A-Za-zÀ-ž\u2019\x27-]*'
_AUTHOR = rf'{_NAME}(?:\s+et al\.|\s*(?:&|and)\s*{_NAME})?'
_YEAR = r'(?:19|20)\d{2}[a-z]?'
_CITATION = rf'\({_AUTHOR},\s*{_YEAR}(?:\s*;\s*(?:{_AUTHOR},\s*)?{_YEAR})*\)|{_AUTHOR}\s+\({_YEAR}(?:\s*;\s*{_YEAR})*\)'
_MATH = r'(?<![\\$])(?P<delimiter>\${1,2})(?!\$)(?:\\.|[^$\n]){1,4096}?(?P=delimiter)(?!\$)|\\\([^\n]{1,4096}?\\\)|\\\[[^\n]{1,4096}?\\\]'
TOKEN = re.compile(rf'(?P<url>https?://[^\s<>"\x00-\x20]+)|(?P<math>{_MATH})|(?P<citation>{_CITATION})|(?P<quantity>{MAGNITUDE})|(?P<scalar>−→|[←→⇒⇐↔≤≥≠≈√∞]|(?<![A-Za-z0-9_])(?:\d+(?:[.,]\d+)*%?)(?![A-Za-z0-9_]))')
PLAIN_TOKEN = re.compile(TOKEN.pattern.replace(rf'(?P<math>{_MATH})|', ''))


def tokens(text):
    for match in TOKEN.finditer(text):
        # Dollar currency pairs and mismatched delimiters are ordinary text.
        if match.lastgroup == 'math' and match[0].startswith('$'):
            delimiter = '$$' if match[0].startswith('$$') else '$'
            value = match[0][len(delimiter):-len(delimiter)].strip()
            if ('\\' not in value and re.search(r'[A-Za-z]{2,}', value)) or (not re.search(r'[\\_^=+*/<>]|\b[A-Za-z]\b', value) and not re.fullmatch(r'[\d.]+', value)):
                yield from PLAIN_TOKEN.finditer(text, match.start(), match.end())
                continue
        yield match
