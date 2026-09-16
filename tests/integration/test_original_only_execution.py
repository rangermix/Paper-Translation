"""Production queue/QA/publication with synthetic content and FakeProvider."""
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from packages.domain.models import Document, Draft, Job, Permit, QA, SegmentVersion, SourceRevision, TranslationRevision
from packages.editorial.drafts import current_segments, edit_segment, translation_snapshot
from packages.ir import canonical_bytes, digest, validate_ir
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.publisher import Publisher, export_bundle, export_single_html
from packages.storage import read_snapshot, write_snapshot
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import setup_library
from tests.unit.test_original_only import RETAINED, academic_paper


def setup_paper(db, cfg):
    setup_library(db, cfg)
    src = academic_paper()
    previous_id, src['id'] = src['id'], 'src_academic'
    key = 'academic-source.json'
    sha = write_snapshot(cfg.data, key, src)
    with db.transaction() as session:
        session.add(SourceRevision(id=src['id'], document_id='doc', asset_id=src['original_asset_id'],
            parent_id=previous_id, storage_key=key, snapshot_hash=sha))
        session.flush()
        session.get(Document, 'doc').current_source_id = src['id']
        session.get(Draft, 'draft').source_revision_id = src['id']
        job = session.get(Job, 'job')
        job.payload = job.payload | {'source_revision_id': src['id'], 'source_hash': sha, 'publish_policy': 'auto_publish'}
    return src


def test_retained_content_never_dispatched_and_survives_qa_publication(database):
    from packages.editorial.drafts import render_input
    db, cfg = database
    src = setup_paper(db, cfg)
    provider = FakeProvider()
    while lease := claim(db):
        if lease.kind == 'publish':
            from workers.main import publish
            publish(db, cfg, lease)
        elif lease.kind == 'index':
            from packages.search import update_index
            update_index(db, cfg, lease)
        else:
            execute_translation(db, cfg, lease, provider)
    expected = {b['id'] for b in src['blocks']} - RETAINED.keys()
    assert {u['owner_block_id'] for call in provider.calls for u in call} == expected
    with db.transaction() as session:
        assert set(current_segments(session, 'draft')) == expected
        job = session.get(Job, 'job')
        assert job.status == 'succeeded'
        assert job.progress['fallback_blocks'] == 0
        qa = session.get(QA, session.get(Draft, 'draft').qa_id)
        assert qa.issues == []
        revision = session.get(TranslationRevision, job.progress['translation_revision_id'])
        tr = read_snapshot(cfg.data, revision)
        for row in tr['results']:
            if row['block_id'] in RETAINED:
                assert row['status'] == 'retained'
                assert row['reason'] == RETAINED[row['block_id']]
                assert row['target_inline'] == [] and row['warnings'] == []
        assert read_snapshot(cfg.data, session.get(SourceRevision, src['id'])) == src
        assert all(p.state == 'settled' for p in session.scalars(select(Permit)))
        assert len(list(session.scalars(select(Permit)))) == len(provider.calls)
        ir = render_input('doc', src, tr, 'reader-v3')
        validate_ir(ir)
    # Optional durable browser fixture stays in this run's evidence directory.
    output = Path(os.environ['ORIGINAL_ONLY_EVIDENCE']) if os.environ.get('ORIGINAL_ONLY_EVIDENCE') else cfg.data / 'reading-test'
    output.mkdir(parents=True, exist_ok=True)
    Publisher().build(ir, cfg.data, output / 'artifact', include_source=True)
    export_single_html(output / 'artifact', output / 'reading.html', include_source=True)
    export_bundle(output / 'artifact', output / 'reading.zip', include_source=True)
    (output / 'render-input.json').write_bytes(canonical_bytes(ir))


def test_retained_metadata_is_not_editable_and_old_segments_do_not_supply_a_target(database):
    from apps.api.editorial import draft_view
    from packages.domain.errors import DomainError
    db, cfg = database
    src = setup_paper(db, cfg)
    with db.transaction() as session:
        draft = session.get(Draft, 'draft')
        view = draft_view(session, cfg, draft)
        assert {s['block_id'] for s in view['segments'] if not s['translatable']} == RETAINED.keys()
        with pytest.raises(DomainError) as exc:
            edit_segment(session, cfg, draft, 'authors', [{'type': 'text', 'text': 'Discarded translation'}], 0, 'Attempt edit')
        assert exc.value.code == 'NOT_FOUND'
        block = next(b for b in src['blocks'] if b['id'] == 'authors')
        session.add(SegmentVersion(id='old-authors', draft_id='draft', block_id='authors', sequence=1,
            target_inline=[{'type': 'text', 'text': 'Historical translated authors'}], source_hash=block['source_hash'],
            context_hash='a' * 64, origin='revision_copy', reason='Synthetic old revision'))
        session.flush()
        tr = translation_snapshot(session, cfg, draft)
        row = next(r for r in tr['results'] if r['block_id'] == 'authors')
        assert row['status'] == 'retained' and row['target_inline'] == []
        assert row['review_state'] == 'not_reviewed' and row['review_record'] is None
        assert session.get(SegmentVersion, 'old-authors').target_inline == [{'type': 'text', 'text': 'Historical translated authors'}]


@pytest.mark.parametrize('route', ['candidates', 'semantic-review'])
def test_retained_blocks_are_rejected_before_creating_candidate_or_review_jobs(client, database, monkeypatch, route):
    from tests.integration.test_translation_execution import PROFILE
    db, cfg = database
    setup_paper(db, cfg)
    profile = PROFILE | {'semantic_review_enabled': True}
    monkeypatch.setattr('apps.api.workflow.provider_profile', lambda: profile)
    body = {'block_ids': ['authors'], 'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile),
        'glossary_revision': 'empty-v1', 'budget_micro': 1_000_000, 'external_processing_confirmed': True}
    result = client.post('/api/v1/drafts/draft/' + route, json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'retained-selection'})
    assert result.status_code == 409, result.text
    assert result.json()['error']['code'] == 'BLOCK_SELECTION_INVALID'
    with db.transaction() as session:
        assert list(session.scalars(select(Job.id))) == ['job']


def test_preflight_counts_match_planned_content(client, database):
    from packages.domain.models import SourceDraft
    db, cfg = database
    src = setup_paper(db, cfg)
    with db.transaction() as session:
        session.add(SourceDraft(id='parsed', document_id='doc', asset_id=src['original_asset_id'],
            source=src, coverage={'pages': [], 'unresolved': []}, evidence={}))
    result = client.get('/api/v1/imports/parsed/preflight')
    assert result.status_code == 200, result.text
    assert result.json()['required_blocks'] == len(src['blocks']) - len(RETAINED)
    assert result.json()['retained_blocks'] == len(RETAINED)


def test_glossary_impact_omits_original_only_blocks(client, database):
    setup_paper(*database)
    response = client.post('/api/v1/glossaries/revisions', json={
        'source_language': 'en', 'target_language': 'zh-Hans', 'scope': 'global',
        'entries': [{'source': 'Alice', 'target': '姓名', 'mode': 'must'},
                    {'source': 'method', 'target': '方法', 'mode': 'must'}]},
        headers={'Idempotency-Key': 'glossary'})
    assert response.status_code == 201, response.text
    impact = client.post('/api/v1/glossaries/' + response.json()['id'] + '/impact', json={},
        headers={'Idempotency-Key': 'impact'})
    assert impact.status_code == 200, impact.text
    assert {row['block_id'] for row in impact.json()['items']} == {'body'}
