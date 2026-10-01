import httpx
import pytest
from fastapi.testclient import TestClient

from packages.local_models.catalog import artifact, get_model, models


@pytest.fixture(autouse=True)
def all_deployment_formats(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf,mlx,safetensors')


def test_catalog_get_does_not_download_and_unknown_post_is_rejected(tmp_path):
    from packages.local_models.service import create_app
    def handle(request):
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm-metal test',
                                             'llama.cpp': 'Running: llama.cpp test'})
        return httpx.Response(200, json=[])
    app = create_app(cache=tmp_path, transport=httpx.MockTransport(handle))
    with TestClient(app) as client:
        response = client.get('/models')
        assert response.status_code == 200
        assert len(response.json()['models']) == 10
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


def test_paddle_tag_resolves_to_explicit_owned_artifact(tmp_path, monkeypatch):
    from packages.local_models.service import Manager
    import json
    paddle = 'sha256:' + 'a' * 64
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', paddle)
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == '/engines/ps':
            return httpx.Response(200, json=[{'backend_name':'vllm','model_name':'docker.io/local/paddle:latest'}])
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id':paddle,'tags':['docker.io/local/paddle:latest']}])
        assert json.loads(request.content)['models'] == [paddle]
        return httpx.Response(200, json={'unloaded_runners':1})
    Manager(tmp_path,httpx.MockTransport(handle)).reserve_gpu(models()[0])
    assert calls[-1].method == 'POST'


def test_gpu_handoff_does_not_proceed_when_model_became_active(tmp_path):
    from packages.local_models.service import Manager
    import pytest
    other = artifact(models()[1])['id']
    def handle(request):
        return httpx.Response(200, json=[{'backend_name':'vllm','model_name':other}] if request.method=='GET' else {'unloaded_runners':0})
    with pytest.raises(ValueError, match='LOCAL_MODEL_BUSY'):
        Manager(tmp_path,httpx.MockTransport(handle)).reserve_gpu(models()[0])


def test_prepare_ready_model_does_not_interrupt_concurrent_inference(tmp_path):
    from packages.local_models.service import Manager, RUNTIME_FLAGS
    model = models()[0]; ident = artifact(model)['id']; calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == '/models': return httpx.Response(200, json=[{'id': ident}])
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm-metal test'})
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': 'vllm', 'ModelID': ident,
                'Config': {'context-size': model['context_size'], 'runtime-flags': RUNTIME_FLAGS}}])
        raise AssertionError(request.url.path)
    manager = Manager(tmp_path, httpx.MockTransport(handle))
    manager.states[model['id']] = {'status': 'ready'}
    # An active inference owns this lock. Same-model preparation must leave
    # readiness intact and must not enqueue another configuration operation.
    with manager.inference_lock:
        assert manager.prepare(model)['status'] == 'ready'
        assert manager.state(model)['status'] == 'ready'
    assert all(request.method == 'GET' for request in calls)
    assert any(request.url.path == '/engines/_configure' for request in calls)


def test_deployment_capability_is_separate_from_backend_installation(tmp_path):
    from packages.local_models.service import create_app
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        'vllm': 'Not Installed', 'llama.cpp': 'Not Installed'} if r.url.path == '/engines/status' else []))
    with TestClient(create_app(cache=tmp_path, transport=transport, formats='gguf')) as client:
        rows = client.get('/models').json()['models']
        assert [row['format'] for row in rows] == ['gguf'] * 5
        assert all(row['status'] == 'unavailable' for row in rows)
        assert client.post('/models/hy-mt2-1.8b-q8/prepare').status_code == 409
    with TestClient(create_app(cache=tmp_path, transport=transport, formats='safetensors')) as client:
        rows = client.get('/models').json()['models']
        assert [row['id'] for row in rows] == ['hy-mt2-1.8b-bf16-vllm']
        assert rows[0]['status'] == 'unavailable'


def test_format_defaults_and_explicit_deployment_capabilities(monkeypatch):
    from packages.local_models.service import configured_formats
    monkeypatch.delenv('LOCAL_TRANSLATION_FORMATS')
    monkeypatch.delenv('PADDLE_MLX_MODEL_ID', raising=False)
    assert configured_formats() == {'gguf'}
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', 'sha256:' + 'a' * 64)
    assert configured_formats() == {'gguf', 'mlx'}
    assert configured_formats('gguf,safetensors') == {'gguf', 'safetensors'}
    with pytest.raises(ValueError, match='LOCAL_MODEL_FORMATS_INVALID'):
        configured_formats('gguf,unknown')


