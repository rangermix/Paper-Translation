"""Fixed public endpoints and bounded DOI/title/author requests and replies."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from urllib.parse import quote, urlencode

import httpx

from packages.ir import strict_loads
from .discovery import normalize_doi
from .mapping import map_metadata, matches_search, search_terms

MAX_BYTES = 1024 * 1024
REQUEST_SECONDS = 10
TOTAL_SECONDS = 30
SEARCH_ROWS = 5


@dataclass
class LookupResult:
    status: str
    service: str
    value: dict | None = None
    response: dict | None = None
    code: str | None = None
    retry_after: float | None = None


def retry_after(value):
    try: return max(0, float(value))
    except (TypeError, ValueError):
        try: return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError): return 2


def _request(client, url, service, deadline):
    if time.monotonic() >= deadline:
        return LookupResult('failed', service, code='METADATA_TIMEOUT', retry_after=2)
    try:
        with client.stream('GET', url, follow_redirects=False,
                timeout=min(REQUEST_SECONDS, deadline-time.monotonic()),
                headers={'Accept': 'application/vnd.citationstyles.csl+json' if service == 'doi' else 'application/json',
                         'User-Agent': 'PaperTranslation (+https://github.com/rangermix/Paper-Translation) metadata'}) as response:
            if response.status_code == 404:
                return LookupResult('not_found', service, code='METADATA_NOT_FOUND')
            if response.status_code in {408, 429, 500, 502, 503, 504}:
                return LookupResult('failed', service, code='METADATA_RATE_LIMIT' if response.status_code == 429 else 'METADATA_TEMPORARY',
                    retry_after=retry_after(response.headers.get('Retry-After')))
            if response.status_code != 200:
                return LookupResult('failed', service, code='METADATA_HTTP_ERROR')
            if int(response.headers.get('Content-Length', 0)) > MAX_BYTES:
                return LookupResult('failed', service, code='METADATA_RESPONSE_TOO_LARGE')
            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_BYTES:
                    return LookupResult('failed', service, code='METADATA_RESPONSE_TOO_LARGE')
                if time.monotonic() > deadline: raise httpx.TimeoutException('metadata deadline')
                body.extend(chunk)
            raw = strict_loads(bytes(body))
            if service == 'crossref':
                if not isinstance(raw, dict) or raw.get('status') != 'ok': raise ValueError('METADATA_INVALID_RESPONSE')
                raw = raw.get('message')
            if not isinstance(raw, dict): raise ValueError('METADATA_INVALID_RESPONSE')
            return LookupResult('succeeded', service, response=raw)
    except httpx.HTTPError:
        return LookupResult('failed', service, code='METADATA_NETWORK_ERROR', retry_after=2)
    except (ValueError, TypeError, KeyError, OverflowError):
        return LookupResult('failed', service, code='METADATA_INVALID_RESPONSE')


def _search(client, search, deadline):
    params = {'query.title': search['title'], 'rows': SEARCH_ROWS,
        'select': 'DOI,title,author,published-print,published-online,issued,published,container-title,publisher,volume,issue,page,type'}
    if search.get('author'): params['query.author'] = search['author']
    result = _request(client, 'https://api.crossref.org/works?' + urlencode(params), 'crossref', deadline)
    if result.status != 'succeeded': return result
    items = result.response.get('items')
    if not isinstance(items, list):
        return LookupResult('failed', 'crossref', code='METADATA_INVALID_RESPONSE')
    if not items: return LookupResult('not_found', 'crossref', code='METADATA_NOT_FOUND')
    matches = {}
    for raw in items[:SEARCH_ROWS]:
        doi = normalize_doi(raw.get('DOI')) if isinstance(raw, dict) else None
        if not doi: continue
        try: value = map_metadata(raw, doi, 'crossref')
        except (ValueError, TypeError, KeyError, OverflowError): continue
        if matches_search(value, search): matches[doi] = (value, raw)
    if len(matches) > 1: return LookupResult('ambiguous', 'crossref', code='METADATA_AMBIGUOUS')
    if not matches: return LookupResult('unverified', 'crossref', code='METADATA_PAPER_MISMATCH')
    value, raw = next(iter(matches.values()))
    return LookupResult('succeeded', 'crossref', value=value, response=raw)


def lookup(doi, *, search=None, client=None):
    search = search_terms({'title_hint': (search or {}).get('title'), 'author_hint': (search or {}).get('author')})
    if not doi and not search: return LookupResult('no_doi', 'crossref')
    owned = client is None
    client = client or httpx.Client(follow_redirects=False, trust_env=False)
    deadline = time.monotonic() + TOTAL_SECONDS
    try:
        if not doi: return _search(client, search, deadline)
        outcome = LookupResult('not_found', 'crossref', code='METADATA_NOT_FOUND')
        for service, url in [('crossref', 'https://api.crossref.org/works/' + quote(doi, safe='')),
                             ('doi', 'https://citation.doi.org/metadata?' + urlencode({'doi': doi}))]:
            outcome = _request(client, url, service, deadline)
            if outcome.retry_after is not None: return outcome
            if outcome.status != 'succeeded': continue
            try:
                outcome.value = map_metadata(outcome.response, doi, service)
                return outcome
            except (ValueError, TypeError, KeyError, OverflowError):
                outcome = LookupResult('failed', service, code='METADATA_INVALID_RESPONSE')
        return outcome
    finally:
        if owned: client.close()
