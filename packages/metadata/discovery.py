"""Bounded DOI evidence from embedded metadata and the first two PDF pages."""
import re
from urllib.parse import unquote

VERSION = 'doi-discovery-v1'
DOI = re.compile(r'10\.\d{4,9}/[^\s<>"\u201c\u201d]+', re.I)
REFERENCES = re.compile(r'(?im)^\s*(?:references|bibliography|参考文献)\s*:?\s*$')


def normalize_doi(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    value = unquote(value.strip()).replace('\u00ad', '')
    value = re.sub(r'^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)', '', value, flags=re.I)
    value = re.sub(r'\s+', '', value).strip().rstrip('.,;:')
    while value and value[-1] in ')]}':
        close = value[-1]; opening = {')': '(', ']': '[', '}': '{'}[close]
        if value.count(close) <= value.count(opening): break
        value = value[:-1]
    if not DOI.fullmatch(value) or any(ord(c) < 32 for c in value):
        return None
    return value.casefold()


def _matches(text):
    # PDF line wrapping immediately after '/' is unambiguous. A trailing
    # hyphen inside a DOI is preserved when its continuation starts next line.
    text = re.sub(r'(10\.\d{4,9}/)\s*\n\s*', r'\1', text, flags=re.I)
    text = re.sub(r'(10\.\d{4,9}/[^\s]+-)\s*\n\s*(?=[A-Za-z0-9])', r'\1', text, flags=re.I)
    for match in DOI.finditer(text):
        identifier = normalize_doi(match.group())
        if identifier:
            yield identifier, match.start(), text[max(0, match.start()-12):match.start()]


def discover_doi(metadata, pages, *, xmp=''):
    candidates = []
    title_hint = str(metadata.get('/Title') or '')[:2000]
    author_hint = str(metadata.get('/Author') or '')[:2000]
    def add(doi, method, confidence, *, page=None, bbox=None, reference=False):
        if len(candidates) >= 100: return
        record = {'doi': doi, 'method': method, 'confidence': confidence, 'page': page,
            'bbox': bbox, 'reference': reference}
        if record not in candidates: candidates.append(record)
    for key, value in list(metadata.items())[:100]:
        if not isinstance(value, str): continue
        for doi, _, _ in _matches(value[:16000]):
            if 'doi' in key.casefold() or re.match(r'\s*(?:doi:|https?://(?:dx\.)?doi.org/)', value, re.I):
                add(doi, 'metadata', 100)
    for doi, _, _ in _matches(xmp[:262144]):
        add(doi, 'xmp', 100)
    headers = []
    for page in pages[:2]:
        regions = sorted(page.get('text_regions', []), key=lambda row: (row['bbox'][1], row['bbox'][0]))
        joined = '\n'.join(row.get('text', '') for row in regions)[:50000]
        reference_start = REFERENCES.search(joined)
        reference_offset = reference_start.start() if reference_start else len(joined)
        header = joined[:reference_offset]
        header = re.split(r'(?im)^\s*(?:abstract|introduction|摘要)\b', header, maxsplit=1)[0]
        if page['page'] == 1: headers.append(header[:12000])
        # Split before unwrapping DOI lines: normalization changes offsets and
        # must never move a bibliography DOI into the paper header.
        for chunk, is_reference in ((joined[:reference_offset], False), (joined[reference_offset:], True)):
            for doi, _, prefix in _matches(chunk):
                confidence = 90 if re.search(r'doi\s*:\s*$|doi\.org/$', prefix, re.I) else 70
                if page['page'] > 1: confidence -= 15
                boxes = [row['bbox'] for row in regions if any(value == doi for value, _, _ in _matches(row.get('text', '')))]
                add(doi, 'header', 0 if is_reference else confidence, page=page['page'],
                    bbox=boxes[0] if len(boxes) == 1 else None, reference=is_reference)
        for link in page.get('links', [])[:100]:
            identifier = normalize_doi(link.get('uri'))
            if not identifier: continue
            bounds = link.get('bbox')
            in_refs = bool(reference_start and any(row['bbox'][1] <= (bounds or [0,0])[1] and REFERENCES.search(row.get('text','')) for row in regions))
            add(identifier, 'link', 0 if in_refs else 80 if page['page'] == 1 else 55,
                page=page['page'], bbox=bounds, reference=in_refs)
    strong = {entry['doi'] for entry in candidates if not entry['reference'] and entry['confidence'] >= 70}
    embedded = {entry['doi'] for entry in candidates if entry['method'] in {'metadata', 'xmp'}}
    selected = next(iter(embedded)) if len(embedded) == 1 else next(iter(strong)) if len(strong) == 1 else None
    return {'version': VERSION, 'status': 'found' if selected else 'ambiguous' if len(strong) > 1 else 'no_doi',
        'selected': selected, 'candidates': candidates, 'title_hint': title_hint or None,
        'author_hint': author_hint or None, 'header_text': '\n'.join(headers)}
