import pytest
from sqlalchemy import select

from packages.domain.models import Attempt, Draft, Job, Permit, SegmentVersion, Settings, Task
from packages.ir import digest
from tests.support import seed_editor
from tests.integration.test_translation_execution import PROFILE


def prepare(db, cfg, monkeypatch, *, state='needs_review', permit=None):
    seed_editor(db, cfg)
    profile = PROFILE | {'cost_control_enabled': False}
    monkeypatch.setattr('packages.domain.config.provider_profile', lambda: profile)
    monkeypatch.setattr('apps.api.workflow.provider_profile', lambda: profile)
    with db.transaction() as session:
        session.get(Settings, 'singleton').dispatch_disabled = False
        session.add(Job(id='old', document_id='doc_fixture', stage='translate', status=state,
            payload={'draft_id': 'draft_fixture', 'source_revision_id': 'src_fixture', 'locale': 'zh-Hans'}))
        session.flush()
        if permit:
            session.add(Task(id='oldtask', job_id='old', kind='translate', status='outcome_unknown'))
            session.flush()
            session.add(Attempt(id='oldattempt', task_id='oldtask', job_id='old', fence=1, control_epoch=0, state='outcome_unknown'))
            session.flush()
            session.add(Permit(id='oldpermit', attempt_id='oldattempt', job_id='old', control_epoch=0,
                price_snapshot={}, state=permit))


def test_legacy_continuation_copies_existing_translation_and_creates_new_history(client, database, monkeypatch):
    db, cfg = database
    prepare(db, cfg, monkeypatch)
    p = client.get('/api/v1/drafts/draft_fixture/translation-preflight').json()
    body = {key: p[key] for key in ('source_revision_id', 'source_hash', 'profile_hash')}
    body.update(profile_revision=PROFILE['profile_revision'], external_processing_confirmed=True, publish_policy='auto_publish')
    headers = {'If-Match': '"' + str(p['generation']) + '"', 'Idempotency-Key': 'continue-once'}
    result = client.post('/api/v1/drafts/draft_fixture/translate', json=body, headers=headers)
    assert result.status_code == 202, result.text
    assert client.post('/api/v1/drafts/draft_fixture/translate', json=body, headers=headers).json() == result.json()
    with db.transaction() as session:
        old = session.get(Job, 'old')
        new = session.get(Job, result.json()['job_id'])
        assert old.status == 'needs_review'
        assert new.parent_job_id == old.id and new.actual_model is None
        assert new.payload['draft_id'] != 'draft_fixture'
        prior = session.scalars(select(SegmentVersion).where(SegmentVersion.draft_id == 'draft_fixture')).all()
        copied = session.scalars(select(SegmentVersion).where(SegmentVersion.draft_id == new.payload['draft_id'])).all()
        assert len(copied) == len(prior) > 0
        assert {digest(s.target_inline) for s in prior} == {digest(s.target_inline) for s in copied}


@pytest.mark.parametrize('permit,code', [('unknown', 'OUTCOME_UNKNOWN'), ('reserved', 'REQUEST_IN_FLIGHT')])
def test_continuation_never_evades_unknown_or_inflight_permits(client, database, monkeypatch, permit, code):
    db, cfg = database
    prepare(db, cfg, monkeypatch, state='waiting_config', permit=permit)
    p = client.get('/api/v1/drafts/draft_fixture/translation-preflight').json()
    assert p['blocked_reason'] == code
    body = {key: p[key] for key in ('source_revision_id', 'source_hash', 'profile_hash')}
    body.update(profile_revision=PROFILE['profile_revision'], external_processing_confirmed=True)
    result = client.post('/api/v1/drafts/draft_fixture/translate', json=body,
        headers={'If-Match': '"' + str(p['generation']) + '"', 'Idempotency-Key': 'unknown-cannot-continue'})
    assert result.status_code == 409 and result.json()['error']['code'] == code
    with db.transaction() as session:
        assert len(session.scalars(select(Draft)).all()) == 1


def test_waiting_configuration_continuation_uses_new_consent_and_cancels_old_wait(client, database, monkeypatch):
    db, cfg = database
    prepare(db, cfg, monkeypatch, state='waiting_config')
    p = client.get('/api/v1/drafts/draft_fixture/translation-preflight').json()
    body = {key: p[key] for key in ('source_revision_id', 'source_hash', 'profile_hash')}
    body.update(profile_revision=PROFILE['profile_revision'], external_processing_confirmed=False)
    headers = {'If-Match': '"' + str(p['generation']) + '"', 'Idempotency-Key': 'no-consent'}
    assert client.post('/api/v1/drafts/draft_fixture/translate', json=body, headers=headers).status_code == 409
    body['external_processing_confirmed'] = True
    headers['Idempotency-Key'] = 'new-consent'
    result = client.post('/api/v1/drafts/draft_fixture/translate', json=body, headers=headers)
    assert result.status_code == 202, result.text
    with db.transaction() as session:
        assert session.get(Job, 'old').status == 'cancelled'
        new = session.get(Job, result.json()['job_id'])
        assert new.payload['origin'] == 'explicit_continuation' and new.payload['confirmed_at']


def test_continuation_reports_paused_dispatch_instead_of_claiming_config_is_ready(client, database, monkeypatch):
    db, cfg = database
    prepare(db, cfg, monkeypatch, state='waiting_config')
    with db.transaction() as session:
        session.get(Settings, 'singleton').dispatch_disabled = True
    p = client.get('/api/v1/drafts/draft_fixture/translation-preflight').json()
    assert p['can_translate'] is False and p['blocked_reason'] == 'DISPATCH_DISABLED'
    body = {key: p[key] for key in ('source_revision_id', 'source_hash', 'profile_hash')}
    body.update(profile_revision=PROFILE['profile_revision'], external_processing_confirmed=True)
    result = client.post('/api/v1/drafts/draft_fixture/translate', json=body,
        headers={'If-Match': '"'+str(p['generation'])+'"', 'Idempotency-Key': 'paused-no-new-job'})
    assert result.status_code == 409 and result.json()['error']['code'] == 'DISPATCH_DISABLED'
    with db.transaction() as session:
        assert session.get(Job, 'old').status == 'waiting_config'
        assert len(session.scalars(select(Draft)).all()) == 1
