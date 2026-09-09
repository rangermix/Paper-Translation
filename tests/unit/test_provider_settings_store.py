import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from packages.domain.config import provider_profile
from packages.domain.errors import DomainError
from packages.providers.contract import ProviderFailure
from packages.providers.settings import configuration_view, resolve_provider_credentials, save_configuration
from tests.integration.test_translation_execution import PROFILE


def complete(**changes):
    value = copy.deepcopy(PROFILE)
    value.update(endpoint='http://localhost:11434/v1/chat/completions', api_protocol='chat_completions', auth_mode='bearer', cost_control_enabled=True)
    value.update(changes)
    return value


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / 'provider-config'
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(root))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(tmp_path / 'absent-profile'))
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(tmp_path / 'absent-key'))
    return root


def save(profile, key=None, *, generation=0, operation='first', clear=False):
    return save_configuration(profile, key, clear, f'"{generation}"', operation)


def test_partial_config_keeps_input_without_invented_prices(store):
    public = save({'endpoint': 'http://localhost:11434/v1/chat/completions', 'model_id': 'local:latest', 'cost_control_enabled': True}, 'synthetic-private-key')
    assert not public['configured'] and public['has_api_key']
    assert public['max_input_tokens'] == 32768 and 'price.input_micro_per_million' in public['missing_fields']
    assert 'input_micro_per_million' not in public['price']
    assert provider_profile()['model_id'] == 'local:latest'
    with pytest.raises(ProviderFailure):
        resolve_provider_credentials(provider_profile())
    for path in store.rglob('*'):
        if path.is_file() and path.name != 'key':
            assert b'synthetic-private-key' not in path.read_bytes()


def test_free_local_model_without_auth_requires_no_key(store):
    profile = complete(model_id='local:latest', auth_mode='none')
    for name in ('input_micro_per_million', 'cached_input_micro_per_million', 'output_micro_per_million'):
        profile['price'][name] = 0
    saved = save(profile)
    assert saved['configured'] and saved['dispatch_configuration_ready'] and not saved['has_api_key']
    assert resolve_provider_credentials(provider_profile()) == (profile['endpoint'], 'chat_completions', 'none', None)


def test_versions_bind_old_endpoint_and_old_credential_and_blank_retains(store):
    first = save(complete(), 'synthetic-key-A')
    a = provider_profile()
    retained = save(complete(max_output_tokens=512), '', generation=1, operation='second')
    assert retained['credential_revision'] == first['credential_revision']
    assert retained['profile_hash'] != first['profile_hash']
    second = save(complete(endpoint='https://second.invalid/v1/responses', api_protocol='responses'),
                  'synthetic-key-B', generation=2, operation='third')
    b = provider_profile()
    assert second['credential_revision'] != first['credential_revision']
    assert resolve_provider_credentials(a)[0] == a['endpoint']
    assert resolve_provider_credentials(a)[3].read_text() == 'synthetic-key-A'
    assert resolve_provider_credentials(b)[3].read_text() == 'synthetic-key-B'
    with pytest.raises(ProviderFailure):
        resolve_provider_credentials({**a, 'endpoint': b['endpoint']})
    with pytest.raises(ProviderFailure):
        resolve_provider_credentials({**a, 'credential_revision': b['credential_revision']})


@pytest.mark.parametrize('change', [{'endpoint': 'https://other.invalid/v1/responses'}, {'api_protocol': 'responses'}, {'auth_mode': 'none'}])
def test_credential_rebinding_needs_explicit_action(store, change):
    save(complete(), 'synthetic-key-A')
    with pytest.raises(DomainError) as error:
        save(complete(**change), '', generation=1, operation='unsafe-rebind')
    assert error.value.code == 'PROVIDER_KEY_REBIND_REQUIRED'
    assert configuration_view()['generation'] == 1


def test_clear_does_not_switch_auth_or_destroy_inflight_revision(store):
    save(complete(), 'synthetic-key-A')
    original = provider_profile()
    cleared = save(complete(), clear=True, generation=1, operation='clear')
    assert cleared['auth_mode'] == 'bearer' and not cleared['has_api_key']
    assert 'api_key' in cleared['missing_fields'] and not cleared['dispatch_configuration_ready']
    with pytest.raises(ProviderFailure):
        resolve_provider_credentials(provider_profile())
    assert resolve_provider_credentials(original)[3].read_text() == 'synthetic-key-A'


