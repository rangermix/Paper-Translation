"""Synthetic native Messages request/response contracts; no HTTP or credentials."""
import copy
import json

import httpx
import pytest

from packages.billing.price import actual_cost
from packages.ir import canonical_bytes
from packages.providers.claude_messages import normalize_response, request_body
from packages.providers.contract import OUTPUT_SCHEMA, REVIEW_SCHEMA, ProviderFailure, validate_output
from tests.unit.test_openai_responses import PROFILE, UNIT as BASE_UNIT

PRICE = {'revision': 'synthetic-explicit-price', 'currency': 'USD', 'input_micro_per_million': 1_000_000,
    'cached_input_micro_per_million': 100_000, 'output_micro_per_million': 2_000_000,
    'output_includes_reasoning': True, 'input_bound_rule': 'utf8-byte-ceiling-v1'}
UNIT = BASE_UNIT | {'source_inline': [{'type': 'text', 'text': 'There are '},
    {'type': 'protected_ref', 'ref': 'count'}, {'type': 'text', 'text': ' tasks; preserve '},
    {'type': 'protected_ref', 'ref': 'count'}], 'protected_atoms': {'count': {'kind': 'number', 'value': '64'}},
    'context': {'heading': 'Synthetic throughput'}}


def profile():
    return PROFILE | {'provider': 'anthropic', 'api_protocol': 'claude_messages',
        'endpoint': 'https://api.anthropic.com/v1/messages', 'auth_mode': 'api_key',
        'model_id': 'configured-claude-model', 'api_key': 'SYNTHETIC_NEVER_IN_WIRE'}


def response(**changes):
    return {'type': 'message', 'role': 'assistant', 'id': 'message-id-not-request-id',
        'model': 'configured-claude-model', 'content': [{'type': 'text', 'text': '{"results":[]}'}],
        'stop_reason': 'end_turn', 'stop_details': None,
        'usage': {'input_tokens': 100, 'output_tokens': 30, 'cache_read_input_tokens': 40,
            'cache_creation_input_tokens': 0, 'output_tokens_details': {'thinking_tokens': 7}}, **changes}


def normalize(value):
    return normalize_response(value, httpx.Response(200, headers={'request-id': 'actual-claude-request-id'}))


@pytest.mark.parametrize('review', [False, True])
def test_native_schema_request_has_no_openai_storage_tools_or_automatic_cache(review):
    unit = copy.deepcopy(UNIT) | {'review_target_text': '准确译文'}
    before = copy.deepcopy(unit)
    body = request_body([unit], profile(), [{'source': 'term', 'target': '术语'}], review=review)
    assert body['model'] == 'configured-claude-model' and body['max_tokens'] == PROFILE['max_output_tokens']
    assert body['stream'] is False
    assert body['output_config'] == {'format': {'type': 'json_schema', 'schema': REVIEW_SCHEMA if review else OUTPUT_SCHEMA}}
    assert set(body) == {'model', 'max_tokens', 'system', 'messages', 'stream', 'output_config'}
    payload = json.loads(body['messages'][0]['content'])
    assert body['messages'][0]['role'] == 'user'
    assert payload['units'][0]['source_inline'] == UNIT['source_inline']
    assert payload['units'][0]['protected_atoms'] == UNIT['protected_atoms']
    assert payload['units'][0]['context'] == UNIT['context']
    assert ('target_text' in payload['units'][0]) is review
    assert unit == before
    assert 'SYNTHETIC_NEVER_IN_WIRE' not in json.dumps(body)
    body['output_config']['format']['schema']['properties'].clear()
    assert ('issues' if review else 'results') in (REVIEW_SCHEMA if review else OUTPUT_SCHEMA)['properties']


def test_single_repair_instruction_and_actual_request_size_bound_include_review_target():
    unit = copy.deepcopy(UNIT) | {'repair_reason': 'invalid schema', 'review_target_text': 'x' * 10000}
    body = request_body([unit], profile(), [])
    assert 'single allowed repair' in body['system']
    with pytest.raises(ProviderFailure) as error:
        request_body([unit], profile() | {'max_input_tokens': len(canonical_bytes(body)) + 4096}, [], review=True)
    assert error.value.code == 'UNIT_TOO_LARGE' and error.value.outcome == 'not_sent'


@pytest.mark.parametrize('override', [{'provider': 'openai'}, {'api_protocol': 'responses'}])
def test_mismatched_profile_cannot_use_messages_wire(override):
    with pytest.raises(ProviderFailure) as error:
        request_body([UNIT], profile() | override, [])
    assert error.value.outcome == 'not_sent'


def test_cache_read_counts_add_to_total_input_and_reasoning_is_not_charged_twice():
    value = normalize(response())
    assert value['request_id'] == 'actual-claude-request-id'
    assert value['usage']['input_tokens'] == 140
    assert value['usage']['output_tokens'] == 30
    assert value['usage']['input_tokens_details'] == {'cached_tokens': 40, 'cache_write_tokens': 0}
    assert value['usage']['output_tokens_details'] == {'reasoning_tokens': 7}
    price = PRICE | {'input_micro_per_million': 1_000_000,
        'cached_input_micro_per_million': 100_000, 'output_micro_per_million': 2_000_000}
    assert actual_cost(price, value['usage']) == 100 + 4 + 60


def test_cache_writes_preserve_ttl_but_never_use_normal_input_price():
    usage = {'input_tokens': 100, 'output_tokens': 30, 'cache_read_input_tokens': 40,
        'cache_creation_input_tokens': 50, 'cache_creation': {'ephemeral_5m_input_tokens': 20, 'ephemeral_1h_input_tokens': 30}}
    value = normalize(response(usage=usage))['usage']
    assert value['input_tokens'] == 190
    assert value['input_tokens_details']['cache_write_tokens'] == 50
    assert value['input_tokens_details']['cache_creation'] == usage['cache_creation']
    with pytest.raises(ValueError, match='UNPRICED_USAGE_DIMENSION'):
        actual_cost(PRICE, value)


