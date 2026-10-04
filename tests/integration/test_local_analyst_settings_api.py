"""Independent analyst preferences and immutable PostgreSQL task snapshots."""
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.main import create_app
from packages.domain.models import Job, Permit, Settings, Upload, now
from packages.local_models.catalog import artifact, get_model
from tests.integration.test_optional_cost_workflow import prepare, start

pytestmark = pytest.mark.postgres


def choice(slug):
    model = get_model(slug)
    return {'local_analyst_model_id': artifact(model)['id'], 'local_analyst_backend': model['runtime']}


GGUF = choice('minicpm5-1b-q4-k-m-gguf')
MLX = choice('minicpm5-1b-q4')


@pytest.fixture(autouse=True)
def supported_deployment(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf,mlx')
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'llama.cpp,mlx')


def save(client, body, etag=None):
    return client.patch('/api/v1/settings/preferences', json=body,
        headers={'If-Match': etag or client.get('/api/v1/settings/preferences').headers['etag']})


def test_save_reload_cas_and_translator_independence_without_model_side_effects(client, database, monkeypatch, tmp_path):
    db, cfg, translator, _ = prepare(client, database, monkeypatch, tmp_path)
    provider_before = client.get('/api/v1/settings/provider').json()
    before = client.get('/api/v1/settings/preferences')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda *_: pytest.fail('Settings must not call model services'))
    saved = save(client, GGUF, before.headers['etag'])
    assert saved.status_code == 200, saved.text
    assert all(saved.json()[key] == value for key, value in GGUF.items())
    with TestClient(create_app(cfg, db)) as restarted:
        assert restarted.get('/api/v1/settings/preferences').json() == saved.json()
    assert save(client, MLX, before.headers['etag']).status_code == 412
    after = client.get('/api/v1/settings/provider').json()
    for key in ('profile_hash', 'config_revision', 'credential_revision', 'model_id', 'local_backend'):
        assert after.get(key) == provider_before.get(key)
    with db.transaction() as session:
        assert all(session.get(Settings, 'singleton').preferences[key] == value for key, value in GGUF.items())
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(Permit)) == 0


@pytest.mark.parametrize('invalid', [
    {'local_analyst_model_id': 'unknown'}, {'local_analyst_model_id': 'sha256:' + 'a' * 64},
    choice('hy-mt2-1.8b-q4-k-m-gguf'), GGUF | {'local_analyst_backend': 'mlx'},
    GGUF | {'local_analyst_backend': 'invalid'}, {'local_analyst_model_id': None},
])
def test_invalid_analyst_choice_never_changes_saved_preferences(client, invalid):
    before = client.get('/api/v1/settings/preferences')
    result = save(client, invalid, before.headers['etag'])
    assert result.status_code in (409, 422), result.text
    assert client.get('/api/v1/settings/preferences').json() == before.json()


def test_deployment_changes_preserve_explicit_selection_and_unrelated_settings(client, database, monkeypatch):
    assert save(client, MLX).status_code == 200
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'gguf')
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'llama.cpp')
    current = client.get('/api/v1/settings/preferences').json()
    assert all(current[key] == value for key, value in MLX.items())
    unrelated = save(client, {'theme': 'dark'})
    assert unrelated.status_code == 200
    assert unrelated.json()['local_analyst_model_id'] == MLX['local_analyst_model_id']
    assert save(client, MLX).json()['error']['code'] == 'LOCAL_MODEL_FORMAT_UNSUPPORTED'
    assert save(client, GGUF).status_code == 200
    with database[0].transaction() as session:
        session.get(Settings, 'singleton').preferences = {}
    assert client.get('/api/v1/settings/preferences').json()['local_analyst_model_id'] == GGUF['local_analyst_model_id']
    with database[0].transaction() as session:
        assert session.get(Settings, 'singleton').preferences == {}
    monkeypatch.setenv('LOCAL_TRANSLATION_FORMATS', 'safetensors')
    monkeypatch.setenv('LOCAL_TRANSLATION_BACKENDS', 'vllm')
    assert 'local_analyst_model_id' not in client.get('/api/v1/settings/preferences').json()


@pytest.mark.parametrize('flow', ['import', 'edition', 'candidate', 'continuation', 'upload', 'reparse'])
def test_all_entry_points_freeze_selected_analyst_before_settings_rotation(client, database, monkeypatch, tmp_path, flow):
    db, cfg, translator, source = prepare(client, database, monkeypatch, tmp_path)
    assert save(client, GGUF).status_code == 200
    if flow in ('import', 'edition', 'candidate'):
        result = start(client, db, translator, source, flow, preparation={'mode': 'local'})
        job_key = 'job_id'
    elif flow == 'continuation':
        with db.transaction() as session:
            session.add(Job(id='old', document_id='doc_fixture', stage='translate', status='needs_review',
                payload={'draft_id': 'draft_fixture', 'source_revision_id': 'src_fixture', 'locale': 'zh-Hans'}))
        preflight = client.get('/api/v1/drafts/draft_fixture/translation-preflight').json()
        body = {key: preflight[key] for key in ('source_revision_id', 'source_hash', 'profile_hash')}
        body.update(profile_revision=translator['profile_revision'], external_processing_confirmed=True,
                    preparation={'mode': 'local'})
        result = client.post('/api/v1/drafts/draft_fixture/translate', json=body,
            headers={'If-Match': '"' + str(preflight['generation']) + '"', 'Idempotency-Key': 'analyst-continuation'})
        job_key = 'job_id'
    elif flow == 'reparse':
        result = client.post('/api/v1/documents/doc_fixture/parse', json={'source_asset_id': 'source_pdf',
            'workflow': {'preparation': {'mode': 'local'}}},
            headers={'If-Match': '"1"', 'Idempotency-Key': 'analyst-reparse'})
        job_key = 'job_id'
    else:
        with db.transaction() as session:
            session.add(Upload(id='uploaded_pdf', filename='synthetic.pdf', byte_size=3822,
                expires_at=now() + timedelta(hours=1), status='verified', source_asset_id='source_pdf'))
        result = client.post('/api/v1/imports', json={'source': {'kind': 'pdf_upload', 'upload_id': 'uploaded_pdf'},
            'workflow': {'preparation': {'mode': 'local'}}}, headers={'Idempotency-Key': 'analyst-upload'})
        job_key = 'current_job_id'
    assert result.status_code in (201, 202), result.text
    job_id = result.json()[job_key]
    with db.transaction() as session:
        original_payload = session.get(Job, job_id).payload
        frozen = original_payload['workflow'] if flow in ('upload', 'reparse') else original_payload
        assert frozen['analysis_profile']['model_id'] == GGUF['local_analyst_model_id']
        assert frozen['analysis_profile']['local_backend'] == 'llama.cpp'
        assert frozen['profile']['model_id'] == translator['model_id']
    assert save(client, MLX).status_code == 200
    with db.transaction() as session:
        assert session.get(Job, job_id).payload == original_payload
        from packages.preparation import freeze_options
        new = freeze_options({'mode': 'local'}, translator, session.get(Settings, 'singleton').preferences)
        assert new['analysis_profile']['model_id'] == MLX['local_analyst_model_id']
        assert new['analysis_profile']['local_backend'] == 'mlx'
