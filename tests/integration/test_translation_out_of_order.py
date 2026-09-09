"""Held first transport returns after later units commit; ordering remains exact."""
import copy
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy import func, select

from packages.domain.models import Draft, Job, Permit, SegmentVersion, Task
from packages.ir import flatten_inline
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import PROFILE, setup_library

pytestmark = pytest.mark.postgres


def test_parallel_late_first_unit_reassembles_in_original_order(database):
    db, cfg = database
    source = setup_library(db, cfg)
    profile = PROFILE | {'max_unit_characters': 8}
    with db.transaction() as session:
        job = session.get(Job, 'job')
        job.payload = job.payload | {'block_ids': ['p1'], 'profile': profile}
        session.get(Draft, 'draft').profile = profile
    execute_translation(db, cfg, claim(db), FakeProvider())
    leases = []
    while lease := claim(db):
        leases.append(lease)
    leases.sort(key=lambda lease: lease.payload['unit']['unit_order'])
    assert len(leases) >= 3 and all(lease.payload['unit']['owner_block_id'] == 'p1' for lease in leases)
    entered, release = threading.Event(), threading.Event()
    completions, inflight = [], []

    def held_first(units):
        entered.set()
        assert release.wait(10), 'Test must release the first Provider response.'
        return {'results': [{'unit_id': units[0]['unit_id'], 'target_inline': copy.deepcopy(units[0]['source_inline'])}]}

    def observe_later(units):
        with db.transaction() as session:
            inflight.append(session.scalar(select(func.count()).select_from(Permit).where(Permit.state == 'reserved')))
        return {'results': [{'unit_id': units[0]['unit_id'], 'target_inline': copy.deepcopy(units[0]['source_inline'])}]}

    first_provider = FakeProvider([held_first])
    later_provider = FakeProvider([observe_later] * (len(leases) - 1))
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(execute_translation, db, cfg, leases[0], first_provider)
        try:
            assert entered.wait(5), 'First transport did not start.'
            for later in reversed(leases[1:]):
                execute_translation(db, cfg, later, later_provider)
                completions.append(later.payload['unit']['unit_order'])
                with db.transaction() as session:
                    assert session.get(Task, later.task_id).status == 'succeeded'
                    assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
                    assert session.get(Job, 'job').progress['verified_blocks'] == 0
        finally:
            release.set()
        first.result(timeout=10)
    completions.append(0)
    assert completions == list(reversed(range(len(leases))))
    assert inflight == [2] * (len(leases) - 1)
    with db.transaction() as session:
        segments = list(session.scalars(select(SegmentVersion)))
        assert len(segments) == 1 and segments[0].block_id == 'p1'
        paragraph = next(b for b in source['blocks'] if b['id'] == 'p1')
        assert flatten_inline(segments[0].target_inline, source['protected_atoms']) == paragraph['normalized_text']
        job = session.get(Job, 'job')
        assert job.progress['verified_blocks'] == 1 and job.progress['verified_units'] == len(leases)
        assert job.progress['requests'] == len(first_provider.calls) + len(later_provider.calls) == len(leases)
        assert all(permit.state == 'settled' for permit in session.scalars(select(Permit)))
