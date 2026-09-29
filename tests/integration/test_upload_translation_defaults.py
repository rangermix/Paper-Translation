"""Saved upload permission, using isolated PostgreSQL and synthetic providers."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.main import create_app
from packages.domain.models import Job, Permit, Settings, SourceDraft, Upload, now
from packages.translation.pipeline import advance_parse
from tests.integration.test_provider_settings_api import put, settings_store
from tests.support import seed_editor
from tests.unit.test_provider_settings_store import complete

pytestmark = pytest.mark.postgres


def save_default(client, profile_hash, etag=None):
    return client.patch('/api/v1/settings/preferences',
        json={'upload_translation_profile_hash': profile_hash},
        headers={'If-Match': etag or client.get('/api/v1/settings/preferences').headers['etag']})


def configured(client, **overrides):
    result = put(client, complete(cost_control_enabled=False, **overrides), 'SYNTHETIC_UPLOAD_KEY')
    assert result.status_code == 200, result.text
    return result.json()


def test_default_off_persists_and_clears_without_jobs_or_credentials(client, database, settings_store):
    with database[0].transaction() as session:
        session.get(Settings, 'singleton').dispatch_disabled = True
    before = client.get('/api/v1/settings/preferences')
    assert before.json()['upload_translation_profile_hash'] is None
    profile = configured(client)
    saved = save_default(client, profile['profile_hash'])
    assert saved.status_code == 200, saved.text
    db, cfg = database
    with TestClient(create_app(cfg, db)) as restarted:
        assert restarted.get('/api/v1/settings/preferences').json() == saved.json()
    changed = client.patch('/api/v1/settings/preferences', json={'locale': 'ja'},
        headers={'If-Match': saved.headers['etag']})
    assert changed.json()['upload_translation_profile_hash'] == profile['profile_hash']
    assert save_default(client, None, before.headers['etag']).status_code == 412
    cleared = save_default(client, None)
    assert cleared.status_code == 200
    assert cleared.json()['upload_translation_profile_hash'] is None
    assert cleared.json()['locale'] == 'ja'
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
        assert 'SYNTHETIC_UPLOAD_KEY' not in str(session.get(Settings, 'singleton').preferences)
        assert session.get(Settings, 'singleton').dispatch_disabled is True


def test_enabling_requires_current_ready_provider_and_leaves_preferences_unchanged_on_failure(client, settings_store):
    before = client.get('/api/v1/settings/preferences').json()
    missing = save_default(client, 'a' * 64)
    assert missing.status_code == 409 and missing.json()['error']['code'] == 'PROVIDER_CONFIG'
    assert client.get('/api/v1/settings/preferences').json() == before
    profile = configured(client)
    stale = save_default(client, 'a' * 64)
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'PROFILE_STALE'
    assert save_default(client, profile['profile_hash']).status_code == 200
    changed = put(client, complete(cost_control_enabled=False, model_id='changed-model'),
        generation=1, operation='change-model')
    assert changed.status_code == 200
    # Saving unrelated preferences never silently rebinds the user's permission.
    assert client.get('/api/v1/settings/preferences').json()['upload_translation_profile_hash'] != changed.json()['profile_hash']
    assert save_default(client, profile['profile_hash']).json()['error']['code'] == 'PROFILE_STALE'
    assert save_default(client, changed.json()['profile_hash']).status_code == 200
    assert put(client, complete(), generation=2, operation='remove-key', clear=True).status_code == 200
    assert save_default(client, None).status_code == 200


@pytest.mark.parametrize('value', [True, '', 'not-a-profile', 'A' * 64, 12])
def test_invalid_upload_default_cannot_mutate_settings(client, settings_store, value):
    before = client.get('/api/v1/settings/preferences')
    assert save_default(client, value).status_code == 422
    assert client.get('/api/v1/settings/preferences').json() == before.json()


def test_default_updates_respect_maintenance(client, database, settings_store):
    profile = configured(client)
    with database[0].transaction() as session:
        session.get(Settings, 'singleton').maintenance = True
    before = client.get('/api/v1/settings/preferences').json()
    assert save_default(client, profile['profile_hash']).status_code == 503
    assert client.get('/api/v1/settings/preferences').json() == before


@pytest.mark.parametrize('consent,translate,controlled,budget,paused,expected', [
    (True, True, False, None, False, 'pending'),
    (False, True, False, None, False, 'waiting_config'),
    (True, False, False, None, False, None),
    (True, True, True, None, False, 'waiting_budget'),
    (True, True, True, 100000, False, 'pending'),
    (True, True, False, None, True, 'waiting_config'),
])
def test_upload_permission_continues_into_translation_with_existing_controls(client, database, settings_store,
        consent, translate, controlled, budget, paused, expected):
    profile = put(client, complete(cost_control_enabled=controlled), 'SYNTHETIC_UPLOAD_KEY').json()
    assert save_default(client, profile['profile_hash']).status_code == 200
    db, cfg = database
    ir = seed_editor(db, cfg)
    with db.transaction() as session:
        session.get(Settings, 'singleton').dispatch_disabled = paused
        session.add(Upload(id='default_upload', filename='default.pdf', byte_size=3822,
            expires_at=now() + timedelta(hours=1), status='verified', source_asset_id='source_pdf'))
    workflow = {'translate': translate, 'target_locale': 'zh-Hans', 'external_processing_confirmed': consent,
        'use_saved_upload_permission': consent and translate,
        'profile_hash': profile['profile_hash'], **({'budget_micro': budget} if budget else {})}
    result = client.post('/api/v1/imports', json={'source': {'kind': 'pdf_upload', 'upload_id': 'default_upload'},
        'workflow': workflow}, headers={'Idempotency-Key': 'default-import'})
    assert result.status_code == 201, result.text
    with db.transaction() as session:
        parent = session.scalar(select(Job).where(Job.document_id == result.json()['id'], Job.stage == 'parse'))
        assert parent.payload['workflow']['external_processing_confirmed'] is consent
        source = SourceDraft(id='default_source', document_id=result.json()['id'], asset_id='source_pdf',
            source=ir['source_revision'], coverage={}, evidence={})
        session.add(source)
        session.flush()
        advance_parse(session, cfg, source, parent)
        translation = session.scalar(select(Job).where(Job.parent_job_id == parent.id, Job.stage == 'translate'))
        if expected is None:
            assert translation is None
        else:
            assert translation.status == expected
            if expected == 'pending':
                assert translation.payload['profile_hash'] == profile['profile_hash']
                assert translation.payload['external_processing_confirmed'] is True
        assert session.scalar(select(func.count()).select_from(Permit)) == 0


@pytest.mark.parametrize('changed', ['revoked', 'preparation'])
def test_import_rechecks_saved_permission_before_enqueuing(client, database, settings_store, changed):
    profile = configured(client)
    assert save_default(client, profile['profile_hash']).status_code == 200
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.add(Upload(id='stale_upload', filename='stale.pdf', byte_size=3822,
            expires_at=now() + timedelta(hours=1), status='verified', source_asset_id='source_pdf'))
    if changed == 'revoked':
        assert save_default(client, None).status_code == 200
    workflow = {'translate': True, 'external_processing_confirmed': True, 'use_saved_upload_permission': True,
        'profile_hash': profile['profile_hash'], 'preparation': {'mode': 'provider' if changed == 'preparation' else 'extractive'}}
    body = {'source': {'kind': 'pdf_upload', 'upload_id': 'stale_upload'}, 'workflow': workflow}
    stale = client.post('/api/v1/imports', json=body, headers={'Idempotency-Key': 'stale-default'})
    assert stale.status_code == 409, stale.text
    assert stale.json()['error']['code'] == 'UPLOAD_TRANSLATION_DEFAULT_STALE'
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
    # A new one-time confirmation can still authorize this upload explicitly.
    workflow['use_saved_upload_permission'] = False
    confirmed = client.post('/api/v1/imports', json=body, headers={'Idempotency-Key': 'explicit-confirmation'})
    assert confirmed.status_code == 201, confirmed.text
