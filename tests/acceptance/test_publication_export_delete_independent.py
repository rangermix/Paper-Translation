"""Real local artifact/export writes cannot run after the cleanup boundary."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from sqlalchemy import event, text

from packages.domain.errors import DomainError
from packages.jobs.queue import claim
from packages.privacy import cleanup_document
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('operation', ['publish', 'export', 'rebuild'])
def test_delete_waits_for_actual_artifact_or_export_file_producer(client, database, monkeypatch, operation):
    import workers.main as worker
    db, cfg = database
    seed_editor(db, cfg)
    headers = {'If-Match': '"1"', 'Idempotency-Key': 'independent-qa'}
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={}, headers=headers).json()
    assert qa['valid'], qa
    sealed = client.post('/api/v1/drafts/draft_fixture/seal', json={'qa_id': qa['id'], 'qa_fingerprint': qa['fingerprint'], 'generation': 1},
        headers={**headers, 'Idempotency-Key': 'independent-seal'}).json()
    queued = client.post('/api/v1/editions/edition_fixture/publish', json={'translation_revision_id': sealed['id'], 'expected_generation': 1},
        headers={**headers, 'Idempotency-Key': 'independent-publish'})
    assert queued.status_code == 202, queued.text
    lease = claim(db)
    export_id = None
    if operation in ('export','rebuild'):
        worker.publish(db, cfg, lease)
        while pending := claim(db):
            worker.execute(db, cfg, pending)
        artifact_id = client.get('/api/v1/documents/doc_fixture').json()['editions'][0]['current_artifact_id']
        if operation=='export':
            queued = client.post('/api/v1/artifacts/'+artifact_id+'/exports', json={'format': 'bundle', 'include_source': False},
                headers={'Idempotency-Key': 'independent-export'})
        else:
            from packages.domain.models import Document
            with db.transaction() as session:
                session.add(Document(id='shared_rebuild_original',title='Keep shared PDF',source_asset_id='source_pdf'))
            queued = client.post('/api/v1/artifacts/'+artifact_id+'/rebuild', json={'template_id':'reader-v2','preview_only':False,'expected_generation':2},
                headers={'If-Match':'"2"','Idempotency-Key':'independent-rebuild'})
        assert queued.status_code == 202, queued.text
        export_id = queued.json().get('export_id')
        lease = claim(db)
    assert lease.kind == operation
    paused, proceed = threading.Event(), threading.Event()
    pids = {'producer': [], 'delete': []}

    def observe(conn, cursor, statement, params, context, many):
        if statement == 'SELECT pg_advisory_xact_lock(798205425)':
            role = 'producer' if threading.current_thread().name == 'late-file-review' else 'delete'
            pids[role].append(conn.connection.driver_connection.info.backend_pid)

    def barrier(original):
        def wrapped(*args, **kwargs):
            paused.set()
            assert proceed.wait(12)
            return original(*args, **kwargs)
        return wrapped

    if operation in ('publish','rebuild'):
        monkeypatch.setattr(worker.Publisher, 'build', barrier(worker.Publisher.build))
    else:
        monkeypatch.setattr(worker, 'export_bundle', barrier(worker.export_bundle))

    def produce():
        threading.current_thread().name = 'late-file-review'
        try:
            (worker.publish if operation in ('publish','rebuild') else worker.export)(db, cfg, lease)
            return 'committed'
        except DomainError as error:
            return error.code

    event.listen(db.engine, 'before_cursor_execute', observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            produced = pool.submit(produce)
            assert paused.wait(10)
            removed = pool.submit(client.request, 'DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True}, headers={'If-Match': '"1"'})
            try:
                deadline = time.monotonic()+8
                blocked = False
                while time.monotonic() < deadline:
                    if pids['delete'] and pids['producer']:
                        with db.engine.connect() as observer:
                            blocked = pids['producer'][-1] in observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': pids['delete'][-1]})
                        if blocked:
                            break
                    if removed.done():
                        break
                    time.sleep(.02)
                assert blocked, 'Deletion did not wait for the actual protected local file producer'
            finally:
                proceed.set()
            assert produced.result(timeout=15) in {'committed', 'CONTROL_CHANGED', 'DOCUMENT_DELETED', 'FENCE_EXPIRED'}
            response = removed.result(timeout=15)
            assert response.status_code == 202, response.text
    finally:
        proceed.set()
        event.remove(db.engine, 'before_cursor_execute', observe)
    cleanup_lease = claim(db)
    assert cleanup_lease.kind == 'cleanup'
    cleanup_document(db, cfg, cleanup_lease)
    assert not (cfg.data/'documents/doc_fixture').exists()
    if export_id:
        assert not (cfg.data/'exports'/export_id).exists()
    assert client.get('/api/v1/documents/doc_fixture/original').status_code == 410
    if operation=='rebuild':
        from pathlib import Path
        assert client.get('/api/v1/documents/shared_rebuild_original/original').content==Path('fixtures/sample.pdf').read_bytes()
