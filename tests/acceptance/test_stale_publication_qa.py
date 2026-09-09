"""The approval/seal gate cannot reuse pre-edit QA or a pre-edit draft ETag.

Publishing an explicitly selected historical sealed revision remains valid;
these assertions concern approving the new edited content with stale evidence.
"""
import pytest
from sqlalchemy import func, select

from packages.domain.models import Publication, TranslationRevision
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('etag', ['old', 'current'])
def test_changed_target_cannot_enter_publication_with_old_qa_or_etag(client, database, etag):
    seed_editor(*database)
    original = client.get('/api/v1/drafts/draft_fixture')
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': original.headers['etag'], 'Idempotency-Key': 'pre-edit-qa'})
    assert qa.status_code == 200 and qa.json()['valid']
    edited = client.patch('/api/v1/drafts/draft_fixture/segments/item',
        json={'base_segment_version': 1, 'target_inline': [{'type': 'text', 'text': '新版译文内容。'}],
            'reason': 'Explicit local revision after prior QA'},
        headers={'If-Match': original.headers['etag'], 'Idempotency-Key': 'post-qa-edit'})
    assert edited.status_code == 200, edited.text
    rejected = client.post('/api/v1/drafts/draft_fixture/seal', json={'qa_id': qa.json()['id'],
        'qa_fingerprint': qa.json()['fingerprint'], 'generation': edited.json()['generation']},
        headers={'If-Match': (original if etag == 'old' else edited).headers['etag'], 'Idempotency-Key': 'stale-publication-gate'})
    assert rejected.status_code == (412 if etag == 'old' else 201)
    if etag == 'old': assert rejected.json()['error']['code'] == 'PRECONDITION_FAILED'
    with database[0].transaction() as session:
        assert session.scalar(select(func.count()).select_from(TranslationRevision)) == (0 if etag == 'old' else 1)
        assert session.scalar(select(func.count()).select_from(Publication)) == 0
