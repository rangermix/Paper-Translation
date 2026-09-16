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


def test_saved_parse_result_exposes_current_translation_draft(client, database, monkeypatch):
    from packages.domain.models import Edition
    db, cfg = database
    ir = seed_editor(db, cfg)
    monkeypatch.setattr('packages.translation.pipeline.provider_profile', lambda: PROFILE | {'cost_control_enabled': False})
    with db.transaction() as session:
        parent = Job(id='parse_parent', document_id='doc_fixture', stage='parse', status='running',
            payload={'workflow': freeze_pipeline(PipelineOptions(translate=False), 'source_pdf')})
        source = SourceDraft(id='saved_parse', document_id='doc_fixture', asset_id='source_pdf',
            base_revision_id='src_fixture', source=ir['source_revision'], coverage={}, evidence={})
        session.add_all([parent, source]); session.flush()
        advance_parse(session, cfg, source, parent)
        draft_id = parent.progress['draft_id']
    p = client.get('/api/v1/imports/saved_parse/preflight').json()
    assert p['status'] == 'sealed'
    assert p['translation_targets'] == [{'draft_id': draft_id, 'target_locale': 'zh-Hans'}]
    with db.transaction() as session:
        session.get(Document, 'doc_fixture').current_source_id = 'src_fixture'
    stale = client.get('/api/v1/imports/saved_parse/preflight').json()
    assert stale['status'] == 'superseded' and stale['translation_targets'] == []


def test_parse_only_result_can_translate_with_current_configuration_end_to_end(client, database, monkeypatch):
    from packages.providers.fake import FakeProvider
    from packages.jobs.queue import claim
    from packages.translation.execution import execute_translation
    from workers.main import publish
    db, cfg = database
    ir = seed_editor(db, cfg)
    profile = PROFILE | {'cost_control_enabled': False}
    monkeypatch.setattr('packages.translation.pipeline.provider_profile', lambda: profile)
    monkeypatch.setattr('packages.domain.config.provider_profile', lambda: profile)
    monkeypatch.setattr('apps.api.workflow.provider_profile', lambda: profile)
    with db.transaction() as session:
        session.get(Settings, 'singleton').dispatch_disabled = False
        parent = Job(id='parse_parent', document_id='doc_fixture', stage='parse', status='succeeded',
            payload={'workflow': freeze_pipeline(PipelineOptions(translate=False), 'source_pdf')})
        source = SourceDraft(id='parse_result', document_id='doc_fixture', asset_id='source_pdf',
            base_revision_id='src_fixture', source=ir['source_revision'], coverage={}, evidence={})
        session.add_all([parent, source]); session.flush()
        advance_parse(session, cfg, source, parent)
    initial = claim(db)
    assert initial.kind == 'publish'
    publish(db, cfg, initial)
    result = client.get('/api/v1/imports/parse_result/preflight').json()
    draft = result['translation_targets'][0]['draft_id']
    preflight = client.get(f'/api/v1/drafts/{draft}/translation-preflight').json()
    body = {key: preflight[key] for key in ('source_revision_id', 'source_hash', 'profile_hash')}
    body.update(profile_revision=profile['profile_revision'], external_processing_confirmed=True, publish_policy='auto_publish')
    response = client.post(f'/api/v1/drafts/{draft}/translate', json=body,
        headers={'If-Match': '"'+str(preflight['generation'])+'"', 'Idempotency-Key': 'parse-to-translation'})
    assert response.status_code == 202, response.text
    provider = FakeProvider()
    while lease := claim(db):
        if lease.kind == 'publish':
            publish(db, cfg, lease)
        elif lease.kind == 'index':
            from packages.search import update_index
            update_index(db, cfg, lease)
        else:
            execute_translation(db, cfg, lease, provider)
    job = client.get('/api/v1/jobs/'+response.json()['job_id']).json()
    assert job['status'] in ('succeeded', 'completed_with_warnings')
    assert job['verified_blocks'] == job['total_blocks'] > 0
    assert provider.calls and job['request_count'] > 0
    assert job['progress']['publication_job_id']
