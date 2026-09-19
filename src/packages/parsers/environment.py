"""Parser-owned capability detection; no secrets, model downloads or inference."""
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from .profiles import DOCLING_PROFILE, GRANITE_PROFILE, PADDLE_PROFILE

ACCELERATORS = ('cpu', 'cuda', 'mlx')


def cuda_probe(executable, framework):
    if not any(Path(device).exists() for device in ('/dev/nvidiactl', '/dev/dxg')) or not Path(executable).is_file():
        return {'available': False}
    code = ('import torch; ok=torch.cuda.is_available(); print(__import__("json").dumps({"available":ok,"name":torch.cuda.get_device_name(0) if ok else None}))'
        if framework == 'torch' else
        'import paddle; ok=paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count()>0; print(__import__("json").dumps({"available":ok}))')
    try:
        result = subprocess.run([str(executable), '-c', code], capture_output=True, text=True, timeout=12, check=True)
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {'available': False}


def memory_limit():
    limits = []
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemTotal:'):
                limits.append(int(line.split()[1]) * 1024)
        for name in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
            p = Path(name)
            if p.exists() and p.read_text().strip().isdigit():
                limits.append(int(p.read_text()))
    except (OSError, ValueError):
        pass
    return min(limits) if limits else None


def mlx_available():
    """Setup records image-inference proof; heartbeat rechecks model presence.

    A tag or installed MLX package alone is insufficient. Only deployment setup
    may provide this receipt after testing its Docker-managed vision backend.
    Refresh it after any model/backend change. DMR's cached status cannot attest
    the running package version: this remains a setup receipt, not continuous
    image-inference proof. No inference or installation occurs in the heartbeat.
    """
    model_id = os.environ.get('PADDLE_MLX_MODEL_ID')
    if not model_id or os.environ.get('PARSER_MLX_VERIFIED_MODEL_ID') != model_id:
        return False
    from .inspect import PDFError
    from .runtime import runtime_config, verify_mlx_service
    try:
        verify_mlx_service(runtime_config(PADDLE_PROFILE, 'mlx'))
        return True
    except (PDFError, ValueError):
        return False


def detect_environment():
    torch = cuda_probe(sys.executable, 'torch')
    paddle = cuda_probe('/app/.venv-paddle/bin/python', 'paddle')
    gpu_profiles = ([DOCLING_PROFILE, GRANITE_PROFILE] if torch.get('available') is True else [])
    if paddle.get('available') is True:
        gpu_profiles.append(PADDLE_PROFILE)
    mlx = mlx_available()
    cpus = os.cpu_count() or 1
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            cpus = min(cpus, int(quota) / int(period))
    except (OSError, ValueError, ZeroDivisionError):
        pass
    return {'detected_at': time.time(), 'system': platform.system(), 'architecture': platform.machine(),
        'cpu_count': cpus, 'memory_bytes': memory_limit(), 'gpu_name': torch.get('name'),
        'default': os.environ.get('PARSER_ACCELERATOR', 'cpu'),
        'options': [
            {'id': 'cpu', 'profiles': [DOCLING_PROFILE, GRANITE_PROFILE, PADDLE_PROFILE], 'reason': None},
            {'id': 'cuda', 'profiles': gpu_profiles, 'reason': 'CUDA_UNAVAILABLE_OR_MODEL_UNSUPPORTED'},
            {'id': 'mlx', 'profiles': [PADDLE_PROFILE] if mlx else [],
                'reason': None if mlx else 'MLX_IMAGE_BACKEND_UNAVAILABLE'}]}


def read_environment(root=None):
    offline = {'online': False, 'options': []}
    try:
        with (Path(root or os.environ.get('PARSER_OUTPUTS_DIR', '/parser_outputs')) / 'heartbeat.json').open('rb') as stream:
            body = json.loads(stream.read(65537))
        env = body['environment']
        if (body.get('models_verified') is not True or not 0 <= time.time() - body['timestamp'] < 90
                or not 0 <= time.time() - env['detected_at'] < 180
                or env.get('default') not in ACCELERATORS
                or not isinstance(env['options'], list)
                or any(not isinstance(option, dict) or option.get('id') not in ACCELERATORS
                    or not isinstance(option.get('profiles'), list)
                    or any(profile not in (DOCLING_PROFILE, GRANITE_PROFILE, PADDLE_PROFILE) for profile in option['profiles'])
                    for option in env['options'])
                or len({option['id'] for option in env['options']}) != len(env['options'])):
            return offline
        public = {key: env[key] for key in ('detected_at', 'system', 'architecture', 'cpu_count', 'memory_bytes', 'gpu_name', 'default') if key in env}
        public['options'] = [{key: option[key] for key in ('id', 'profiles', 'reason') if key in option} for option in env['options']]
        return {**public, 'online': True}
    except (OSError, ValueError, KeyError, TypeError):
        return offline


def resolve_accelerator(profile, root=None):
    """Resolve the parser's Compose mode, never a saved user device override."""
    env = read_environment(root)
    if not env['online']:
        return None  # The parser applies its Compose configuration when available.
    choice = env['default']
    if choice == 'mlx' and profile != PADDLE_PROFILE:
        choice = 'cpu'
    if not any(option['id'] == choice and profile in option['profiles'] for option in env['options']):
        raise ValueError('PARSER_ACCELERATOR_UNAVAILABLE')
    return choice
