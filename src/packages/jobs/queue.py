"""Short PostgreSQL leases. External dispatch is a separate durable decision."""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import exists, func, select, text

from packages.domain.db import get_document, lock_lifecycle, writable
from packages.domain.errors import require
from packages.domain.models import Attempt, Event, Job, Permit, Settings, Task, new_id, now


@dataclass(frozen=True)
class Lease:
    task_id: str
    job_id: str
    attempt_id: str
    fence: int
    control_epoch: int
    kind: str
    document_id: str | None
    payload: dict


def emit(session, job):
    job.generation += 1
    session.add(Event(id=new_id('event'), job_id=job.id, generation=job.generation,
        payload={'stage': job.stage, 'status': job.status, 'progress': job.progress, 'control_epoch': job.control_epoch}))
    session.flush()  # Return the same transactional timestamps that readers will see.


def claim(db, lease_seconds=60):
    with db.transaction() as session:
        session.execute(text('SELECT pg_advisory_xact_lock_shared(798205424)'))
        settings = session.get(Settings, 'singleton')
        if not settings or settings.maintenance:
            return None
        eligible = exists(select(Task.id).where(Task.job_id == Job.id, Task.status == 'pending', Task.available_at <= now()))
        last_claim = (select(Attempt.job_id, func.max(Attempt.created_at).label('at'))
            .group_by(Attempt.job_id).subquery())
        # Rotate jobs after every claim, including retries. A large document's
        # many ready units must not monopolize the pool ahead of smaller files.
        job = session.scalar(select(Job).outerjoin(last_claim, last_claim.c.job_id == Job.id)
            .where(Job.status.in_(['pending', 'running']), eligible)
            .order_by(func.coalesce(last_claim.c.at, Job.created_at), Job.created_at, Job.id)
            .with_for_update(of=Job, skip_locked=True).limit(1))
        if not job:
            return None
        task = session.scalar(select(Task).where(Task.job_id == job.id, Task.status == 'pending', Task.available_at <= now())
            .order_by(Task.created_at, Task.id).with_for_update(skip_locked=True).limit(1))
        if not task:
            return None
        if job.document_id and task.kind != 'cleanup':
            get_document(session, job.document_id)
        task.status, job.status = 'leased', 'running'
        task.fence += 1
        task.attempts += 1
        task.lease_expires = now() + timedelta(seconds=lease_seconds)
        attempt = Attempt(id=new_id('attempt'), task_id=task.id, job_id=job.id, fence=task.fence, control_epoch=job.control_epoch)
        if task.kind not in {'parse', 'recovery', 'translate', 'candidate', 'semantic_review', 'provider_test'}:
            job.actual_model = task.actual_model = attempt.actual_model = {'kind': 'none', 'models': []}
        session.add(attempt)
        emit(session, job)
        return Lease(task.id, job.id, attempt.id, task.fence, job.control_epoch, task.kind, job.document_id, task.payload)


def assert_current(session, lease, *, allow_paused=False):
    # Includes index/cache FK insertion: it can implicitly lock Document even
    # when no explicit get_document(lock=True) appears in the worker code.
    lock_lifecycle(session)
    job = session.scalar(select(Job).where(Job.id == lease.job_id).with_for_update().execution_options(populate_existing=True))
    task = session.scalar(select(Task).where(Task.id == lease.task_id).with_for_update().execution_options(populate_existing=True))
    # Once a live lease is checked under these locks, no other transaction can
    # renew, reclaim or cancel it until commit/rollback. Local result validation
    # can exceed the lease duration while holding the locks. Rechecking wall
    # time at finish would reject our own commit and repeatedly redo inference.
    # Bind this proof to the exact transaction/savepoint that owns the locks;
    # a later transaction (or a rolled-back savepoint) must check expiry again.
    transaction = session.get_nested_transaction() or session.get_transaction()
    checked_transaction, checked = session.info.get('locked_leases', (None, set()))
    if checked_transaction is not transaction:
        checked = set()
    identity = (lease.job_id, lease.task_id, lease.attempt_id, lease.fence, lease.control_epoch)
    require(job and task and task.fence == lease.fence and task.status == 'leased'
        and (identity in checked or task.lease_expires > now()), 'FENCE_EXPIRED')
    require(job.control_epoch == lease.control_epoch and job.status in (('running', 'paused') if allow_paused else ('running',)), 'CONTROL_CHANGED')
    if job.document_id and task.kind != 'cleanup':
        get_document(session, job.document_id)
    checked.add(identity)
    session.info['locked_leases'] = (transaction, checked)
    return job, task


def renew(db, lease, lease_seconds=60):
    with db.transaction() as session:
        session.execute(text('SELECT pg_advisory_xact_lock_shared(798205424)'))
        if session.get(Settings, 'singleton').maintenance:
            return False
        job = session.get(Job, lease.job_id)
        task = session.scalar(select(Task).where(Task.id == lease.task_id).with_for_update())
        if not task or task.fence != lease.fence or task.status != 'leased' or task.lease_expires <= now():
            return False
        if job.control_epoch != lease.control_epoch:
            return False
        task.lease_expires = now() + timedelta(seconds=lease_seconds)
        return True


def finish(session, lease, result=None, status='succeeded'):
    job, task = assert_current(session, lease)
    task.status, task.result = 'succeeded', result or {}
    attempt = session.get(Attempt, lease.attempt_id)
    attempt.finished_at = now()
    if attempt.state == 'created':
        attempt.state = 'succeeded'
    session.flush()
    left = session.scalar(select(Task.id).where(Task.job_id == job.id, Task.status.in_(['pending', 'leased'])).limit(1))
    if not left:
        job.status = status
    emit(session, job)
    return job


def recover_expired(db):
    with db.transaction() as session:
        session.execute(text('SELECT pg_advisory_xact_lock_shared(798205424)'))
        if session.get(Settings, 'singleton').maintenance:
            return
        lock_lifecycle(session)
        jobs = session.scalars(select(Job).where(exists(select(Task.id).where(Task.job_id == Job.id, Task.status == 'leased', Task.lease_expires <= now())))
            .with_for_update(skip_locked=True))
        for job in jobs:
            for task in session.scalars(select(Task).where(Task.job_id == job.id, Task.status == 'leased', Task.lease_expires <= now()).with_for_update()):
                attempt = session.scalar(select(Attempt).where(Attempt.task_id == task.id, Attempt.fence == task.fence))
                if attempt:
                    attempt.finished_at = now()
                    if attempt.state == 'created':
                        attempt.state = 'failed'
                permit = session.scalar(select(Permit).where(Permit.attempt_id == attempt.id)) if attempt else None
                if permit and permit.state in ('reserved', 'unknown'):
                    permit.state, attempt.state, job.status, task.status = 'unknown', 'outcome_unknown', 'outcome_unknown', 'outcome_unknown'
                elif job.status in ('cancelled', 'cancel_requested'):
                    task.status = 'cancelled'
                elif task.kind == 'provider_test':
                    # A connection test is a single explicit attempt. Even a
                    # settled response lost before finish must never be resent.
                    task.status, job.status = 'failed', 'failed'
                    job.error = {'code': 'PROVIDER_TEST_INTERRUPTED'}
                elif task.attempts >= 3:
                    task.status, job.status = 'failed', 'failed'
                    job.error = {'code': 'ATTEMPT_LIMIT'}
                else:
                    task.status = 'pending'
                    if job.status != 'paused':
                        job.status = 'pending'
                emit(session, job)
