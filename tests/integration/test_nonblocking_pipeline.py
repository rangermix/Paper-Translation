from sqlalchemy import select

from packages.domain.models import Document, SourceDraft, SourceRevision, Job, Task, Settings, Upload, now
from packages.ir import digest
from packages.translation.pipeline import PipelineOptions, freeze_pipeline, advance_parse
from tests.support import seed_editor
from tests.integration.test_translation_execution import PROFILE


def test_authorized_parse_advances_with_unresolved_quality_and_frozen_destination(database, monkeypatch):
    db, cfg = database
    ir = seed_editor(db, cfg)
    profile = PROFILE | {'cost_control_enabled': False}
    monkeypatch.setattr('packages.translation.pipeline.provider_profile', lambda: profile)
    with db.transaction() as session:
        session.get(Settings, 'singleton').dispatch_disabled = False
        frozen = freeze_pipeline(PipelineOptions(external_processing_confirmed=True, profile_hash=digest(profile)), 'source_pdf')
        parent = Job(id='parse_parent', document_id='doc_fixture', stage='parse', status='running', payload={'workflow': frozen})
        source = SourceDraft(id='source_draft', document_id='doc_fixture', asset_id='source_pdf',
            base_revision_id='src_fixture', source=ir['source_revision'], coverage={'can_translate': False,
                'unresolved': [{'code': 'MISSING_PAGE', 'page': 14}]}, evidence={})
        session.add_all([parent, source]); session.flush()
        advance_parse(session, cfg, source, parent)
        translation = session.scalar(select(Job).where(Job.parent_job_id == parent.id, Job.stage == 'translate'))
        assert translation.status == 'pending'
        assert translation.payload['profile']['model_id'] == profile['model_id']
        assert translation.payload['external_processing_confirmed'] is True
        revision = session.get(SourceRevision, translation.payload['source_revision_id'])
        assert revision.metadata_json['origin'] == 'automatic_workflow'
        assert revision.metadata_json['coverage']['unresolved']
        assert 'confirmed_at' not in revision.metadata_json


def test_unconfigured_pipeline_creates_local_reading_and_explicit_wait(database, monkeypatch):
    db, cfg = database
    ir = seed_editor(db, cfg)
    monkeypatch.setattr('packages.translation.pipeline.provider_profile', lambda: {'configured': False})
    with db.transaction() as session:
        parent = Job(id='parse_parent', document_id='doc_fixture', stage='parse', status='running',
            payload={'workflow': freeze_pipeline(PipelineOptions(), 'source_pdf')})
        source = SourceDraft(id='source_draft', document_id='doc_fixture', asset_id='source_pdf',
            base_revision_id='src_fixture', source=ir['source_revision'], coverage={'can_translate': False}, evidence={})
        session.add_all([parent, source]); session.flush()
        advance_parse(session, cfg, source, parent)
        translation = session.scalar(select(Job).where(Job.parent_job_id == parent.id, Job.stage == 'translate'))
        assert translation.status == 'waiting_config' and translation.error['code'] == 'PROVIDER_CONFIG'
        local = session.scalar(select(Job).where(Job.parent_job_id == parent.id, Job.stage == 'publish'))
        assert local and local.payload['source_only']
        assert not session.scalar(select(Task).where(Task.job_id == translation.id)).attempts


def test_import_starts_frozen_pipeline_and_replay_does_not_duplicate(client, database, monkeypatch):
    from datetime import timedelta
    db, cfg = database
    seed_editor(db, cfg)
    monkeypatch.setattr('packages.translation.pipeline.provider_profile', lambda: {'configured': False})
    with db.transaction() as session:
        session.add(Upload(id='new_upload', filename='new.pdf', byte_size=3822, expires_at=now()+timedelta(hours=1),
            status='verified', source_asset_id='source_pdf'))
    body = {'source': {'kind': 'pdf_upload', 'upload_id': 'new_upload'}, 'parser_profile_revision': 'granite-docling-v1',
        'workflow': {'translate': False, 'target_locale': 'ja'}}
    headers = {'Idempotency-Key': 'automatic-import'}
    result = client.post('/api/v1/imports', json=body, headers=headers)
    assert result.status_code == 201, result.text
    assert result.json()['status'] == 'parsing'
    assert client.post('/api/v1/imports', json=body, headers=headers).json() == result.json()
    with db.transaction() as session:
        jobs = session.scalars(select(Job).where(Job.document_id == result.json()['id'])).all()
        assert len(jobs) == 1
        assert jobs[0].config_snapshot['target_locale'] == 'ja'
        assert jobs[0].payload['parser_timeout_seconds'] == 7200
