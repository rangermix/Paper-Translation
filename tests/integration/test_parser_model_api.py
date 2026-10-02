"""Settings preparation controls with PostgreSQL and a synthetic local service."""
import httpx
import pytest

pytestmark = pytest.mark.postgres


def bridge(monkeypatch, wire):
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(wire), **kwargs))
    monkeypatch.setattr('packages.parsers.environment.read_environment', lambda *args: {
        'online': True, 'default': 'dmr', 'backend': 'vllm', 'options': [{'id': 'dmr', 'profiles': ['surya-ocr-2-v1']}]})


def test_model_listing_and_preference_save_never_prepare(client, monkeypatch):
    requests = []
    def wire(request):
        requests.append(request)
        assert request.method == 'GET' and request.url.path == '/models'
        return httpx.Response(200, json={'models': [{'id': 'surya-ocr-2-v1', 'status': 'not_downloaded'}]})
    bridge(monkeypatch, wire)
    listing = client.get('/api/v1/settings/parser-models')
    assert listing.status_code == 200 and len(listing.json()['models']) == 4
    before = client.get('/api/v1/settings/preferences')
    saved = client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'surya-ocr-2-v1'},
                         headers={'If-Match': before.headers['etag']})
    assert saved.status_code == 200
    assert len(requests) == 1


def test_explicit_prepare_is_idempotent_and_does_not_change_preferences(client, monkeypatch):
    requests = []
    def wire(request):
        requests.append(request)
        assert request.method == 'POST' and request.url.path == '/models/surya-ocr-2-v1/prepare'
        assert request.url.params['backend'] == 'vllm'
        assert request.content == b''
        return httpx.Response(202, json={'status': 'downloading', 'downloaded_bytes': 0, 'total_bytes': 1374048660})
    bridge(monkeypatch, wire)
    before = client.get('/api/v1/settings/preferences').json()
    body = {'parser_profile_revision': 'surya-ocr-2-v1'}
    headers = {'Idempotency-Key': 'prepare-parser-once'}
    first = client.post('/api/v1/settings/parser-models/prepare', json=body, headers=headers)
    replay = client.post('/api/v1/settings/parser-models/prepare', json=body, headers=headers)
    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json() and len(requests) == 1
    assert client.get('/api/v1/settings/preferences').json() == before


def test_unknown_parser_never_dispatches_to_download_service(client, monkeypatch):
    bridge(monkeypatch, lambda _: pytest.fail('Invalid model must not dispatch'))
    assert client.post('/api/v1/settings/parser-models/prepare', json={'parser_profile_revision': 'unknown'}).status_code == 422
    assert client.post('/api/v1/settings/parser-models/prepare', json={'parser_profile_revision': 'surya-ocr-2-v1',
        'endpoint': 'https://outside.example'}).status_code == 422
