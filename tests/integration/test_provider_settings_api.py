import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from apps.api.main import create_app
from packages.domain.models import Idempotency, Job, Permit, Settings
from tests.unit.test_provider_settings_store import complete

pytestmark = pytest.mark.postgres


@pytest.fixture
def settings_store(tmp_path, monkeypatch):
    root = tmp_path / 'provider_config'
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(root))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(tmp_path / 'absent-profile'))
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(tmp_path / 'absent-secret'))
    return root


def put(client, profile, key=None, generation=0, operation='save-provider', clear=False):
    return client.put('/api/v1/settings/provider', json={'profile': profile, 'api_key': key, 'clear_api_key': clear},
                      headers={'If-Match': f'"{generation}"', 'Idempotency-Key': operation})


def test_settings_persist_across_app_recreate_without_secret_db_or_dispatch(client, database, settings_store, caplog):
    db, cfg = database
    secret = 'SYNTHETIC_ONLY_SETTINGS_KEY_NEVER_PERSIST_IN_DB'
    before = client.get('/api/v1/settings/provider')
    assert before.headers['etag'] == '"0"' and before.json()['has_api_key'] is False
    saved = put(client, complete(), secret)
    assert saved.status_code == 200, saved.text
    assert saved.headers['etag'] == '"1"' and saved.json()['has_api_key']
    assert secret not in saved.text
    with TestClient(create_app(cfg, db)) as recreated:
        current = recreated.get('/api/v1/settings/provider')
        assert current.json()['profile_hash'] == saved.json()['profile_hash']
        assert current.json()['endpoint'] == complete()['endpoint']
    again = put(client, complete(), secret)
    assert again.status_code == 200 and again.json()['generation'] == 1
    conflict = put(client, complete(), secret + '-changed')
    assert conflict.status_code == 409 and secret not in conflict.text
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Idempotency)) == 0
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
        assert secret not in json.dumps(session.get(Settings, 'singleton').preferences)
    assert secret not in caplog.text
    for directory in (cfg.data, cfg.uploads, cfg.parser_inputs, cfg.parser_outputs):
        assert all(secret.encode() not in path.read_bytes() for path in directory.rglob('*') if path.is_file())


def test_app_setup_needs_no_external_provider_files(client, database, settings_store, monkeypatch):
    monkeypatch.delenv('PROVIDER_PROFILE_FILE', raising=False)
    monkeypatch.delenv('PROVIDER_KEY_FILE', raising=False)
    before = client.get('/api/v1/settings/provider')
    assert before.status_code == 200 and before.json()['config_source'] == 'unconfigured'
    assert before.json()['has_api_key'] is False
    assert not client.get('/api/v1/capabilities').json()['provider_configured']
    assert not (settings_store / 'current.json').exists()
    secret = 'SYNTHETIC_IN_APP_SETUP_ONLY'
    saved = put(client, {'endpoint': 'https://example.invalid/v1/chat/completions',
        'api_protocol': 'chat_completions', 'model_id': 'synthetic-model'}, secret)
    assert saved.status_code == 200 and saved.json()['dispatch_configuration_ready'], saved.text
    assert saved.json()['config_source'] == 'managed' and not saved.json()['cost_control_enabled']
    assert secret not in saved.text
    from packages.providers.settings import resolve_provider_credentials
    from packages.domain.config import provider_profile
    endpoint, protocol, auth, key_path = resolve_provider_credentials(provider_profile())
    assert (endpoint, protocol, auth) == ('https://example.invalid/v1/chat/completions', 'chat_completions', 'bearer')
    assert key_path.is_relative_to(settings_store) and key_path.read_text() == secret
    db, cfg = database
    with TestClient(create_app(cfg, db)) as recreated:
        current = recreated.get('/api/v1/settings/provider')
        assert current.json()['profile_hash'] == saved.json()['profile_hash'] and secret not in current.text
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(Permit)) == 0


def test_partial_settings_no_guessed_prices_and_clear_key_readiness(client, settings_store):
    saved = put(client, {'endpoint': 'http://localhost:11434/v1/chat/completions', 'api_protocol': 'chat_completions',
                         'model_id': 'local:latest', 'cost_control_enabled': True}, 'SYNTHETIC_KEY')
    assert saved.status_code == 200, saved.text
    assert not saved.json()['configured'] and saved.json()['has_api_key']
    assert saved.json()['max_output_tokens'] == 8192 and 'price.output_micro_per_million' in saved.json()['missing_fields']
    assert not client.get('/api/v1/capabilities').json()['provider_configured']
    full = put(client, complete(), generation=1, operation='full')
    assert full.status_code == 200 and full.json()['dispatch_configuration_ready']
    clear = put(client, complete(), generation=2, operation='clear', clear=True)
    assert clear.status_code == 200 and not clear.json()['has_api_key']
    assert clear.json()['auth_mode'] == 'bearer' and 'api_key' in clear.json()['missing_fields']


