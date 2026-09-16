import time
from pathlib import Path

import pytest

from packages.ir import canonical_bytes
from packages.parsers.profiles import PADDLE_PROFILE


def test_detection_distinguishes_installed_image_and_attached_gpu(monkeypatch):
    from packages.parsers import environment as env
    monkeypatch.setattr(env, 'cuda_probe', lambda executable, framework: {'available': framework == 'torch', 'name': 'Test GPU'})
    result = env.detect_environment()
    assert result['options'][0]['profiles'] == ['docling-v1', 'granite-docling-v1', PADDLE_PROFILE]
    assert result['options'][1]['profiles'] == ['docling-v1', 'granite-docling-v1']
    assert result['options'][2]['profiles'] == []


def test_report_expires_and_selection_fails_closed(tmp_path):
    from packages.parsers.environment import read_environment, resolve_accelerator
    report = {'detected_at': time.time(), 'default': 'cpu', 'options': [
        {'id': 'cpu', 'profiles': [PADDLE_PROFILE]}, {'id': 'cuda', 'profiles': []}]}
    heartbeat = {'timestamp': time.time(), 'models_verified': True, 'environment': report}
    (tmp_path / 'heartbeat.json').write_bytes(canonical_bytes(heartbeat))
    assert read_environment(tmp_path)['online'] is True
    assert resolve_accelerator({'parser_accelerator': 'cpu'}, PADDLE_PROFILE, tmp_path) == 'cpu'
    with pytest.raises(ValueError, match='PARSER_ACCELERATOR_UNAVAILABLE'):
        resolve_accelerator({'parser_accelerator': 'cuda'}, PADDLE_PROFILE, tmp_path)
    heartbeat['timestamp'] -= 91
    (tmp_path / 'heartbeat.json').write_bytes(canonical_bytes(heartbeat))
    assert read_environment(tmp_path)['online'] is False
    with pytest.raises(ValueError):
        resolve_accelerator({'parser_accelerator': 'cpu'}, PADDLE_PROFILE, tmp_path)
    # Old deployments without reports preserve their default until upgraded.
    assert resolve_accelerator({}, PADDLE_PROFILE, tmp_path) is None


def test_job_runtime_override_does_not_mutate_parent_environment(monkeypatch):
    from packages.parsers.runtime import runtime_config
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cuda')
    assert runtime_config(PADDLE_PROFILE, 'cpu').device == 'cpu'
    assert runtime_config(PADDLE_PROFILE).device == 'cuda:0'


@pytest.mark.parametrize('options', [[{}], [None], [{'id': 'cpu', 'profiles': 'docling-v1'}], [{'id': 'unknown', 'profiles': []}]])
def test_malformed_capabilities_fail_closed(tmp_path, options):
    from packages.parsers.environment import read_environment
    body = {'timestamp': time.time(), 'models_verified': True, 'environment': {
        'detected_at': time.time(), 'default': 'cpu', 'options': options}}
    (tmp_path / 'heartbeat.json').write_bytes(canonical_bytes(body))
    assert read_environment(tmp_path)['online'] is False


def test_child_applies_frozen_runtime_and_rejects_unknown_values(tmp_path, monkeypatch):
    from workers.parser import child
    from packages.parsers.models import parser_version
    from packages.parsers.runtime import runtime_config
    from datetime import datetime, timezone, timedelta
    request = {'task_id': 'runtime_test', 'fence': 1, 'source_sha256': '0' * 64,
        'max_pages': 1, 'deadline': (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
        'parser_version': parser_version(PADDLE_PROFILE), 'profile': {'parser_profile_revision': PADDLE_PROFILE},
        'accelerator': 'cpu'}
    path = tmp_path / 'request.json'
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cuda')
    monkeypatch.setattr('sys.argv', ['child', str(path), str(tmp_path / 'source.pdf'), str(tmp_path / 'out')])
    results = []
    monkeypatch.setattr(child, 'process_request', lambda *args: results.append(runtime_config(PADDLE_PROFILE).device))
    path.write_bytes(canonical_bytes(request))
    child.main()
    assert results == ['cpu']
    request['accelerator'] = 'deployment'
    path.write_bytes(canonical_bytes(request))
    with pytest.raises(ValueError, match='accelerator'):
        child.main()
    assert results == ['cpu']


def test_wsl_gpu_reaches_framework_probe(monkeypatch):
    from packages.parsers import environment as env
    from types import SimpleNamespace
    monkeypatch.setattr(env.Path, 'exists', lambda path: str(path) == '/dev/dxg')
    monkeypatch.setattr(env.Path, 'is_file', lambda path: True)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='{"available": true, "name": "WSL NVIDIA"}')
    monkeypatch.setattr(env.subprocess, 'run', run)
    assert env.cuda_probe('/app/.venv/bin/python', 'torch')['available'] is True
    assert len(calls) == 1


def test_mlx_requires_setup_image_proof_bound_to_current_model(monkeypatch):
    from packages.parsers import environment as env
    from packages.parsers import runtime
    calls = []
    monkeypatch.setattr(env, 'cuda_probe', lambda *args: {'available': False})
    monkeypatch.setattr(runtime, 'verify_mlx_service', lambda configured: calls.append(configured.model_id))
    model_id = 'sha256:' + 'a' * 64
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', model_id)
    monkeypatch.delenv('PARSER_MLX_VERIFIED_MODEL_ID', raising=False)
    assert env.detect_environment()['options'][2]['profiles'] == []
    assert not calls
    monkeypatch.setenv('PARSER_MLX_VERIFIED_MODEL_ID', 'sha256:' + 'b' * 64)
    assert env.detect_environment()['options'][2]['profiles'] == []
    assert not calls
    monkeypatch.setenv('PARSER_MLX_VERIFIED_MODEL_ID', model_id)
    option = env.detect_environment()['options'][2]
    assert option['profiles'] == [PADDLE_PROFILE]
    assert option['reason'] is None
    assert calls == [model_id]


def test_mlx_revokes_availability_when_model_runner_metadata_fails(monkeypatch):
    from packages.parsers import environment as env
    from packages.parsers import runtime
    from packages.parsers.inspect import PDFError
    monkeypatch.setattr(env, 'cuda_probe', lambda *args: {'available': False})
    model_id = 'sha256:' + 'a' * 64
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', model_id)
    monkeypatch.setenv('PARSER_MLX_VERIFIED_MODEL_ID', model_id)
    def unavailable(configured):
        raise PDFError('PARSER_MLX_UNAVAILABLE_OR_MISMATCH')
    monkeypatch.setattr(runtime, 'verify_mlx_service', unavailable)
    assert env.detect_environment()['options'][2]['profiles'] == []
