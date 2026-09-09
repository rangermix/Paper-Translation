"""Wire contracts use synthetic transports, never credentials or a live service."""
import copy
import json

import httpx
import pytest

from packages.billing.price import actual_cost
from packages.providers.contract import ProviderFailure
from packages.providers.openai_responses import OpenAIResponses, request_body
from tests.unit.test_openai_responses import PROFILE, UNIT


def profile(protocol='chat_completions', auth='bearer'):
    return PROFILE | {'endpoint': 'http://127.0.0.1:11434/custom/endpoint',
        'api_protocol': protocol, 'auth_mode': auth, 'model_id': 'local-model:latest'}


def chat_result(**changes):
    return {'id': 'chat-id', 'model': 'local-model:latest',
        'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{"results":[]}'}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20,
            'prompt_tokens_details': {'cached_tokens': 40},
            'completion_tokens_details': {'reasoning_tokens': 7}}, **changes}


def adapter(tmp_path, handler, p):
    key = tmp_path/'synthetic-key'
    key.write_text('synthetic-A-only', encoding='utf-8')
    return OpenAIResponses(key, httpx.MockTransport(handler), endpoint=p['endpoint'],
        api_protocol=p['api_protocol'], auth_mode=p['auth_mode'])


@pytest.mark.parametrize('protocol', ['responses', 'chat_completions'])
def test_explicit_url_protocol_and_model_are_sent_without_suffix_or_fallback(tmp_path, protocol):
    p = profile(protocol); calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == p['endpoint']
        assert request.headers['authorization'] == 'Bearer synthetic-A-only'
        body = json.loads(request.content)
        assert body['model'] == 'local-model:latest' and body['stream'] is False and body['store'] is False
        if protocol == 'responses':
            assert body['text']['format']['strict'] is True
            assert body['tools'] == [] and body['tool_choice'] == 'none'
            return httpx.Response(200, json={'status': 'completed', 'output': [], 'usage': {'input_tokens': 1, 'output_tokens': 2}})
        assert body['response_format']['json_schema']['strict'] is True
        assert body['max_completion_tokens'] == p['max_output_tokens']
        assert body['n'] == 1 and 'tools' not in body and 'functions' not in body
        assert body['messages'][0]['role'] == 'system'
        assert 'input' not in body and 'text' not in body and 'max_tokens' not in body
        return httpx.Response(200, json=chat_result(), headers={'x-request-id': 'request-id'})
    result = adapter(tmp_path, handler, p).translate([UNIT], p, [])
    assert result['status'] == 'completed' and len(calls) == 1


def test_chat_usage_and_review_quotes_are_normalized_without_double_billing(tmp_path):
    p = profile(); unit = UNIT | {'review_target_text': '你好'}
    def handler(request):
        body = json.loads(request.content)
        assert body['response_format']['json_schema']['name'] == 'semantic_issues'
        content = json.loads(body['messages'][1]['content'])
        assert content['units'][0]['target_text'] == '你好'
        assert 'accuracy score' in body['messages'][0]['content']
        return httpx.Response(200, json=chat_result(), headers={'x-request-id': 'request-id'})
    result = adapter(tmp_path, handler, p).review([unit], p, [])
    assert result['request_id'] == 'request-id' and result['response_model'] == 'local-model:latest'
    assert result['usage'] == {'input_tokens': 100, 'output_tokens': 20,
        'input_tokens_details': {'cached_tokens': 40}, 'output_tokens_details': {'reasoning_tokens': 7}}
    from tests.integration.test_translation_execution import PROFILE as PRICED
    assert actual_cost(PRICED['price'], result['usage']) == 120


def test_explicit_auth_none_does_not_read_key_or_send_authorization(tmp_path):
    p = profile(auth='none'); calls = []
    def handler(request):
        calls.append(request)
        assert 'authorization' not in request.headers
        return httpx.Response(200, json=chat_result())
    result = OpenAIResponses(None, httpx.MockTransport(handler), endpoint=p['endpoint'],
        api_protocol=p['api_protocol'], auth_mode='none').translate([UNIT], p, [])
    assert result['status'] == 'completed' and len(calls) == 1