@pytest.mark.parametrize('slug,status,code', [
    ('hy-mt2-1.8b-q4-k-m-gguf',
     'Error: failed to check CUDA 11 capability: fork/exec C:\\Users\\synthetic\\.docker\\bin\\inference\\com.docker.nv-gpu-info.exe: The system cannot find the file specified.',
     'LOCAL_CUDA_PROBE_MISSING'),
    ('hy-mt2-1.8b-q4-k-m-gguf',
     'Error: failed to check CUDA 11 capability: com.docker.nv-gpu-info.exe: Access is denied.',
     'LOCAL_GGUF_UNAVAILABLE'),
    ('hy-mt2-1.8b-bf16-vllm', 'Not Installed: only supported on Linux',
     'LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED'),
])
def test_backend_failures_have_bounded_actionable_codes(tmp_path, slug, status, code):
    from packages.local_models.service import create_app, engine
    model = get_model(slug); calls = []
    def handle(request):
        calls.append(request)
        assert request.url.path == '/engines/status'
        return httpx.Response(200, json={engine(model): status})
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(handle))) as client:
        rows = client.get('/models').json()['models']
    row = next(row for row in rows if row['id'] == slug)
    assert row['status'] == 'unavailable' and row['code'] == code
    assert all(request.method == 'GET' for request in calls)
    assert 'synthetic' not in str(rows)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('slug', [
    'milmmt-46-1b-q4-k-m-gguf', 'milmmt-46-4b-q4-k-m-gguf', 'milmmt-46-12b-q4-k-m-gguf',
])
def test_milmmt_gguf_uses_native_completion_without_chat_template(tmp_path, slug):
    from packages.local_models.service import create_app
    model = get_model(slug); ident = artifact(model)['id']; sent = []
    prompt = 'Translate this from English to Chinese (Simplified):\nEnglish: Hello.\nChinese (Simplified):'
    def handle(request):
        sent.append(request)
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'llama.cpp': 'Running: llama.cpp test'})
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id': ident}])
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': 'llama.cpp', 'ModelID': ident,
                'Config': {'context-size': model['context_size'], 'runtime-flags': []}}])
        assert request.url.path == '/engines/llama.cpp/v1/completions'
        import json
        payload = json.loads(request.content)
        assert payload['prompt'] == prompt and payload['model'] == ident
        assert payload['add_special_tokens'] is False and 'messages' not in payload
        return httpx.Response(200, json={'model': ident, 'choices': [{'text': '你好。', 'finish_reason': 'stop'}]})
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(handle), formats='gguf')) as client:
        result = client.post('/v1/completions', json={'model': ident, 'prompt': prompt, 'max_tokens': 32})
    assert result.status_code == 200
    assert result.json()['model'] == ident
    assert [request.method for request in sent].count('POST') == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('slug,backend,expected_path', [
    ('hy-mt2-1.8b-q4-k-m-gguf', 'llama.cpp', '/engines/llama.cpp/v1/chat/completions'),
    ('hy-mt2-1.8b-bf16-vllm', 'vllm', '/engines/vllm/v1/chat/completions'),
])
def test_non_mlx_translation_routes_to_exact_engine(tmp_path, slug, backend, expected_path):
    from packages.local_models.service import RUNTIME_FLAGS, create_app
    model = get_model(slug); ident = artifact(model)['id']; sent = []
    def handle(request):
        sent.append(request)
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={backend: 'Running: ' + backend + ' test'})
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id': ident}])
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': backend, 'ModelID': ident,
                'Config': {'context-size': 8192, 'runtime-flags': RUNTIME_FLAGS if backend == 'vllm' else []}}])
        if request.url.path == expected_path:
            return httpx.Response(200, json={'id': 'local-test', 'model': ident,
                'choices': [{'message': {'role': 'assistant', 'content': '你好。'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 3}})
        raise AssertionError(request.url.path)
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(handle),
                               formats='gguf,safetensors')) as client:
        response = client.post('/v1/completions', json={'model': ident,
            'messages': [{'role': 'user', 'content': 'Translate Hello.'}], 'max_tokens': 32})
    assert response.status_code == 200, response.text
    assert response.json()['choices'][0]['text'] == '你好。'
    assert response.json()['model'] == ident
    assert any(request.url.path == expected_path for request in sent)


def test_gguf_artifact_uses_gguf_layer_and_fixed_quantization():
    import json
    model = get_model('hy-mt2-1.8b-q4-k-m-gguf')
    package = artifact(model)
    config, manifest = json.loads(package['config']), json.loads(package['manifest'])
    assert config['config']['format'] == 'gguf'
    assert config['config']['quantization'] == 'Q4_K_M'
    assert manifest['layers'][0]['mediaType'] == 'application/vnd.docker.ai.gguf.v3'
    assert manifest['layers'][0]['digest'] == 'sha256:' + model['files'][0]['sha256']


