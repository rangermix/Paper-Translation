"""Private, read-only memory telemetry for the application scheduler."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import time
from urllib.request import ProxyHandler, build_opener


def snapshot():
    memory = {line.split(':')[0]: int(line.split()[1]) * 1024
              for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line}
    result = {'ram_total_bytes': memory['MemTotal'],
              'ram_used_bytes': memory['MemTotal'] - memory['MemAvailable'],
              'ram_scope': 'docker_host', 'vram_total_bytes': None, 'vram_used_bytes': None,
              'observed_at': time.time(), 'resident_models': [], 'loading_models': [], 'inventory_complete': False}
    try:
        output = subprocess.run(['nvidia-smi', '--query-gpu=memory.total,memory.used',
            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2, check=True)
        # The app uses one device. Do not sum separate GPUs into fictional space.
        total, used = [int(value.strip()) * 1024**2 for value in output.stdout.splitlines()[0].split(',')]
        result.update(vram_total_bytes=total, vram_used_bytes=used)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    try:
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:12434/engines/ps', timeout=1) as response:
            rows = json.loads(response.read(65536))
        result.update(resident_models=[row['model_name'] for row in rows if not row.get('loading')],
                      loading_models=[row['model_name'] for row in rows if row.get('loading')], inventory_complete=True)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/resources':
            self.send_error(404)
            return
        body = json.dumps(snapshot()).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 12435), Handler).serve_forever()
