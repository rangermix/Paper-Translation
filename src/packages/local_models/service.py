"""Compose-only model cache and inference bridge. No DB, documents or credentials."""
import os
from pathlib import Path
import threading
import time
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .catalog import (artifact, compatible_backends, configured_backends, configured_formats,
                      get_model, public_models, select_backend, selectable_format)
from .download import archive, download

DMR = 'http://model-runner.docker.internal'
RUNTIME_FLAGS = ['--gpu-memory-utilization', '0.8', '--max-num-seqs', '1', '--max-num-batched-tokens', '512']


Backend = Literal['llama.cpp', 'vllm', 'mlx']


def engine(model, backend=None):
    return 'vllm' if select_backend(model, backend) in ('mlx', 'vllm') else 'llama.cpp'


def runtime_flags(model, backend=None):
    return RUNTIME_FLAGS if engine(model, backend) == 'vllm' else []


class Completion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str
    backend: Backend | None = None
    prompt: str | None = Field(None, max_length=30000)
    messages: list[dict[str, str]] | None = None
    chat_template_kwargs: dict[str, bool] | None = None
    add_special_tokens: bool = False
    max_tokens: int = Field(2048, ge=1, le=2048)
    temperature: float = Field(0, ge=0, le=0)
    stream: bool = False


class Manager:
    def __init__(self, cache, transport=None, formats=None, vllm_dmr=None, gguf_dmr=None, backends=None):
        self.cache, self.transport = Path(cache), transport
        self.formats = configured_formats(formats)
        self.backends = configured_backends(backends, formats=self.formats)
        self.vllm_dmr = (vllm_dmr if vllm_dmr is not None else
                         os.environ.get('LOCAL_VLLM_DMR_URL', '')).rstrip('/') or DMR
        self.gguf_dmr = (gguf_dmr if gguf_dmr is not None else
                         os.environ.get('LOCAL_GGUF_DMR_URL', '')).rstrip('/') or DMR
        for runner in (self.vllm_dmr, self.gguf_dmr):
            url = httpx.URL(runner)
            if (url.scheme not in ('http', 'https') or not url.host or url.userinfo
                    or url.query or url.fragment):
                raise ValueError('LOCAL_MODEL_RUNNER_URL_INVALID')
        self.states = {}
        self.lock = threading.RLock()
        self.inference_lock = threading.Lock()


    def client(self, timeout=10):
        return httpx.Client(transport=self.transport or httpx.HTTPTransport(retries=0), timeout=timeout,
                            follow_redirects=False, trust_env=False)

    def supported(self, model, backend=None):
        return selectable_format(model) in self.formats and select_backend(model, backend) in self.backends

    def state_key(self, model, backend=None):
        selected = select_backend(model, backend)
        return model['id'] if selected == model['runtime'] else (model['id'], selected)

    def runner(self, model, backend=None):
        """The selected backend determines its Runner, without fallback."""
        return {'vllm': self.vllm_dmr, 'llama.cpp': self.gguf_dmr}.get(select_backend(model, backend), DMR)

    def installed(self, model, backend=None):
        with self.client() as client:
            response = client.get(self.runner(model, backend) + '/models')
            response.raise_for_status()
            return any(row['id'] == artifact(model)['id'] for row in response.json())

    def engine_status(self, model=None, backend=None):
        with self.client() as client:
            response = client.get((self.runner(model, backend) if model is not None else DMR) + '/engines/status')
            response.raise_for_status()
            return response.json()

    def backend(self, model, statuses=None, backend=None):
        selected = select_backend(model, backend)
        name = engine(model, selected)
        backend = (statuses if statuses is not None else self.engine_status(model, selected)).get(name, '')
        expected = {'mlx': 'Running: vllm-metal ', 'vllm': 'Running: vllm ',
                    'llama.cpp': 'Running: llama.cpp '}[selected]
        if not isinstance(backend, str) or not backend.startswith(expected):
            if isinstance(backend, str):
                if (selected == 'llama.cpp' and 'com.docker.nv-gpu-info.exe' in backend
                        and ('cannot find the file' in backend.lower() or 'no such file' in backend.lower())):
                    raise ValueError('LOCAL_CUDA_PROBE_MISSING')
                if selected == 'vllm' and 'only supported on Linux' in backend:
                    raise ValueError('LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED')
            raise ValueError({'mlx': 'LOCAL_MLX_UNAVAILABLE', 'vllm': 'LOCAL_VLLM_UNAVAILABLE',
                              'llama.cpp': 'LOCAL_GGUF_UNAVAILABLE'}[selected])
        return backend

    def reserve_gpu(self, model, backend=None):
        """Retire only idle project models; never interrupt another running request."""
        if select_backend(model, backend) != 'mlx':
            return
        owned = {m['model_id'] for m in public_models(purpose='all') if m['runtime'] == 'mlx'}
        from packages.parsers.catalog import vlm_lock
        owned.update(artifact(parser)['id'] for parser in vlm_lock()['models'])
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

    def configuration_matches(self, model, backend=None):
        with self.client() as client:
            response = client.get(self.runner(model, backend) + '/engines/_configure', params={'model': artifact(model)['id']})
            response.raise_for_status()
            return any(row.get('Backend') == engine(model, backend) and row.get('ModelID') == artifact(model)['id']
                       and (row.get('Config', {}).get('runtime-flags') or []) == runtime_flags(model, backend)
                       and row.get('Config', {}).get('context-size') == model['context_size']
                       for row in response.json())

    def state(self, model, statuses=None, backend=None):
        selected = select_backend(model, backend)
        if not self.supported(model, selected):
            return {'status': 'unavailable', 'code': 'LOCAL_MODEL_FORMAT_UNSUPPORTED' if selectable_format(model) not in self.formats else 'LOCAL_MODEL_BACKEND_UNSUPPORTED'}
        key = self.state_key(model, selected)
        with self.lock:
            current = dict(self.states.get(key, {}))
        if current.get('status') in ('downloading', 'loading', 'failed'):
            return current
        try:
            backend = self.backend(model, statuses, selected)
            status = 'ready' if self.installed(model, selected) else 'not_downloaded'
            return {'status': status, 'backend': backend}
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            code = str(exc) if str(exc) in {'LOCAL_CUDA_PROBE_MISSING', 'LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED'} else {
                'mlx': 'LOCAL_MLX_UNAVAILABLE', 'vllm': 'LOCAL_VLLM_UNAVAILABLE',
                'llama.cpp': 'LOCAL_GGUF_UNAVAILABLE'}[selected]
            return {'status': 'unavailable', 'code': code}

    def prepare(self, model, backend=None):
        selected = select_backend(model, backend)
        if not self.supported(model, selected):
            raise ValueError('LOCAL_MODEL_BACKEND_UNSUPPORTED')
        key = self.state_key(model, selected)
        with self.lock:
            existing = self.states.get(key, {})
            if existing.get('status') in ('downloading', 'loading'):
                return dict(existing)
            if existing.get('status') == 'ready':
                try:
                    # Every unit prepares, including while another is inferring.
                    # Revalidate DMR's effective configuration without taking a
                    # working model offline or queueing behind inference.
                    self.backend(model, backend=selected)
                    if self.installed(model, selected) and self.configuration_matches(model, selected):
                        return dict(existing)
                except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                    pass
            self.states[key] = {'status': 'downloading', 'downloaded_bytes': 0,
                                      'total_bytes': sum(f['size'] for f in model['files'])}
            threading.Thread(target=self._prepare, args=(model, selected), daemon=True).start()
            return dict(self.states[key])

    def _prepare(self, model, backend=None):
        selected = select_backend(model, backend)
        key = self.state_key(model, selected)
        from packages.providers.settings import _locked
        started = time.monotonic()
        def update(**fields):
            if time.monotonic() - started > 3600:
                raise ValueError('LOCAL_MODEL_DOWNLOAD_TIMEOUT')
            with self.lock:
                self.states[key].update(fields)
        try:
            self.backend(model, backend=selected)
            # Cross-process cache lock and one active download. No shared secret storage.
            with _locked(self.cache):
                if not self.installed(model, selected):
                    root = self.cache / (model['id'] + '-' + model['revision'])
                    with self.client(timeout=60) as client:
                        download(model, root, client, update)
                    update(status='loading')
                    try:
                        with self.client(timeout=600) as client:
                            response = client.post(self.runner(model, selected) + '/models/load', content=archive(model, root),
                                                   headers={'Content-Type': 'application/x-tar'})
                            response.raise_for_status()
                    except httpx.HTTPError:
                        raise ValueError('LOCAL_MODEL_LOAD_FAILED') from None
                    if not self.installed(model, selected):
                        raise ValueError('LOCAL_MODEL_LOAD_FAILED')
                with self.inference_lock:
                    self.reserve_gpu(model, selected)
                    # Unloading a DMR model also removes its runtime configuration.
                    # Recheck effective flags instead of caching a preparation receipt.
                    if not self.configuration_matches(model, selected):
                        with self.client(timeout=30) as client:
                            response = client.post(self.runner(model, selected) + '/engines/' + engine(model, selected) + '/_configure', json={
                                'model': artifact(model)['id'], 'context-size': model['context_size'],
                                'keep_alive': '30s', 'runtime-flags': runtime_flags(model, selected)})
                            if response.status_code not in (200, 202, 204):
                                raise ValueError('LOCAL_MODEL_BACKEND_CONFIG')
            update(status='ready')
        except Exception as exc:
            allowed = {'LOCAL_MODEL_HASH', 'LOCAL_MODEL_PATH', 'LOCAL_MODEL_DOWNLOAD_TIMEOUT',
                       'LOCAL_MODEL_LOAD_FAILED', 'LOCAL_MLX_UNAVAILABLE', 'LOCAL_VLLM_UNAVAILABLE', 'LOCAL_GGUF_UNAVAILABLE',
                       'LOCAL_CUDA_PROBE_MISSING', 'LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED',
                       'LOCAL_MODEL_BACKEND_CONFIG', 'LOCAL_MODEL_BUSY'}
            code = str(exc) if str(exc) in allowed else 'LOCAL_MODEL_DOWNLOAD_FAILED'
            with self.lock:
                self.states[key].update(status='failed', code=code)


