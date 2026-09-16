"""Deployment-owned acceleration; PDF/job input can never select an endpoint."""
from dataclasses import dataclass
import os
import re
from urllib.parse import quote

from .inspect import PDFError
from .profiles import PADDLE_PROFILE, selected_profile

DMR_URL = 'http://model-runner.docker.internal/engines/vllm/v1'


@dataclass(frozen=True)
class ParserRuntime:
    device: str
    backend: str = 'native'
    server_url: str | None = None
    model_id: str | None = None

    @property
    def paddle_device(self):
        return 'gpu:0' if self.device == 'cuda:0' else 'cpu'

    @property
    def dtype(self):
        return 'float32' if self.device == 'cpu' else 'float16'

    def identity(self):
        data = {'device': self.device, 'backend': self.backend}
        if self.device == 'mlx':
            data.update(layout_device='cpu', inference_engine='docker-model-runner/vllm-metal',
                model_artifact_id=self.model_id)
        return data


def runtime_config(profile, accelerator=None):
    selected_profile({'parser_profile_revision': profile})
    accelerator = accelerator or os.environ.get('PARSER_ACCELERATOR', 'cpu')
    if accelerator not in {'cpu', 'cuda', 'mlx'}:
        raise ValueError('PARSER_ACCELERATOR_INVALID')
    if accelerator == 'cuda':
        return ParserRuntime('cuda:0')
    if accelerator == 'mlx' and profile == PADDLE_PROFILE:
        model_id = os.environ.get('PADDLE_MLX_MODEL_ID', '')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', model_id):
            raise ValueError('PARSER_MLX_MODEL_ID_REQUIRED')
        return ParserRuntime('mlx', 'vllm-server', DMR_URL, model_id)
    # MLX is supported for Paddle region recognition. Other profiles keep their
    # explicitly documented CPU engine, and report CPU in execution history.
    return ParserRuntime('cpu')


def require_device(runtime, profile):
    if runtime.device != 'cuda:0':
        return
    try:
        if profile == PADDLE_PROFILE:
            import paddle
            available = paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
        else:
            import torch
            available = torch.cuda.is_available()
        if available:
            return
    except (ImportError, RuntimeError):
        pass
    raise PDFError('PARSER_ACCELERATOR_UNAVAILABLE')


def verify_mlx_service(runtime):
    """Read only local DMR metadata; never pull models or install a backend."""
    import httpx
    try:
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            status = client.get('http://model-runner.docker.internal/engines/status')
            backend = status.json().get('vllm') if status.status_code == 200 else None
            # DMR caches this string at installation: it identifies a running
            # Metal backend, not its current package version or vision support.
            if not isinstance(backend, str) or not backend.startswith('Running: vllm-metal '):
                raise PDFError('PARSER_MLX_UNAVAILABLE_OR_MISMATCH')
            response = client.get('http://model-runner.docker.internal/models/' + quote(runtime.model_id, safe=':'))
            if response.status_code == 200:
                body = response.json()
                config = body.get('config', {})
                # DMR 1.2 omits architecture for locally packaged safetensors.
                # The content ID is mandatory; reject conflicting architecture
                # when supplied, but do not reject Docker's own package output.
                if (body.get('id') == runtime.model_id and config.get('format') == 'safetensors'
                        and config.get('architecture') in (None, 'paddleocr_vl')):
                    return
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        pass
    raise PDFError('PARSER_MLX_UNAVAILABLE_OR_MISMATCH')


def child_executable(profile, accelerator=None):
    """CUDA libraries conflict: select the isolated Paddle subprocess environment."""
    import sys
    from pathlib import Path
    runtime = runtime_config(profile, accelerator)
    if runtime.device == 'cuda:0' and profile == PADDLE_PROFILE:
        executable = Path('/app/.venv-paddle/bin/python')
        if not executable.is_file():
            raise PDFError('PARSER_CUDA_IMAGE_REQUIRED')
        return str(executable)
    return sys.executable