@pytest.mark.parametrize('mutate', [lambda body: body.update(api_key={'value': 'SYNTHETIC_NO_ECHO'}),
                                 lambda body: body['profile'].update(api_key='SYNTHETIC_NO_ECHO'),
                                 lambda body: body.update(api_key='SYNTHETIC_NO_ECHO', clear_api_key=True)])
def test_validation_never_echoes_key_input(client, settings_store, mutate):
    body = {'profile': complete()}
    mutate(body)
    result = client.put('/api/v1/settings/provider', json=body, headers={'If-Match': '"0"', 'Idempotency-Key': 'bad-input'})
    assert result.status_code == 422
    assert 'SYNTHETIC_NO_ECHO' not in result.text
    assert not (settings_store / 'current.json').exists()


def test_real_two_client_cas_and_maintenance_guard(client, database, settings_store):
    db, cfg = database
    assert put(client, complete(), 'SYNTHETIC_KEY').status_code == 200
    barrier = Barrier(2)
    def update(index):
        with TestClient(create_app(cfg, db)) as peer:
            peer.headers['X-Library-Request'] = '1'
            barrier.wait()
            return put(peer, complete(model_id='model-' + str(index)), generation=1, operation='update-' + str(index)).status_code
    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(update, (1, 2))) == [200, 412]
    with db.transaction() as session:
        session.get(Settings, 'singleton').maintenance = True
    blocked = put(client, complete(), generation=2, operation='maintenance')
    assert blocked.status_code == 503
    assert client.get('/api/v1/settings/provider').json()['generation'] == 2


def test_large_request_and_missing_cas_have_no_secret_receipt(client, database, settings_store):
    large = client.put('/api/v1/settings/provider', json={'profile': complete(), 'api_key': 'X' * 33000},
                       headers={'If-Match': '"0"', 'Idempotency-Key': 'large'})
    assert large.status_code == 413 and 'X' * 50 not in large.text
    missing = client.put('/api/v1/settings/provider', json={'profile': complete(), 'api_key': 'SYNTHETIC_KEY'},
                         headers={'Idempotency-Key': 'missing-cas'})
    assert missing.status_code == 428
    assert not (settings_store / 'current.json').exists()


def test_backup_reference_collection_excludes_secret_volume_and_all_db_rows(client, database, settings_store):
    from packages.domain.models import Base
    from packages.maintenance.__main__ import referenced_files
    from tests.support import seed_editor
    db, cfg = database
    seed_editor(db, cfg)
    secret = 'SYNTHETIC_SETTINGS_NOT_IN_DB_OR_BACKUP_REFERENCES'
    assert put(client, complete(), secret).status_code == 200
    references = referenced_files(db, cfg)
    assert references, 'The backup must include real document files, not an empty example.'
    for kind, relative in references:
        assert kind in ('data', 'uploads')
        path = (cfg.data if kind == 'data' else cfg.uploads) / relative
        assert not path.resolve().is_relative_to(settings_store.resolve())
        assert secret.encode() not in path.read_bytes()
    with db.engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            rows = connection.execute(select(table)).mappings().all()
            assert secret not in json.dumps([dict(row) for row in rows], default=str)


def test_idempotent_old_response_never_combines_new_profile_aliases(client, settings_store):
    profile_a = complete()
    first = put(client, profile_a, 'SYNTHETIC_KEY', operation='profile-a')
    assert first.status_code == 200
    profile_b = complete(enabled_pairs=[['en', 'de']])
    profile_b['price']['revision'] = 'price-b'
    profile_b['price']['input_micro_per_million'] = 9000000
    newer = put(client, profile_b, generation=1, operation='profile-b')
    assert newer.status_code == 200
    replay = put(client, profile_a, 'SYNTHETIC_KEY', operation='profile-a')
    assert replay.status_code == 200
    for name in ('profile_hash', 'generation', 'model_id', 'price', 'prices', 'price_revision', 'enabled_pairs', 'language_policy'):
        assert replay.json()[name] == first.json()[name], name
    assert replay.json()['language_policy'] == 'all'
    assert 'locale_matrix' not in replay.json() and 'experimental_locales' not in replay.json()
    assert client.get('/api/v1/settings/provider').json()['profile_hash'] == newer.json()['profile_hash']
