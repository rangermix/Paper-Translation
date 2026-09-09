import json

import httpx
import pytest

from packages.providers.contract import ProviderFailure
from packages.providers.native import NativeProvider
from packages.providers.registry import validate_protocol_profile
from tests.unit.test_openai_responses import UNIT, PROFILE
from tests.unit.test_claude_messages import response as claude_response
from tests.unit.test_gemini_interactions import response as gemini_response


def profile(protocol):
    return PROFILE | {'provider': 'gemini' if protocol == 'gemini_interactions' else 'anthropic',
        'api_protocol': protocol, 'auth_mode': 'api_key', 'endpoint': 'http://127.0.0.1:19009/exact-path'}


@pytest.mark.parametrize('protocol', ['gemini_interactions', 'claude_messages'])
@pytest.mark.parametrize('status,code,outcome', [(401,'PROVIDER_CONFIG','not_executed'),
    (429,'PROVIDER_RATE_LIMIT','not_executed'), (307,'OUTCOME_UNKNOWN','unknown'), (500,'OUTCOME_UNKNOWN','unknown')])
def test_native_http_failures_do_not_redirect_retry_or_expose_credentials(tmp_path, protocol, status, code, outcome):
    key = tmp_path/'key'; key.write_text('synthetic-native-secret'); calls = []
    def wire(request):
        calls.append(request)
        assert str(request.url) == profile(protocol)['endpoint']
        assert 'synthetic-native-secret' not in request.content.decode()
        return httpx.Response(status, headers={'location': 'http://other.invalid/stolen', 'retry-after':'999'}, text='synthetic-native-secret')
    provider = NativeProvider(profile(protocol), key, httpx.MockTransport(wire))
    with pytest.raises(ProviderFailure) as error: provider.translate([UNIT], profile(protocol), [])
    assert (error.value.code,error.value.outcome) == (code,outcome)
    assert 'synthetic-native-secret' not in str(error.value)
    if status == 429: assert error.value.retry_after == 60
    assert len(calls) == 1


@pytest.mark.parametrize('changed', [{'api_protocol':'responses'}, {'auth_mode':'bearer'},
    {'provider':'openai'}, {'endpoint':'https://other.invalid/messages'}, {'api_version':'2026-09-06'}, {'model_id':'changed-model'}])
def test_changed_profile_cannot_reuse_already_bound_native_headers(tmp_path, changed):
    key = tmp_path/'key'; key.write_text('synthetic-native-secret'); calls=[]
    p = profile('claude_messages')
    provider=NativeProvider(p,key,httpx.MockTransport(lambda r: calls.append(r)))
    with pytest.raises(ProviderFailure) as error: provider.translate([UNIT],p|changed,[])
    assert error.value.outcome=='not_sent' and not calls


@pytest.mark.parametrize('version', ['2023-06-01\r\nx-api-key: bad','2026-99-99','20230601',None])
def test_api_version_is_a_valid_date_and_cannot_inject_headers(version):
    with pytest.raises(ValueError): validate_protocol_profile(profile('claude_messages')|{'api_version':version})


def test_native_connect_and_read_timeout_are_distinct_without_retry(tmp_path):
    key=tmp_path/'key';key.write_text('synthetic-native-secret')
    for failure,outcome in [(httpx.ConnectTimeout('synthetic'),'not_sent'),(httpx.ReadTimeout('synthetic'),'unknown')]:
        calls=[]
        def wire(request):
            calls.append(request);raise failure
        p=profile('gemini_interactions');provider=NativeProvider(p,key,httpx.MockTransport(wire))
        with pytest.raises(ProviderFailure) as error:provider.translate([UNIT],p,[])
        assert error.value.outcome==outcome and len(calls)==1


@pytest.mark.parametrize('protocol', ['gemini_interactions', 'claude_messages'])
@pytest.mark.parametrize('tracking', [None, '', 'r'*201, '\x00', '\n', 'valid-request-id', 'r'*200])
def test_native_tracking_metadata_cannot_break_accounting(protocol, tracking):
    p = profile(protocol) | {'auth_mode':'none'}
    value = (gemini_response if protocol == 'gemini_interactions' else claude_response)(model=p['model_id'])
    value['id'] = None
    header = 'x-request-id' if protocol == 'gemini_interactions' else 'request-id'
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=value, headers={header:tracking} if tracking is not None else {}))
    result = NativeProvider(p, transport=transport).translate([UNIT],p,[])
    expected = tracking if tracking and len(tracking)<=200 and tracking.isprintable() else None
    assert result['request_id'] == expected and result['usage'] and result['status']=='completed'


@pytest.mark.parametrize('tracking', [{}, 5, True])
def test_non_string_gemini_interaction_id_is_not_forwarded_to_ledger(tracking):
    p = profile('gemini_interactions') | {'auth_mode':'none'}
    transport = httpx.MockTransport(lambda r: httpx.Response(200,json=gemini_response(model=p['model_id'],id=tracking)))
    result = NativeProvider(p,transport=transport).translate([UNIT],p,[])
    assert result['request_id'] is None and result['usage']
