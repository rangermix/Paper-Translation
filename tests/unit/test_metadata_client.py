import httpx
from packages.metadata.client import lookup, MAX_BYTES


def test_only_fixed_doi_endpoints_receive_encoded_identifier():
    seen = []
    def respond(request):
        seen.append(request)
        if request.url.host == 'citation.doi.org': return httpx.Response(404)
        return httpx.Response(200, json={'status': 'ok', 'message': {'DOI': '10.1234/a(b)', 'title': ['Controlled title']}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = lookup('10.1234/a(b)', client=client)
    assert result.status == 'succeeded' and result.service == 'crossref'
    assert [request.url.host for request in seen] == ['citation.doi.org', 'api.crossref.org']
    assert all(not request.content and 'authorization' not in request.headers for request in seen)
    assert seen[0].url.params['doi'] == '10.1234/a(b)'


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
