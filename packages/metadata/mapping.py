"""Strict DOI binding and plain-text CSL/Crossref mapping."""
from datetime import date
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import quote

from .discovery import normalize_doi

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


def matches_paper(value, discovery):
    selected = discovery.get('selected')
    if selected != value['doi']: return False
    if any(c['doi'] == selected and c['method'] == 'manual' for c in discovery.get('candidates', [])):
        return True
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
