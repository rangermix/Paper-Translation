"""Response labels must never enter the authorization hash or frozen task profile."""
import pytest

from packages.domain.config import provider_profile
from packages.domain.models import Edition, Job, Settings, SourceDraft, SourceRevision
from packages.ir import digest
from packages.local_models.catalog import get_model
from packages.providers.settings import save_configuration
from packages.storage import read_snapshot
from tests.support import seed_editor
from tests.unit.test_local_translation_provider import profile as local_profile


@pytest.mark.parametrize('flow', ['import', 'edition', 'continuation'])
def test_local_display_name_keeps_original_hash_valid_at_each_confirmation(client, database, monkeypatch, tmp_path, flow):
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'synthetic-provider-config'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(tmp_path / 'absent-profile'))
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(tmp_path / 'absent-key'))
    save_configuration(local_profile('hy-mt2-7b-q4-k-m-gguf'), None, False, '"0"', 'local-config')
    original = provider_profile()
    original_hash = digest(original)
    label = get_model(original['model_id'])['label']
    public = client.get('/api/v1/settings/provider').json()
    assert public['model_display_name'] == label
    assert public['profile_hash'] == original_hash
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.get(Settings, 'singleton').dispatch_disabled = False
        source = read_snapshot(cfg.data, session.get(SourceRevision, 'src_fixture'))
        if flow == 'import':
            session.add(SourceDraft(id='parsed', document_id='doc_fixture', asset_id='source_pdf', source=source,
                coverage={'can_translate': True, 'unresolved': []}, evidence={'kind': 'controlled-fixture'}))
        if flow == 'edition':
            session.get(Edition, 'edition_fixture').target_locale = 'en'
            session.flush()
            session.add(Edition(id='new_edition', document_id='doc_fixture', target_locale='zh-Hans'))
    preflight_path = {'import': '/imports/parsed/preflight', 'edition': '/editions/new_edition/preflight',
                      'continuation': '/drafts/draft_fixture/translation-preflight'}[flow]
    response = client.get('/api/v1' + preflight_path)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view['profile']['model_display_name'] == label
    assert view['profile']['model_id'] == original['model_id']
    assert view['profile_hash'] == original_hash
    body = {'profile_hash': view['profile_hash'], 'profile_revision': original['profile_revision'],
            'external_processing_confirmed': True, 'publish_policy': 'manual_approval'}
    if flow == 'import':
        body.update(source_hash=view['source_hash'], preflight_generation=view['preflight_generation'], locale='zh-Hans')
        path = '/imports/parsed/confirm'
    else:
        body.update(source_revision_id=view['source_revision_id'], source_hash=view['source_hash'])
        path = '/editions/new_edition/translate' if flow == 'edition' else '/drafts/draft_fixture/translate'
    headers = {'If-Match': response.headers['etag'], 'Idempotency-Key': 'no-consent'}
    rejected = client.post('/api/v1' + path, json={**body, 'external_processing_confirmed': False}, headers=headers)
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'EXTERNAL_PROCESSING_UNCONFIRMED'
    headers['Idempotency-Key'] = 'confirmed-original-hash'
    started = client.post('/api/v1' + path, json=body, headers=headers)
    assert started.status_code == 202, started.text
    with db.transaction() as session:
        frozen = session.get(Job, started.json()['job_id']).payload['profile']
        assert 'model_display_name' not in frozen
        assert frozen['model_id'] == original['model_id'] and frozen['endpoint'] == original['endpoint']
    assert provider_profile() == original and digest(provider_profile()) == original_hash
