import copy

import pytest
from sqlalchemy import select

from packages.domain.models import Draft, ReviewRecord, SegmentVersion, TranslationRevision
from packages.storage import file_hash
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_review_edit_invalidates_only_current_block_and_stale_qa(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    fetched = client.get('/api/v1/drafts/draft_fixture')
    draft = fetched.json()
    segment = next(s for s in draft['segments'] if s['block_id'] == 'p1')
    review = client.post('/api/v1/drafts/draft_fixture/segments/p1/confirm-review', json={'source_hash': segment['source_hash'], 'base_segment_version': 1,
        'context_hash': segment['context_hash'], 'glossary_revision': 'empty-v1', 'reason': 'Compared against original page 1'},
        headers={'If-Match': fetched.headers['etag'], 'Idempotency-Key': 'review'})
    assert review.status_code == 200, review.text
    assert next(s for s in review.json()['segments'] if s['block_id'] == 'p1')['review_status'] == 'human_reviewed'
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={}, headers={'If-Match': review.headers['etag'], 'Idempotency-Key': 'validate'})
    assert qa.status_code == 200 and qa.json()['valid'], qa.text
    changed = client.patch('/api/v1/drafts/draft_fixture/segments/p1', json={'base_segment_version': 1, 'reason': 'Introduce test mistranslation',
        'target_inline': [{'type': 'text', 'text': '该任务有32个token。'}]}, headers={'If-Match': review.headers['etag'], 'Idempotency-Key': 'edit'})
    assert changed.status_code == 200, changed.text
    assert next(s for s in changed.json()['segments'] if s['block_id'] == 'p1')['review_status'] == 'not_reviewed'
    stale = client.post('/api/v1/drafts/draft_fixture/seal', json={'qa_id': qa.json()['id'], 'qa_fingerprint': qa.json()['fingerprint'], 'generation': changed.json()['generation']},
        headers={'If-Match': changed.headers['etag'], 'Idempotency-Key': 'stale-seal'})
    assert stale.status_code == 201  # Stale QA is refreshed; current draft ETag still applies.
    bad = client.post('/api/v1/drafts/draft_fixture/validate', json={}, headers={'If-Match': changed.headers['etag'], 'Idempotency-Key': 'validate-bad'})
    assert not bad.json()['valid']
    assert {'PROTECTED_MISMATCH', 'NUMBER_MISMATCH'} <= {i['code'] for i in bad.json()['issues']}
    with db.transaction() as s:
        assert len(list(s.scalars(select(ReviewRecord)))) == 1
        assert len(list(s.scalars(select(SegmentVersion).where(SegmentVersion.block_id == 'p1')))) == 2


def test_sealed_revision_immutable_and_etag_conflict(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={}, headers={'If-Match': '"1"', 'Idempotency-Key': 'qa'})
    assert qa.json()['valid'], qa.text
    sealed = client.post('/api/v1/drafts/draft_fixture/seal', json={'qa_id': qa.json()['id'], 'qa_fingerprint': qa.json()['fingerprint'], 'generation': 1},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'seal'})
    assert sealed.status_code == 201, sealed.text
    with db.transaction() as session:
        entity = session.get(TranslationRevision, sealed.json()['id'])
        path = cfg.data / entity.storage_key
        before = file_hash(path)
    body = {'base_segment_version': 1, 'reason': 'A local revision', 'target_inline': [{'type': 'text', 'text': '保留这份原件。'}]}
    assert client.patch('/api/v1/drafts/draft_fixture/segments/item', json=body, headers={'If-Match': '"1"', 'Idempotency-Key': 'first'}).status_code == 200
    assert client.patch('/api/v1/drafts/draft_fixture/segments/item', json=body, headers={'If-Match': '"1"', 'Idempotency-Key': 'second'}).status_code == 412
    assert file_hash(path) == before
