"""A locked commit can outlast its lease; a released lock cannot authorize one."""
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from packages.domain.errors import DomainError
from packages.domain.models import Attempt, Job, Task, now
from packages.jobs import queue
from tests.integration.test_queue import make_job

pytestmark = pytest.mark.postgres


def expire_clock(monkeypatch):
    later = now() + timedelta(minutes=2)
    monkeypatch.setattr(queue, 'now', lambda: later)


def test_locked_commit_finishes_after_wall_clock_lease_expiry(database, monkeypatch):
    db, _ = database
    make_job(db)
    lease = queue.claim(db)
    with db.transaction() as session:
        queue.assert_current(session, lease)
        # Real PostgreSQL locks exclude both renewal and a competing writer.
        with pytest.raises(OperationalError):
            with db.transaction() as competitor:
                competitor.scalar(select(Task).where(Task.id == lease.task_id).with_for_update(nowait=True))
        expire_clock(monkeypatch)
        queue.finish(session, lease, {'saved': True})
    queue.recover_expired(db)
    assert queue.claim(db) is None
    with db.transaction() as session:
        assert session.get(Job, lease.job_id).status == 'succeeded'
        assert session.get(Task, lease.task_id).result == {'saved': True}
        assert session.get(Attempt, lease.attempt_id).state == 'succeeded'


def test_parser_result_commit_can_outlast_lease(client, database, monkeypatch):
    import workers.main as worker
    from tests.integration.test_source_replacement import test_reparse_worker_binds_parent_and_explicit_preflight_images
    _, cfg = database
    original_write = worker.atomic_write

    def slow_result_copy(root, key, data):
        result = original_write(root, key, data)
        if root == cfg.data and '/parser/' in key:
            expire_clock(monkeypatch)
        return result

    monkeypatch.setattr(worker, 'atomic_write', slow_result_copy)
    test_reparse_worker_binds_parent_and_explicit_preflight_images(client, database, monkeypatch, False)


@pytest.mark.parametrize('end', ['commit', 'rollback'])
def test_checked_lease_is_not_reused_in_next_transaction(database, monkeypatch, end):
    db, _ = database
    make_job(db)
    lease = queue.claim(db)
    with db.session_factory() as session:
        queue.assert_current(session, lease)
        getattr(session, end)()
        expire_clock(monkeypatch)
        with pytest.raises(DomainError, match='Fence expired'):
            queue.finish(session, lease)


def test_savepoint_rollback_cannot_preserve_released_lock_proof(database, monkeypatch):
    db, _ = database
    make_job(db)
    lease = queue.claim(db)
    with db.transaction() as session:
        nested = session.begin_nested()
        queue.assert_current(session, lease)
        nested.rollback()
        expire_clock(monkeypatch)
        with pytest.raises(DomainError, match='Fence expired'):
            queue.finish(session, lease)


@pytest.mark.parametrize('mutation,code', [('fence', 'FENCE_EXPIRED'),
    ('status', 'FENCE_EXPIRED'), ('control_epoch', 'CONTROL_CHANGED'), ('cancel', 'CONTROL_CHANGED')])
def test_locked_commit_still_rechecks_identity_and_control(database, monkeypatch, mutation, code):
    db, _ = database
    make_job(db)
    lease = queue.claim(db)
    with db.transaction() as session:
        job, task = queue.assert_current(session, lease)
        if mutation == 'fence':
            task.fence += 1
        elif mutation == 'status':
            task.status = 'cancelled'
        elif mutation == 'control_epoch':
            job.control_epoch += 1
        else:
            job.status = 'cancelled'
        expire_clock(monkeypatch)
        with pytest.raises(DomainError) as rejected:
            queue.finish(session, lease)
        assert rejected.value.code == code


def test_expired_other_lease_cannot_borrow_same_transaction_proof(database, monkeypatch):
    db, _ = database
    make_job(db)
    make_job(db)
    lease, other = queue.claim(db), queue.claim(db)
    with db.transaction() as session:
        queue.assert_current(session, lease)
        expire_clock(monkeypatch)
        with pytest.raises(DomainError, match='Fence expired'):
            queue.finish(session, other)


def test_failed_control_check_does_not_establish_lock_proof(database, monkeypatch):
    db, _ = database
    make_job(db)
    lease = queue.claim(db)
    with db.transaction() as session:
        with pytest.raises(DomainError, match='Control changed'):
            queue.assert_current(session, replace(lease, control_epoch=lease.control_epoch + 1))
        expire_clock(monkeypatch)
        with pytest.raises(DomainError, match='Fence expired'):
            queue.finish(session, lease)