@pytest.mark.parametrize('usage', [None, [], {}, {'input_tokens': 1}, {'input_tokens': 1, 'output_tokens': None},
    {'input_tokens': True, 'output_tokens': 2}, {'input_tokens': -1, 'output_tokens': 2},
    {'input_tokens': 1, 'output_tokens': 2, 'cache_read_input_tokens': None},
    {'input_tokens': 1, 'output_tokens': 2, 'cache_creation_input_tokens': 'SYNTHETIC_BAD_COUNTER'}])
def test_missing_or_invalid_usage_never_becomes_zero_cost(usage):
    value = normalize(response(usage=usage))['usage']
    assert 'SYNTHETIC_BAD_COUNTER' not in json.dumps(value)
    with pytest.raises(ValueError):
        actual_cost(PRICE, value)


def test_optional_absent_cache_and_reasoning_details_accept_authoritative_totals():
    usage = normalize(response(usage={'input_tokens': 10, 'output_tokens': 20, 'output_tokens_details': None}))['usage']
    assert usage == {'input_tokens': 10, 'output_tokens': 20, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}


@pytest.mark.parametrize('stop,status,refusal', [('end_turn', 'completed', False), ('max_tokens', 'incomplete', False),
    ('model_context_window_exceeded', 'incomplete', False), ('refusal', 'completed', True)])
def test_stop_reason_normalization_preserves_accounting(stop, status, refusal):
    value = normalize(response(stop_reason=stop))
    assert (value['status'], value['refusal']) == (status, refusal)
    assert value['usage']['input_tokens'] == 140


@pytest.mark.parametrize('stop', ['tool_use', 'pause_turn', 'stop_sequence', None, 'new_unrecognized_reason'])
def test_unrequested_stop_modes_cannot_trigger_continuation_or_a_target(stop):
    value = normalize(response(stop_reason=stop))
    assert value['failure_code'] == 'PROVIDER_UNSUPPORTED_RESPONSE'
    assert value['output_text'] == '' and value['usage']['output_tokens'] == 30


def test_thinking_is_ignored_but_final_text_still_undergoes_original_contract():
    target = [{'type': 'text', 'text': '翻译'}, *[n for n in UNIT['source_inline'] if n['type'] == 'protected_ref']]
    text = json.dumps({'results': [{'unit_id': UNIT['unit_id'], 'target_inline': target}]})
    value = normalize(response(content=[{'type': 'thinking', 'thinking': 'not target text'},
        {'type': 'redacted_thinking', 'data': 'opaque'}, {'type': 'text', 'text': text}]))
    assert value['output_text'] == text
    assert validate_output(value['output_text'], [UNIT]) == {UNIT['unit_id']: target}
    assert 'not target text' not in json.dumps(value)


@pytest.mark.parametrize('block', [{'type': 'tool_use', 'name': 'run', 'input': {'command': 'SYNTHETIC_ACTION'}},
    {'type': 'server_tool_use'}, {'type': 'image'}, {'type': 'text', 'text': []}, None])
def test_unsolicited_actions_or_nontext_blocks_remain_inert(block):
    value = normalize(response(content=[block]))
    assert value['failure_code'] == 'PROVIDER_UNSUPPORTED_RESPONSE'
    assert value['output_text'] == '' and value['usage']['output_tokens'] == 30
    assert 'SYNTHETIC_ACTION' not in json.dumps(value)


def test_empty_refusal_keeps_counts_but_marks_uncertain_billing():
    value = normalize(response(content=[], stop_reason='refusal', stop_details={'type': 'refusal', 'explanation': 'SYNTHETIC_RAW'}))
    assert value['refusal'] and value['usage']['billing_unconfirmed'] is True
    assert value['usage']['input_tokens'] == 140 and value['output_text'] == ''
    assert 'SYNTHETIC_RAW' not in json.dumps(value)
    partial = normalize(response(stop_reason='refusal'))
    assert 'billing_unconfirmed' not in partial['usage']


def test_refusal_stop_details_cannot_be_accepted_as_normal_completion():
    value = normalize(response(stop_details={'type': 'refusal'}))
    assert value['refusal'] is True


@pytest.mark.parametrize('extra,dimension', [({'server_tool_use': {'web_search_requests': 1, 'web_fetch_requests': 0}}, 'server_tool_use'),
    ({'iterations': [{'input_tokens': 12, 'output_tokens': 2}]}, 'iterations')])
def test_unrequested_paid_dimensions_are_explicitly_flagged(extra, dimension):
    value = normalize(response(usage=response()['usage'] | extra))['usage']
    assert dimension in value['unpriced_usage_dimensions']


def test_inconsistent_cache_ttl_counters_mark_billing_unconfirmed():
    value = normalize(response(usage=response()['usage'] | {'cache_creation': {'ephemeral_5m_input_tokens': 12, 'ephemeral_1h_input_tokens': 0}}))
    assert value['usage']['billing_unconfirmed'] is True


def test_non_message_envelope_is_not_exposed_as_target_or_diagnostic_text():
    value = normalize({'type': 'error', 'error': {'message': 'SYNTHETIC_RAW'}})
    assert value['failure_code'] == 'PROVIDER_UNSUPPORTED_RESPONSE' and value['usage'] is None
    assert 'SYNTHETIC_RAW' not in json.dumps(value)
    no_header = normalize_response(response(), httpx.Response(200))
    assert no_header['request_id'] is None
