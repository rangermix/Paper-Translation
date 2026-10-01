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
from packages.parsers.profiles import DMR_PROFILES, PROFILE_IDS, SURYA_PROFILE, TELEOCR_PROFILE, INFINITY_PRO_PROFILE


def spec(data=b'locked', path='weights/model.bin'):
    return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'url': 'https://huggingface.co/test/resolve/fixed/model'}


def test_all_requested_parsers_have_pinned_manifests_and_public_choices():
    rows = {r['id']: r for r in public_models()}
    assert set(rows) == set(PROFILE_IDS)
    assert len(vlm_lock()['models']) == 6
    for model in vlm_lock()['models']:
        assert len(model['revision']) == 40
        assert model['files'] and all(len(f['sha256']) == 64 and f['size'] > 0 for f in model['files'])
        assert rows[model['id']]['download_bytes'] == sum(f['size'] for f in model['files'])
        assert model['id'] in download_spec(model['id'])[0]['path'] or model['revision'] in download_spec(model['id'])[0]['path']
    assert rows[INFINITY_PRO_PROFILE]['devices'] == ['dmr']
    assert TELEOCR_PROFILE not in DMR_PROFILES


def test_native_profiles_require_only_their_selected_dependencies():
    assert all('PaddlePaddle' not in s['path'] for s in download_spec('docling-v1'))
    assert all('ibm-granite' in s['path'] for s in download_spec('granite-docling-v1'))
    assert all('CodeFormula' not in s['path'] for s in download_spec('paddleocr-vl-1.6-v1'))


def test_health_and_listing_never_download_or_contact_runner(tmp_path):
    def reject(request):
        pytest.fail('Startup/listing must not contact a model or weight endpoint')
    app = create_app(tmp_path / 'absent', httpx.MockTransport(reject))
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        rows = client.get('/models').json()['models']
        assert len(rows) == 9 and all(row['status'] == 'not_downloaded' for row in rows)
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


def test_parser_preserves_preparation_failure_code(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from packages.parsers.preparation import prepare_models
    def fetch(request):
        return httpx.Response(202 if request.method == 'POST' else 200,
                             json={'status': 'failed', 'code': 'PARSER_DMR_BACKEND_UNAVAILABLE'})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(fetch), **kwargs))
    with pytest.raises(PDFError, match='PARSER_DMR_BACKEND_UNAVAILABLE'):
        prepare_models(SURYA_PROFILE, tmp_path, SimpleNamespace(device='dmr', backend='vllm'))


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
    manager = Manager(tmp_path, httpx.MockTransport(lambda req: httpx.Response(200, content=b'locked')))
    manager.states[(SURYA_PROFILE, 'native')] = {'status': 'downloading'}
    manager._prepare(SURYA_PROFILE, 'native')
    assert manager.state(SURYA_PROFILE)['status'] == 'ready'
    assert strict_loads(manager.receipt(SURYA_PROFILE, 'native').read_bytes())['manifest_id']


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
        assert client.post('/models/teleocr-v1/prepare?backend=vllm').status_code == 409
        assert client.post('/models/unknown/prepare').status_code == 404


def test_dmr_mode_records_exact_artifact_and_excludes_native_runtime(monkeypatch):
    from packages.parsers.runtime import runtime_config
    from packages.local_models.catalog import artifact
    from packages.parsers.catalog import vlm_model
    from packages.parsers.environment import detect_environment
    monkeypatch.setenv('PARSER_ACCELERATOR', 'dmr')
    monkeypatch.setenv('PARSER_IMAGE_FLAVOR', 'runner')
    monkeypatch.setenv('PARSER_DMR_URL', 'http://runner')
    monkeypatch.setattr('packages.parsers.environment.cuda_probe', lambda *args: {'available': False})
    runtime = runtime_config(SURYA_PROFILE)
    assert runtime.model_id == artifact(vlm_model(SURYA_PROFILE))['id']
    assert runtime.server_url == 'http://runner/engines/vllm/v1'
    env = detect_environment()
    assert env['options'][0]['profiles'] == []
    assert env['options'][3]['profiles'] == list(DMR_PROFILES)
    with pytest.raises(ValueError, match='BACKEND_UNSUPPORTED'):
        runtime_config(TELEOCR_PROFILE)


@pytest.mark.parametrize('accelerator', ['cpu', 'cuda'])
def test_teleocr_uses_pinned_environment_in_both_native_modes(monkeypatch, accelerator):
    from packages.parsers.runtime import child_executable
    monkeypatch.setattr(Path, 'is_file', lambda path: str(path) == '/app/.venv-tele/bin/python')
    assert child_executable(TELEOCR_PROFILE, accelerator) == '/app/.venv-tele/bin/python'
    monkeypatch.setattr(Path, 'is_file', lambda _: False)
    with pytest.raises(PDFError, match='PARSER_TELEOCR_ENVIRONMENT_REQUIRED'):
        child_executable(TELEOCR_PROFILE, accelerator)
