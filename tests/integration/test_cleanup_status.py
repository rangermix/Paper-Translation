"""Deleted content stays inaccessible while a minimal cleanup receipt remains readable."""
import json

import pytest
from packages.domain.models import Document, Event, Job
from packages.jobs.queue import claim
from packages.privacy import cleanup_document
from tests.support import seed_editor

pytestmark = pytest.mark.postgres
SENTINEL = 'private-cleanup-content-must-not-escape'


def delete_fixture(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.add(Document(id='doc_shared', title='Shared original', source_asset_id='source_pdf'))
        session.add(Job(id='job_prior', document_id='doc_fixture', stage='parse', status='succeeded',
            payload={'text': SENTINEL}))
    removed = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True},
        headers={'If-Match': '"1"'})
    assert removed.status_code == 202, removed.text
    job_id = removed.json()['job_id']
    with db.transaction() as session:
        job = session.get(Job, job_id)
        job.payload = {**job.payload, 'text': SENTINEL}
        job.progress = {'semantic_issues': [{'source_quote': SENTINEL}], 'private': SENTINEL}
        job.error = {'code': SENTINEL, 'message': SENTINEL}
        session.add(Event(id='event_private_cleanup', job_id=job_id, generation=999, payload={'text': SENTINEL}))
    return job_id


def assert_receipt(client, job_id, state):
    response = client.get('/api/v1/jobs/' + job_id)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['cleanup'] == {'online_content': 'unavailable', 'files': state,
        'shared_assets': 'retained_while_referenced', 'backups': 'retained_until_expiry',
        'downloaded_copies': 'outside_instance'}
    assert value['progress'] == {} and value['issues'] == []
    assert value['draft_id'] is None and value['request_count'] == 0
    for suffix in ('', '?document_id=doc_fixture'):
        listed = client.get('/api/v1/jobs' + suffix)
        assert listed.status_code == 200, listed.text
        assert {item['id'] for item in listed.json()['items']} == {job_id, 'job_prior'}
        assert SENTINEL not in listed.text
    events = client.get('/api/v1/jobs/' + job_id + '/events', headers={'Last-Event-ID': 'event_private_cleanup'})
    assert events.status_code == 200
    assert 'event: snapshot\n' in events.text and 'event: progress\n' not in events.text
    snapshot = json.loads(events.text.split('data: ', 1)[1])
    assert snapshot['cleanup']['files'] == state
    assert SENTINEL not in response.text + events.text
    assert client.get('/api/v1/jobs/job_prior').status_code == 200
    assert client.get('/api/v1/jobs/job_prior/events').status_code == 200
    assert client.get('/api/v1/documents/doc_fixture/original').status_code == 410
    return response


def test_cleanup_receipt_pending_running_complete_without_deleted_content(client, database):
    db, cfg = database
    job_id = delete_fixture(client, database)
    pending = assert_receipt(client, job_id, 'pending')
    assert client.post('/api/v1/jobs/' + job_id + '/pause', json={},
        headers={'Idempotency-Key': 'no-cleanup-control', 'If-Match': pending.headers['etag']}).status_code == 410
    lease = claim(db)
    assert lease.job_id == job_id and lease.kind == 'cleanup'
    assert_receipt(client, job_id, 'running')
    cleanup_document(db, cfg, lease)
    done = assert_receipt(client, job_id, 'completed').json()
    assert done['status'] == 'succeeded' and done['result'] == {'deleted': True}
    assert client.get('/api/v1/documents/doc_shared/original').status_code == 200
    assert client.get('/api/v1/drafts/draft_fixture').status_code == 404


def test_cleanup_failure_is_visible_without_internal_error_content(client, database):
    db, _ = database
    job_id = delete_fixture(client, database)
    with db.transaction() as session:
        session.get(Job, job_id).status = 'failed'
    value = assert_receipt(client, job_id, 'failed').json()
    assert value['error'] == {'code': 'CLEANUP_FAILED', 'message': 'File cleanup failed.'}
