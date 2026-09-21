"""Bounded DOI evidence from embedded metadata and the first two PDF pages."""
import re
from statistics import median
from urllib.parse import unquote

VERSION = 'doi-discovery-v4'
DOI = re.compile(r'10\.\d{4,9}/[^\s<>"\u201c\u201d]+', re.I)
SECTION_NUMBER = r'(?:(?:\d+(?:\.\d+)*|[ivxlcdm]+)[.)]?[ \t]+)?'
REFERENCES = re.compile(r'(?im)^\s*' + SECTION_NUMBER + r'(?:references|bibliography|参考文献)\s*:?\s*$')
BODY_START = re.compile(r'(?im)^\s*' + SECTION_NUMBER + r'(?:abstract|introduction|摘要|references|bibliography|参考文献)\s*[:：]?\s*$')
BODY_BOUNDARY = re.compile(r'(?im)^[ \t]*' + SECTION_NUMBER + r'(?:abstract|introduction|摘要)\b[^\n]*')
ARXIV_STAMP = re.compile(
    r'(?im)^[ \t]*arxiv[ \t]*:[ \t]*'
    r'(?P<id>\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}|[a-z][a-z.-]*/\d{2}(?:0[1-9]|1[0-2])\d{3})'
    r'(?P<version>v[1-9]\d*)?(?:[ \t]+\[[a-z][a-z.-]*\])?'
    r'(?:[ \t]+(?P<date>\d{1,2}[ \t]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[ \t]+\d{4}))?[ \t]*$')


def bibliographic_title(value):
    """Accept a bounded title, never a filename, URL, placeholder or paragraph."""
    if not isinstance(value, str): return None
    value = ' '.join(value.split())
    if not 12 <= len(value) <= 500 or not any(c.isalpha() for c in value): return None
    if re.search(r'https?://|@|\.(?:pdf|docx?|tex)\b|^(?:untitled|microsoft word|manuscript|document)\s*$', value, re.I):
        return None
    if BODY_START.match(value): return None
    return value


