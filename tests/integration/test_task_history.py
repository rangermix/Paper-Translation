"""NB-AT03/04: durable lifecycle history and content-free technical logs."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from apps.api.library import enqueue
from packages.domain.models import Attempt, Job, Settings, Task, now
from packages.jobs.queue import claim, finish, recover_expired

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('kind', ['inspect', 'parse', 'recovery', 'quality_check', 'translate', 'candidate',
    'semantic_review', 'metadata_lookup', 'publish', 'rebuild', 'export', 'cleanup', 'provider_test', 'index'])
def test_each_task_records_attempt_and_fixed_terminal_times(database, client, kind):
    db, _ = database
    with db.transaction() as session:
        job = enqueue(session, kind, {})
        identifier = job.id
    lease = claim(db)
    with db.transaction() as session:
        finish(session, lease)
    first = client.get('/api/v1/jobs/' + identifier).json()
    assert first['queued_at'] and first['started_at'] and first['finished_at']
    assert first['execution_ms'] >= 0 and first['queue_ms'] >= 0
    assert first['attempts'][0]['started_at'] and first['attempts'][0]['finished_at']
    assert client.get('/api/v1/jobs/' + identifier).json()['finished_at'] == first['finished_at']
    logs = client.get('/api/v1/jobs/' + identifier + '/logs').json()['items']
    assert {'created', 'started', 'finished'} <= {e['operation'] for e in logs}
    assert len({e['sequence'] for e in logs}) == len(logs)


def test_expired_attempt_closes_and_retry_keeps_first_start(database, client):
    db, _ = database
    with db.transaction() as session:
        identifier = enqueue(session, 'parse', {}).id
    first = claim(db)
    with db.transaction() as session:
        session.get(Task, first.task_id).lease_expires = now() - timedelta(seconds=1)
        original_start = session.get(Job, identifier).started_at
    recover_expired(db)
    second = claim(db)
    with db.transaction() as session:
        finish(session, second)
        assert session.get(Attempt, first.attempt_id).finished_at is not None
        assert session.get(Job, identifier).started_at == original_start
    detail = client.get('/api/v1/jobs/' + identifier).json()
    assert len(detail['attempts']) == 2


def test_logs_are_deduplicated_paginated_filtered_and_never_copy_payload(database, client):
    from packages.jobs.history import record_log
    db, _ = database
    with db.transaction() as session:
        job = enqueue(session, 'metadata_lookup', {'api_key': 'sk-private', 'body': 'FULL PDF SECRET'})
        identifier = job.id
        for _ in range(2):
            record_log(session, job, event_key='one-warning', operation='check_failed', level='warning',
                       details={'code': 'CHECK_FAILED', 'api_key': 'sk-private', 'body': 'FULL PDF SECRET',
                                'nested': {'Authorization': 'Bearer secret'}})
    result = client.get('/api/v1/jobs/' + identifier + '/logs?level=warning').json()
    assert len(result['items']) == 1
    raw = client.get('/api/v1/jobs/' + identifier + '/logs/download').text
    assert 'sk-private' not in raw and 'FULL PDF SECRET' not in raw and 'Bearer secret' not in raw
    assert 'CHECK_FAILED' in raw
    first = client.get('/api/v1/jobs/' + identifier + '/logs?limit=1').json()
    assert first['next_cursor'] is not None
    second = client.get(f'/api/v1/jobs/{identifier}/logs?cursor={first["next_cursor"]}').json()
    assert second['items'][0]['sequence'] > first['items'][0]['sequence']


def test_actual_model_does_not_come_from_current_settings(database, client):
    from packages.jobs.history import set_actual_model
    db, _ = database
    with db.transaction() as session:
        identifier = enqueue(session, 'provider_test', {'profile': {'model_id': 'selected-model',
            'api_protocol': 'responses', 'provider': 'openai', 'endpoint': 'http://localhost:9000/v1/responses'}}).id
    lease = claim(db)
    with db.transaction() as session:
        set_actual_model(session, lease, {'kind': 'api', 'model_id': 'returned-model', 'api_protocol': 'responses'})
        finish(session, lease)
        session.get(Settings, 'singleton').preferences = {'model_id': 'new-current-model'}
    detail = client.get('/api/v1/jobs/' + identifier).json()
    assert detail['config_snapshot']['model_id'] == 'selected-model'
    assert detail['actual_model']['model_id'] == 'returned-model'
    assert detail['attempts'][0]['actual_model']['model_id'] == 'returned-model'
