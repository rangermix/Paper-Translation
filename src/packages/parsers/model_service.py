"""Compose parser model preparation. No PDFs, database, provider keys or socket."""
import os
from pathlib import Path
import threading
import time
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException

from packages.ir import canonical_bytes, safe_path, strict_loads
from .catalog import download_spec, manifest_id, public_models, vlm_model
from .download import cache_lock, download
from .profiles import PROFILE_IDS

CONTROL_URL = 'http://parser-models:8091'
DMR_URL = 'http://model-runner.docker.internal'
Backend = Literal['vllm', 'mlx']


def runner_url(value=None):
    value = (value or os.environ.get('PARSER_DMR_URL') or DMR_URL).rstrip('/')
    url = httpx.URL(value)
    if url.scheme not in ('http', 'https') or not url.host or url.userinfo or url.query or url.fragment or url.path != '/':
        raise ValueError('PARSER_MODEL_RUNNER_URL_INVALID')
    return value


def dmr_flags(model, backend):
    return ([] if backend == 'mlx' else ['--gpu-memory-utilization', '0.8', '--max-num-seqs', '1',
        '--max-num-batched-tokens', '2048', '--default-chat-template-kwargs', '{"enable_thinking":false}'])


class Manager:
    def __init__(self, cache, transport=None, dmr=None):
        self.cache, self.transport, self.dmr = Path(cache), transport, runner_url(dmr)
        self.states, self.lock = {}, threading.RLock()

    def client(self, timeout=10):
        return httpx.Client(transport=self.transport or httpx.HTTPTransport(retries=0),
                            timeout=timeout, trust_env=False, follow_redirects=False)

    def receipt(self, profile, backend):
        return safe_path(self.cache, f'{profile}-{backend}.json', must_exist=False)

    def state(self, profile, backend='vllm'):
        with self.lock:
            value = dict(self.states.get((profile, backend), {}))
        if value:
            return value
        try:
            ready = strict_loads(self.receipt(profile, backend).read_bytes()).get('manifest_id') == manifest_id(profile)
        except (OSError, ValueError):
            ready = False
        return {'status': 'ready' if ready else 'not_downloaded',
                'total_bytes': sum(f['size'] for f in download_spec(profile))}

    def prepare(self, profile, backend='vllm'):
        if profile not in PROFILE_IDS or backend not in ('vllm', 'mlx'):
            raise ValueError('PARSER_PROFILE_INVALID')
        with self.lock:
            key = (profile, backend)
            if self.states.get(key, {}).get('status') in ('downloading', 'loading'):
                return dict(self.states[key])
            # Recheck hashes/configuration on every explicit use, including after restart.
            self.states[key] = {'status': 'downloading', 'downloaded_bytes': 0,
                                'total_bytes': sum(f['size'] for f in download_spec(profile))}
            threading.Thread(target=self._prepare, args=(profile, backend), daemon=True).start()
            return dict(self.states[key])

    def verify_backend(self, client, backend):
        response = client.get(self.dmr + '/engines/status')
        response.raise_for_status()
        value = response.json().get('vllm', '')
        expected = 'Running: vllm-metal ' if backend == 'mlx' else 'Running: vllm '
        if not isinstance(value, str) or not value.startswith(expected):
            raise ValueError('PARSER_DMR_BACKEND_UNAVAILABLE')

    def prepare_dmr(self, profile, backend, update):
        from packages.local_models.catalog import artifact
        from packages.local_models.download import archive
        model = vlm_model(profile)
        ident = artifact(model)['id']
        root = self.cache / model['repo'].replace('/', '--') / model['revision']
        update(status='loading')
        with self.client(timeout=600) as client:
            self.verify_backend(client, backend)
            response = client.get(self.dmr + '/models/' + ident)
            if response.status_code == 404:
                response = client.post(self.dmr + '/models/load', content=archive(model, root),
                                       headers={'Content-Type': 'application/x-tar'})
                response.raise_for_status()
                response = client.get(self.dmr + '/models/' + ident)
            response.raise_for_status()
            if response.json().get('id') != ident or response.json().get('config', {}).get('format') != 'safetensors':
                raise ValueError('PARSER_DMR_MODEL_MISMATCH')
            response = client.post(self.dmr + '/engines/vllm/_configure', json={
                'model': ident, 'context-size': model['context_size'], 'keep_alive': '30s',
                'runtime-flags': dmr_flags(model, backend)})
            response.raise_for_status()

    def _prepare(self, profile, backend):
        started = time.monotonic()
        def update(**fields):
            if time.monotonic() - started > 86400:
                raise ValueError('PARSER_MODEL_DOWNLOAD_TIMEOUT')
            with self.lock:
                self.states[(profile, backend)].update(fields)
        try:
            with cache_lock(self.cache):
                # Do not fetch tens of GB when the selected engine is absent.
                with self.client() as client:
                    self.verify_backend(client, backend)
                with self.client(timeout=120) as client:
                    download(download_spec(profile), self.cache, client, update)
                self.prepare_dmr(profile, backend, update)
                receipt = self.receipt(profile, backend)
                temporary = safe_path(self.cache, receipt.name + '.part', must_exist=False)
                temporary.write_bytes(canonical_bytes({'manifest_id': manifest_id(profile)}))
                temporary.replace(receipt)
                update(status='ready')
        except Exception as exc:
            allowed = {'PARSER_MODEL_HASH_MISMATCH', 'PARSER_MODEL_PATH', 'PARSER_MODEL_DOWNLOAD_TIMEOUT',
                       'PARSER_DMR_BACKEND_UNAVAILABLE', 'PARSER_DMR_MODEL_MISMATCH'}
            with self.lock:
                self.states[(profile, backend)].update(status='failed',
                    code=str(exc) if str(exc) in allowed else 'PARSER_MODEL_PREPARATION_FAILED')


def create_app(cache=None, transport=None, dmr=None):
    app = FastAPI(docs_url=None, redoc_url=None)
    manager = Manager(cache or os.environ.get('PARSER_MODEL_CACHE', '/model_cache'), transport, dmr)
    app.state.manager = manager

    def lookup(profile):
        if profile not in PROFILE_IDS:
            raise HTTPException(404, 'PARSER_PROFILE_INVALID')

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/models')
    def catalog(backend: Backend = 'vllm'):
        return {'models': [{**m, **manager.state(m['id'], backend)} for m in public_models()]}

    @app.get('/models/{profile}')
    def state(profile: str, backend: Backend = 'vllm'):
        lookup(profile)
        return manager.state(profile, backend)

    @app.post('/models/{profile}/prepare', status_code=202)
    def prepare(profile: str, backend: Backend = 'vllm'):
        lookup(profile)
        try:
            return manager.prepare(profile, backend)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    return app


app = create_app()
