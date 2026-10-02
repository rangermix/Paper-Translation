"""Parser client readiness, independent of weights and inference hardware."""
import json
import os
import platform
import time
from pathlib import Path
from .profiles import PROFILE_IDS, selected_profile

ACCELERATORS = ('dmr',)


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


def detect_environment():
    from .runtime import runtime_config
    from .profiles import DEFAULT_PROFILE
    runtime = runtime_config(DEFAULT_PROFILE)
    cpus = os.cpu_count() or 1
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            cpus = min(cpus, int(quota) / int(period))
    except (OSError, ValueError, ZeroDivisionError):
        pass
    # Client readiness is distinct from model/backend inference readiness. No
    # network/model request belongs in startup or a settings-read heartbeat.
    return {'detected_at': time.time(), 'system': platform.system(), 'architecture': platform.machine(),
        'cpu_count': cpus, 'memory_bytes': memory_limit(), 'gpu_name': None,
        'default': 'dmr', 'backend': runtime.backend,
        'options': [{'id': 'dmr', 'profiles': list(PROFILE_IDS), 'reason': None}]}


def read_environment(root=None):
    offline = {'online': False, 'options': []}
    try:
        with (Path(root or os.environ.get('PARSER_OUTPUTS_DIR', '/parser_outputs')) / 'heartbeat.json').open('rb') as stream:
            body = json.loads(stream.read(65537))
        env = body['environment']
        if (body.get('service_ready') is not True and body.get('models_verified') is not True
                or not 0 <= time.time() - body['timestamp'] < 90
                or not 0 <= time.time() - env['detected_at'] < 180
                or env.get('default') not in ACCELERATORS
                or not isinstance(env['options'], list)
                or any(not isinstance(option, dict) or option.get('id') not in ACCELERATORS
                    or not isinstance(option.get('profiles'), list)
                    or any(profile not in PROFILE_IDS for profile in option['profiles'])
                    for option in env['options'])
                or len({option['id'] for option in env['options']}) != len(env['options'])):
            return offline
        public = {key: env[key] for key in ('detected_at', 'system', 'architecture', 'cpu_count', 'memory_bytes', 'gpu_name', 'default', 'backend') if key in env}
        public['options'] = [{key: option[key] for key in ('id', 'profiles', 'reason') if key in option} for option in env['options']]
        return {**public, 'online': True}
    except (OSError, ValueError, KeyError, TypeError):
        return offline


def resolve_accelerator(profile, root=None):
    """Freeze DMR even while the parser is offline; never change a saved choice."""
    selected_profile({'parser_profile_revision': profile})
    env = read_environment(root)
    if env['online'] and not any(option['id'] == 'dmr' and profile in option['profiles'] for option in env['options']):
        raise ValueError('PARSER_ACCELERATOR_UNAVAILABLE')
    return 'dmr'