def test_separate_cuda_runner_catalog_preserves_native_gguf_and_mlx(tmp_path):
    from packages.local_models.service import create_app
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == '/engines/status':
            statuses = ({'vllm': 'Running: vllm 0.19.1'} if request.url.host == 'vllm-runner' else
                        {'vllm': 'Running: vllm-metal test', 'llama.cpp': 'Running: llama.cpp cuda'})
            return httpx.Response(200, json=statuses)
        assert request.url.path == '/models'
        return httpx.Response(200, json=[])
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(handle),
                              vllm_dmr='http://vllm-runner:12434/')) as client:
        rows = client.get('/models').json()['models']
    assert len(rows) == 10 and all(row['status'] == 'not_downloaded' for row in rows)
    assert {r.url.host for r in calls if r.url.path == '/engines/status'} == {
        'model-runner.docker.internal', 'vllm-runner'}
    assert sum(r.url.path == '/engines/status' for r in calls) == 2
    assert all(r.method == 'GET' for r in calls) and not list(tmp_path.iterdir())


def test_cuda_runner_outage_does_not_hide_catalog_or_redirect_to_native(tmp_path):
    from packages.local_models.service import create_app
    def handle(request):
        if request.url.host == 'vllm-runner':
            raise httpx.ConnectError('synthetic CUDA runner outage')
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'llama.cpp': 'Running: llama.cpp cuda'})
        return httpx.Response(200, json=[])
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(handle), formats='gguf,safetensors',
                              vllm_dmr='http://vllm-runner:12434')) as client:
        rows = client.get('/models').json()['models']
    assert len(rows) == 6
    assert next(row for row in rows if row['runtime'] == 'vllm')['code'] == 'LOCAL_VLLM_UNAVAILABLE'
    assert all(row['status'] == 'not_downloaded' for row in rows if row['runtime'] == 'llama.cpp')


def test_cuda_prepare_and_inference_use_same_explicit_runner_and_exact_model(tmp_path):
    from packages.local_models.service import Manager, RUNTIME_FLAGS, create_app
    model = get_model('hy-mt2-1.8b-bf16-vllm'); ident = artifact(model)['id']; calls = []
    configured = False
    def handle(request):
        nonlocal configured
        import json
        calls.append(request)
        assert request.url.host == 'vllm-runner' and request.url.port == 12434
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm 0.19.1'})
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id': ident}])
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': 'vllm', 'ModelID': ident,
                'Config': {'context-size': 8192, 'runtime-flags': RUNTIME_FLAGS}}] if configured else [])
        if request.url.path == '/engines/vllm/_configure':
            assert json.loads(request.content)['model'] == ident
            configured = True
            return httpx.Response(202)
        assert request.url.path == '/engines/vllm/v1/chat/completions'
        assert json.loads(request.content)['model'] == ident
        return httpx.Response(200, json={'model': ident, 'choices': [
            {'message': {'role': 'assistant', 'content': 'synthetic translation'}}]})
    transport = httpx.MockTransport(handle)
    manager = Manager(tmp_path, transport, vllm_dmr='http://vllm-runner:12434')
    manager.states[model['id']] = {'status': 'loading'}
    manager._prepare(model)
    assert manager.states[model['id']]['status'] == 'ready'
    with TestClient(create_app(cache=tmp_path, transport=transport,
                              vllm_dmr='http://vllm-runner:12434')) as client:
        response = client.post('/v1/completions', json={'model': ident,
            'messages': [{'role': 'user', 'content': 'Synthetic test input.'}], 'max_tokens': 32})
    assert response.status_code == 200 and response.json()['model'] == ident
    assert response.json()['choices'][0]['text'] == 'synthetic translation'
    assert [r.url.path for r in calls if r.method == 'POST'] == [
        '/engines/vllm/_configure', '/engines/vllm/v1/chat/completions']
    assert all(path.name == '.lock' for path in tmp_path.iterdir())


