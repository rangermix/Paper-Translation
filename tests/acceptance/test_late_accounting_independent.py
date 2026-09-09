"""Late money classification after controls change; FakeProvider is explicit."""
import pytest
from sqlalchemy import select

from packages.domain.errors import DomainError
from packages.domain.models import Attempt, Document, Draft, Job, Permit, Settings, SegmentVersion, Task
from packages.jobs.queue import claim
from packages.providers.contract import ProviderFailure
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import setup_library

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('control', ['maintenance', 'delete'])
def test_unknown_response_is_classified_after_maintenance_or_deletion(client, database, control):
    db, cfg = database
    setup_library(db, cfg)
    execute_translation(db, cfg, claim(db), FakeProvider())
    lease = claim(db)

    def late_failure(units):
        if control == 'delete':
            removed = client.request('DELETE', '/api/v1/documents/doc', json={'confirm': True}, headers={'If-Match': '"1"'})
            assert removed.status_code == 202, removed.text
        else:
            with db.transaction() as session:
                session.get(Settings, 'singleton').maintenance = True
        raise ProviderFailure('OUTCOME_UNKNOWN', 'unknown')

    provider = FakeProvider([late_failure])
    try:
        execute_translation(db, cfg, lease, provider)
    except DomainError as error:
        assert error.code in {'DOCUMENT_DELETED', 'CONTROL_CHANGED'}
    assert len(provider.calls) == 1
    with db.transaction() as session:
        permit = session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id))
        assert permit.state == 'unknown', 'Already-dispatched uncertainty must survive content/control rejection'
        assert permit.actual_micro is None
        attempt = session.get(Attempt, lease.attempt_id)
        assert attempt.state == 'outcome_unknown' and attempt.usage is None
        assert not list(session.scalars(select(SegmentVersion)))
        if control == 'maintenance':
            assert session.get(Job, lease.job_id).status == 'outcome_unknown'


@pytest.mark.parametrize('outcome,permit_state,attempt_state', [
    ('unknown', 'unknown', 'outcome_unknown'),
    ('not_executed', 'released', 'not_executed'),
])
def test_late_response_after_completed_cleanup_keeps_money_only(client, database, outcome, permit_state, attempt_state):
    from packages.privacy import cleanup_document
    db, cfg = database
    setup_library(db, cfg)
    execute_translation(db, cfg, claim(db), FakeProvider())
    lease = claim(db)
    after_cleanup = {}

    def late_failure(units):
        removed = client.request('DELETE', '/api/v1/documents/doc', json={'confirm': True}, headers={'If-Match': '"1"'})
        assert removed.status_code == 202, removed.text
        cleanup = claim(db)
        assert cleanup.kind == 'cleanup'
        cleanup_document(db, cfg, cleanup)
        with db.transaction() as session:
            after_cleanup.update(job_status=session.get(Job, lease.job_id).status,
                task_status=session.get(Task, lease.task_id).status,
                epoch=session.get(Job, lease.job_id).control_epoch)
        raise ProviderFailure('INDEPENDENT_CONTROLLED_LATE_FAILURE', outcome)

    provider = FakeProvider([late_failure])
    execute_translation(db, cfg, lease, provider)
    assert len(provider.calls) == 1
    with db.transaction() as session:
        permit = session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id))
        assert permit.state == permit_state and permit.actual_micro is None
        assert permit.reserved_micro > 0
        attempt = session.get(Attempt, lease.attempt_id)
        assert attempt.state == attempt_state and attempt.usage is None and attempt.request_id is None
        job, task = session.get(Job, lease.job_id), session.get(Task, lease.task_id)
        assert (job.status, task.status, job.control_epoch) == (
            after_cleanup['job_status'], after_cleanup['task_status'], after_cleanup['epoch'])
        assert job.payload == {} and task.payload == {} and task.result is None
        assert not list(session.scalars(select(Draft)))
        assert not list(session.scalars(select(SegmentVersion)))
        assert session.get(Document, 'doc').status == 'deleted'
    assert not (cfg.data / 'documents' / 'doc').exists()
    assert client.get('/api/v1/documents/doc').status_code == 410
    assert claim(db) is None


def test_late_unknown_accounting_waits_for_active_backup_boundary(database):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    from sqlalchemy import event, text
    from packages.billing.ledger import authorize
    from packages.translation.execution import retry_or_stop
    from tests.integration.test_budget import PRICE, setup
    db, _ = database
    lease, _ = setup(db)
    with db.transaction() as session:
        authorize(session, lease, 80, PRICE)
        session.get(Settings, 'singleton').maintenance = True
    called = threading.Event()
    waiting_pid = []

    def observe(conn, cursor, statement, params, context, many):
        if statement == 'SELECT pg_advisory_xact_lock_shared(798205424)':
            waiting_pid.append(conn.connection.driver_connection.info.backend_pid)
            called.set()

    with db.engine.connect() as backup:
        backup.execute(text('SELECT pg_advisory_lock(798205424)'))
        owner = backup.scalar(text('SELECT pg_backend_pid()'))
        backup.commit()
        event.listen(db.engine, 'before_cursor_execute', observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(retry_or_stop, db, lease, ProviderFailure('CONTROLLED_LATE_UNKNOWN', 'unknown'))
                try:
                    assert called.wait(5)
                    deadline = time.monotonic() + 5
                    blocked = False
                    while time.monotonic() < deadline:
                        blocked = owner in backup.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': waiting_pid[0]})
                        backup.commit()
                        if blocked:
                            break
                        time.sleep(.01)
                    assert blocked, 'Late accounting must wait for the actual exclusive maintenance lock'
                    assert not future.done()
                    with db.transaction() as session:
                        permit = session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id))
                        assert permit.state == 'reserved'
                finally:
                    backup.execute(text('SELECT pg_advisory_unlock(798205424)'))
                    backup.commit()
                future.result(timeout=5)
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe)
            backup.execute(text('SELECT pg_advisory_unlock_all()'))
            backup.commit()
    with db.transaction() as session:
        assert session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id)).state == 'unknown'
        assert session.get(Settings, 'singleton').maintenance
    assert claim(db) is None
