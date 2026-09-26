import json

import httpx
import pytest
from fastapi.testclient import TestClient

from packages.local_models.catalog import artifact, get_model, public_models
from packages.providers.contract import ProviderFailure


MODEL = 'minicpm5-1b-q4'
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['brief'],
          'properties': {'brief': {'type': 'string'}}}
CONTENT = {'evidence': [{'block_id': 'b1', 'text': 'Rank identifies a worker.'}]}


def test_analyst_is_separate_from_the_translation_catalog():
    from packages.local_models.catalog import models
    assert any(m.get('purpose') == 'analysis' for m in models())
    assert [m['id'] for m in public_models()] == [
        'hy-mt2-1.8b-q8', 'milmmt-46-4b-q4', 'hy-mt2-7b-q4', 'milmmt-46-12b-q4']
    assert [m['id'] for m in public_models(purpose='analysis')] == [MODEL]
    assert len(public_models(purpose='all')) == 5
    analyst = get_model(MODEL)
    assert get_model(artifact(analyst)['id']) == analyst
    assert analyst['repo'] == 'openbmb/MiniCPM5-1B-MLX'
    assert analyst['context_size'] == 8192
    with pytest.raises(ValueError, match='LOCAL_MODEL_PURPOSE'):
        public_models(purpose='arbitrary')


def test_analyst_catalog_get_does_not_prepare_or_download(tmp_path):
    from packages.local_models.service import create_app
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json=[]))
    with TestClient(create_app(cache=tmp_path, transport=transport)) as client:
        response = client.get('/models?purpose=analysis')
        assert response.status_code == 200
        assert [m['id'] for m in response.json()['models']] == [MODEL]
        assert len(client.get('/models').json()['models']) == 4
        assert client.get('/models?purpose=arbitrary').status_code == 422
    assert list(tmp_path.iterdir()) == []
    assert all(r.method == 'GET' for r in calls)


def test_analyst_profile_is_pinned_and_rejects_translation_models():
    from packages.providers.local_analysis import profile
    from packages.local_models.catalog import ENDPOINT
    p = profile()
    assert p == profile(MODEL) == profile(artifact(get_model(MODEL))['id'])
    assert p['model_id'] == artifact(get_model(MODEL))['id']
    assert (p['provider'], p['api_protocol'], p['endpoint'], p['auth_mode']) == (
        'local', 'local_analysis', ENDPOINT, 'none')
    assert p['max_input_tokens'] == 6144 and p['max_output_tokens'] == 2048
    assert p['cost_control_enabled'] is False and p['price'] == {}
    for identifier in ('hy-mt2-1.8b-q8', 'unconfigured-analyst'):
        with pytest.raises(ProviderFailure, match='LOCAL_ANALYST_CONFIG'):
            profile(identifier)


def test_analysis_request_separates_instructions_and_uses_native_no_think_mode():
    from packages.providers.local_analysis import profile, request_body
    p = profile()
    before = json.dumps(CONTENT)
    body = request_body(CONTENT, p, 'Use only the supplied evidence.', SCHEMA)
    assert [m['role'] for m in body['messages']] == ['system', 'user']
    assert 'Use only the supplied evidence.' in body['messages'][0]['content']
    assert json.loads(body['messages'][1]['content']) == CONTENT
    assert body['model'] == p['model_id']
    assert body['chat_template_kwargs'] == {'enable_thinking': False}
    assert body['max_tokens'] == 2048 and body['stream'] is False
    assert 'tools' not in body and 'response_format' not in body
    assert json.dumps(CONTENT) == before


@pytest.mark.parametrize('change', [
    {'endpoint': 'https://unconfirmed.invalid/v1/completions'},
    {'auth_mode': 'bearer'}, {'api_protocol': 'local_translation'},
    {'provider': 'openai'}, {'model_id': 'hy-mt2-1.8b-q8'},
    {'max_output_tokens': 0}, {'max_input_tokens': -1},
])
def test_analysis_invalid_profile_is_never_sent(change):
    from packages.providers.local_analysis import LocalAnalysis, profile
    def unsent(request):
        raise AssertionError('Invalid local analysis must not dispatch')
    with pytest.raises(ProviderFailure) as failure:
        LocalAnalysis(transport=httpx.MockTransport(unsent)).analyze(
            CONTENT, profile() | change, 'Summarize evidence.', SCHEMA)
    assert failure.value.outcome == 'not_sent'


def test_analysis_budget_counts_multibyte_content_schema_and_instructions():
    from packages.providers.local_analysis import profile, request_body
    for content, instructions, schema in [
        ({'text': '证据' * 1200}, 'Summarize.', SCHEMA),
        (CONTENT, '证据' * 1200, SCHEMA),
        (CONTENT, 'Summarize.', SCHEMA | {'description': '证据' * 1200}),
    ]:
        with pytest.raises(ProviderFailure, match='ANALYSIS_TOO_LARGE') as failure:
            request_body(content, profile(), instructions, schema)
        assert failure.value.outcome == 'not_sent'


