import httpx
import pytest

from packages.metadata.client import lookup, MAX_BYTES
from packages.metadata.mapping import map_metadata, matches_paper


TITLE = 'A Controlled Research Paper about Reliable Metadata'
DISCOVERY = {'status': 'no_doi', 'selected': None, 'title_hint': TITLE,
    'author_hint': 'Alice Example', 'header_text': TITLE + '\nAlice Example', 'candidates': []}
RECORD = {'DOI': '10.1234/example', 'title': [TITLE],
    'author': [{'given': 'Alice', 'family': 'Example'}], 'issued': {'date-parts': [[2020]]}}


def test_title_lookup_sends_only_bibliographic_fields_to_crossref():
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={'status': 'ok', 'message': {'items': [RECORD]}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = lookup(None, search={'title': TITLE, 'author': 'Alice Example'}, client=client)
    assert result.status == 'succeeded' and result.value['doi'] == '10.1234/example'
    assert result.service == 'crossref' and result.response == RECORD
    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == 'api.crossref.org' and request.url.path == '/works'
    assert request.url.params['query.title'] == TITLE
    assert request.url.params['query.author'] == 'Alice Example'
    assert request.url.params['rows'] == '5'
    assert not request.content and 'authorization' not in request.headers


@pytest.mark.parametrize('items,status', [
    ([], 'not_found'),
    ([RECORD | {'title': ['An Entirely Different Study']}], 'unverified'),
    ([RECORD | {'author': [{'given': 'Bob', 'family': 'Unrelated'}]}], 'unverified'),
    ([RECORD, RECORD | {'DOI': '10.1234/another'}], 'ambiguous'),
    ([{'title': [TITLE]}], 'unverified'),
])
def test_search_never_accepts_unrelated_or_ambiguous_results(items, status):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            json={'status': 'ok', 'message': {'items': items}}))) as client:
        result = lookup(None, search={'title': TITLE, 'author': 'Alice Example'}, client=client)
    assert result.status == status and result.value is None


def test_search_ignores_ranking_and_deduplicates_identical_dois():
    items = [RECORD | {'DOI': '10.1234/wrong', 'title': ['Other work'], 'score': 999}, RECORD, RECORD]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            json={'status': 'ok', 'message': {'items': items}}))) as client:
        result = lookup(None, search={'title': TITLE, 'author': 'Alice Example'}, client=client)
    assert result.status == 'succeeded' and result.value['doi'] == RECORD['DOI']


@pytest.mark.parametrize('response,code', [
    (httpx.Response(429, headers={'Retry-After': '60'}), 'METADATA_RATE_LIMIT'),
    (httpx.Response(200, content=b' ' * (MAX_BYTES + 1)), 'METADATA_RESPONSE_TOO_LARGE'),
    (httpx.Response(200, json={'status': 'ok', 'message': {}}), 'METADATA_INVALID_RESPONSE'),
    (httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'}), 'METADATA_HTTP_ERROR'),
])
def test_search_has_the_same_http_bounds_as_doi_lookup(response, code):
    seen = []
    def respond(request):
        seen.append(request)
        return response
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = lookup(None, search={'title': TITLE}, client=client)
    assert result.status == 'failed' and result.code == code
    assert len(seen) == 1
    if code == 'METADATA_RATE_LIMIT': assert result.retry_after == 60


def test_paper_without_a_doi_requires_an_exact_normalized_title_and_matching_author():
    value = map_metadata(RECORD, RECORD['DOI'], 'crossref')
    assert matches_paper(value, DISCOVERY)
    assert matches_paper(value | {'title': TITLE.upper() + '.'}, DISCOVERY)
    assert not matches_paper(value | {'title': TITLE.replace('Reliable', 'Unreliable')}, DISCOVERY)
    assert not matches_paper(value | {'authors': []}, DISCOVERY)
    assert not matches_paper(value, DISCOVERY | {'title_hint': 'Metadata'})


def test_a_distinctive_exact_title_can_match_without_embedded_authors():
    value = map_metadata(RECORD, RECORD['DOI'], 'crossref')
    assert matches_paper(value, DISCOVERY | {'author_hint': None})
    assert not matches_paper(value | {'title': 'Research methods'}, DISCOVERY | {
        'title_hint': 'Research methods', 'author_hint': None})


def test_missing_or_placeholder_title_does_not_make_a_search_request():
    from packages.metadata.mapping import search_terms
    for title in [None, '', 'Untitled', 'Microsoft Word - manuscript.docx', 'main.pdf', 'a' * 501]:
        assert search_terms(DISCOVERY | {'title_hint': title}) is None
    assert search_terms(DISCOVERY) == {'title': TITLE, 'author': 'Alice Example'}
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('No usable query'))) as client:
        assert lookup(None, client=client).status == 'no_doi'


@pytest.mark.parametrize('hint,given,family,expected', [
    ('John Smith', 'Mary', 'John', False),
    ('Peter de Vries', 'Jane', 'de Jong', False),
    ('John Smith, Jane Jones', 'Jane', 'Smith', False),
    ('Alice Example', 'Bob', 'Example', False),
    ('Alice Example', 'Alice', 'Example', True),
    ('A. Example', 'Alice', 'Example', True),
    ('Example, Alice', 'Alice', 'Example', True),
    ('Alice Example; Bob Sample', 'Bob', 'Sample', True),
    ('Peter de Vries', 'Peter', 'de Vries', True),
])
def test_title_search_requires_author_identity_not_a_shared_name_word(hint, given, family, expected):
    record = RECORD | {'author': [{'given': given, 'family': family}]}
    value = map_metadata(record, RECORD['DOI'], 'crossref')
    assert matches_paper(value, DISCOVERY | {'author_hint': hint}) is expected
