"""Backend compatibility, routing and immutable configuration contracts.

Multi-engine fixtures describe a future reviewed adapter, not real GGUF/vLLM support.
"""
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from packages.domain.errors import DomainError
from packages.local_models import catalog, service
from tests.unit.test_local_translation_provider import profile


@pytest.fixture(autouse=True)
def deployment(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf,safetensors')
    monkeypatch.delenv('LOCAL_TRANSLATION_BACKENDS', raising=False)


@pytest.fixture
def multi_engine(monkeypatch):
    original = catalog.get_model('hy-mt2-1.8b-q4-k-m-gguf')
    model = copy.deepcopy(original)
    model['inference_backends'] = ['llama.cpp', 'vllm']
    monkeypatch.setattr(catalog, 'models', lambda: [model])
    return model


def test_catalog_compatibility_metadata_preserves_artifact_id():
    for model in catalog.models():
        legacy = {key: value for key, value in model.items() if key != 'inference_backends'}
        assert catalog.artifact(model) == catalog.artifact(legacy)
        assert catalog.select_backend(model) == model['runtime']
        assert len(set(model['inference_backends'])) == len(model['inference_backends'])
        assert all(catalog.select_backend(model, backend) == backend for backend in model['inference_backends'])


def test_declared_backends_are_independent_of_installed_engines(monkeypatch):
    assert catalog.configured_backends() == {'llama.cpp', 'vllm'}
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'vllm')
    assert catalog.configured_backends() == {'vllm'}
    assert catalog.configured_backends('llama.cpp,mlx') == {'llama.cpp', 'mlx'}
    for invalid in ('unknown', 'vllm,vllm', 'vllm,'):
        with pytest.raises(ValueError, match='LOCAL_MODEL_BACKENDS_INVALID'):
            catalog.configured_backends(invalid)


def test_unsupported_backend_is_rejected_before_network_or_download(tmp_path):
    calls = []
    model = catalog.get_model('hy-mt2-1.8b-q4-k-m-gguf')
    app = service.create_app(cache=tmp_path, transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, json={})))
    with TestClient(app) as client:
        for method, path, kwargs in [
            ('GET', f'/models/{model["id"]}?backend=vllm', {}),
            ('POST', f'/models/{model["id"]}/prepare?backend=vllm', {}),
            ('POST', '/v1/completions', {'json': {'model': catalog.artifact(model)['id'], 'backend': 'vllm',
                'messages': [{'role': 'user', 'content': 'Synthetic input.'}]}}),
        ]:
            result = client.request(method, path, **kwargs)
            assert result.status_code == 409
            assert result.json()['detail'] == 'LOCAL_MODEL_BACKEND_UNSUPPORTED'
    assert calls == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('backend,runner', [('llama.cpp', 'gguf-runner'), ('vllm', 'cuda-runner')])
def test_selected_backend_routes_prepare_status_and_inference_without_changing_artifact(tmp_path, multi_engine, backend, runner):
    model = multi_engine
    ident = catalog.artifact(model)['id']
    calls = []
    configured = False
    def handle(request):
        nonlocal configured
        calls.append(request)
        assert request.url.host == runner
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={backend: f'Running: {backend} synthetic'})
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id': ident}])
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': backend, 'ModelID': ident, 'Config': {
                'context-size': model['context_size'], 'runtime-flags': service.runtime_flags(model, backend)}}] if configured else [])
        if request.url.path == f'/engines/{backend}/_configure':
            body = json.loads(request.content)
            assert body['model'] == ident
            configured = True
            return httpx.Response(202)
        assert request.url.path == f'/engines/{backend}/v1/chat/completions'
        body = json.loads(request.content)
        assert body['model'] == ident and 'backend' not in body
        return httpx.Response(200, json={'model': ident, 'choices': [
            {'message': {'role': 'assistant', 'content': 'Synthetic output.'}}]})
    app = service.create_app(cache=tmp_path, transport=httpx.MockTransport(handle),
        gguf_dmr='http://gguf-runner:12434', vllm_dmr='http://cuda-runner:12434', backends='llama.cpp,vllm')
    manager = app.state.manager
    manager.states[manager.state_key(model, backend)] = {'status': 'loading'}
    manager._prepare(model, backend)
    with TestClient(app) as client:
        assert client.get(f'/models/{model["id"]}?backend={backend}').json()['status'] == 'ready'
        result = client.post('/v1/completions', json={'model': ident, 'backend': backend,
            'messages': [{'role': 'user', 'content': 'Synthetic input.'}], 'max_tokens': 32})
        assert result.status_code == 200 and result.json()['model'] == ident
    assert [request.url.path for request in calls if request.method == 'POST'] == [
        f'/engines/{backend}/_configure', f'/engines/{backend}/v1/chat/completions']
    assert not list(tmp_path.iterdir()) or all(path.name == '.lock' for path in tmp_path.iterdir())


def test_backend_states_do_not_mix_and_choices_survive_outage(tmp_path, multi_engine):
    app = service.create_app(cache=tmp_path, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={'llama.cpp': 'Not Installed', 'vllm': 'Not Installed'})), backends='llama.cpp,vllm')
    manager = app.state.manager
    manager.states[manager.state_key(multi_engine, 'vllm')] = {'status': 'loading'}
    with TestClient(app) as client:
        row = client.get('/models').json()['models'][0]
    assert row['inference_backends'] == ['llama.cpp', 'vllm']
    assert row['backend_states'] == {'llama.cpp': {'status': 'unavailable', 'code': 'LOCAL_GGUF_UNAVAILABLE'},
                                     'vllm': {'status': 'loading'}}


