"""DMR-only inference configuration owned by deployment, never document input."""
from dataclasses import dataclass
import os
import sys

from .profiles import selected_profile


@dataclass(frozen=True)
class ParserRuntime:
    device: str
    backend: str
    server_url: str
    model_id: str

    def identity(self):
        return {'device': 'dmr', 'backend': self.backend,
                'inference_engine': 'docker-model-runner/' + ('vllm-metal' if self.backend == 'mlx' else 'vllm'),
                'model_artifact_id': self.model_id}


def runtime_config(profile, accelerator=None, expected_backend=None):
    selected_profile({'parser_profile_revision': profile})
    choice = accelerator or os.environ.get('PARSER_ACCELERATOR', 'dmr')
    if choice != 'dmr':
        raise ValueError('PARSER_NATIVE_RUNTIME_RETIRED' if choice in {'cpu', 'cuda', 'mlx'} else 'PARSER_ACCELERATOR_INVALID')
    backend = os.environ.get('PARSER_DMR_BACKEND', 'vllm')
    if backend not in {'vllm', 'mlx'}:
        raise ValueError('PARSER_MODEL_BACKEND_UNSUPPORTED')
    if expected_backend is not None and backend != expected_backend:
        raise ValueError('PARSER_BACKEND_CHANGED')
    from packages.local_models.catalog import artifact
    from .catalog import vlm_model
    from .model_service import runner_url
    return ParserRuntime('dmr', backend, runner_url() + '/engines/vllm/v1', artifact(vlm_model(profile))['id'])


def child_executable(profile, accelerator=None, expected_backend=None):
    runtime_config(profile, accelerator, expected_backend)
    return sys.executable
