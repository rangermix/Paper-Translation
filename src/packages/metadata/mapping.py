"""Strict DOI binding and plain-text CSL/Crossref mapping."""
from datetime import date
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import quote

from .discovery import bibliographic_title, normalize_doi

VERSION = 'bibliography-v1'


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}: self.hidden += 1
    def handle_endtag(self, tag):
        if tag in {'script', 'style'}: self.hidden = max(0, self.hidden - 1)
    def handle_data(self, value):
        if not self.hidden: self.parts.append(value)


def clean(value, maximum=5000):
    if isinstance(value, list): value = value[0] if value else None
    if not isinstance(value, str): return None
    parser = PlainText(); parser.feed(value[:maximum * 4])
    result = ' '.join(''.join(parser.parts).split())[:maximum]
    return result or None


def publication_date(value):
    try:
        parts = value['date-parts'][0]
        if not 1 <= len(parts) <= 3 or any(type(n) is not int for n in parts): return None
        y, m, d = (parts + [1, 1])[:3]
        date(y, m, d)
        return {'parts': parts, 'precision': ['year', 'month', 'day'][len(parts)-1]}
    except (KeyError, TypeError, IndexError, ValueError): return None


def map_metadata(raw, doi, service):
    if not isinstance(raw, dict) or normalize_doi(raw.get('DOI') or raw.get('doi')) != doi:
        raise ValueError('METADATA_DOI_MISMATCH')
    title = clean(raw.get('title'))
    if not title: raise ValueError('METADATA_TITLE_MISSING')
    authors = []
    if isinstance(raw.get('author'), list):
        for entry in raw['author'][:200]:
            if not isinstance(entry, dict): continue
            given, family, literal = clean(entry.get('given'), 200), clean(entry.get('family'), 200), clean(entry.get('literal') or entry.get('name'), 500)
            name = literal or ' '.join(part for part in (given, family) if part)
            if name: authors.append({'name': name, 'given': given, 'family': family})
    dates = {key: publication_date(raw.get(key)) for key in ('published-print', 'published-online', 'issued', 'published')}
    chosen = next((dates[key] for key in dates if dates[key]), None)
    return {'mapping_version': VERSION, 'doi': doi, 'doi_url': 'https://doi.org/' + quote(doi, safe='/'), 'title': title,
        'authors': authors, 'date': chosen, 'dates': dates, 'year': chosen['parts'][0] if chosen else None,
        'container': clean(raw.get('container-title')), 'publisher': clean(raw.get('publisher')),
        'volume': clean(raw.get('volume'), 100), 'issue': clean(raw.get('issue'), 100), 'pages': clean(raw.get('page'), 200),
        'type': clean(raw.get('type'), 100), 'service': service}


def words(value):
    return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', value or '').casefold())


def search_terms(discovery):
    title = bibliographic_title(clean(discovery.get('title_hint')))
    if not title: return None
    author = clean(discovery.get('author_hint'), 200)
    return {'title': title, **({'author': author} if author else {})}


def _matches_author(entry, hint):
    given, family = words(entry.get('given')), words(entry.get('family'))
    def given_match(left, right):
        return len(left) == len(right) and all(a == b or min(len(a), len(b)) == 1 and a[0] == b[0]
            for a, b in zip(left, right))
    for segment in re.split(r';|\band\b|&|、', hint, flags=re.I):
        parts = segment.split(',')
        # Support a single inverted name without joining two different authors.
        if given and family and len(parts) == 2 and words(parts[0]) == family and given_match(words(parts[1]), given):
            return True
        for part in parts:
            tokens = words(part)
            if given and family:
                length = len(given) + len(family)
                for start in range(len(tokens) - length + 1):
                    if tokens[start + len(given):start + length] == family and given_match(tokens[start:start + len(given)], given):
                        return True
            else:
                name = words(entry['name'])
                if name and (tokens == name or len(name) >= 2 and any(
                        tokens[start:start + len(name)] == name for start in range(len(tokens) - len(name) + 1))):
                    return True
    return False


def matches_search(value, search):
    if not search or words(value['title']) != words(search['title']): return False
    title = words(search['title'])
    if search.get('author'):
        return any(_matches_author(entry, search['author']) for entry in value['authors'])
    # Short generic titles need author corroboration; distinctive exact titles
    # can match when the PDF has no embedded author field (including CJK titles).
    return len(set(title)) >= 5 or len(re.findall(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]', search['title'])) >= 12


def matches_paper(value, discovery):
    selected = discovery.get('selected')
    if not selected: return matches_search(value, search_terms(discovery))
    if selected != value['doi']: return False
    if any(c['doi'] == selected and c['method'] == 'manual' for c in discovery.get('candidates', [])):
        return True
    if any(c['doi'] == selected and c['method'] == 'crossref_search' for c in discovery.get('candidates', [])):
        return matches_search(value, search_terms(discovery))
    title = words(value['title'])
    hint = words(discovery.get('title_hint'))
    header = words(discovery.get('header_text'))
    score = lambda haystack: len(set(title) & set(haystack)) / max(1, len(set(title)))
    if hint or header:
        if max(score(hint), score(header)) < .75: return False
    elif not any(c['doi'] == selected and c['method'] in {'metadata', 'xmp'} for c in discovery.get('candidates', [])):
        return False
    author_hint = set(words(discovery.get('author_hint')))
    family_names = {word for entry in value['authors'] for word in words(entry.get('family') or entry['name'])}
    if author_hint and family_names and not author_hint.intersection(family_names): return False
    return True