def test_platform_declaration_filters_options_but_rejects_incompatible_preparation(tmp_path, multi_engine):
    calls = []
    app = service.create_app(cache=tmp_path, backends='vllm', transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, json={})))
    with TestClient(app) as client:
        row = client.get('/models').json()['models'][0]
        assert row['inference_backends'] == ['vllm']
        before = len(calls)
        result = client.post(f'/models/{multi_engine["id"]}/prepare?backend=llama.cpp')
        assert result.status_code == 409
        assert len(calls) == before


def test_saved_backend_versions_and_task_snapshots_are_immutable(tmp_path, monkeypatch, multi_engine):
    from packages.domain.config import provider_profile
    from packages.jobs.history import config_snapshot
    from packages.providers.settings import configuration_view, save_configuration
    from packages.providers.local_translation import request_body
    from packages.providers.connection import TEST_UNIT
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'store'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(tmp_path / 'absent'))
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(tmp_path / 'absent-key'))
    p = profile(multi_engine['id'])
    first = save_configuration(p | {'local_backend': 'vllm'}, None, False, '"0"', 'first')
    old = provider_profile()
    bundle = tmp_path / 'store' / 'versions' / old['config_revision'] / 'profile.json'
    before = bundle.read_bytes()
    snapshot = config_snapshot('translate', {'workflow': {'profile': old | {'api_key': 'synthetic-secret'}}})
    second = save_configuration(p | {'local_backend': 'llama.cpp'}, None, False, '"1"', 'second')
    assert configuration_view()['local_backend'] == 'llama.cpp'
    assert first['profile_hash'] != second['profile_hash']
    assert bundle.read_bytes() == before
    assert snapshot['local_backend'] == 'vllm' and 'api_key' not in snapshot
    assert request_body([TEST_UNIT], old, [])['backend'] == 'vllm'
    assert 'backend' not in request_body([TEST_UNIT], p, [])
    assert save_configuration(p, None, False, '"2"', 'default')['local_backend'] == 'llama.cpp'


def test_reading_legacy_local_profile_does_not_rewrite_it(tmp_path, monkeypatch):
    from packages.domain.config import provider_profile
    from packages.ir import digest
    from packages.providers.settings import configuration_view
    p = profile('hy-mt2-1.8b-q4-k-m-gguf')
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps(p))
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'store'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(path))
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(tmp_path / 'absent-key'))
    before = path.read_bytes()
    assert configuration_view()['profile_hash'] == digest(provider_profile())
    assert 'local_backend' not in provider_profile()
    assert path.read_bytes() == before and not (tmp_path / 'store').exists()


@pytest.mark.parametrize('backend', ['vllm', 'mlx', 'unknown', ['llama.cpp']])
def test_saving_unsupported_backend_fails_before_storage(tmp_path, monkeypatch, backend):
    from packages.providers.settings import save_configuration
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'store'))
    with pytest.raises(DomainError) as error:
        save_configuration(profile('hy-mt2-1.8b-q4-k-m-gguf') | {'local_backend': backend}, None, False, '"0"', 'invalid')
    assert error.value.code == 'PROVIDER_CONFIG_INVALID'
    assert not (tmp_path / 'store').exists()


def test_external_protocol_cannot_persist_a_local_backend(tmp_path, monkeypatch):
    from packages.providers.settings import save_configuration
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'store'))
    external = profile() | {'api_protocol': 'chat_completions', 'provider': 'openai', 'auth_mode': 'none',
        'endpoint': 'http://synthetic.invalid/v1/chat/completions', 'model_id': 'synthetic-model', 'local_backend': 'llama.cpp'}
    with pytest.raises(DomainError) as error:
        save_configuration(external, None, False, '"0"', 'invalid')
    assert error.value.code == 'PROVIDER_CONFIG_INVALID'
    assert not (tmp_path / 'store').exists()


def test_prepare_api_binds_backend_to_query_and_idempotency_payload(monkeypatch):
    from apps.api import common, provider_settings
    model = catalog.get_model('hy-mt2-1.8b-bf16-vllm')
    calls = []
    original_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(202, json={'status': 'loading'})), **kwargs))
    monkeypatch.setattr(provider_settings, 'lock_lifecycle', lambda _: None)
    commands = []
    monkeypatch.setattr(common, 'command', lambda session, request, payload, execute, status:
        commands.append(payload) or execute())
    request = Request({'type': 'http'})
    assert provider_settings.prepare_local_model(model['id'], request, backend='vllm', session=object()) == {'status': 'loading'}
    assert calls[0].url.params['backend'] == 'vllm' and commands == [{'backend': 'vllm'}]
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'llama.cpp')
    with pytest.raises(DomainError) as error:
        provider_settings.prepare_local_model(model['id'], request, backend='vllm', session=object())
    assert error.value.code == 'LOCAL_MODEL_BACKEND_UNSUPPORTED' and len(calls) == 1


def test_provider_prepare_polls_the_same_backend_without_document_content(monkeypatch):
    from packages.providers import local_translation
    calls = []
    original_client = httpx.Client
    def handle(request):
        calls.append(request)
        assert request.url.params['backend'] == 'vllm'
        assert not request.content
        return httpx.Response(202 if request.method == 'POST' else 200,
                              json={'status': 'loading' if request.method == 'POST' else 'ready'})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(local_translation.time, 'sleep', lambda _: None)
    local_translation.LocalTranslation().prepare(profile('hy-mt2-1.8b-bf16-vllm') | {'local_backend': 'vllm'})
    assert [request.method for request in calls] == ['POST', 'GET']
