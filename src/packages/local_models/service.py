"""Compose-only model cache and inference bridge. No DB, documents or credentials."""
import os
from pathlib import Path
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .catalog import artifact, get_model, public_models
from .download import archive, download

DMR = 'http://model-runner.docker.internal'
RUNTIME_FLAGS = ['--gpu-memory-utilization', '0.8', '--max-num-seqs', '1', '--max-num-batched-tokens', '512']


class Completion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str
    prompt: str | None = Field(None, max_length=30000)
    messages: list[dict[str, str]] | None = None
    add_special_tokens: bool = False
    max_tokens: int = Field(2048, ge=1, le=2048)
    temperature: float = Field(0, ge=0, le=0)
    stream: bool = False


class Manager:
    def __init__(self, cache, transport=None):
        self.cache, self.transport = Path(cache), transport
        self.states = {}
        self.lock = threading.RLock()
        self.inference_lock = threading.Lock()


    def client(self, timeout=10):
        return httpx.Client(transport=self.transport or httpx.HTTPTransport(retries=0), timeout=timeout,
                            follow_redirects=False, trust_env=False)

    def installed(self, model):
        with self.client() as client:
            response = client.get(DMR + '/models')
            response.raise_for_status()
            return any(row['id'] == artifact(model)['id'] for row in response.json())

    def backend(self):
        with self.client() as client:
            response = client.get(DMR + '/engines/status')
            response.raise_for_status()
            backend = response.json().get('vllm', '')
            if not isinstance(backend, str) or not backend.startswith('Running: vllm-metal '):
                raise ValueError('LOCAL_MLX_UNAVAILABLE')
            return backend

    def reserve_gpu(self, model):
        """Retire only idle project models; never interrupt another running request."""
        owned = {m['model_id'] for m in public_models()}
        paddle = os.environ.get('PADDLE_MLX_MODEL_ID', '')
        if paddle.startswith('sha256:'):
            owned.add(paddle)
        target = artifact(model)['id']
        with self.client(timeout=30) as client:
            response = client.get(DMR + '/engines/ps')
            response.raise_for_status()
            others = [r for r in response.json() if r.get('backend_name') == 'vllm' and r.get('model_name') != target]
            if any(r.get('in_use') or r.get('loading') for r in others):
                raise ValueError('LOCAL_MODEL_BUSY')
            aliases = {identifier: identifier for identifier in owned}
            if any(r.get('model_name') not in aliases for r in others):
                inventory = client.get(DMR + '/models')
                inventory.raise_for_status()
                for entry in inventory.json():
                    if entry.get('id') in owned:
                        aliases.update({tag: entry['id'] for tag in entry.get('tags') or []})
            if any(r.get('model_name') not in aliases for r in others):
                raise ValueError('LOCAL_MODEL_BUSY')
            if others:
                retire = list(dict.fromkeys(aliases[r['model_name']] for r in others))
                response = client.post(DMR + '/engines/unload', json={'backend': 'vllm', 'models': retire})
                response.raise_for_status()
                # DMR atomically refuses to evict runners with active references.
                # A request may have started after our status read.
                if response.json().get('unloaded_runners', 0) < len(retire):
                    raise ValueError('LOCAL_MODEL_BUSY')

    def configuration_matches(self, model):
        with self.client() as client:
            response = client.get(DMR + '/engines/_configure', params={'model': artifact(model)['id']})
            response.raise_for_status()
            return any(row.get('Backend') == 'vllm' and row.get('ModelID') == artifact(model)['id']
                       and row.get('Config', {}).get('runtime-flags') == RUNTIME_FLAGS
                       and row.get('Config', {}).get('context-size') == model['context_size']
                       for row in response.json())

    def state(self, model):
        with self.lock:
            current = dict(self.states.get(model['id'], {}))
        if current.get('status') in ('downloading', 'loading', 'failed'):
            return current
        try:
            backend = self.backend()
            status = 'ready' if self.installed(model) else 'not_downloaded'
            return {'status': status, 'backend': backend}
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            return {'status': 'unavailable', 'code': 'LOCAL_MLX_UNAVAILABLE'}

    def prepare(self, model):
        with self.lock:
            existing = self.states.get(model['id'], {})
            if existing.get('status') in ('downloading', 'loading'):
                return dict(existing)
            if existing.get('status') == 'ready':
                try:
                    # Every unit prepares, including while another is inferring.
                    # Revalidate DMR's effective configuration without taking a
                    # working model offline or queueing behind inference.
                    self.backend()
                    if self.installed(model) and self.configuration_matches(model):
                        return dict(existing)
                except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                    pass
            self.states[model['id']] = {'status': 'downloading', 'downloaded_bytes': 0,
                                      'total_bytes': sum(f['size'] for f in model['files'])}
            threading.Thread(target=self._prepare, args=(model,), daemon=True).start()
            return dict(self.states[model['id']])

    def _prepare(self, model):
        from packages.providers.settings import _locked
        started = time.monotonic()
        def update(**fields):
            if time.monotonic() - started > 3600:
                raise ValueError('LOCAL_MODEL_DOWNLOAD_TIMEOUT')
            with self.lock:
                self.states[model['id']].update(fields)
        try:
            self.backend()
            # Cross-process cache lock and one active download. No shared secret storage.
            with _locked(self.cache):
                if not self.installed(model):
                    root = self.cache / (model['id'] + '-' + model['revision'])
                    with self.client(timeout=60) as client:
                        download(model, root, client, update)
                    update(status='loading')
                    with self.client(timeout=600) as client:
                        response = client.post(DMR + '/models/load', content=archive(model, root),
                                               headers={'Content-Type': 'application/x-tar'})
                        response.raise_for_status()
                    if not self.installed(model):
                        raise ValueError('LOCAL_MODEL_LOAD_FAILED')
                with self.inference_lock:
                    self.reserve_gpu(model)
                    # Unloading a DMR model also removes its runtime configuration.
                    # Recheck effective flags instead of caching a preparation receipt.
                    if not self.configuration_matches(model):
                        with self.client(timeout=30) as client:
                            response = client.post(DMR + '/engines/vllm/_configure', json={
                                'model': artifact(model)['id'], 'context-size': model['context_size'],
                                'keep_alive': '30s', 'runtime-flags': RUNTIME_FLAGS})
                            if response.status_code not in (200, 202, 204):
                                raise ValueError('LOCAL_MODEL_BACKEND_CONFIG')
            update(status='ready')
        except Exception as exc:
            allowed = {'LOCAL_MODEL_HASH', 'LOCAL_MODEL_PATH', 'LOCAL_MODEL_DOWNLOAD_TIMEOUT',
                       'LOCAL_MODEL_LOAD_FAILED', 'LOCAL_MLX_UNAVAILABLE', 'LOCAL_MODEL_BACKEND_CONFIG', 'LOCAL_MODEL_BUSY'}
            code = str(exc) if str(exc) in allowed else 'LOCAL_MODEL_DOWNLOAD_FAILED'
            with self.lock:
                self.states[model['id']].update(status='failed', code=code)


