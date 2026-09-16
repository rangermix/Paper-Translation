"""Hardware selection must not rewrite old jobs or silently choose another device."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.ir import strict_loads
from packages.parsers import profiles


def test_paddle_default_for_new_jobs_preserves_saved_and_legacy_choices():
    assert profiles.DEFAULT_PROFILE == profiles.PADDLE_PROFILE
    assert profiles.preferred_profile({}) == profiles.PADDLE_PROFILE
    assert profiles.preferred_profile({'parser_profile_revision': 'docling-v1'}) == 'docling-v1'
    assert profiles.selected_profile({}) == 'docling-v1'


def test_explicit_accelerator_selection(monkeypatch):
    from packages.parsers.runtime import runtime_config
    monkeypatch.delenv('PARSER_ACCELERATOR', raising=False)
    assert runtime_config(profiles.PADDLE_PROFILE).device == 'cpu'
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cuda')
    assert runtime_config(profiles.PADDLE_PROFILE).device == 'cuda:0'
    assert runtime_config('docling-v1').device == 'cuda:0'
    monkeypatch.setenv('PARSER_ACCELERATOR', 'mlx')
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', 'sha256:' + 'a' * 64)
    assert runtime_config(profiles.PADDLE_PROFILE).device == 'mlx'
    assert runtime_config(profiles.GRANITE_PROFILE).device == 'cpu'
    monkeypatch.setenv('PARSER_ACCELERATOR', 'auto')
    with pytest.raises(ValueError, match='PARSER_ACCELERATOR_INVALID'):
        runtime_config(profiles.PADDLE_PROFILE)


def test_cuda_unavailable_is_an_error(monkeypatch):
    from packages.parsers.runtime import require_device, runtime_config
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cuda')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    with pytest.raises(Exception, match='PARSER_ACCELERATOR_UNAVAILABLE'):
        require_device(runtime_config('docling-v1'), 'docling-v1')
    monkeypatch.setitem(sys.modules, 'paddle', SimpleNamespace(is_compiled_with_cuda=lambda: False))
    with pytest.raises(Exception, match='PARSER_ACCELERATOR_UNAVAILABLE'):
        require_device(runtime_config(profiles.PADDLE_PROFILE), profiles.PADDLE_PROFILE)


def test_fingerprint_and_identity_record_device(monkeypatch):
    from packages.parsers.config import pipeline_fingerprint
    from packages.parsers.progress import local_identity
    lock = strict_loads(Path('deployment/parser-models.lock.json').read_bytes())
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cpu')
    cpu = pipeline_fingerprint(lock, 'docling-v1')
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cuda')
    assert pipeline_fingerprint(lock, 'docling-v1') != cpu
    assert local_identity(profiles.PADDLE_PROFILE, lock)['device'] == 'cuda:0'
    monkeypatch.setenv('PARSER_ACCELERATOR', 'mlx')
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', 'sha256:' + 'a' * 64)
    info = local_identity(profiles.PADDLE_PROFILE, lock)
    assert info['device'] == 'mlx'
    assert info['layout_device'] == 'cpu'
    assert info['backend'] == 'vllm-server'


def test_paddle_options_use_accelerator_and_pinned_local_paths(monkeypatch):
    from packages.parsers.pdf_paddleocr import paddle_options
    lock = strict_loads(Path('deployment/parser-models.lock.json').read_bytes())
    monkeypatch.setitem(sys.modules, 'paddlex.inference', SimpleNamespace(load_pipeline_config=lambda _: {
        'SubModules': {'LayoutDetection': {}, 'VLRecognition': {}}}))
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cuda')
    options = paddle_options(Path('/models'), lock)
    assert options['device'] == 'gpu:0'
    assert options['vl_rec_backend'] == 'native'
    monkeypatch.setenv('PARSER_ACCELERATOR', 'mlx')
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', 'sha256:' + 'a' * 64)
    options = paddle_options(Path('/models'), lock)
    assert options['device'] == 'cpu'
    assert options['vl_rec_backend'] == 'vllm-server'
    assert options['vl_rec_api_model_name'] == 'sha256:' + 'a' * 64
    assert 'vl_rec_model_dir' not in options
    assert options['vl_rec_server_url'] == 'http://model-runner.docker.internal/engines/vllm/v1'


def test_runtime_identity_fits_persisted_contract(monkeypatch):
    from packages.domain.workflow import ModelIdentity
    from packages.parsers.progress import local_identity
    lock = strict_loads(Path('deployment/parser-models.lock.json').read_bytes())
    for device in ('cpu', 'cuda', 'mlx'):
        monkeypatch.setenv('PARSER_ACCELERATOR', device)
        monkeypatch.setenv('PADDLE_MLX_MODEL_ID', 'sha256:' + 'a' * 64)
        identity = local_identity(profiles.PADDLE_PROFILE, lock)
        assert ModelIdentity.model_validate(identity).device == identity['device']


@pytest.mark.parametrize('model_id', ['', 'latest', 'sha256:abc', 'other/model'])
def test_mlx_requires_pinned_model_id(monkeypatch, model_id):
    from packages.parsers.runtime import runtime_config
    monkeypatch.setenv('PARSER_ACCELERATOR', 'mlx')
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', model_id)
    with pytest.raises(ValueError, match='PARSER_MLX_MODEL_ID_REQUIRED'):
        runtime_config(profiles.PADDLE_PROFILE)


@pytest.mark.parametrize('mismatch', [None, 'architecture_absent', 'id', 'architecture', 'format', 'redirect'])
def test_dmr_metadata_is_checked_without_pulling_models(monkeypatch, mismatch):
    import httpx
    from packages.parsers.runtime import runtime_config, verify_mlx_service
    model_id = 'sha256:' + 'a' * 64
    monkeypatch.setenv('PARSER_ACCELERATOR', 'mlx')
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', model_id)
    metadata = {'id': model_id, 'config': {'architecture': 'paddleocr_vl', 'format': 'safetensors'}}
    if mismatch == 'id': metadata['id'] = 'sha256:' + 'b' * 64
    elif mismatch == 'architecture_absent': metadata['config'].pop('architecture')
    elif mismatch in ('architecture', 'format'): metadata['config'][mismatch] = 'wrong'
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm-metal dev'})
        return httpx.Response(302 if mismatch == 'redirect' else 200, json=metadata,
            headers={'Location': 'https://example.org'})
    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client)
    if mismatch not in (None, 'architecture_absent'):
        with pytest.raises(Exception, match='PARSER_MLX_UNAVAILABLE_OR_MISMATCH'):
            verify_mlx_service(runtime_config(profiles.PADDLE_PROFILE))
    else:
        verify_mlx_service(runtime_config(profiles.PADDLE_PROFILE))
    assert len(requests) == 2
    assert all(request.method == 'GET' and request.url.host == 'model-runner.docker.internal'
        and request.content == b'' for request in requests)


@pytest.mark.parametrize('status', ['Not Installed', 'Error: import failed', 'Running: vLLM CUDA', None])
def test_dmr_model_inventory_does_not_establish_running_metal_backend(monkeypatch, status):
    import httpx
    from packages.parsers.runtime import runtime_config, verify_mlx_service
    model_id = 'sha256:' + 'a' * 64
    monkeypatch.setenv('PADDLE_MLX_MODEL_ID', model_id)
    def respond(request):
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': status})
        return httpx.Response(200, json={'id': model_id, 'config': {'format': 'safetensors'}})
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client)
    with pytest.raises(Exception, match='PARSER_MLX_UNAVAILABLE_OR_MISMATCH'):
        verify_mlx_service(runtime_config(profiles.PADDLE_PROFILE, 'mlx'))


def test_cpu_uses_current_interpreter_cuda_paddle_requires_unified_image(monkeypatch):
    from packages.parsers.runtime import child_executable
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cpu')
    assert child_executable(profiles.PADDLE_PROFILE) == sys.executable
    monkeypatch.setenv('PARSER_ACCELERATOR', 'cuda')
    assert child_executable('docling-v1') == sys.executable
    monkeypatch.setattr(Path, 'is_file', lambda self: False)
    with pytest.raises(Exception, match='PARSER_CUDA_IMAGE_REQUIRED'):
        child_executable(profiles.PADDLE_PROFILE)
    monkeypatch.setattr(Path, 'is_file', lambda self: True)
    assert child_executable(profiles.PADDLE_PROFILE) == '/app/.venv-paddle/bin/python'
