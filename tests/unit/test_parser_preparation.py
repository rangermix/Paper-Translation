"""Offline cache/model identity regressions, with no real weights or inference."""
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import pytest

from packages.ir import strict_loads
from packages.parsers.catalog import download_spec, public_models, vlm_lock
from packages.parsers.download import download
from packages.parsers.inspect import PDFError
from packages.parsers.model_service import Manager, create_app
from packages.parsers.profiles import DMR_PROFILES, PROFILE_IDS, SURYA_PROFILE, INFINITY_PRO_PROFILE


def spec(data=b'locked', path='weights/model.bin'):
    return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'url': 'https://huggingface.co/test/resolve/fixed/model'}


def test_all_requested_parsers_have_pinned_manifests_and_public_choices():
    rows = {r['id']: r for r in public_models()}
    assert set(rows) == set(PROFILE_IDS)
    assert len(vlm_lock()['models']) == 4
    for model in vlm_lock()['models']:
        assert len(model['revision']) == 40
        assert model['files'] and all(len(f['sha256']) == 64 and f['size'] > 0 for f in model['files'])
        assert rows[model['id']]['download_bytes'] == sum(f['size'] for f in model['files'])
        assert model['id'] in download_spec(model['id'])[0]['path'] or model['revision'] in download_spec(model['id'])[0]['path']
    assert rows[INFINITY_PRO_PROFILE]['devices'] == ['dmr']
    assert set(DMR_PROFILES) == set(PROFILE_IDS)


def test_health_and_listing_never_download_or_contact_runner(tmp_path):
    def reject(request):
        pytest.fail('Startup/listing must not contact a model or weight endpoint')
    app = create_app(tmp_path / 'absent', httpx.MockTransport(reject))
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        rows = client.get('/models').json()['models']
        assert len(rows) == 4 and all(row['status'] == 'not_downloaded' for row in rows)
    assert not (tmp_path / 'absent').exists()


@pytest.mark.parametrize('body', [b'wrong!', b'locked extra', b'short'])
def test_bad_download_never_replaces_files_or_leaves_parts(tmp_path, body):
    old = tmp_path / 'weights/model.bin'
    old.parent.mkdir()
    old.write_bytes(b'previous bytes')
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body))) as client:
        with pytest.raises(ValueError, match='HASH_MISMATCH'):
            download([spec()], tmp_path, client)
    assert old.read_bytes() == b'previous bytes'
    assert not list(tmp_path.rglob('*.part'))


def test_cache_reuses_verified_files_and_resumes_failed_preparation(tmp_path):
    requests = []
    def fetch(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=b'locked')
    with httpx.Client(transport=httpx.MockTransport(fetch)) as client:
        download([spec()], tmp_path, client)
        download([spec()], tmp_path, client)
    assert len(requests) == 1
    (tmp_path / 'weights/model.bin').write_bytes(b'tamper')
    with httpx.Client(transport=httpx.MockTransport(fetch)) as client:
        download([spec()], tmp_path, client)
    assert len(requests) == 2 and (tmp_path / 'weights/model.bin').read_bytes() == b'locked'


def test_parser_reports_corrupt_cache_as_hash_mismatch(tmp_path, monkeypatch):
    from packages.parsers.preparation import verify_cached_models
    target = tmp_path / 'weights/model.bin'
    target.parent.mkdir()
    target.write_bytes(b'tamper')
    monkeypatch.setattr('packages.parsers.preparation.download_spec', lambda _: [spec()])
    with pytest.raises(PDFError, match='PARSER_MODEL_HASH_MISMATCH'):
        verify_cached_models(SURYA_PROFILE, tmp_path)


@pytest.mark.parametrize('code', ['PARSER_DMR_BACKEND_UNAVAILABLE', 'PARSER_DMR_CONFIGURATION_FAILED'])
def test_parser_preserves_preparation_failure_code(tmp_path, monkeypatch, code):
    from types import SimpleNamespace
    from packages.parsers.preparation import prepare_models
    def fetch(request):
        return httpx.Response(202 if request.method == 'POST' else 200,
                             json={'status': 'failed', 'code': code})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(fetch), **kwargs))
    with pytest.raises(PDFError, match=code):
        prepare_models(SURYA_PROFILE, tmp_path, SimpleNamespace(device='dmr', backend='vllm'))


@pytest.mark.parametrize('profile', PROFILE_IDS)
@pytest.mark.parametrize('backend', ['vllm', 'mlx'])
def test_dmr_preparation_uses_allowed_engine_flags_and_exact_import(tmp_path, monkeypatch, profile, backend):
    from packages.parsers.catalog import vlm_model
    from packages.local_models.catalog import artifact
    model = vlm_model(profile)
    ident = artifact(model)['id']
    installed = False
    calls = []
    # Replay the real DMR flag rejection; this previously blocked every vLLM
    # parser after a successful download/import, before any page inference.
    allowed_flags = {'--gpu-memory-utilization', '--max-num-seqs', '--max-num-batched-tokens'}
    def fetch(request):
        nonlocal installed
        calls.append((request.method, request.url.path))
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm-metal test' if backend == 'mlx' else 'Running: vllm test'})
        if request.url.path == '/models/' + ident:
            return httpx.Response(200, json={'id': ident, 'config': {'format': 'safetensors'}}) if installed else httpx.Response(404)
        if request.url.path == '/models/load':
            assert request.content == b'synthetic pinned archive'
            installed = True
            return httpx.Response(200)
        if request.url.path == '/engines/vllm/_configure':
            body = strict_loads(request.content)
            assert body['model'] == ident
            assert body['context-size'] == model['context_size']
            assert body['keep_alive'] == '30s'
            flags = body['runtime-flags']
            if backend == 'mlx':
                assert flags == []
            if any(flag.startswith('--') and flag not in allowed_flags for flag in flags):
                return httpx.Response(500, text='runtime flag is not allowed for backend vllm')
            return httpx.Response(200)
        pytest.fail('Preparation must not request inference or contact another model: ' + str(request.url))
    monkeypatch.setattr('packages.parsers.model_service.download', lambda *args: None)
    monkeypatch.setattr('packages.local_models.download.archive', lambda *args: iter([b'synthetic pinned archive']))
    manager = Manager(tmp_path, httpx.MockTransport(fetch), dmr='http://runner')
    manager.states[(profile, backend)] = {'status': 'downloading'}
    manager._prepare(profile, backend)
    assert manager.state(profile, backend)['status'] == 'ready'
    assert manager.receipt(profile, backend).is_file()
    assert calls == [('GET', '/engines/status'), ('GET', '/engines/status'),
                     ('GET', '/models/' + ident), ('POST', '/models/load'),
                     ('GET', '/models/' + ident), ('POST', '/engines/vllm/_configure')]


