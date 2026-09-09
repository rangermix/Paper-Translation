"""Independent current-scope checks for optional, explicitly simulated review."""
import copy

import pytest
from sqlalchemy import select

from packages.domain.models import Draft, Job, ReviewRecord, Task
from packages.editorial.drafts import current_segments, edit_segment
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_semantic_review_status import begin_review
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def edit(client, block_id, key):
    draft = client.get('/api/v1/drafts/draft_fixture')
    segment = next(s for s in draft.json()['segments'] if s['block_id'] == block_id)
    nodes = copy.deepcopy(segment['target_inline'])
    next(n for n in nodes if n['type'] == 'text')['text'] += '字'
    changed = client.patch('/api/v1/drafts/draft_fixture/segments/' + block_id,
        json={'target_inline': nodes, 'base_segment_version': segment['version'], 'reason': 'Independent controlled review-scope change'},
        headers={'If-Match': draft.headers['etag'], 'Idempotency-Key': key})
    assert changed.status_code == 200, changed.text
    return changed.json()


def test_unrequested_semantic_review_is_explicit(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    draft = client.get('/api/v1/drafts/draft_fixture').json()
    assert draft['semantic_review_status'] == 'not_requested' and draft['semantic_reviews'] == []


@pytest.mark.parametrize('timing,block_id,expected', [
    ('after', 'item', 'completed'), ('during', 'item', 'completed'), ('during', 'p1', 'stale')])
def test_review_currentness_tracks_only_selected_target(client, database, monkeypatch, tmp_path, timing, block_id, expected):
    db, cfg = database
    job_id, _ = begin_review(client, db, cfg, monkeypatch, tmp_path)

    class ScopedProvider(FakeProvider):
        def review(self, units, profile, glossary):
            if timing == 'during':
                edit(client, block_id, 'during-review')
            return super().review(units, profile, glossary)

    provider = ScopedProvider()
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    if timing == 'after':
        edit(client, block_id, 'after-review')
    observed = client.get('/api/v1/drafts/draft_fixture').json()
    assert observed['semantic_review_status'] == expected
    row = observed['semantic_reviews'][-1]
    assert row['job_id'] == job_id and row['block_ids'] == ['p1'] and row['completed'] == (expected == 'completed')
    assert len(provider.calls) == 1
    with db.transaction() as session:
        assert session.get(Job, job_id).progress['review_completed'] is True
        assert not list(session.scalars(select(ReviewRecord)))
        review_tasks = [t for t in session.scalars(select(Task).where(Task.job_id == job_id)) if 'unit' in t.payload]
        assert len(review_tasks) == 1 and review_tasks[0].result['stale'] == (timing == 'during' and block_id == 'p1')


def test_same_target_with_new_selected_glossary_lineage_is_stale(client, database, monkeypatch, tmp_path):
    db, cfg = database
    job_id, _ = begin_review(client, db, cfg, monkeypatch, tmp_path)
    while lease := claim(db):
        execute_translation(db, cfg, lease, FakeProvider())
    assert client.get('/api/v1/drafts/draft_fixture').json()['semantic_review_status'] == 'completed'
    with db.transaction() as session:
        draft = session.get(Draft, 'draft_fixture')
        segment = current_segments(session, draft.id)['p1']
        edit_segment(session, cfg, draft, 'p1', copy.deepcopy(segment.target_inline), segment.sequence,
            'Controlled lineage-only accepted candidate equivalent', provenance={'glossary_revision': 'independent-new-terms'})
    observed = client.get('/api/v1/drafts/draft_fixture').json()
    assert observed['semantic_review_status'] == 'stale'
    with db.transaction() as session:
        assert session.get(Job, job_id).progress['review_completed'] is True
