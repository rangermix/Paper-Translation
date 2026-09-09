"""Document FK locks must not invert the job/delete locking order."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest
from sqlalchemy import event, select, text

from packages.domain.errors import DomainError
from packages.domain.models import SearchEntry
from packages.jobs.queue import claim
from packages.privacy import cleanup_document
from tests.integration.test_publication_lifecycle import seal_and_publish
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_delete_and_late_index_never_deadlock_or_resurrect_rows(client, database, monkeypatch):
    import apps.api.library as library
    import packages.search as search
    db, cfg = database
    seed_editor(db, cfg)
    seal_and_publish(client, db, cfg, 1, 1, 'index-delete')
    lease = claim(db)
    assert lease.kind == 'index'
    ready, proceed, delete_locked = Event(), Event(), Event()
    original_read = search.read_snapshot
    original_get = library.get_document
    original_assert = search.assert_current
    pids = {'index': None, 'delete': None}

    def observed_lease(session, current, **kwargs):
        result = original_assert(session, current, **kwargs)
        pids['index'] = session.scalar(text('SELECT pg_backend_pid()'))
        return result

    def pause_read(*args, **kwargs):
        result = original_read(*args, **kwargs)
        if not ready.is_set():
            ready.set()
            assert proceed.wait(10)
        return result

    def observe_document(*args, **kwargs):
        result = original_get(*args, **kwargs)
        if kwargs.get('lock'):
            delete_locked.set()
        return result

    monkeypatch.setattr(search, 'read_snapshot', pause_read)
    monkeypatch.setattr(search, 'assert_current', observed_lease)
    monkeypatch.setattr(library, 'get_document', observe_document)
    def observe_global(conn, cursor, statement, params, context, many):
        if ready.is_set() and statement == 'SELECT pg_advisory_xact_lock(798205425)' and not proceed.is_set():
            pids['delete'] = conn.connection.driver_connection.info.backend_pid
    event.listen(db.engine, 'before_cursor_execute', observe_global)
    doc = client.get('/api/v1/documents/doc_fixture')
    def index():
        try:
            search.update_index(db, cfg, lease)
            return 'completed'
        except DomainError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        indexed = pool.submit(index)
        assert ready.wait(10)
        deleted = pool.submit(client.request, 'DELETE', '/api/v1/documents/doc_fixture',
            json={'confirm': True}, headers={'If-Match': doc.headers['etag']})
        try:
            deadline = time.monotonic()+5
            blocked = False
            while time.monotonic() < deadline:
                if pids['delete'] and pids['index']:
                    with db.engine.connect() as observer:
                        blocked = pids['index'] in observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': pids['delete']})
                    if blocked:
                        break
                time.sleep(.02)
            assert blocked, 'Delete did not wait for the actual index transaction'
        finally:
            proceed.set()
        assert indexed.result(timeout=15) in ('completed', 'CONTROL_CHANGED', 'DOCUMENT_DELETED')
        assert deleted.result(timeout=15).status_code == 202
        assert delete_locked.is_set()
    event.remove(db.engine, 'before_cursor_execute', observe_global)
    cleanup_document(db, cfg, claim(db))
    with db.transaction() as session:
        assert not list(session.scalars(select(SearchEntry)))
    assert client.get('/api/v1/search', params={'q': 'tokens'}).json()['items'] == []