def test_rejected_dmr_configuration_has_safe_failure_code_and_no_receipt(tmp_path, monkeypatch):
    from packages.parsers.catalog import vlm_model
    from packages.local_models.catalog import artifact
    ident = artifact(vlm_model(SURYA_PROFILE))['id']
    def fetch(request):
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm test'})
        if request.url.path == '/models/' + ident:
            return httpx.Response(200, json={'id': ident, 'config': {'format': 'safetensors'}})
        assert request.url.path == '/engines/vllm/_configure'
        return httpx.Response(500, text='untrusted backend detail containing private credentials')
    monkeypatch.setattr('packages.parsers.model_service.download', lambda *args: None)
    manager = Manager(tmp_path, httpx.MockTransport(fetch), dmr='http://runner')
    manager.states[(SURYA_PROFILE, 'vllm')] = {'status': 'downloading'}
    manager._prepare(SURYA_PROFILE, 'vllm')
    assert manager.state(SURYA_PROFILE) == {'status': 'failed', 'code': 'PARSER_DMR_CONFIGURATION_FAILED'}
    assert not manager.receipt(SURYA_PROFILE, 'vllm').exists()


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'bad\\path', 'link/file'])
def test_unsafe_cache_paths_fail_before_network(tmp_path, path):
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir(exist_ok=True)
    (tmp_path / 'link').symlink_to(outside, target_is_directory=True)
    with httpx.Client(transport=httpx.MockTransport(lambda req: pytest.fail('No unsafe download'))) as client:
        with pytest.raises(ValueError):
            download([spec(path=path)], tmp_path, client)
    assert not list(outside.iterdir())


def test_manager_commits_receipt_only_after_verified_download(tmp_path, monkeypatch):
    monkeypatch.setattr('packages.parsers.model_service.download_spec', lambda _: [spec()])
    manager = Manager(tmp_path, httpx.MockTransport(lambda req: httpx.Response(200, json={'vllm': 'Running: vllm test'}) if req.url.path == '/engines/status' else httpx.Response(200, content=b'locked')))
    monkeypatch.setattr(manager, 'prepare_dmr', lambda *args: None)
    manager.states[(SURYA_PROFILE, 'vllm')] = {'status': 'downloading'}
    manager._prepare(SURYA_PROFILE, 'vllm')
    assert manager.state(SURYA_PROFILE)['status'] == 'ready'
    assert strict_loads(manager.receipt(SURYA_PROFILE, 'vllm').read_bytes())['manifest_id']


def test_missing_dmr_engine_fails_before_weight_download(tmp_path, monkeypatch):
    requests = []
    def fetch(request):
        requests.append(str(request.url))
        assert request.url.path == '/engines/status'
        return httpx.Response(200, json={'vllm': 'not installed'})
    monkeypatch.setattr('packages.parsers.model_service.download_spec', lambda _: [spec()])
    manager = Manager(tmp_path, httpx.MockTransport(fetch), dmr='http://runner')
    manager.states[(SURYA_PROFILE, 'vllm')] = {'status': 'downloading'}
    manager._prepare(SURYA_PROFILE, 'vllm')
    assert manager.state(SURYA_PROFILE, 'vllm')['code'] == 'PARSER_DMR_BACKEND_UNAVAILABLE'
    assert requests == ['http://runner/engines/status']
    assert not list(tmp_path.glob('*.json'))


def test_prepare_rejects_custom_teleocr_dmr_without_network(tmp_path):
    app = create_app(tmp_path, httpx.MockTransport(lambda req: pytest.fail('No requests')))
    with TestClient(app) as client:
        assert client.post('/models/teleocr-v1/prepare?backend=vllm').status_code == 404
        assert client.post('/models/unknown/prepare').status_code == 404


def test_dmr_mode_records_exact_artifact_and_excludes_native_runtime(monkeypatch):
    from packages.parsers.runtime import runtime_config
    from packages.local_models.catalog import artifact
    from packages.parsers.catalog import vlm_model
    from packages.parsers.environment import detect_environment
    monkeypatch.setenv('PARSER_ACCELERATOR', 'dmr')
    monkeypatch.setenv('PARSER_IMAGE_FLAVOR', 'runner')
    monkeypatch.setenv('PARSER_DMR_URL', 'http://runner')
    runtime = runtime_config(SURYA_PROFILE)
    assert runtime.model_id == artifact(vlm_model(SURYA_PROFILE))['id']
    assert runtime.server_url == 'http://runner/engines/vllm/v1'
    env = detect_environment()
    assert env['options'][0]['profiles'] == list(DMR_PROFILES)
    assert len(env['options']) == 1
    with pytest.raises(ValueError, match='PROFILE_UNAVAILABLE'):
        runtime_config('teleocr-v1')
