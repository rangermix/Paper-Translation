"""Literal M0-AT14B: real PostgreSQL commit races and expired fencing."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, Lock

import pytest
from sqlalchemy import select

from packages.domain.errors import DomainError
from packages.domain.models import Artifact, Edition, Publication, Task, now
from packages.jobs.queue import claim, recover_expired
from tests.support import seed_editor
import workers.main as worker

pytestmark = pytest.mark.postgres


def queue_publications(client, count):
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'race-qa'}).json()
    assert qa['valid'], qa
    sealed = client.post('/api/v1/drafts/draft_fixture/seal',
        json={'qa_id': qa['id'], 'qa_fingerprint': qa['fingerprint'], 'generation': 1},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'race-seal'})
    assert sealed.status_code == 201, sealed.text
    for index in range(count):
        queued = client.post('/api/v1/editions/edition_fixture/publish',
            json={'translation_revision_id': sealed.json()['id'], 'expected_generation': 1},
            headers={'If-Match': '"1"', 'Idempotency-Key': f'race-publish-{index}'})
        assert queued.status_code == 202, queued.text


def synchronize_commit(monkeypatch):
    original = worker.assert_current
    counts, lock, barrier, waiting = Counter(), Lock(), Barrier(2), Event()
    def checked(session, lease, **kwargs):
        with lock:
            counts[(lease.task_id, lease.fence)] += 1
            at_commit = counts[(lease.task_id, lease.fence)] == 2
        if at_commit:
            waiting.set()
            barrier.wait(timeout=15)
        return original(session, lease, **kwargs)
    monkeypatch.setattr(worker, 'assert_current', checked)
    return waiting


def outcome(db, cfg, lease):
    try:
        worker.publish(db, cfg, lease)
        return 'published'
    except DomainError as error:
        return error.code


def assert_one_publication(db):
    with db.transaction() as session:
        edition = session.get(Edition, 'edition_fixture')
        events = list(session.scalars(select(Publication)))
        artifacts = list(session.scalars(select(Artifact)))
        assert edition.generation == 2 and len(events) == len(artifacts) == 1
        assert events[0].artifact_id == artifacts[0].id == edition.current_artifact_id


def test_two_workers_same_expected_generation_commit_once(client, database, monkeypatch):
    db, cfg = database
    seed_editor(db, cfg)
    queue_publications(client, 2)
    leases = [claim(db), claim(db)]
    assert leases[0].task_id != leases[1].task_id
    synchronize_commit(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda lease: outcome(db, cfg, lease), leases))
    assert sorted(results) == ['PRECONDITION_FAILED', 'published']
    assert_one_publication(db)


def test_expired_and_reclaimed_worker_simultaneous_commit_rejects_old_fence(client, database, monkeypatch):
    db, cfg = database
    seed_editor(db, cfg)
    queue_publications(client, 1)
    expired = claim(db)
    waiting = synchronize_commit(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_result = pool.submit(outcome, db, cfg, expired)
        assert waiting.wait(timeout=10), 'Old worker did not finish its immutable artifact.'
        # Fault injection expires a real persisted lease while its worker is
        # paused immediately before commit, then uses normal queue recovery.
        with db.transaction() as session:
            session.get(Task, expired.task_id).lease_expires = now() - timedelta(seconds=1)
        recover_expired(db)
        current = claim(db)
        assert current.task_id == expired.task_id and current.fence == expired.fence + 1
        new_result = pool.submit(outcome, db, cfg, current)
        assert old_result.result(timeout=20) == 'FENCE_EXPIRED'
        assert new_result.result(timeout=20) == 'published'
    assert_one_publication(db)