def test_idempotency_distinguishes_secret_changes_without_public_secret_hash(store):
    first = save(complete(), 'synthetic-key-A')
    again = save(complete(), 'synthetic-key-A')
    assert again == first
    with pytest.raises(DomainError) as error:
        save(complete(), 'synthetic-key-B')
    assert error.value.code == 'IDEMPOTENCY_CONFLICT'
    assert configuration_view()['generation'] == 1
    for path in store.rglob('*.json'):
        assert 'synthetic-key-' not in path.read_text()


def test_concurrent_cas_has_exactly_one_winner(store):
    save(complete(), 'synthetic-key-A')
    barrier = Barrier(2)
    def update(index):
        barrier.wait()
        try:
            return save(complete(model_id='variant-' + str(index)), generation=1, operation='race-' + str(index))['generation']
        except DomainError as error:
            return error.status
    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(update, (1, 2))) == [2, 412]
    assert configuration_view()['generation'] == 2


def test_uncommitted_bundle_never_replaces_current_on_pointer_failure(store, monkeypatch):
    import packages.providers.settings as settings
    saved = save(complete(), 'synthetic-key-A')
    original_replace = settings.os.replace
    def fail(*args):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(settings.os, 'replace', fail)
    with pytest.raises(OSError):
        save(complete(model_id='new'), 'synthetic-key-B', generation=1, operation='second')
    assert configuration_view()['profile_hash'] == saved['profile_hash']
    monkeypatch.setattr(settings.os, 'replace', original_replace)
    retried = save(complete(model_id='new'), 'synthetic-key-B', generation=1, operation='second')
    assert retried['generation'] == 2


@pytest.mark.parametrize('endpoint', ['https://user:password@example.invalid/v1/responses', 'https://example.invalid/v1/responses?token=secret',
                                    'https://example.invalid/v1/responses#fragment', 'file:///tmp/key', 'http://example.invalid'])
def test_non_public_or_incomplete_request_endpoint_rejected(store, endpoint):
    with pytest.raises(DomainError) as error:
        save(complete(endpoint=endpoint), 'synthetic-key-A')
    assert error.value.status == 422
    assert not (store / 'current.json').exists()


def test_corrupt_managed_pointer_does_not_fall_back_to_external_key(store, monkeypatch, tmp_path):
    external = tmp_path / 'public.json'
    external.write_text(json.dumps(PROFILE))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(external))
    store.mkdir()
    (store / 'current.json').write_text('{bad')
    assert not provider_profile()['configured']
    with pytest.raises(ProviderFailure):
        resolve_provider_credentials(PROFILE)


def test_external_file_fallback_preserves_hash_and_uses_exact_bound_profile(store, monkeypatch, tmp_path):
    from packages.ir import digest
    path = tmp_path / 'legacy-profile.json'
    key = tmp_path / 'legacy-key'
    path.write_text(json.dumps(PROFILE))
    key.write_text('SYNTHETIC_LEGACY_KEY')
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(path))
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(key))
    assert provider_profile() == PROFILE
    view = configuration_view()
    assert view['has_api_key'] is None and view['profile_hash'] == digest(PROFILE)
    assert resolve_provider_credentials(PROFILE)[3] == key
    changed = {**PROFILE, 'model_id': 'new-external-model'}
    path.write_text(json.dumps(changed))
    with pytest.raises(ProviderFailure):
        resolve_provider_credentials(PROFILE)
    assert resolve_provider_credentials(changed)[3] == key


def test_incomplete_config_preserves_key_without_bound_endpoint_change(store):
    first = save({'model_id': 'local:latest'}, 'SYNTHETIC_KEY')
    second = save({'model_id': 'local:latest', 'max_input_tokens': 128}, generation=1, operation='limits')
    assert first['has_api_key'] and second['has_api_key']
    with pytest.raises(DomainError) as error:
        save({'model_id': 'local:latest', 'endpoint': 'http://localhost:11434/v1/responses'}, generation=2, operation='bind')
    assert error.value.code == 'PROVIDER_KEY_REBIND_REQUIRED'


@pytest.mark.parametrize('field', ['input_tokens_details', 'output_tokens_details'])
@pytest.mark.parametrize('details', [None, [], 'wrong'])
def test_invalid_usage_details_fail_as_value_error(field, details):
    from packages.billing.price import actual_cost
    with pytest.raises(ValueError, match='USAGE_INVALID'):
        actual_cost(PROFILE['price'], {'input_tokens': 1, 'output_tokens': 2, field: details})
