"""Local analyst selection and immutable profiles; all inference is synthetic."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from packages.domain.errors import DomainError
from packages.local_models.catalog import artifact, get_model
from packages.preparation import freeze_options
from packages.providers.contract import ProviderFailure
from packages.providers.local_analysis import LocalAnalysis, profile, request_body, selection, selected_profile


GGUF = 'minicpm5-1b-q4-k-m-gguf'
MLX = 'minicpm5-1b-q4'
CONTENT = {'evidence': [{'text': 'Synthetic source evidence.'}]}
SCHEMA = {'type': 'object'}


def chosen(slug):
    model = get_model(slug)
    return {'local_analyst_model_id': artifact(model)['id'], 'local_analyst_backend': model['runtime']}


@pytest.mark.parametrize('formats,backends,expected', [
    ('gguf', 'llama.cpp', GGUF), ('mlx', 'mlx', MLX),
    ('gguf,mlx', 'llama.cpp', GGUF), ('safetensors', 'vllm', None),
])
def test_defaults_only_select_declared_compatible_models(monkeypatch, formats, backends, expected):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', formats)
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', backends)
    assert selection() == (chosen(expected) if expected else {})
    assert profile()['model_id'] == artifact(get_model(MLX))['id']  # Legacy default is unchanged.
    saved = chosen(MLX)
    assert selection(saved) == saved  # A changed deployment never rewrites an explicit choice.
    if expected == GGUF:
        with pytest.raises(DomainError):
            selected_profile(saved)


def test_freezing_new_local_options_uses_saved_choice_without_mutating_prior_snapshot(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf,mlx')
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'llama.cpp,mlx')
    preferences = chosen(GGUF)
    translator = {'model_id': 'independent-translator'}
    first = freeze_options({'mode': 'local'}, translator, preferences)
    before = json.dumps(first)
    preferences.update(chosen(MLX))
    second = freeze_options({'mode': 'local'}, translator, preferences)
    assert first['analysis_profile']['model_id'] == chosen(GGUF)['local_analyst_model_id']
    assert first['analysis_profile']['local_backend'] == 'llama.cpp'
    assert second['analysis_profile']['model_id'] == chosen(MLX)['local_analyst_model_id']
    assert json.dumps(first) == before
    assert translator == {'model_id': 'independent-translator'}
    assert 'analysis_profile' not in freeze_options({'mode': 'extractive'}, translator, preferences)


@pytest.mark.parametrize('slug,backend', [(MLX, None), (MLX, 'mlx'), (GGUF, 'llama.cpp')])
def test_dispatch_uses_exact_new_or_legacy_analyst_profile(monkeypatch, slug, backend):
    from types import SimpleNamespace
    from packages.billing.ledger import dispatch_profile
    frozen = profile(slug, backend)
    job = SimpleNamespace(payload={'preparation_options': {'mode': 'local'}, 'analysis_profile': frozen})
    task = SimpleNamespace(payload={'phase': 'preparation'})
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'safetensors')
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'vllm')
    assert dispatch_profile(job, task) == frozen
    job.payload['analysis_profile'] = frozen | {'max_input_tokens': 123}
    with pytest.raises(DomainError, match='Provider profile stale'):
        dispatch_profile(job, task)


def test_upload_pipeline_freezes_the_same_saved_analyst(monkeypatch):
    from packages.translation.pipeline import PipelineOptions, freeze_pipeline
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf')
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'llama.cpp')
    monkeypatch.setattr('packages.translation.pipeline.provider_profile', lambda: {'configured': False})
    result = freeze_pipeline(PipelineOptions(preparation={'mode': 'local'}), 'asset', chosen(GGUF))
    assert result['analysis_profile']['model_id'] == chosen(GGUF)['local_analyst_model_id']
    assert result['analysis_profile']['local_backend'] == 'llama.cpp'


@pytest.mark.parametrize('variant', ['exact', 'wrong-digest', 'wrong-file', 'wrong-root'])
def test_analysis_accepts_only_the_exact_gguf_bundle_receipt(variant):
    model = get_model(GGUF)
    p = profile(GGUF, 'llama.cpp')
    reported = '/models/bundles/sha256/' + p['model_id'].split(':')[1] + '/model/' + model['files'][0]['path']
    if variant == 'wrong-digest':
        reported = reported.replace(p['model_id'].split(':')[1], 'a' * 64)
    elif variant == 'wrong-file':
        reported = reported.replace(model['files'][0]['path'], 'other.gguf')
    elif variant == 'wrong-root':
        reported = reported.replace('/models/bundles/', '/untrusted/')
    def respond(request):
        assert json.loads(request.content)['backend'] == 'llama.cpp'
        return httpx.Response(200, json={'model': reported,
            'choices': [{'text': '{}', 'finish_reason': 'stop'}]})
    result = LocalAnalysis(transport=httpx.MockTransport(respond)).analyze(CONTENT, p, 'Summarize.', SCHEMA)
    if variant == 'exact':
        assert result['status'] == 'completed'
        assert result['response_model'] == p['model_id'] and result['reported_model_id'] == reported
    else:
        assert result['failure_code'] == 'PROVIDER_MODEL_MISMATCH' and result['output_text'] == ''


def test_explicit_backend_reaches_prepare_and_legacy_profiles_remain_unchanged(monkeypatch):
    original = httpx.Client
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.params['backend'] == 'llama.cpp'
        return httpx.Response(200, json={'status': 'ready'})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    LocalAnalysis().prepare(profile(GGUF, 'llama.cpp'))
    assert len(calls) == 1 and calls[0].url.path.endswith('/' + GGUF + '/prepare')
    legacy = profile()
    assert 'local_backend' not in legacy
    assert 'backend' not in request_body(CONTENT, legacy, 'Summarize.', SCHEMA)
    with pytest.raises(ProviderFailure, match='LOCAL_ANALYST_CONFIG'):
        request_body(CONTENT, legacy | {'local_backend': 'llama.cpp'}, 'Summarize.', SCHEMA)


def test_gguf_analyst_bridge_uses_explicit_runner_and_native_chat(tmp_path):
    from packages.local_models.service import create_app
    p = profile(GGUF, 'llama.cpp')
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.host == 'gguf-runner'
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'llama.cpp': 'Running: llama.cpp synthetic'})
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id': p['model_id']}])
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': 'llama.cpp', 'ModelID': p['model_id'],
                'Config': {'context-size': 8192, 'runtime-flags': []}}])
        assert request.url.path == '/engines/llama.cpp/v1/chat/completions'
        assert json.loads(request.content)['chat_template_kwargs'] == {'enable_thinking': False}
        assert 'backend' not in json.loads(request.content)
        return httpx.Response(200, json={'model': p['model_id'], 'choices': [
            {'message': {'role': 'assistant', 'content': '{}'}, 'finish_reason': 'stop'}]})
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(respond),
            formats='gguf', backends='llama.cpp', gguf_dmr='http://gguf-runner:12434')) as client:
        result = client.post('/v1/completions', json=request_body(CONTENT, p, 'Summarize.', SCHEMA))
    assert result.status_code == 200 and result.json()['choices'][0]['text'] == '{}'
    assert len([r for r in calls if r.method == 'POST']) == 1
    assert list(tmp_path.iterdir()) == []
