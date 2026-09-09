"""Cost controls are optional; application limits and immutable bindings remain explicit."""
from copy import deepcopy
import json

import pytest

from packages.billing import price
from packages.domain.config import provider_profile
from packages.domain.errors import DomainError
from packages.ir import digest
from packages.providers.settings import configuration_view, resolve_provider_credentials, save_configuration
from tests.integration.test_translation_execution import PROFILE


DEFAULTS = {'max_input_tokens': 32768, 'max_output_tokens': 8192, 'max_unit_characters': 2000}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'config'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(tmp_path / 'absent'))
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(tmp_path / 'absent-key'))
    return tmp_path / 'config'


def save(value, *, generation=0, key=None, idem='save'):
    return save_configuration(value, key, False, f'"{generation}"', idem)


def minimal(**changes):
    return {'endpoint': 'http://localhost:11434/v1/responses', 'model_id': 'local:latest', 'auth_mode': 'none', **changes}


def test_new_config_is_usable_without_prices_and_has_application_defaults(store):
    saved = save(minimal())
    assert saved['configured'] and saved['dispatch_configuration_ready']
    assert saved['cost_control_enabled'] is False
    assert {k: saved[k] for k in DEFAULTS} == DEFAULTS
    assert saved['token_limits_defaults'] == DEFAULTS
    assert 'input_micro_per_million' not in saved['price']
    frozen = provider_profile()
    assert 'token_limits_defaults' not in frozen and digest(frozen) == saved['profile_hash']
    assert resolve_provider_credentials(frozen)[3] is None


def test_unconfigured_view_shows_defaults_but_does_not_claim_configuration(store):
    public = configuration_view()
    assert not public['configured'] and public['cost_control_enabled'] is False
    assert public['token_limits_defaults'] == DEFAULTS
    assert {k: public[k] for k in DEFAULTS} == DEFAULTS
    assert not any(field.startswith('price.') or field in DEFAULTS for field in public['missing_fields'])


def test_explicit_control_requires_rates_and_never_silently_switches_off(store):
    saved = save(minimal(cost_control_enabled=True))
    assert not saved['configured'] and saved['cost_control_enabled'] is True
    assert 'price.input_micro_per_million' in saved['missing_fields']
    again = save(minimal(), generation=1, idem='omitted-flag')
    assert again['cost_control_enabled'] is True and not again['configured']


def test_omitted_flag_replay_stays_same_revision_after_later_toggle(store):
    first = save(minimal(), idem='original')
    enabled = save(minimal(cost_control_enabled=True), generation=1, idem='toggle')
    assert enabled['cost_control_enabled'] is True
    replay = save(minimal(), idem='original')
    assert replay == first
    assert configuration_view()['config_revision'] == enabled['config_revision']


def test_reset_is_normal_cas_save_of_only_limits_and_preserves_credential(store):
    entered = minimal(auth_mode='bearer', max_input_tokens=128, max_output_tokens=64, max_unit_characters=50)
    first = save(entered, key='SYNTHETIC_OPTIONAL_COST_KEY')
    frozen = provider_profile()
    reset = save(entered | configuration_view()['token_limits_defaults'], generation=1, idem='reset')
    assert {k: reset[k] for k in DEFAULTS} == DEFAULTS
    assert reset['endpoint'] == first['endpoint'] and reset['credential_revision'] == first['credential_revision']
    assert reset['profile_hash'] != first['profile_hash']
    assert resolve_provider_credentials(frozen)[0] == first['endpoint']
    assert resolve_provider_credentials(provider_profile())[3].read_text() == 'SYNTHETIC_OPTIONAL_COST_KEY'
    with pytest.raises(DomainError) as caught:
        save(entered, generation=1, idem='stale-reset')
    assert caught.value.status == 412


def test_legacy_public_hash_and_enabled_behavior_remain_unchanged(store, tmp_path, monkeypatch):
    file = tmp_path / 'legacy.json'; file.write_text(json.dumps(PROFILE))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(file))
    before = deepcopy(PROFILE)
    assert provider_profile() == before
    public = configuration_view()
    assert public['cost_control_enabled'] is True and public['profile_hash'] == digest(before)
    assert price.reserve_cost(before) > 0 and before == PROFILE


def test_off_profile_accepts_absent_price_and_reserves_no_amount():
    profile = deepcopy(PROFILE) | {'cost_control_enabled': False}
    profile.pop('price')
    assert price.validate_profile(profile) == profile
    assert price.reserve_cost(profile) is None
    with pytest.raises(ValueError): price.validate_profile(profile | {'cost_control_enabled': True})


@pytest.mark.parametrize('value', [None, 0, 1, 'false', [], {}])
def test_cost_control_flag_is_strict_boolean(store, value):
    with pytest.raises(DomainError): save(minimal(cost_control_enabled=value))


@pytest.mark.parametrize('field', list(DEFAULTS))
def test_explicit_invalid_limit_is_not_replaced_with_default(store, field):
    with pytest.raises(DomainError): save(minimal(**{field: 0}))


def test_incomplete_rates_are_preserved_while_control_is_off(store):
    saved = save(minimal(price={'input_micro_per_million': 7}))
    assert saved['configured'] and saved['price']['input_micro_per_million'] == 7
    assert 'output_micro_per_million' not in saved['price']


def test_omitted_limits_preserve_current_values_until_explicit_reset(store):
    first = save(minimal(max_input_tokens=129, max_output_tokens=65, max_unit_characters=51))
    second = save(minimal(), generation=1, idem='omitted-limits')
    assert {k: second[k] for k in DEFAULTS} == {k: first[k] for k in DEFAULTS}
    assert second['token_limits_defaults'] == DEFAULTS


def test_old_managed_bundle_without_flag_keeps_hash_and_control_on(store):
    first = save(deepcopy(PROFILE) | minimal(cost_control_enabled=True))
    path = store / 'versions' / first['config_revision'] / 'profile.json'
    legacy = json.loads(path.read_text()); legacy.pop('cost_control_enabled')
    # Controlled disk fixture models a pre-feature immutable revision.
    path.write_text(json.dumps(legacy))
    assert provider_profile() == legacy
    assert configuration_view()['profile_hash'] == digest(legacy)
    second = save(minimal(), generation=1, idem='legacy-edit')
    assert second['cost_control_enabled'] is True


def test_old_incomplete_draft_can_adopt_defaults_without_inventing_fees(store):
    first = save(minimal(model_id='', cost_control_enabled=True))
    path = store / 'versions' / first['config_revision'] / 'profile.json'
    legacy = json.loads(path.read_text()); legacy.pop('cost_control_enabled')
    for key in DEFAULTS: legacy.pop(key)
    path.write_text(json.dumps(legacy))
    assert not provider_profile()['configured']
    second = save(minimal(), generation=1, idem='complete-old-draft')
    assert second['configured'] and second['cost_control_enabled'] is False