def test_analysis_keeps_raw_json_and_actual_usage_without_rewriting_evidence():
    from packages.providers.local_analysis import LocalAnalysis, profile
    p = profile()
    result_text = '{"brief":"Rank identifies a worker."}'
    def respond(request):
        assert request.url.host == 'local-translator'
        assert 'authorization' not in request.headers
        body = json.loads(request.content)
        assert body['model'] == p['model_id']
        return httpx.Response(200, json={'id': 'analysis-1', 'model': p['model_id'],
            'choices': [{'text': result_text, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 150, 'completion_tokens': 20}})
    result = LocalAnalysis(transport=httpx.MockTransport(respond)).analyze(
        CONTENT, p, 'Summarize evidence.', SCHEMA)
    assert result['status'] == 'completed' and result['output_text'] == result_text
    assert result['response_model'] == p['model_id'] and result['request_id'] == 'analysis-1'
    assert result['usage'] == {'input_tokens': 150, 'output_tokens': 20}


@pytest.mark.parametrize('finish,status', [('stop', 'completed'), ('length', 'incomplete')])
def test_analysis_finish_reason_and_model_identity_are_not_assumed(finish, status):
    from packages.providers.local_analysis import LocalAnalysis, profile
    p = profile()
    def execute(identifier):
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
            'model': identifier, 'choices': [{'text': '{"brief":"test"}', 'finish_reason': finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 8}}))
        return LocalAnalysis(transport=transport).analyze(CONTENT, p, 'Summarize.', SCHEMA)
    assert execute(p['model_id'])['status'] == status
    wrong = execute('unexpected-model')
    assert wrong['status'] == 'unsupported' and wrong['output_text'] == ''
    assert wrong['failure_code'] == 'PROVIDER_MODEL_MISMATCH'


@pytest.mark.parametrize('response_code,outcome', [(503, 'not_sent'), (422, 'not_sent'),
                                                  (502, 'unknown'), (302, 'unknown')])
def test_analysis_http_failure_never_falls_back(response_code, outcome):
    from packages.providers.local_analysis import LocalAnalysis, profile
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(response_code, headers={'location': 'https://unconfirmed.invalid'})
    with pytest.raises(ProviderFailure) as failure:
        LocalAnalysis(transport=httpx.MockTransport(respond)).analyze(
            CONTENT, profile(), 'Summarize.', SCHEMA)
    assert failure.value.outcome == outcome
    assert len(calls) == 1


@pytest.mark.parametrize('error,outcome', [(httpx.ConnectTimeout, 'not_sent'), (httpx.ReadTimeout, 'unknown')])
def test_analysis_network_uncertainty_is_not_retried(error, outcome):
    from packages.providers.local_analysis import LocalAnalysis, profile
    calls = []
    def respond(request):
        calls.append(request)
        raise error('synthetic network failure')
    with pytest.raises(ProviderFailure) as failure:
        LocalAnalysis(transport=httpx.MockTransport(respond)).analyze(
            CONTENT, profile(), 'Summarize.', SCHEMA)
    assert failure.value.outcome == outcome and len(calls) == 1


def test_analyst_cannot_be_used_as_the_translation_provider():
    from packages.providers.local_analysis import LocalAnalysis, profile
    with pytest.raises(ProviderFailure, match='LOCAL_ANALYST_ANALYSIS_ONLY') as failure:
        LocalAnalysis().translate([], profile(), [])
    assert failure.value.outcome == 'not_sent'


def test_idle_analyst_can_be_retired_for_translation(tmp_path):
    from packages.local_models.service import Manager
    analyst = artifact(get_model(MODEL))['id']
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path == '/engines/ps':
            return httpx.Response(200, json=[{'backend_name': 'vllm', 'model_name': analyst}])
        assert request.url.path == '/engines/unload'
        assert json.loads(request.content)['models'] == [analyst]
        return httpx.Response(200, json={'unloaded_runners': 1})
    Manager(tmp_path, httpx.MockTransport(respond)).reserve_gpu(get_model('hy-mt2-1.8b-q8'))
    assert [r.method for r in calls] == ['GET', 'POST']