def create_app(*, cache=None, transport=None):
    app = FastAPI(docs_url=None, redoc_url=None)
    manager = Manager(cache or os.environ.get('LOCAL_MODEL_CACHE', '/model_cache'), transport)
    app.state.manager = manager

    def lookup(identifier):
        try:
            return get_model(identifier)
        except ValueError:
            raise HTTPException(404, 'LOCAL_MODEL_UNKNOWN') from None

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/models')
    def catalog():
        return {'models': [{**m, **manager.state(get_model(m['id']))} for m in public_models()]}

    @app.get('/models/{identifier}')
    def status(identifier: str):
        return manager.state(lookup(identifier))

    @app.post('/models/{identifier}/prepare', status_code=202)
    def prepare(identifier: str):
        return manager.prepare(lookup(identifier))

    @app.post('/v1/completions')
    def complete(body: Completion):
        model = lookup(body.model)
        if body.model != artifact(model)['id'] or body.stream:
            raise HTTPException(422, 'LOCAL_MODEL_CONFIG')
        if model['family'] == 'hy':
            if (body.prompt is not None or not body.messages or len(body.messages) != 1
                    or set(body.messages[0]) != {'role', 'content'} or body.messages[0]['role'] != 'user'
                    or len(body.messages[0]['content'].encode()) + 256 + body.max_tokens > model['context_size']):
                raise HTTPException(422, 'LOCAL_MODEL_PROMPT')
            route = '/chat/completions'
        else:
            if (body.messages is not None or body.prompt is None or body.add_special_tokens
                    or len(body.prompt.encode()) + 256 + body.max_tokens > model['context_size']):
                raise HTTPException(422, 'LOCAL_MODEL_PROMPT')
            route = '/completions'
        # No downloads or reconfiguration after dispatch. This call either runs the exact model or fails.
        if manager.state(model)['status'] != 'ready':
            raise HTTPException(503, 'LOCAL_MODEL_NOT_READY')
        with manager.inference_lock:
            try:
                manager.reserve_gpu(model)
                if not manager.configuration_matches(model):
                    raise HTTPException(503, 'LOCAL_MODEL_NOT_READY')
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                raise HTTPException(503, 'LOCAL_MODEL_NOT_READY') from None
            try:
                with manager.client(timeout=300) as client:
                    response = client.post(DMR + '/engines/vllm/v1' + route, json=body.model_dump(exclude_none=True))
                    if response.status_code != 200:
                        raise HTTPException(502, 'LOCAL_MODEL_INFERENCE_FAILED')
                    data = response.json()
                    if model['family'] == 'hy':
                        for choice in data.get('choices', []):
                            message = choice.get('message', {})
                            if message.get('tool_calls') or message.get('refusal') or message.get('role') != 'assistant':
                                raise HTTPException(502, 'LOCAL_MODEL_OUTPUT_INVALID')
                            choice['text'] = message.get('content')
                            choice.pop('message', None)
                    # Only bounded inference metadata and output return, never upstream error bodies.
                    return {k: data[k] for k in ('id', 'model', 'choices', 'usage') if k in data}
            except (httpx.ConnectError, httpx.ConnectTimeout):
                raise HTTPException(503, 'LOCAL_MODEL_NOT_READY') from None
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                raise HTTPException(502, 'LOCAL_MODEL_INFERENCE_FAILED') from None

    return app


app = create_app()
