"""A long job cannot consume every claim ahead of newly queued small jobs."""
from datetime import timedelta

import pytest

from packages.domain.models import Job, Task, now
from packages.jobs.queue import claim, finish

pytestmark = pytest.mark.postgres


def test_small_jobs_get_a_turn_between_large_job_units(database):
    db, _ = database
    with db.transaction() as session:
        session.add(Job(id='bulk_job', stage='translate', created_at=now()-timedelta(minutes=1)))
        session.add(Job(id='small_job', stage='translate'))
        session.flush()
        for i in range(12):
            session.add(Task(id=f'bulk_{i:02}', job_id='bulk_job', kind='unit'))
        session.add(Task(id='small_00', job_id='small_job', kind='unit'))
    first = claim(db)
    assert first.job_id == 'bulk_job'
    second = claim(db)
    assert second.job_id == 'small_job'
    with db.transaction() as session:
        finish(session, second)
    # The large job can continue while its first unit remains in flight.
    third = claim(db)
    assert third.job_id == 'bulk_job' and third.task_id != first.task_id
