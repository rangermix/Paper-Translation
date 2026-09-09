"""Independent tombstone projection and action-boundary PostgreSQL checks."""
import pytest
from sqlalchemy import select

from packages.domain.models import Attempt, Job, Permit, Task
from tests.integration.test_cleanup_status import SENTINEL, delete_fixture

pytestmark = pytest.mark.postgres


def test_cleanup_receipt_cannot_surface_task_or_attempt_material(client, database):
    db, _ = database
    job_id = delete_fixture(client, database)
    with db.transaction() as session:
        task = session.scalar(select(Task).where(Task.job_id == job_id))
        task.result = {'artifact_id': SENTINEL, 'export_id': SENTINEL, 'text': SENTINEL}
        task.payload = {'source': SENTINEL, 'unit': {'text': SENTINEL}}
        session.add(Attempt(id='attempt_receipt_poison', task_id=task.id, job_id=job_id,
            fence=0, control_epoch=0, state='outcome_unknown', request_id=SENTINEL,
            usage={'text': SENTINEL}, evidence=[{'quote': SENTINEL}]))
        session.flush()
        session.add(Permit(id='permit_receipt_poison', attempt_id='attempt_receipt_poison',
            job_id=job_id, control_epoch=0, price_snapshot={'private': SENTINEL},
            reserved_micro=123456, state='unknown'))
        session.get(Job, job_id).budget_micro = 123456
    paths = ['/api/v1/jobs/' + job_id, '/api/v1/jobs',
        '/api/v1/jobs?document_id=doc_fixture', '/api/v1/jobs/' + job_id + '/events']
    for path in paths:
        response = client.get(path, headers={'Last-Event-ID': 'event_private_cleanup'})
        assert response.status_code == 200, response.text
        assert SENTINEL not in response.text and '123456' not in response.text
    row = client.get(paths[0]).json()
    assert len(row['attempts']) == 1 and row['result'] == {} and row['progress'] == {}
    assert row['request_count'] == 0 and row['unknown_micro'] == 0
    assert row['draft_id'] is None and row['import_id'] is None
    # The read-only projection must not erase the independently retained ledger.
    with db.transaction() as session:
        assert session.get(Permit, 'permit_receipt_poison').reserved_micro == 123456
        assert session.get(Attempt, 'attempt_receipt_poison').request_id == SENTINEL


def test_tombstone_receipt_never_enables_control_or_old_job_events(client, database):
    db, _ = database
    job_id = delete_fixture(client, database)
    before = client.get('/api/v1/jobs/' + job_id)
    for action in ('pause', 'resume', 'cancel'):
        result = client.post('/api/v1/jobs/' + job_id + '/' + action, json={},
            headers={'If-Match': before.headers['etag'], 'Idempotency-Key': 'cleanup-' + action})
        assert result.status_code == 410, result.text
    for path in ('/api/v1/jobs/job_prior', '/api/v1/jobs/job_prior/events',
                 '/api/v1/documents/doc_fixture/original', '/api/v1/documents/doc_fixture'):
        assert client.get(path).status_code == (200 if '/jobs/' in path else 410)
    assert client.get('/api/v1/jobs?document_id=missing').status_code == 404
    assert client.get('/api/v1/jobs/missing/events').status_code == 404
    with db.transaction() as session:
        job = session.get(Job, job_id)
        assert job.status == 'pending' and job.control_epoch == before.json()['control_epoch']
