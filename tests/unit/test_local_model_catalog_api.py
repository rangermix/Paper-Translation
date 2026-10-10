import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.provider_settings import router
from packages.local_models.catalog import public_models


def catalog_client(monkeypatch, handler):
    from apps.api.common import session_dependency
    from types import SimpleNamespace
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[session_dependency] = lambda: SimpleNamespace(scalars=lambda _: [])
    client = TestClient(app)
    original_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs:
        original_client(transport=httpx.MockTransport(handler), **kwargs))
    return client


@pytest.mark.parametrize('formats,families,count', [
    ('gguf', {'hy', 'milmmt'}, 5),
    ('gguf,mlx', {'hy', 'milmmt'}, 9),
    ('gguf,safetensors', {'hy', 'milmmt'}, 6),
])
def test_service_outage_keeps_platform_supported_catalog(monkeypatch, formats, families, count):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', formats)
    calls = []
    def unavailable(request):
        calls.append(request)
        raise httpx.ConnectError('synthetic stopped sidecar', request=request)
    with catalog_client(monkeypatch, unavailable) as client:
        result = client.get('/api/v1/settings/local-models')
    assert result.status_code == 200
    body = result.json()
    assert body['code'] == 'LOCAL_MODEL_SERVICE_UNAVAILABLE'
    assert len(body['models']) == count
    assert {row['family'] for row in body['models']} == families
    assert {row['format'] for row in body['models']} == set(formats.split(','))
    expected = [row for row in public_models() if row['format'] in formats.split(',')]
    for row, pinned in zip(body['models'], expected, strict=True):
        state = {'status': 'unavailable', 'code': body['code']}
        assert row == {**pinned, **state, 'backend_states': {backend: state for backend in pinned['inference_backends']}}
    assert len(calls) == 1
    assert calls[0].method == 'GET' and calls[0].url.path == '/models'


def test_runtime_state_cannot_replace_pinned_catalog_metadata(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf')
    pinned = next(row for row in public_models() if row['format'] == 'gguf')
    runtime = {**pinned, 'model_id': 'untrusted', 'repo': 'untrusted', 'family': 'untrusted',
               'status': 'ready', 'backend': 'llama.cpp', 'downloaded_bytes': 10, 'total_bytes': 10}
    with catalog_client(monkeypatch, lambda _: httpx.Response(200, json={'models': [runtime]})) as client:
        body = client.get('/api/v1/settings/local-models').json()
    assert 'code' not in body
    state = {'status': 'ready', 'backend': 'llama.cpp', 'downloaded_bytes': 10, 'total_bytes': 10}
    assert body['models'][0] == {**pinned, **state, 'backend_states': {'llama.cpp': state}}
    assert body['models'][1]['status'] == 'unavailable'
    assert body['models'][1]['code'] == 'LOCAL_MODEL_FORMAT_UNSUPPORTED'


@pytest.mark.parametrize('formats,count', [('gguf', 1), ('gguf,mlx', 2)])
def test_outage_preserves_separate_analysis_catalog(monkeypatch, formats, count):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', formats)
    calls = []
    def unavailable(request):
        calls.append(request)
        raise httpx.ConnectError('synthetic stopped sidecar', request=request)
    with catalog_client(monkeypatch, unavailable) as client:
        body = client.get('/api/v1/settings/local-models?purpose=analysis').json()
    assert len(body['models']) == count
    assert all(row['family'] == 'minicpm5' for row in body['models'])
    assert calls[0].url.params['purpose'] == 'analysis'


def test_invalid_sidecar_response_does_not_hide_catalog(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf')
    with catalog_client(monkeypatch, lambda _: httpx.Response(200, json={'models': None})) as client:
        body = client.get('/api/v1/settings/local-models').json()
    assert len(body['models']) == 5
    assert body['code'] == 'LOCAL_MODEL_SERVICE_UNAVAILABLE'


def test_backend_state_is_whitelisted_and_cannot_add_model_compatibility(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf')
    pinned = next(row for row in public_models() if row['format'] == 'gguf')
    state = {'status': 'unavailable', 'code': 'LOCAL_GGUF_UNAVAILABLE'}
    runtime = {**pinned, 'inference_backends': ['llama.cpp', 'vllm'], 'default_backend': 'vllm',
               'backend_states': {'llama.cpp': {**state, 'repo': 'untrusted', 'local_backend': 'vllm'},
                                  'vllm': {'status': 'ready'}}}
    with catalog_client(monkeypatch, lambda _: httpx.Response(200, json={'models': [runtime]})) as client:
        row = client.get('/api/v1/settings/local-models').json()['models'][0]
    assert row['default_backend'] == 'llama.cpp' and row['inference_backends'] == ['llama.cpp']
    assert row['backend_states'] == {'llama.cpp': state}


def test_backend_capability_declaration_is_applied_even_during_outage(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf,safetensors')
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'llama.cpp')
    def unavailable(request):
        raise httpx.ConnectError('synthetic outage', request=request)
    with catalog_client(monkeypatch, unavailable) as client:
        rows = client.get('/api/v1/settings/local-models').json()['models']
    assert all(row['inference_backends'] == ['llama.cpp'] for row in rows if row['format'] == 'gguf')
    safetensors = next(row for row in rows if row['format'] == 'safetensors')
    assert safetensors['inference_backends'] == [] and safetensors['backend_states'] == {}
