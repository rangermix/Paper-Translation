import copy

import pytest
from sqlalchemy import delete, func, select

from packages.domain.models import Artifact, Edition, Export, Job, Publication, SegmentVersion, TranslationRevision
from packages.jobs.queue import claim
from packages.storage import write_snapshot
from tests.support import seed_editor
from workers.main import execute

pytestmark = pytest.mark.postgres


def test_explicit_draft_export_freezes_missing_blocks_without_publication(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.execute(delete(SegmentVersion).where(SegmentVersion.block_id == 'item'))
    body = {'format': 'single_html', 'include_source': False, 'confirm_draft': False}
    headers = {'If-Match': '"1"', 'Idempotency-Key': 'draft-export'}
    queued = client.post('/api/v1/drafts/draft_fixture/exports', json=body, headers=headers)
    assert queued.status_code == 202, queued.text
    assert queued.json()['missing_blocks'] == 1
    # A later edit must not change the exact snapshot already selected for export.
    changed = client.patch('/api/v1/drafts/draft_fixture/segments/item', json={'base_segment_version': 0,
        'reason': 'Later edit', 'target_inline': [{'type': 'text', 'text': 'Later target sentinel'}]},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'later-edit'})
    assert changed.status_code == 200, changed.text
    execute(db, cfg, claim(db))
    result = client.get('/api/v1/exports/' + queued.json()['export_id']).json()
    assert result['status'] == 'succeeded' and result['draft']
    exported = client.get(result['download_url'])
    assert exported.status_code == 200
    assert 'DRAFT' in exported.text and '缺失 1 块译文' in exported.text
    assert 'Later target sentinel' not in exported.text
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Artifact)) == 0
        assert session.scalar(select(func.count()).select_from(Publication)) == 0
        assert session.get(Edition, 'edition_fixture').current_artifact_id is None
        assert session.get(Export, queued.json()['export_id']).artifact_id is None


def test_direct_publish_of_incomplete_internal_revision_is_blocked_before_enqueue(client, database):
    db, cfg = database
    fixture = seed_editor(db, cfg)
    tr = copy.deepcopy(fixture['translation_revision'])
    tr['id'] = 'tr_invalid'
    tr['source_revision_id'] = fixture['source_revision']['id']
    tr['results'] = [r for r in tr['results'] if r['block_id'] != 'item']
    key = 'documents/doc_fixture/translations/invalid.json'
    snapshot_hash = write_snapshot(cfg.data, key, tr)
    with db.transaction() as session:
        session.add(TranslationRevision(id='tr_invalid', document_id='doc_fixture', edition_id='edition_fixture',
            source_revision_id='src_fixture', snapshot_hash=snapshot_hash, storage_key=key, qa_fingerprint='controlled-invalid-fixture'))
    answer = client.post('/api/v1/editions/edition_fixture/publish', json={'translation_revision_id': 'tr_invalid',
        'template_id': 'reader-v1', 'expected_generation': 1}, headers={'If-Match': '"1"', 'Idempotency-Key': 'invalid-publish'})
    assert answer.status_code == 409 and answer.json()['error']['code'] == 'PUBLICATION_INPUT_INVALID'
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(Publication)) == 0
