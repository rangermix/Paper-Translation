"""Clearing the task list preserves execution and billing evidence."""
import uuid

import pytest
from sqlalchemy import func, select, text

from apps.api.library import enqueue
from packages.domain.db import Database
from packages.domain.models import Attempt, Job, Permit, Settings, Task, TaskLog
from packages.jobs.queue import emit

pytestmark = pytest.mark.postgres


def seed_job(db, status, *, permit=None, leased=False):
    with db.transaction() as session:
        job = enqueue(session, 'parse', {})
        job.status = status
        task = session.scalar(select(Task).where(Task.job_id == job.id))
        task.status = 'leased' if leased else 'cancelled' if status == 'cancelled' else 'succeeded'
        if permit:
            attempt = Attempt(id='attempt_' + uuid.uuid4().hex, task_id=task.id, job_id=job.id,
                              fence=1, control_epoch=0, state='outcome_unknown' if permit == 'unknown' else 'committed')
            session.add(attempt)
            session.flush()
            session.add(Permit(id='permit_' + uuid.uuid4().hex, attempt_id=attempt.id, job_id=job.id,
                control_epoch=0, price_snapshot={}, reserved_micro=42, actual_micro=20 if permit == 'settled' else None, state=permit))
        return job.id


def clear(client, *, key=None, etag=None, body=None):
    headers = {'Idempotency-Key': key or uuid.uuid4().hex,
               'If-Match': etag or client.get('/api/v1/jobs/history').headers.get('ETag', '"0"')}
    return client.post('/api/v1/jobs/history/clear', headers=headers, json=body or {'confirm': True})


def ids(client, query=''):
    response = client.get('/api/v1/jobs' + query)
    assert response.status_code == 200
    return {item['id'] for item in response.json()['items']}


def test_clear_finished_history_preserves_records_and_filters_before_pagination(database, client):
    db, _ = database
    finished = {seed_job(db, status) for status in ['succeeded', 'completed', 'completed_with_warnings',
                'partially_completed', 'failed', 'cancelled']}
    active = {seed_job(db, status) for status in ['pending', 'running', 'paused', 'waiting_config',
              'waiting_budget', 'needs_review', 'outcome_unknown', 'cancel_requested']}
    detail = {identifier: client.get('/api/v1/jobs/' + identifier).json() for identifier in finished}
    logs = {identifier: client.get('/api/v1/jobs/' + identifier + '/logs/download').text for identifier in finished}
    preview = client.get('/api/v1/jobs/history')
    assert preview.status_code == 200
    assert preview.json()['clearable_count'] == len(finished)
    response = clear(client)
    assert response.status_code == 200, response.text
    assert response.json()['cleared_count'] == len(finished)
    assert ids(client) == active
    assert ids(client, '?include_cleared=true') == active | finished
    assert ids(client, '?group=completed') == set()
    assert clear(client).json()['cleared_count'] == 0
    for identifier in finished:
        # All task details, model/time snapshots, results and logs remain readable.
        assert client.get('/api/v1/jobs/' + identifier).json() == detail[identifier]
        assert client.get('/api/v1/jobs/' + identifier + '/logs/download').text == logs[identifier]
    page = client.get('/api/v1/jobs?limit=3').json()
    assert len(page['items']) == 3 and page['next_cursor']
    assert {j['id'] for j in page['items']} <= active
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == len(active | finished)


def test_unsettled_requests_and_leased_work_stay_visible(database, client):
    db, _ = database
    protected = {seed_job(db, 'cancelled', permit='unknown'), seed_job(db, 'failed', permit='reserved'),
                 seed_job(db, 'cancelled', leased=True)}
    settled = seed_job(db, 'succeeded', permit='settled')
    assert clear(client).json()['cleared_count'] == 1
    assert ids(client) == protected
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Permit)) == 3
        assert session.scalar(select(func.sum(Permit.actual_micro))) == 20
        # A protected job must not become hidden just because its request settles later.
        for permit in session.scalars(select(Permit).where(Permit.state.in_(['unknown', 'reserved']))):
            permit.state = 'settled'
    assert ids(client) == protected
    assert settled in ids(client, '?include_cleared=true')


def test_changed_job_generation_reappears_and_new_tasks_are_not_cleared(database, client):
    db, _ = database
    identifier = seed_job(db, 'failed')
    assert clear(client).status_code == 200
    assert not ids(client)
    with db.transaction() as session:
        job = session.get(Job, identifier)
        emit(session, job)
    new = seed_job(db, 'succeeded')
    assert ids(client) == {identifier, new}
    # A fresh API instance uses the persisted marker, not browser storage.
    from apps.api.main import create_app
    from fastapi.testclient import TestClient
    assert clear(client).status_code == 200
    with TestClient(create_app(database[1], db)) as fresh:
        assert not ids(fresh)
        assert ids(fresh, '?include_cleared=true') == {identifier, new}


def test_clear_is_confirmed_idempotent_versioned_and_maintenance_protected(database, client):
    db, _ = database
    first = seed_job(db, 'succeeded')
    preview = client.get('/api/v1/jobs/history')
    assert preview.status_code == 200
    etag = preview.headers['ETag']
    assert clear(client, etag=etag, body={'confirm': False}).status_code == 422
    assert client.post('/api/v1/jobs/history/clear', json={'confirm': True}).status_code == 428
    key = uuid.uuid4().hex
    result = clear(client, key=key, etag=etag)
    assert result.status_code == 200
    new = seed_job(db, 'succeeded')
    assert clear(client, key=key, etag=etag).json() == result.json()
    assert ids(client) == {new}
    assert clear(client, etag=etag).status_code == 412
    assert first in ids(client, '?include_cleared=true')
    with db.transaction() as session:
        session.get(Settings, 'singleton').maintenance = True
    assert clear(client).status_code == 503
    assert ids(client) == {new}


def test_schema_12_upgrade_retains_existing_history(database, monkeypatch):
    admin, cfg = database
    schema = 'library_test_' + uuid.uuid4().hex
    with admin.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    monkeypatch.setenv('TEST_DATABASE_SCHEMA', schema)
    db = Database(cfg)
    try:
        db.migrate(12)
        with db.engine.begin() as conn:
            conn.execute(text("INSERT INTO jobs (id,stage,status,control_epoch,payload,progress,budget_micro,generation,created_at) VALUES ('old','parse','succeeded',0,'{}','{}',0,5,now())"))
        db.migrate()
        db.migrate()
        db.ready()
        with db.transaction() as session:
            job = session.get(Job, 'old')
            assert job.history_cleared_generation is None
            assert job.generation == 5 and job.status == 'succeeded'
            assert job.actual_model is None and job.finished_at is None
    finally:
        db.engine.dispose()
        with admin.engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
