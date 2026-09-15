import httpx
from fastapi.testclient import TestClient

from packages.local_models.catalog import artifact, models


def test_catalog_get_does_not_download_and_unknown_post_is_rejected(tmp_path):
    from packages.local_models.service import create_app
    app = create_app(cache=tmp_path)
    with TestClient(app) as client:
        response = client.get('/models')
        assert response.status_code == 200
        assert len(response.json()['models']) == 4
        assert list(tmp_path.iterdir()) == []
        assert client.post('/models/arbitrary/prepare').status_code == 404


def test_inference_never_downloads_or_falls_back(tmp_path):
    from packages.local_models.service import create_app
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json=[]))
    with TestClient(create_app(cache=tmp_path, transport=transport)) as client:
        response = client.post('/v1/completions', json={'model': artifact(models()[0])['id'],
            'messages': [{'role': 'user', 'content': 'Translate Hello.'}], 'max_tokens': 32})
    assert response.status_code == 503
    assert not any(r.method == 'POST' for r in calls)


def test_forwarding_returns_actual_model_and_rejects_upstream_redirect(tmp_path):
    from packages.local_models.service import create_app
    model = models()[0]; ident = artifact(model)['id']; sent = []
    def handle(request):
        sent.append(request)
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id': ident}])
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm-metal test'})
        if request.url.path == '/engines/ps': return httpx.Response(200, json=[])
        if request.url.path == '/engines/_configure':
            from packages.local_models.service import RUNTIME_FLAGS
            return httpx.Response(200, json=[{'Backend':'vllm','ModelID':ident,'Config':{'context-size':8192,'runtime-flags':RUNTIME_FLAGS}}])
        return httpx.Response(302, headers={'location': 'https://evil.example'})
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(handle))) as client:
        response = client.post('/v1/completions', json={'model': ident,
            'messages': [{'role': 'user', 'content': 'Hello.'}], 'max_tokens': 32})
    assert response.status_code == 502
    assert all(r.url.host == 'model-runner.docker.internal' for r in sent)


def test_prepare_accepts_dmr_202_and_rejects_conflicting_configuration(tmp_path):
    from packages.local_models.service import Manager
    model = models()[0]; ident = artifact(model)['id']
    def transport(code):
        def handle(request):
            if request.url.path == '/models':
                return httpx.Response(200, json=[{'id': ident}])
            if request.url.path == '/engines/status':
                return httpx.Response(200, json={'vllm': 'Running: vllm-metal test'})
            if request.method == 'GET':
                return httpx.Response(200, json=[])
            return httpx.Response(code)
        return httpx.MockTransport(handle)
    for code, status in [(202, 'ready'), (409, 'failed')]:
        manager = Manager(tmp_path, transport(code))
        manager.states[model['id']] = {'status': 'loading'}
        manager._prepare(model)
        assert manager.states[model['id']]['status'] == status


def test_configuration_failure_before_inference_is_known_unsent(tmp_path):
    from packages.local_models.service import create_app
    model = models()[0]; ident = artifact(model)['id']; posts = []
    def handle(request):
        if request.method == 'POST': posts.append(request)
        if request.url.path == '/models': return httpx.Response(200, json=[{'id': ident}])
        if request.url.path == '/engines/status': return httpx.Response(200, json={'vllm':'Running: vllm-metal test'})
        raise httpx.ReadTimeout('synthetic configuration GET timeout')
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(handle))) as client:
        response = client.post('/v1/completions', json={'model':ident, 'messages':[{'role':'user','content':'Hello'}]})
    assert response.status_code == 503
    assert posts == []


def test_gpu_switch_retires_only_idle_owned_models(tmp_path):
    from packages.local_models.service import Manager
    import pytest
    first, second = models()[:2]; calls = []; current = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=current if request.method == 'GET' else {'unloaded_runners':1})
    manager = Manager(tmp_path, httpx.MockTransport(handle))
    current.append({'backend_name':'vllm','model_name':artifact(second)['id'], 'in_use':True})
    with pytest.raises(ValueError, match='LOCAL_MODEL_BUSY'): manager.reserve_gpu(first)
    assert all(r.method == 'GET' for r in calls)
    current[0]['in_use'] = False
    manager.reserve_gpu(first)
    assert calls[-1].method == 'POST' and calls[-1].url.path == '/engines/unload'
    current[0]['model_name'] = 'unrelated-user-model'
    with pytest.raises(ValueError, match='LOCAL_MODEL_BUSY'): manager.reserve_gpu(first)
    assert calls[-1].method == 'GET'


def test_translation_backend_cache_cap_is_scoped(tmp_path, monkeypatch):
    import importlib.util, json, shutil
    from pathlib import Path
    path = tmp_path / 'translation_startup.py'
    shutil.copyfile('deployment/local-translation-backend/translation_startup.py', path)
    ident = artifact(models()[0])['id']
    path.with_name('translation_model_ids.json').write_text(json.dumps([ident]))
    spec = importlib.util.spec_from_file_location('test_translation_startup', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    cap = module.bounded_cache_budget
    assert cap(ident, 8192, 16, 1024, 9999999) == 513 * 1024
    assert cap(ident, 8192, 16, 1024, 100) == 100
    assert cap('paddle-artifact', 8192, 16, 1024, 9999999) == 9999999
