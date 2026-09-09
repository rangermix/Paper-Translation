from datetime import timedelta

import pytest
from sqlalchemy import select

from packages.domain.errors import DomainError
from packages.domain.models import Attempt, Job, Permit, Task, new_id, now
from packages.jobs.queue import assert_current, claim, recover_expired

pytestmark = pytest.mark.postgres


def make_job(db):
    with db.transaction() as session:
        job = Job(id=new_id('job'), stage='translate', budget_micro=100)
        session.add(job)
        session.flush()
        session.add(Task(id=new_id('task'), job_id=job.id, kind='translate'))
    return job


def test_expired_local_fence_cannot_commit(database):
    db, _ = database
    make_job(db)
    old = claim(db)
    with db.transaction() as session:
        session.get(Task, old.task_id).lease_expires = now() - timedelta(seconds=1)
    recover_expired(db)
    new = claim(db)
    assert new.fence > old.fence
    with pytest.raises(DomainError, match='Fence expired'):
        with db.transaction() as session:
            assert_current(session, old)


def test_dispatched_timeout_keeps_risk_and_never_reclaims(database):
    db, _ = database
    job = make_job(db)
    lease = claim(db)
    with db.transaction() as session:
        session.get(Task, lease.task_id).lease_expires = now() - timedelta(seconds=1)
        session.get(Attempt, lease.attempt_id).state = 'dispatching'
        session.add(Permit(id=new_id('permit'), attempt_id=lease.attempt_id, job_id=job.id, control_epoch=0, price_snapshot={'version': 'test'}, reserved_micro=80))
    recover_expired(db)
    assert claim(db) is None
    with db.transaction() as session:
        assert session.get(Job, job.id).status == 'outcome_unknown'
        permit = session.scalar(select(Permit))
        assert permit.state == 'unknown' and permit.reserved_micro == 80
