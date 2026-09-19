"""Default dispatch and pause recovery, backed by PostgreSQL; never calls a model."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.main import create_app
from packages.billing.ledger import authorize, settle
from packages.domain.models import Attempt, Job, Permit, Settings, Task
from packages.maintenance.__main__ import set_maintenance
from tests.integration.test_budget import PRICE, setup
from tests.integration.test_provider_settings_api import settings_store, put
from tests.unit.test_provider_settings_store import complete

pytestmark = pytest.mark.postgres


def update(client, state, disabled, key='dispatch-setting', **extra):
    return client.patch('/api/v1/settings/dispatch', json={'dispatch_disabled': disabled, **extra},
        headers={'If-Match': f'"{state["generation"]}"', 'Idempotency-Key': key})


def test_state_persists_recreate_without_env_or_changing_provider(client, database, settings_store, monkeypatch):
    saved = put(client, complete(cost_control_enabled=False), 'SYNTHETIC_KEY').json()
    before = client.get('/api/v1/settings/dispatch')
    assert before.status_code == 200
    assert before.json()['dispatch_disabled'] is False
    monkeypatch.setenv('DISPATCH_DISABLED', 'true')  # Old environment is intentionally ignored.
    enabled = update(client, before.json(), False)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()['dispatch_disabled'] is False
    assert enabled.headers['etag'] == f'"{enabled.json()["generation"]}"'
    db, cfg = database
    db.migrate()
    with TestClient(create_app(cfg, db)) as recreated:
        assert recreated.get('/api/v1/settings/dispatch').json()['dispatch_disabled'] is False
        provider = recreated.get('/api/v1/settings/provider').json()
        assert provider['profile_hash'] == saved['profile_hash']
        assert provider['credential_revision'] == saved['credential_revision']
    paused = update(client, enabled.json(), True, key='pause')
    assert paused.json()['dispatch_disabled'] is True
    db.migrate()
    with TestClient(create_app(cfg, db)) as recreated:
        assert recreated.get('/api/v1/settings/dispatch').json()['dispatch_disabled'] is True
    assert client.get('/api/v1/settings/preferences').json()['generation'] == paused.json()['generation']
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(Permit)) == 0


def test_cas_replay_and_invalid_requests(client):
    before = client.get('/api/v1/settings/dispatch').json()
    saved = update(client, before, False)
    assert saved.status_code == 200
    assert update(client, before, False).json() == saved.json()
    assert update(client, before, True, key='old-tab').status_code == 412
    assert update(client, before, True).status_code == 409
    assert client.patch('/api/v1/settings/dispatch', json={'dispatch_disabled': True},
        headers={'Idempotency-Key': 'no-version'}).status_code == 428
    for payload in ({'dispatch_disabled': 'false'}, {'dispatch_disabled': False, 'maintenance': False},
                    {'dispatch_disabled': False, 'api_key': 'SYNTHETIC_NO_ECHO'}):
        rejected = client.patch('/api/v1/settings/dispatch', json=payload,
            headers={'Idempotency-Key': 'bad', 'If-Match': saved.headers['etag']})
        assert rejected.status_code == 422
        assert 'SYNTHETIC_NO_ECHO' not in rejected.text


def test_two_tabs_cannot_overwrite_each_other(client, database):
    before = client.get('/api/v1/settings/dispatch').json()
    db, cfg = database
    barrier = Barrier(2)
    def toggle(index):
        with TestClient(create_app(cfg, db)) as peer:
            peer.headers['X-Library-Request'] = '1'
            barrier.wait()
            return update(peer, before, False, key=f'tab-{index}').status_code
    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(toggle, [1, 2])) == [200, 412]


@pytest.mark.parametrize('amount', [80, None])
def test_unknown_risk_acknowledgment_preserves_permits_and_tasks(client, database, amount):
    db, _ = database
    with db.transaction() as session:
        session.add(Job(id='unknown-job', stage='translate', status='outcome_unknown')); session.flush()
        session.add(Task(id='unknown-task', job_id='unknown-job', kind='translate', status='outcome_unknown')); session.flush()
        session.add(Attempt(id='unknown-attempt', task_id='unknown-task', job_id='unknown-job', fence=1, control_epoch=0, state='outcome_unknown')); session.flush()
        session.add(Permit(id='unknown-permit', attempt_id='unknown-attempt', job_id='unknown-job', control_epoch=0,
            price_snapshot=PRICE, reserved_micro=amount, state='unknown'))
    state = client.get('/api/v1/settings/dispatch').json()
    assert state['unknown_attempts'] == 1 and state['unknown_micro'] == amount
    assert update(client, state, False).status_code == 409
    assert update(client, state, False, accept_unknown_risk=True, reason='  ').status_code == 409
    enabled = update(client, state, False, accept_unknown_risk=True, reason='已核对服务商记录，保留未知费用。')
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()['unknown_attempts'] == 1 and enabled.json()['unknown_micro'] == amount
    assert update(client, state, False, accept_unknown_risk=True, reason='已核对服务商记录，保留未知费用。').status_code == 200
    with db.transaction() as session:
        assert session.get(Permit, 'unknown-permit').state == 'unknown'
        assert session.get(Task, 'unknown-task').status == 'outcome_unknown'
        evidence = session.get(Attempt, 'unknown-attempt').evidence
        assert len(evidence) == 1 and evidence[0]['origin'] == 'manual_ui'


def test_maintenance_remains_a_separate_guard_and_off_keeps_pause(client, database):
    db, _ = database
    state = client.get('/api/v1/settings/dispatch').json()
    assert update(client, state, False).status_code == 200
    set_maintenance(db, True)
    state = client.get('/api/v1/settings/dispatch').json()
    assert state['maintenance'] and state['dispatch_disabled']
    assert update(client, state, False, key='maintenance').status_code == 503
    set_maintenance(db, False)
    state = client.get('/api/v1/settings/dispatch').json()
    assert not state['maintenance'] and state['dispatch_disabled']


def test_pause_blocks_new_permit_and_accepts_inflight_usage(client, database):
    from packages.domain.errors import DomainError
    db, _ = database
    first, second = setup(db)
    with db.transaction() as session: authorize(session, first, 80, PRICE)
    state = client.get('/api/v1/settings/dispatch').json()
    assert state['inflight_requests'] == 1
    assert update(client, state, True).status_code == 200
    with pytest.raises(DomainError, match='Dispatch disabled'):
        with db.transaction() as session: authorize(session, second, 10, PRICE)
    with db.transaction() as session: settle(session, first.attempt_id, {'input_tokens': 10, 'output_tokens': 10}, 'synthetic')
    assert client.get('/api/v1/settings/dispatch').json()['inflight_requests'] == 0


def test_automatic_billing_pause_invalidates_old_page_version(client, database):
    db, _ = database
    first, _ = setup(db)
    with db.transaction() as session: authorize(session, first, 10, PRICE)
    state = client.get('/api/v1/settings/dispatch').json()
    with db.transaction() as session: settle(session, first.attempt_id, {'input_tokens': 10, 'output_tokens': 10}, 'over-bound')
    current = client.get('/api/v1/settings/dispatch').json()
    assert current['dispatch_disabled'] and current['generation'] > state['generation']
    assert update(client, state, False, key='stale-enabled').status_code == 412


def test_new_instance_needs_only_request_confirmation_without_calling_model(client, database, settings_store):
    saved = put(client, complete(cost_control_enabled=False), 'SYNTHETIC_KEY').json()
    def test_request(confirmed):
        return client.post('/api/v1/settings/provider/test', json={'profile_hash': saved['profile_hash'], 'external_processing_confirmed': confirmed},
            headers={'If-Match': f'"{saved["generation"]}"', 'Idempotency-Key': f'confirmed-{confirmed}'})
    assert test_request(False).json()['error']['code'] == 'EXTERNAL_PROCESSING_UNCONFIRMED'
    assert test_request(True).status_code == 202
    with database[0].transaction() as session:
        assert session.scalar(select(func.count()).select_from(Permit)) == 0


def test_pause_recovery_unblocks_connection_test_creation_without_calling_model(client, database, settings_store):
    saved = put(client, complete(cost_control_enabled=False), 'SYNTHETIC_KEY').json()
    state = client.get('/api/v1/settings/dispatch').json()
    assert update(client, state, True, key='pause').status_code == 200
    def test_request(key):
        return client.post('/api/v1/settings/provider/test', json={'profile_hash': saved['profile_hash'], 'external_processing_confirmed': True},
            headers={'If-Match': f'"{saved["generation"]}"', 'Idempotency-Key': key})
    assert test_request('paused').json()['error']['code'] == 'DISPATCH_DISABLED'
    state = client.get('/api/v1/settings/dispatch').json()
    assert update(client, state, False).status_code == 200
    assert test_request('enabled').status_code == 202
    with database[0].transaction() as session:
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
