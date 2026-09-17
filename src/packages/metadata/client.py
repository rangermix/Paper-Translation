"""Fixed public endpoints, bounded replies and no document-content requests."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from urllib.parse import quote, urlencode

import httpx

from packages.ir import strict_loads
from .mapping import map_metadata

MAX_BYTES = 1024 * 1024
REQUEST_SECONDS = 10
TOTAL_SECONDS = 30


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


def lookup(doi, *, client=None):
    owned = client is None
    client = client or httpx.Client(follow_redirects=False, trust_env=False)
    deadline = time.monotonic() + TOTAL_SECONDS
    outcome = LookupResult('not_found', 'doi', code='METADATA_NOT_FOUND')
    try:
        for service, url in [('doi', 'https://citation.doi.org/metadata?' + urlencode({'doi': doi})),
                             ('crossref', 'https://api.crossref.org/works/' + quote(doi, safe=''))]:
            if time.monotonic() >= deadline:
                return LookupResult('failed', service, code='METADATA_TIMEOUT', retry_after=2)
            try:
                with client.stream('GET', url, follow_redirects=False,
                        timeout=min(REQUEST_SECONDS, deadline-time.monotonic()),
                        headers={'Accept': 'application/vnd.citationstyles.csl+json' if service == 'doi' else 'application/json',
                                 'User-Agent': 'PaperTranslation/3.1 DOI-metadata'}) as response:
                    if response.status_code == 404:
                        outcome = LookupResult('not_found', service, code='METADATA_NOT_FOUND'); continue
                    if response.status_code in {408, 429, 500, 502, 503, 504}:
                        return LookupResult('failed', service, code='METADATA_RATE_LIMIT' if response.status_code == 429 else 'METADATA_TEMPORARY',
                            retry_after=retry_after(response.headers.get('Retry-After')))
                    if response.status_code != 200:
                        outcome = LookupResult('failed', service, code='METADATA_HTTP_ERROR'); continue
                    if int(response.headers.get('Content-Length', 0)) > MAX_BYTES:
                        outcome = LookupResult('failed', service, code='METADATA_RESPONSE_TOO_LARGE'); continue
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError('METADATA_RESPONSE_TOO_LARGE')
                        if time.monotonic() > deadline: raise httpx.TimeoutException('metadata deadline')
                        body.extend(chunk)
                    raw = strict_loads(bytes(body))
                    if service == 'crossref':
                        if not isinstance(raw, dict) or raw.get('status') != 'ok': raise ValueError('METADATA_INVALID_RESPONSE')
                        raw = raw.get('message')
                    value = map_metadata(raw, doi, service)
                    return LookupResult('succeeded', service, value=value, response=raw)
            except httpx.HTTPError:
                return LookupResult('failed', service, code='METADATA_NETWORK_ERROR', retry_after=2)
            except (ValueError, TypeError, KeyError, OverflowError):
                outcome = LookupResult('failed', service, code='METADATA_INVALID_RESPONSE')
        return outcome
    finally:
        if owned: client.close()