@pytest.mark.parametrize('endpoint', ['file:///tmp/model', 'ftp://host/infer', 'https://user:pass@host/v1',
    'https://host/v1?key=secret', 'https://host/v1#key', 'https://host/v1?', 'https://host/v1#',
    'https://host\\evil/v1', 'https://host/v1\n'])
def test_unsafe_endpoint_rejected_before_any_transport(tmp_path, endpoint):
    p = profile() | {'endpoint': endpoint}; calls = []
    with pytest.raises(ProviderFailure) as caught:
        adapter(tmp_path, lambda request: calls.append(request), p).translate([UNIT], p, [])
    assert caught.value.outcome == 'not_sent' and calls == []


@pytest.mark.parametrize('field,value', [('api_protocol', 'auto'), ('auth_mode', 'automatic')])
def test_unknown_protocol_or_auth_fails_before_dispatch(tmp_path, field, value):
    p = profile() | {field: value}
    with pytest.raises(ProviderFailure) as caught:
        adapter(tmp_path, lambda request: pytest.fail('must not dispatch'), p).translate([UNIT], p, [])
    assert caught.value.outcome == 'not_sent'


def test_bound_adapter_refuses_profile_endpoint_or_credential_mode_change(tmp_path):
    p = profile(); provider = adapter(tmp_path, lambda r: pytest.fail('wrong binding'), p)
    with pytest.raises(ProviderFailure) as caught:
        provider.translate([UNIT], p | {'endpoint': 'http://other.local/v1/chat/completions'}, [])
    assert caught.value.outcome == 'not_sent'


@pytest.mark.parametrize('protocol', ['responses', 'chat_completions'])
def test_redirect_is_not_followed_and_unsupported_strict_format_is_not_retried(tmp_path, protocol):
    p = profile(protocol)
    for status in [307, 400]:
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(status, headers={'location': 'http://forbidden.local/collect'})
        with pytest.raises(ProviderFailure):
            adapter(tmp_path, handler, p).translate([UNIT], p, [])
        assert len(calls) == 1 and str(calls[0].url) == p['endpoint']


@pytest.mark.parametrize('finish,refusal,expected', [('length', None, 'incomplete'),
    ('stop', 'cannot comply', 'completed'), ('tool_calls', None, 'unsupported')])
def test_chat_finish_refusal_or_tools_never_become_valid_targets(tmp_path, finish, refusal, expected):
    p = profile(); response = chat_result()
    response['choices'][0]['finish_reason'] = finish
    response['choices'][0]['message']['refusal'] = refusal
    if finish == 'tool_calls': response['choices'][0]['message']['tool_calls'] = [{'id': 'not-executed'}]
    result = adapter(tmp_path, lambda r: httpx.Response(200, json=response), p).translate([UNIT], p, [])
    assert result['status'] == expected and result['refusal'] is bool(refusal)
    assert result['usage']['output_tokens'] == 20
    if finish == 'tool_calls': assert result['failure_code'] == 'PROVIDER_UNSUPPORTED_RESPONSE'


def test_missing_chat_usage_remains_unknown_not_zero(tmp_path):
    p = profile(); response = chat_result(usage=None)
    result = adapter(tmp_path, lambda r: httpx.Response(200, json=response), p).translate([UNIT], p, [])
    assert result['usage'] is None


def test_semantic_request_size_is_checked_before_dispatch():
    p = profile() | {'max_input_tokens': 8000}
    with pytest.raises(ProviderFailure) as caught:
        request_body([UNIT | {'review_target_text': 'x'*10000}], p, [], review=True)
    assert caught.value.code == 'UNIT_TOO_LARGE' and caught.value.outcome == 'not_sent'
