"""Block progress must follow complete reconstruction, not request count."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from packages.domain.models import Draft, Job, SegmentVersion, Task, now
from packages.ir import flatten_inline
from packages.jobs.queue import claim
from packages.providers.contract import ProviderFailure
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import PROFILE, setup_library

pytestmark = pytest.mark.postgres


def test_split_blocks_and_retry_report_only_fully_verified_blocks(database):
    db, cfg = database
    source = setup_library(db, cfg)
    profile = PROFILE | {'max_unit_characters': 10}
    with db.transaction() as session:
        job = session.get(Job, 'job')
        job.payload = job.payload | {'profile': profile}
        session.get(Draft, 'draft').profile = profile
    provider = FakeProvider([ProviderFailure('PROVIDER_RATE_LIMIT', 'not_executed', 2)])
    execute_translation(db, cfg, claim(db), provider)
    with db.transaction() as session:
        progress = dict(session.get(Job, 'job').progress)
        assert progress['total_units'] > progress['total_blocks'] > 1
    observations = []
    for _ in range(100):
        lease = claim(db)
        if lease is None:
            break
        execute_translation(db, cfg, lease, provider)
        with db.transaction() as session:
            job = session.get(Job, 'job')
            progress = dict(job.progress)
            complete_blocks = session.scalar(select(func.count()).select_from(SegmentVersion))
            assert progress['verified_blocks'] == complete_blocks
            if progress['verified_units'] < progress['total_units']:
                assert progress['verified_blocks'] < progress['total_blocks']
            observations.append(progress)
            # The first explicitly-not-executed response used the normal retry
            # path. Advance only that persisted backoff for deterministic tests.
            for task in session.scalars(select(Task).where(Task.status == 'pending', Task.available_at > now())):
                task.available_at = now() - timedelta(seconds=1)
    else:
        raise AssertionError('Unexpected unbounded retries.')
    with db.transaction() as session:
        progress = session.get(Job, 'job').progress
        assert progress['requests'] == len(provider.calls) == progress['total_units'] + 1
        assert progress['verified_units'] == progress['total_units']
        assert progress['verified_blocks'] == progress['total_blocks']
        by_id = {b['id']: b for b in source['blocks']}
        for segment in session.scalars(select(SegmentVersion)):
            assert flatten_inline(segment.target_inline, source['protected_atoms']) == by_id[segment.block_id]['normalized_text']
    assert any(o['requests'] > o['verified_blocks'] and o['verified_blocks'] < o['total_blocks'] for o in observations)