def create_app(*, cache=None, transport=None, formats=None, vllm_dmr=None, gguf_dmr=None, backends=None):
    app = FastAPI(docs_url=None, redoc_url=None)
    manager = Manager(cache or os.environ.get('LOCAL_MODEL_CACHE', '/model_cache'), transport, formats, vllm_dmr, gguf_dmr, backends)
    app.state.manager = manager

    def lookup(identifier, backend=None):
        try:
            model = get_model(identifier)
        except ValueError:
            raise HTTPException(404, 'LOCAL_MODEL_UNKNOWN') from None
        try:
            select_backend(model, backend)
        except ValueError:
            raise HTTPException(409, 'LOCAL_MODEL_BACKEND_UNSUPPORTED') from None
        return model

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/models')
    def catalog(purpose: Literal['translation', 'analysis', 'all'] = 'translation'):
        statuses = {}
        available = []
        for model in public_models(purpose=purpose):
            pinned = get_model(model['id'])
            if selectable_format(pinned) in manager.formats:
                choices = [backend for backend in compatible_backends(pinned) if backend in manager.backends]
                states = {}
                for backend in choices:
                    runner = manager.runner(pinned, backend)
                    if runner not in statuses:
                        try:
                            statuses[runner] = manager.engine_status(pinned, backend)
                        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                            statuses[runner] = {}
                    states[backend] = manager.state(pinned, statuses[runner], backend)
                default = states.get(model['default_backend'], {'status': 'unavailable', 'code': 'LOCAL_MODEL_BACKEND_UNSUPPORTED'})
                available.append({**model, **default, 'inference_backends': choices, 'backend_states': states})
        return {'models': available}

    @app.get('/models/{identifier}')
    def status(identifier: str, backend: Backend | None = None):
        return manager.state(lookup(identifier, backend), backend=backend)

    @app.post('/models/{identifier}/prepare', status_code=202)
    def prepare(identifier: str, backend: Backend | None = None):
        model = lookup(identifier, backend)
        if not manager.supported(model, backend):
            raise HTTPException(409, 'LOCAL_MODEL_FORMAT_UNSUPPORTED' if selectable_format(model) not in manager.formats else 'LOCAL_MODEL_BACKEND_UNSUPPORTED')
        return manager.prepare(model, backend)

    @app.post('/v1/completions')
    def complete(body: Completion):
        model = lookup(body.model, body.backend)
        if body.model != artifact(model)['id'] or body.stream:
            raise HTTPException(422, 'LOCAL_MODEL_CONFIG')
        if not manager.supported(model, body.backend):
            raise HTTPException(409, 'LOCAL_MODEL_FORMAT_UNSUPPORTED' if selectable_format(model) not in manager.formats else 'LOCAL_MODEL_BACKEND_UNSUPPORTED')
        if model.get('purpose') == 'analysis':
            if (body.prompt is not None or body.add_special_tokens
                    or body.chat_template_kwargs != {'enable_thinking': False}
                    or not body.messages or len(body.messages) != 2
                    or [m.get('role') for m in body.messages] != ['system', 'user']
                    or any(set(m) != {'role', 'content'} or not m['content'].strip() for m in body.messages)
                    or sum(len(m['content'].encode()) for m in body.messages) + 256 + body.max_tokens > model['context_size']):
                raise HTTPException(422, 'LOCAL_MODEL_PROMPT')
            route = '/chat/completions'
        elif model['family'] == 'hy':
            if (body.prompt is not None or not body.messages or len(body.messages) != 1
                    or body.chat_template_kwargs is not None
                    or set(body.messages[0]) != {'role', 'content'} or body.messages[0]['role'] != 'user'
                    or len(body.messages[0]['content'].encode()) + 256 + body.max_tokens > model['context_size']):
                raise HTTPException(422, 'LOCAL_MODEL_PROMPT')
            route = '/chat/completions'
        else:
            if (body.messages is not None or body.prompt is None or body.add_special_tokens
                    or body.chat_template_kwargs is not None
                    or len(body.prompt.encode()) + 256 + body.max_tokens > model['context_size']):
                raise HTTPException(422, 'LOCAL_MODEL_PROMPT')
            route = '/completions'
        # No downloads or reconfiguration after dispatch. This call either runs the exact model or fails.
        if manager.state(model, backend=body.backend)['status'] != 'ready':
            raise HTTPException(503, 'LOCAL_MODEL_NOT_READY')
        with manager.inference_lock:
            try:
                manager.reserve_gpu(model, body.backend)
                if not manager.configuration_matches(model, body.backend):
                    raise HTTPException(503, 'LOCAL_MODEL_NOT_READY')
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                raise HTTPException(503, 'LOCAL_MODEL_NOT_READY') from None
            try:
                with manager.client(timeout=300) as client:
                    response = client.post(manager.runner(model, body.backend) + '/engines/' + engine(model, body.backend) + '/v1' + route,
                                           json=body.model_dump(exclude_none=True, exclude={'backend'}))
                    if response.status_code != 200:
                        raise HTTPException(502, 'LOCAL_MODEL_INFERENCE_FAILED')
                    data = response.json()
                    if route == '/chat/completions':
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
