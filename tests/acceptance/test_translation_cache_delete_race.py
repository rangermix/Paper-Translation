"""Independent real TranslationCache FK insertion versus document deletion."""
from concurrent.futures import ThreadPoolExecutor
import copy
import threading
import time

import pytest
from sqlalchemy import event, select, text

from packages.domain.errors import DomainError
from packages.domain.models import Task, TranslationCache, SegmentVersion
from packages.jobs.queue import claim
from packages.privacy import cleanup_document
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation, commit_unit
from tests.integration.test_translation_execution import setup_library, PROFILE

pytestmark = pytest.mark.postgres


def test_translation_cache_fk_and_delete_do_not_deadlock_or_restore_content(client, database):
    db, cfg = database
    setup_library(db, cfg)
    execute_translation(db, cfg, claim(db), FakeProvider())  # Planner only, no call.
    lease = claim(db)
    with db.transaction() as session:
        unit = copy.deepcopy(session.get(Task, lease.task_id).payload['unit'])
    before_insert, proceed = threading.Event(), threading.Event()
    worker_pid, deletion_pid = [], []

    def observe(conn, cursor, statement, parameters, context, many):
        pid = conn.connection.driver_connection.info.backend_pid
        if threading.current_thread().name == 'cache-delete-review' and statement.startswith('INSERT INTO translation_cache'):
            worker_pid.append(pid)
            before_insert.set()
            assert proceed.wait(12)
        if threading.current_thread().name != 'cache-delete-review' and statement == 'SELECT pg_advisory_xact_lock(798205425)':
            deletion_pid.append(pid)

    def produce():
        threading.current_thread().name = 'cache-delete-review'
        try:
            commit_unit(db, cfg, lease, unit, unit['source_inline'], 'independent-cache-delete', PROFILE)
            return 'committed'
        except DomainError as error:
            return error.code

    event.listen(db.engine, 'before_cursor_execute', observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            produced = pool.submit(produce)
            assert before_insert.wait(10)
            deleted = pool.submit(client.request, 'DELETE', '/api/v1/documents/doc', json={'confirm': True}, headers={'If-Match': '"1"'})
            try:
                deadline = time.monotonic()+8
                blocked = False
                while time.monotonic() < deadline:
                    if deletion_pid:
                        with db.engine.connect() as observer:
                            blocked = worker_pid[0] in observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': deletion_pid[-1]})
                        if blocked:
                            break
                    time.sleep(.02)
                assert blocked, 'Deletion did not overlap the actual cache-insertion transaction'
            finally:
                proceed.set()
            assert produced.result(timeout=15) in {'committed', 'CONTROL_CHANGED', 'DOCUMENT_DELETED', 'FENCE_EXPIRED'}
            assert deleted.result(timeout=15).status_code == 202
    finally:
        proceed.set()
        event.remove(db.engine, 'before_cursor_execute', observe)
    cleanup_lease = claim(db)
    assert cleanup_lease.kind == 'cleanup'
    cleanup_document(db, cfg, cleanup_lease)
    with db.transaction() as session:
        assert not list(session.scalars(select(TranslationCache)))
        assert not list(session.scalars(select(SegmentVersion)))
    assert client.get('/api/v1/documents/doc/original').status_code == 410
