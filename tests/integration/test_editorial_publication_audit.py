"""Literal numeric correction and published-parent audit through public APIs."""
from pathlib import Path
import json
import uuid

import pytest
from sqlalchemy import select

from packages.domain.models import Artifact, Draft, SegmentVersion, SourceRevision, TranslationRevision
from packages.jobs.queue import claim
from packages.storage import file_hash, read_snapshot
from tests.integration.test_publication_lifecycle import drain, seal_and_publish
from tests.support import seed_editor
from workers.main import execute

pytestmark = pytest.mark.postgres


def test_correct_number_from_published_parent_preserves_auditable_bad_version_and_source(client, database):
    db, cfg = database
    ir = seed_editor(db, cfg)
    artifact_a, path_a = seal_and_publish(client, db, cfg, 1, 1, 'audit-a')
    hash_a = file_hash(path_a)
    drain(db, cfg)
    with db.transaction() as session:
        revision_a = session.get(Artifact, artifact_a).translation_revision_id
        prior = session.get(TranslationRevision, revision_a)
        prior_path, prior_hash = cfg.data / prior.storage_key, prior.snapshot_hash
        source = session.get(SourceRevision, 'src_fixture')
        source_path, source_hash = cfg.data / source.storage_key, source.snapshot_hash
    created = client.post('/api/v1/editions/edition_fixture/drafts', json={'translation_revision_id': revision_a},
        headers={'If-Match': '"2"', 'Idempotency-Key': 'audit-new-draft'})
    assert created.status_code == 201, created.text
    draft_id = created.json()['id']
    reason_bad = 'Controlled intentional numeric error for rejection evidence.'
    bad = client.patch(f'/api/v1/drafts/{draft_id}/segments/p1',
        json={'base_segment_version': 1, 'reason': reason_bad, 'target_inline': [{'type': 'text', 'text': '该任务有32个token。'}]},
        headers={'If-Match': created.headers['etag'], 'Idempotency-Key': 'audit-bad-number'})
    assert bad.status_code == 200, bad.text
    rejected = client.post(f'/api/v1/drafts/{draft_id}/validate', json={},
        headers={'If-Match': bad.headers['etag'], 'Idempotency-Key': 'audit-bad-qa'})
    assert rejected.status_code == 200 and not rejected.json()['valid']
    issue = next(i for i in rejected.json()['issues'] if i['code'] == 'NUMBER_MISMATCH')
    ignore = client.post(f'/api/v1/drafts/{draft_id}/issues/{issue["fingerprint"]}/resolve',
        json={'reason': 'Attempted bypass must fail.', 'evidence': {'page': 1, 'quote': 'The job has 64 tokens.'}},
        headers={'If-Match': bad.headers['etag'], 'Idempotency-Key': 'audit-ignore-hard'})
    assert ignore.status_code == 200  # Optional acknowledgment is an audit record.
    correct_nodes = next(r['target_inline'] for r in ir['translation_revision']['results'] if r['block_id'] == 'p1')
    correction_reason = 'Restored 64 from the saved original page 1; preserved its numeric atom.'
    fixed = client.patch(f'/api/v1/drafts/{draft_id}/segments/p1',
        json={'base_segment_version': 2, 'reason': correction_reason, 'target_inline': correct_nodes},
        headers={'If-Match': ignore.headers['etag'], 'Idempotency-Key': 'audit-correct-number'})
    assert fixed.status_code == 200, fixed.text
    qa = client.post(f'/api/v1/drafts/{draft_id}/validate', json={},
        headers={'If-Match': fixed.headers['etag'], 'Idempotency-Key': 'audit-good-qa'})
    assert qa.status_code == 200 and qa.json()['valid'], qa.text
    sealed = client.post(f'/api/v1/drafts/{draft_id}/seal', json={'qa_id': qa.json()['id'],
        'qa_fingerprint': qa.json()['fingerprint'], 'generation': fixed.json()['generation']},
        headers={'If-Match': fixed.headers['etag'], 'Idempotency-Key': 'audit-seal-b'})
    assert sealed.status_code == 201, sealed.text
    published = client.post('/api/v1/editions/edition_fixture/publish', json={
        'translation_revision_id': sealed.json()['id'], 'expected_generation': 3},
        headers={'If-Match': '"3"', 'Idempotency-Key': 'audit-publish-b'})
    assert published.status_code == 202, published.text
    execute(db, cfg, claim(db))
    with db.transaction() as session:
        revision_b = session.get(TranslationRevision, sealed.json()['id'])
        assert revision_b.parent_id == revision_a
        assert session.get(Draft, draft_id).base_revision_id == revision_a
        history = list(session.scalars(select(SegmentVersion).where(SegmentVersion.draft_id == draft_id,
            SegmentVersion.block_id == 'p1').order_by(SegmentVersion.sequence)))
        assert [s.sequence for s in history] == [1, 2, 3]
        assert history[1].reason == reason_bad and history[2].reason == correction_reason
        assert history[1].target_inline[0]['text'] == '该任务有32个token。'
        assert history[2].target_inline == correct_nodes and history[2].origin == 'manual_ui'
        assert history[0].created_at <= history[1].created_at <= history[2].created_at <= revision_b.created_at
        assert read_snapshot(cfg.data, revision_b)['source_revision_id'] == 'src_fixture'
    assert file_hash(prior_path) == prior_hash and file_hash(source_path) == source_hash
    assert file_hash(path_a) == hash_a
    output = Path('.agent/tmp/evidence/editorial-audit') / uuid.uuid4().hex
    output.mkdir(parents=True)
    (output / 'verification.json').write_text(json.dumps({'scope': 'API numeric correction on authored reviewed fixture; independent source review required',
        'source_pdf': 'fixtures/sample.pdf', 'source_quote': 'The job has 64 tokens.', 'page': 1,
        'bad_qa': rejected.json(), 'good_qa': qa.json(), 'corrected_target_inline': correct_nodes,
        'parent_translation_revision': revision_a, 'new_translation_revision': sealed.json()['id'],
        'prior_snapshot_sha256': prior_hash, 'source_snapshot_sha256': source_hash,
        'old_artifact_sha256': hash_a, 'numeric_history_sequences': [1, 2, 3]}, ensure_ascii=False, indent=2), encoding='utf-8')
