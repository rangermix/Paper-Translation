import json

import httpx
import pytest

from packages.providers.connection import TEST_UNIT
from packages.providers.contract import ProviderFailure, validate_output


def profile(model='hy-mt2-1.8b-q8'):
    from packages.local_models.catalog import ENDPOINT, artifact, get_model
    return {'configured': True, 'provider': 'local', 'api_protocol': 'local_translation', 'auth_mode': 'none',
            'endpoint': ENDPOINT, 'model_id': artifact(get_model(model))['id'],
            'max_input_tokens': 32768, 'max_output_tokens': 2048, 'max_unit_characters': 2000,
            'enabled_pairs': [], 'price': {}, 'cost_control_enabled': False,
            'profile_revision': 'local-v1', 'prompt_version': 'local-translation-v1', 'privacy_revision': 'local-v1'}


def test_native_milmmt_prompt_does_not_request_json():
    from packages.providers.registry import request_body
    p = profile('milmmt-46-4b-q4')
    body = request_body([TEST_UNIT], p, [])
    assert body['prompt'] == 'Translate this from English to Chinese (Simplified):\nEnglish: Hello.\nChinese (Simplified):'
    assert body['add_special_tokens'] is False
    assert 'response_format' not in body


def test_local_output_restores_repeated_protected_references_without_changing_source():
    from packages.providers.local_translation import LocalTranslation, request_body
    unit = {**TEST_UNIT, 'source_inline': [{'type': 'text', 'text': 'Value '},
            {'type': 'protected_ref', 'ref': 'n'}, {'type': 'text', 'text': ' and '}, {'type': 'protected_ref', 'ref': 'n'}],
            'protected_atoms': {'n': {'kind': 'number', 'value': '64'}}}
    original = json.dumps(unit)
    p = profile()
    def handle(request):
        body = json.loads(request.content)
        assert 'authorization' not in request.headers
        prompt = body['messages'][0]['content']
        import re
        marker = re.search(r'__PT_[a-f0-9]+_0__', prompt)[0]
        return httpx.Response(200, json={'model': p['model_id'], 'choices': [{'text': f'值 {marker} 和 {marker}', 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 10}})
    result = LocalTranslation(transport=httpx.MockTransport(handle)).translate([unit], p, [])
    nodes = validate_output(result['output_text'], [unit])[unit['unit_id']]
    assert [n['ref'] for n in nodes if n['type'] == 'protected_ref'] == ['n', 'n']
    assert json.dumps(unit) == original


@pytest.mark.parametrize('change', [{'model': 'wrong'}, {'choices': [{'text': '你好', 'finish_reason': 'length'}]}])
def test_identity_mismatch_and_truncation_are_not_success(change):
    from packages.providers.local_translation import LocalTranslation
    p = profile()
    wire = {'model': p['model_id'], 'choices': [{'text': '你好', 'finish_reason': 'stop'}], **change}
    result = LocalTranslation(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=wire))).translate([TEST_UNIT], p, [])
    assert result.get('failure_code') == 'PROVIDER_MODEL_MISMATCH' or result['status'] != 'completed'


def test_local_profile_cannot_send_credentials_or_change_endpoint():
    from packages.domain.config import validate_public_profile
    validate_public_profile(profile())
    for values in ({'auth_mode': 'bearer'}, {'endpoint': 'https://cloud.example/completions'}, {'semantic_review_enabled': True}):
        with pytest.raises(ValueError):
            validate_public_profile({**profile(), **values})


def test_unknown_after_send_has_no_implicit_retry():
    from packages.providers.local_translation import LocalTranslation
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout('synthetic')
    with pytest.raises(ProviderFailure) as exc:
        LocalTranslation(transport=httpx.MockTransport(handle)).translate([TEST_UNIT], profile(), [])
    assert exc.value.outcome == 'unknown'
    assert len(calls) == 1


def test_catalog_slug_cannot_be_saved_as_frozen_identity():
    from packages.domain.config import validate_public_profile
    with pytest.raises(ValueError):
        validate_public_profile({**profile(), 'model_id': 'hy-mt2-1.8b-q8'})


def test_local_switch_preserves_previous_external_configuration_and_key(tmp_path, monkeypatch):
    from packages.providers.settings import save_configuration, configuration_view, resolve_provider_credentials
    from packages.domain.config import provider_profile
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'provider'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(tmp_path / 'missing.json'))
    external = {**profile(), 'provider': 'openai', 'api_protocol': 'chat_completions', 'auth_mode': 'bearer',
                'endpoint': 'https://synthetic.invalid/v1/chat/completions', 'model_id': 'external-custom'}
    save_configuration(external, 'synthetic-key', False, '"0"', 'external')
    save_configuration(profile(), None, False, '"1"', 'local')
    assert configuration_view()['previous_external']['model_id'] == 'external-custom'
    assert resolve_provider_credentials(provider_profile())[3] is None
    saved = save_configuration(external, None, False, '"2"', 'restore')
    assert saved['has_api_key']
    assert resolve_provider_credentials(provider_profile())[3].read_text() == 'synthetic-key'


def test_legacy_cloud_configuration_survives_first_local_save(tmp_path, monkeypatch):
    from packages.domain.config import provider_profile
    from packages.providers.settings import configuration_view, save_configuration, resolve_provider_credentials
    external = {**profile(), 'provider': 'openai', 'api_protocol': 'chat_completions', 'auth_mode': 'bearer',
                'endpoint': 'https://synthetic.invalid/v1/chat/completions', 'model_id': 'legacy-custom'}
    path = tmp_path / 'legacy.json'; path.write_text(json.dumps(external))
    key = tmp_path / 'legacy.key'; key.write_text('synthetic-key')
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'store'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(path))
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(key))
    saved = save_configuration(profile(), None, False, '"0"', 'local')
    assert saved['previous_external']['model_id'] == 'legacy-custom'
    assert configuration_view()['previous_external']['model_id'] == 'legacy-custom'
    saved = save_configuration(external, None, False, '"1"', 'restore')
    assert saved['has_api_key'] and saved['dispatch_configuration_ready']
    assert resolve_provider_credentials(provider_profile())[3].read_text() == 'synthetic-key'


def test_planner_fits_dense_references_and_multibyte_context():
    from pathlib import Path
    from packages.translation.planner import plan_units
    from packages.providers.local_translation import request_body
    source = json.loads(Path('tests/fixtures/sample-document.json').read_text())['source_revision']
    block = next(b for b in source['blocks'] if b['translatable'])
    block.update(parent_id=None, normalized_text='测试' * 1000,
                 source_inline=[{'type': 'protected_ref', 'ref': f'n{i}'} for i in range(250)])
    source['blocks'] = [block]
    source['protected_atoms'] = {f'n{i}': {'kind': 'number', 'value': '1'} for i in range(250)}
    units = plan_units(source, 'zh-Hans', profile(), nonblocking=True)
    assert len(units) > 1
    assert sum(len(u['source_inline']) for u in units) == 250
    for unit in units:
        request_body([unit], profile(), [])
    block['source_inline'] = [{'type': 'text', 'text': '测试' * 1000}]
    block['language'] = 'zh-Hans'
    units = plan_units(source, 'en', profile(), nonblocking=True)
    for unit in units:
        request_body([unit], profile(), [])