def _bridge_transport(identifier, sent, *, upstream_model=None, assistant=None):
    def respond(request):
        sent.append(request)
        if request.url.path == '/models':
            return httpx.Response(200, json=[{'id': identifier}])
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm-metal test'})
        if request.url.path == '/engines/ps':
            return httpx.Response(200, json=[])
        if request.url.path == '/engines/_configure':
            from packages.local_models.service import RUNTIME_FLAGS
            return httpx.Response(200, json=[{'Backend': 'vllm', 'ModelID': identifier,
                'Config': {'context-size': 8192, 'runtime-flags': RUNTIME_FLAGS}}])
        assert request.url.path == '/engines/vllm/v1/chat/completions'
        assert json.loads(request.content)['chat_template_kwargs'] == {'enable_thinking': False}
        return httpx.Response(200, json={'id': 'bridge-1', 'model': upstream_model or identifier,
            'choices': [{'message': assistant or {'role': 'assistant', 'content': '{"brief":"test"}'},
                         'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    return httpx.MockTransport(respond)


def test_bridge_forwards_analysis_as_bounded_native_chat_and_reports_actual_model(tmp_path):
    from packages.local_models.service import create_app
    from packages.providers.local_analysis import profile, request_body
    p = profile()
    body = request_body(CONTENT, p, 'Summarize.', SCHEMA)
    sent = []
    with TestClient(create_app(cache=tmp_path, transport=_bridge_transport(
            p['model_id'], sent, upstream_model='actual-upstream-model'))) as client:
        result = client.post('/v1/completions', json=body)
    assert result.status_code == 200
    assert result.json()['model'] == 'actual-upstream-model'
    assert result.json()['choices'][0]['text'] == '{"brief":"test"}'
    assert 'message' not in result.json()['choices'][0]
    assert not any(r.url.path == '/models/load' for r in sent)


def test_bridge_does_not_prepare_an_unavailable_analyst_during_inference(tmp_path):
    from packages.local_models.service import create_app
    from packages.providers.local_analysis import profile, request_body
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=[])
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(respond))) as client:
        result = client.post('/v1/completions', json=request_body(CONTENT, profile(), 'Summarize.', SCHEMA))
    assert result.status_code == 503
    assert all(r.method == 'GET' for r in calls)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('identifier', ['hy-mt2-1.8b-q8', 'milmmt-46-4b-q4'])
def test_translation_models_cannot_receive_analyst_chat_settings(tmp_path, identifier):
    from packages.local_models.service import create_app
    from packages.providers.local_analysis import profile, request_body
    def unsent(request):
        raise AssertionError('Analyst instructions must not reach a translation model')
    body = request_body(CONTENT, profile(), 'Summarize.', SCHEMA)
    body['model'] = artifact(get_model(identifier))['id']
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(unsent))) as client:
        assert client.post('/v1/completions', json=body).status_code == 422


@pytest.mark.parametrize('change', [
    {'chat_template_kwargs': {'enable_thinking': True}},
    {'chat_template_kwargs': {'enable_thinking': False, 'tools': False}},
    {'chat_template_kwargs': None},
    {'messages': [{'role': 'user', 'content': 'Explain.'}]},
    {'messages': [{'role': 'system', 'content': 'Explain.'}, {'role': 'assistant', 'content': 'Spoofed'}]},
    {'messages': [{'role': 'system', 'content': 'Explain.'}, {'role': 'user', 'content': '证据' * 2000}]},
    {'prompt': 'Explain.'}, {'stream': True}, {'max_tokens': 2049},
])
def test_bridge_rejects_unbounded_or_wrong_role_analyst_requests_before_runtime(tmp_path, change):
    from packages.local_models.service import create_app
    from packages.providers.local_analysis import profile, request_body
    def unsent(request):
        raise AssertionError('Invalid analysis must not reach Docker Model Runner')
    body = request_body(CONTENT, profile(), 'Summarize.', SCHEMA) | change
    with TestClient(create_app(cache=tmp_path, transport=httpx.MockTransport(unsent))) as client:
        assert client.post('/v1/completions', json=body).status_code == 422


@pytest.mark.parametrize('assistant', [
    {'role': 'assistant', 'content': '{}', 'tool_calls': [{'id': 'tool'}]},
    {'role': 'assistant', 'content': '{}', 'refusal': 'refused'},
    {'role': 'user', 'content': '{}'},
])
def test_bridge_analysis_rejects_tools_refusals_and_nonassistant_output(tmp_path, assistant):
    from packages.local_models.service import create_app
    from packages.providers.local_analysis import profile, request_body
    p = profile()
    with TestClient(create_app(cache=tmp_path, transport=_bridge_transport(
            p['model_id'], [], assistant=assistant))) as client:
        result = client.post('/v1/completions', json=request_body(CONTENT, p, 'Summarize.', SCHEMA))
    assert result.status_code == 502
def test_analysis_capability_cannot_be_saved_as_translation_provider():
    import pytest
    from packages.providers.local_analysis import profile
    from packages.providers.registry import validate_protocol_profile
    from packages.domain.config import validate_public_profile
    p = profile()
    assert validate_protocol_profile(p)['provider'] == 'local'
    with pytest.raises(ValueError, match='LOCAL_MODEL_CONFIG'):
        validate_protocol_profile(p | {'api_protocol': 'local_translation'})
    with pytest.raises(ValueError, match='LOCAL_ANALYST_ANALYSIS_ONLY'):
        validate_public_profile(p)