def test_gguf_import_prepare_and_inference_use_explicit_runner(tmp_path, monkeypatch):
    import json
    from packages.local_models import service
    model = get_model('hy-mt2-7b-q4-k-m-gguf'); ident = artifact(model)['id']
    calls = []; installed = False; configured = False
    monkeypatch.setattr(service, 'download', lambda *args: None)
    monkeypatch.setattr(service, 'archive', lambda *args: iter([b'synthetic model archive']))
    def handle(request):
        nonlocal installed, configured
        calls.append(request)
        assert request.url.host == 'gguf-runner' and request.url.port == 12434
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'llama.cpp': 'Running: llama.cpp cuda'})
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id': ident}] if installed else [])
        if request.url.path == '/models/load':
            assert request.content == b'synthetic model archive'
            installed = True
            return httpx.Response(200)
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': 'llama.cpp', 'ModelID': ident,
                'Config': {'context-size': 8192, 'runtime-flags': []}}] if configured else [])
        if request.url.path == '/engines/llama.cpp/_configure':
            assert json.loads(request.content)['model'] == ident
            configured = True
            return httpx.Response(202)
        assert request.url.path == '/engines/llama.cpp/v1/chat/completions'
        assert json.loads(request.content)['model'] == ident
        return httpx.Response(200, json={'model': ident, 'choices': [
            {'message': {'role': 'assistant', 'content': 'synthetic translation'}}]})
    transport = httpx.MockTransport(handle)
    manager = service.Manager(tmp_path, transport, gguf_dmr='http://gguf-runner:12434/')
    manager.states[model['id']] = {'status': 'loading'}
    manager._prepare(model)
    assert manager.states[model['id']]['status'] == 'ready'
    with TestClient(service.create_app(cache=tmp_path, transport=transport,
                                      gguf_dmr='http://gguf-runner:12434')) as client:
        response = client.post('/v1/completions', json={'model': ident,
            'messages': [{'role': 'user', 'content': 'Synthetic test input.'}], 'max_tokens': 32})
    assert response.status_code == 200 and response.json()['model'] == ident
    assert [r.url.path for r in calls if r.method == 'POST'] == [
        '/models/load', '/engines/llama.cpp/_configure', '/engines/llama.cpp/v1/chat/completions']


def test_explicit_gguf_runner_outage_never_falls_back_to_native(tmp_path):
    from packages.local_models.service import create_app
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.host == 'gguf-runner'
        raise httpx.ConnectError('synthetic Runner outage')
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(handle), formats='gguf',
                              gguf_dmr='http://gguf-runner:12434')) as client:
        rows = client.get('/models').json()['models']
        ident = rows[0]['model_id']
        response = client.post('/v1/completions', json={'model': ident,
            'messages': [{'role': 'user', 'content': 'Synthetic test input.'}]})
    assert len(rows) == 5 and all(row['code'] == 'LOCAL_GGUF_UNAVAILABLE' for row in rows)
    assert response.status_code == 503
    assert all(request.method == 'GET' for request in calls)


@pytest.mark.parametrize('failure', ['http_error', 'timeout'])
def test_model_import_failure_is_distinct_from_weight_download(tmp_path, monkeypatch, failure):
    from packages.local_models import service
    model = get_model('hy-mt2-7b-q4-k-m-gguf')
    monkeypatch.setattr(service, 'download', lambda *args: None)
    monkeypatch.setattr(service, 'archive', lambda *args: iter([b'synthetic cached weights']))
    def handle(request):
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'llama.cpp': 'Running: llama.cpp cuda'})
        if request.url.path == '/models':
            return httpx.Response(200, json=[])
        assert request.url.path == '/models/load'
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic model import timeout')
        return httpx.Response(500, text='missing blob; private upstream diagnostics')
    manager = service.Manager(tmp_path, httpx.MockTransport(handle))
    manager.states[model['id']] = {'status': 'loading'}
    manager._prepare(model)
    assert manager.states[model['id']] == {'status': 'failed', 'code': 'LOCAL_MODEL_LOAD_FAILED'}


@pytest.mark.parametrize('url', ['ftp://runner', 'http://user:secret@runner',
                               'http://runner?key=secret', 'http://runner#fragment'])
def test_explicit_gguf_runner_url_is_validated(tmp_path, url):
    from packages.local_models.service import Manager
    with pytest.raises(ValueError, match='LOCAL_MODEL_RUNNER_URL_INVALID'):
        Manager(tmp_path, gguf_dmr=url)


def test_gguf_runner_environment_does_not_change_other_formats(tmp_path, monkeypatch):
    from packages.local_models.service import DMR, Manager
    monkeypatch.setenv('LOCAL_GGUF_DMR_URL', 'http://gguf-runner:12434/')
    manager = Manager(tmp_path, vllm_dmr='http://vllm-runner:12434')
    assert manager.runner(get_model('hy-mt2-7b-q4-k-m-gguf')) == 'http://gguf-runner:12434'
    assert manager.runner(get_model('hy-mt2-1.8b-bf16-vllm')) == 'http://vllm-runner:12434'
    assert manager.runner(models()[0]) == DMR
