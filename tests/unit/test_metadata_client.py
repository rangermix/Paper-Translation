import httpx
from packages.metadata.client import lookup, MAX_BYTES


def test_crossref_is_first_and_receives_only_encoded_identifier():
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={'status': 'ok', 'message': {'DOI': '10.1234/a(b)', 'title': ['Controlled title']}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = lookup('10.1234/a(b)', client=client)
    assert result.status == 'succeeded' and result.service == 'crossref'
    assert [request.url.host for request in seen] == ['api.crossref.org']
    assert all(not request.content and 'authorization' not in request.headers for request in seen)
    assert seen[0].url.raw_path.endswith(b'10.1234%2Fa%28b%29')


def test_doi_formatter_remains_a_fallback_for_other_registration_agencies():
    seen = []
    def respond(request):
        seen.append(request)
        if request.url.host == 'api.crossref.org': return httpx.Response(404)
        return httpx.Response(200, json={'DOI': '10.1234/example', 'title': 'Controlled title'})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = lookup('10.1234/example', client=client)
    assert result.status == 'succeeded' and result.service == 'doi'
    assert [request.url.host for request in seen] == ['api.crossref.org', 'citation.doi.org']
    assert seen[-1].url.params['doi'] == '10.1234/example'


def test_retry_after_is_preserved_and_redirect_is_not_followed():
    seen = []
    def limited(request):
        seen.append(request)
        return httpx.Response(429, headers={'Retry-After': '60'})
    with httpx.Client(transport=httpx.MockTransport(limited)) as client:
        assert lookup('10.1234/x', client=client).retry_after == 60
    assert len(seen) == 1
    seen.clear()
    def redirect(request):
        seen.append(request)
        return httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'})
    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        assert lookup('10.1234/x', client=client).status == 'failed'
    assert all(r.url.scheme == 'https' and r.url.host in {'citation.doi.org','api.crossref.org'} for r in seen)


def test_oversized_or_wrong_doi_replies_are_rejected():
    def respond(request): return httpx.Response(200, content=b' ' * (MAX_BYTES + 1))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert lookup('10.1234/x', client=client).value is None
    def wrong(request): return httpx.Response(200, json={'DOI': '10.1234/other', 'title': 'Other'})
    with httpx.Client(transport=httpx.MockTransport(wrong)) as client:
        assert lookup('10.1234/x', client=client).status == 'failed'
