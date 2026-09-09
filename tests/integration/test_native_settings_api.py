"""Native protocol settings through HTTP and real PostgreSQL, no provider calls."""
import pytest

from packages.providers.registry import PROTOCOLS
from tests.integration.test_provider_settings_api import put, settings_store
from tests.unit.test_provider_settings_store import complete

pytestmark = pytest.mark.postgres


def native_profile(protocol):
    return complete(**PROTOCOLS[protocol], api_protocol=protocol)


@pytest.mark.parametrize('protocol', ['gemini_interactions', 'claude_messages'])
def test_native_settings_derive_identity_keep_key_and_clear_readiness(client, settings_store, protocol):
    profile = native_profile(protocol)
    profile.pop('provider'); profile.pop('auth_mode')
    saved = put(client, profile, 'SYNTHETIC_NATIVE_SETTINGS')
    assert saved.status_code == 200, saved.text
    view = saved.json()
    assert view['provider'] == PROTOCOLS[protocol]['provider']
    assert view['auth_mode'] == 'api_key' and view['dispatch_configuration_ready']
    if protocol == 'claude_messages': assert view['api_version'] == '2023-06-01'
    else: assert 'api_version' not in view
    assert 'SYNTHETIC_NATIVE_SETTINGS' not in saved.text
    assert client.get('/api/v1/settings/provider').json()['profile_hash'] == view['profile_hash']
    kept = put(client, profile, generation=1, operation='retain-native')
    assert kept.status_code == 200 and kept.json()['has_api_key']
    cleared = put(client, profile, generation=2, operation='clear-native', clear=True)
    assert cleared.status_code == 200 and not cleared.json()['dispatch_configuration_ready']
    assert 'api_key' in cleared.json()['missing_fields']


@pytest.mark.parametrize('protocol,mutation', [
    ('gemini_interactions', {'provider':'anthropic'}),
    ('claude_messages', {'provider':'gemini'}),
    ('gemini_interactions', {'auth_mode':'bearer'}),
    ('claude_messages', {'auth_mode':'bearer'}),
    ('gemini_interactions', {'api_version':'2023-06-01'}),
    ('claude_messages', {'api_version':'2026-99-99'}),
])
def test_native_settings_reject_inconsistent_wire_identity(client, settings_store, protocol, mutation):
    result = put(client, native_profile(protocol) | mutation, 'SYNTHETIC_NATIVE_SETTINGS')
    assert result.status_code == 422, result.text
    assert 'SYNTHETIC_NATIVE_SETTINGS' not in result.text
    assert not (settings_store/'current.json').exists()


def test_cross_provider_blank_key_cannot_reuse_credentials(client, settings_store):
    assert put(client, native_profile('gemini_interactions'), 'SYNTHETIC_GEMINI_KEY').status_code == 200
    switched = put(client, native_profile('claude_messages'), generation=1, operation='switch-native')
    assert switched.status_code == 409
    assert switched.json()['error']['code'] == 'PROVIDER_KEY_REBIND_REQUIRED'
    assert client.get('/api/v1/settings/provider').json()['provider'] == 'gemini'


def test_native_draft_without_endpoint_never_resolves_to_openai(client, settings_store):
    result = put(client, {'api_protocol':'gemini_interactions','model_id':'synthetic-native'})
    assert result.status_code == 200 and not result.json()['configured']
    assert 'endpoint' not in result.json()
    assert 'endpoint' in result.json()['missing_fields']