def _page_title(page):
    """Use a prominent heading before the abstract, with smaller text as evidence."""
    rows = sorted(page.get('text_regions', []), key=lambda row: (row['bbox'][1], row['bbox'][0]))
    heights = [(row['bbox'][3] - row['bbox'][1]) / max(1, len(row.get('text', '').splitlines()))
        for row in rows if row.get('text', '').strip()]
    if not heights: return None
    candidates = []
    page_height = page.get('page_size', [600, 800])[1]
    for row in rows:
        if BODY_START.search(row.get('text', '')): break
        lines = row.get('text', '').splitlines()
        height = (row['bbox'][3] - row['bbox'][1]) / max(1, len(lines))
        if row['bbox'][1] > page_height * .45 or not 10 <= height <= 48: continue
        value = ' '.join(row.get('text', '').split())
        # Individual wrapped lines may be short; validate the complete heading.
        if value and len(value) <= 500 and any(c.isalpha() for c in value):
            candidates.append((row, value, height))
    if not candidates: return None
    largest = max(height for _, _, height in candidates)
    if largest < median(heights) * 1.2: return None
    heading = []
    bottom = None
    for row, value, height in candidates:
        # Native bounds measure the letters, not the font em: a line without
        # descenders can be roughly a quarter shorter in the very same font.
        if height < max(largest * .72, median(heights) * 1.2):
            if heading: break
            continue
        if bottom is not None and row['bbox'][1] - bottom > largest * 1.5: break
        heading.append(value)
        bottom = row['bbox'][3]
        if len(heading) == 4: break
    return bibliographic_title(' '.join(heading))


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
    title_hint = bibliographic_title(metadata.get('/Title'))
    title_method = 'embedded_metadata' if title_hint else None
    author_hint = str(metadata.get('/Author') or '')[:2000]
    def add(doi, method, confidence, *, page=None, bbox=None, reference=False):
        if len(candidates) >= 100: return
        record = {'doi': doi, 'method': method, 'confidence': confidence, 'page': page,
            'bbox': bbox, 'reference': reference}
        if record not in candidates: candidates.append(record)
    def add_arxiv(match, method, bbox):
        arxiv_id = match['id'].casefold()
        if '/' in arxiv_id:
            archive, number = arxiv_id.split('/', 1)
            arxiv_id = archive.split('.')[0] + '/' + number
        add('10.48550/arxiv.' + arxiv_id, method, 85, page=1, bbox=bbox)
    for key, value in list(metadata.items())[:100]:
        if not isinstance(value, str): continue
        for doi, _, _ in _matches(value[:16000]):
            if 'doi' in key.casefold() or re.match(r'\s*(?:doi:|https?://(?:dx\.)?doi.org/)', value, re.I):
                add(doi, 'metadata', 100)
    for doi, _, _ in _matches(xmp[:262144]):
        add(doi, 'xmp', 100)
    headers = []
    header_dois = set()
    for page in pages[:2]:
        if page['page'] == 1 and not title_hint:
            title_hint = _page_title(page)
            title_method = 'first_page_heading' if title_hint else None
        regions = sorted(page.get('text_regions', []), key=lambda row: (row['bbox'][1], row['bbox'][0]))
        joined = '\n'.join(row.get('text', '') for row in regions)[:50000]
        reference_start = REFERENCES.search(joined)
        reference_offset = reference_start.start() if reference_start else len(joined)
        header = joined[:reference_offset]
        for boundary in BODY_BOUNDARY.finditer(header):
            line = ' '.join(boundary.group().split()).casefold()
            # A real title may start with "Introduction to" or "Abstract
            # Interpretation"; it is not a body heading (including wrapped titles).
            if len(line.split()) > 1 and (title_hint or '').casefold().startswith(line): continue
            header = header[:boundary.start()]
            break
        if page['page'] == 1:
            headers.append(header[:12000])
            header_dois.update(doi for doi, _, _ in _matches(header[:12000]))
            # arXiv assigns a DataCite DOI to every paper (not each version).
            # A standalone first-page header or vertical page-margin stamp is
            # evidence; ordinary body citations and links are not.
            # https://info.arxiv.org/help/doi.html
            for match in ARXIV_STAMP.finditer(header[:12000]):
                boxes = [row['bbox'] for row in regions if match.group().strip() in row.get('text', '')]
                add_arxiv(match, 'arxiv_header', boxes[0] if len(boxes) == 1 else None)
            page_width, page_height = page.get('page_size', [600, 800])
            for row in regions:
                text = row.get('text', '').strip()
                if len(text) > 500 or text in header: continue
                match = ARXIV_STAMP.fullmatch(text)
                if not match or not match['version'] or not match['date']: continue
                left, top, right, bottom = row['bbox']
                width, height = right - left, bottom - top
                # The arXiv sidebar can start below the abstract in reading
                # order. Require a complete dated stamp and independent geometry.
                if (0 <= left < right <= page_width and 0 <= top < bottom <= page_height
                        and height >= max(80, 6 * width)
                        and (right <= page_width * .1 or left >= page_width * .9)):
                    add_arxiv(match, 'arxiv_margin', row['bbox'])
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
    # Only DOI metadata or the actual first-page header can supersede a stamp.
    # A DOI cited in the abstract/body or on page two is not publication evidence.
    explicit = {entry['doi'] for entry in candidates if not entry['reference']
        and entry['confidence'] >= 70 and (entry['method'] in {'metadata', 'xmp'} or entry['doi'] in header_dois)}
    arxiv = {entry['doi'] for entry in candidates if entry['method'] in {'arxiv_header', 'arxiv_margin'}}
    if arxiv: strong = explicit or arxiv
    embedded = {entry['doi'] for entry in candidates if entry['method'] in {'metadata', 'xmp'}}
    selected = next(iter(embedded)) if len(embedded) == 1 else next(iter(strong)) if len(strong) == 1 else None
    return {'version': VERSION, 'status': 'found' if selected else 'ambiguous' if len(strong) > 1 else 'no_doi',
        'selected': selected, 'candidates': candidates, 'title_hint': title_hint or None,
        'title_method': title_method, 'author_hint': author_hint or None, 'header_text': '\n'.join(headers)}
