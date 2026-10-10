"""Read-only aggregate telemetry. No Docker socket, credentials or inference."""
import json
import os
from pathlib import Path
import threading
import time
from urllib.request import ProxyHandler, build_opener

_lock = threading.Lock()
_cached = None
_at = 0.0


def local_memory():
    try:
        values = {line.split(':')[0]: int(line.split()[1]) * 1024
                  for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line}
        return {'ram_total_bytes': values['MemTotal'],
                'ram_used_bytes': values['MemTotal'] - values['MemAvailable'],
                'ram_scope': 'docker_host'}
    except (OSError, ValueError, KeyError):
        return {'ram_total_bytes': None, 'ram_used_bytes': None, 'ram_scope': 'unavailable'}


def capacity():
    global _cached, _at
    with _lock:
        if _cached is not None and time.monotonic() - _at < 2:
            return dict(_cached)
        result = {**local_memory(), 'vram_total_bytes': None, 'vram_used_bytes': None,
                  'source': 'docker_host', 'observed_at': time.time(),
                  'resident_models': [], 'loading_models': [], 'inventory_complete': False}
        try:
            url = os.environ.get('RESOURCE_MONITOR_URL', 'http://vllm-runner:12435/resources')
            with build_opener(ProxyHandler({})).open(url, timeout=4) as response:
                remote = json.loads(response.read(65536))
            for key in ('ram_total_bytes', 'ram_used_bytes', 'vram_total_bytes', 'vram_used_bytes'):
                value = remote.get(key)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError('Invalid capacity')
            result.update({key: remote[key] for key in result if key in remote})
            result['source'] = 'model_runner'
        except (OSError, ValueError, TypeError):
            pass
        _cached, _at = result, time.monotonic()
        return dict(result)


def worker_capacity(cfg):
    """Parser heartbeat is on the existing read-only spool boundary."""
    try:
        data = json.loads((cfg.parser_outputs / 'heartbeat.json').read_bytes())
        result = data['resources']
        if -5 <= time.time() - result['observed_at'] < 15:
            return result
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {**local_memory(), 'vram_total_bytes': None, 'vram_used_bytes': None,
            'resident_models': [], 'inventory_complete': False, 'observed_at': time.time()}
