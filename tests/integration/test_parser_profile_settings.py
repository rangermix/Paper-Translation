"""Real PostgreSQL persistence and immutable queued selection; no model calls."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from packages.domain.models import Settings, Task
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_preferences_default_cas_and_provider_independence(client, database):
    prefs = client.get('/api/v1/settings/preferences')
    assert prefs.json()['parser_profile_revision'] == 'paddleocr-vl-1.6-v1'
    assert prefs.json()['parser_timeout_seconds'] == 7200
    with database[0].transaction() as session:
        assert 'parser_timeout_seconds' not in session.get(Settings, 'singleton').preferences
    provider = client.get('/api/v1/settings/provider').json()
    saved = client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'granite-docling-v1', 'parser_timeout_seconds': 10800},
        headers={'If-Match': prefs.headers['etag']})
    assert saved.status_code == 200, saved.text
    assert client.get('/api/v1/settings/preferences').json()['parser_profile_revision'] == 'granite-docling-v1'
    assert client.get('/api/v1/settings/preferences').json()['parser_timeout_seconds'] == 10800
    assert all(saved.json()[key] == value for key, value in prefs.json().items()
        if key not in {'generation', 'parser_profile_revision', 'parser_timeout_seconds'})
    after = client.get('/api/v1/settings/provider').json()
    assert after['parser_profile_revision'] == 'granite-docling-v1'
    for key in ('profile_hash', 'config_revision', 'credential_revision', 'dispatch_disabled'):
        assert provider.get(key) == after.get(key)
    assert client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'docling-v1', 'parser_timeout_seconds': 60},
        headers={'If-Match': prefs.headers['etag']}).status_code == 412
    assert client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'unknown'},
        headers={'If-Match': saved.headers['etag']}).status_code == 422
    assert client.get('/api/v1/settings/preferences').json()['parser_timeout_seconds'] == 10800


@pytest.mark.parametrize('value', [0, 59, 61, 86460, True, '7200', 7200.0])
def test_invalid_timeout_cannot_change_preferences(client, value):
    before = client.get('/api/v1/settings/preferences')
    rejected = client.patch('/api/v1/settings/preferences', json={'parser_timeout_seconds': value},
        headers={'If-Match': before.headers['etag']})
    assert rejected.status_code == 422
    assert client.get('/api/v1/settings/preferences').json() == before.json()


@pytest.mark.parametrize('override,expected', [(None, 'granite-docling-v1'), ('docling-v1', 'docling-v1'), ('paddleocr-vl-1.6-v1', 'paddleocr-vl-1.6-v1')])
def test_enqueue_freezes_default_or_explicit_override(client, database, monkeypatch, override, expected):
    db, cfg = database
    seed_editor(db, cfg)
    prefs = client.get('/api/v1/settings/preferences')
    saved = client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'granite-docling-v1', 'parser_timeout_seconds': 10800},
        headers={'If-Match': prefs.headers['etag']})
    body = {'source_asset_id': 'source_pdf'}
    if override:
        body['parser_profile_revision'] = override
    parsed = client.post('/api/v1/documents/doc_fixture/parse', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'parse-choice'})
    assert parsed.status_code == 202, parsed.text
    client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'docling-v1', 'parser_timeout_seconds': 60},
        headers={'If-Match': saved.headers['etag']})
    with db.transaction() as session:
        task = session.scalar(select(Task).where(Task.job_id == parsed.json()['job_id']))
        assert task.payload['parser_profile_revision'] == expected
        assert task.payload['parser_timeout_seconds'] == 10800
    from packages.jobs.queue import claim
    from packages.parsers.models import parser_version
    from workers.main import parse_spool
    lease = claim(db)
    captured = {}
    def stop_at_spool(root, descriptor, source):
        captured.update(descriptor)
        raise RuntimeError('Captured before inference')
    monkeypatch.setattr('workers.main.write_request', stop_at_spool)
    with pytest.raises(RuntimeError, match='Captured before inference'):
        parse_spool(db, cfg, lease)
    assert captured['profile']['parser_profile_revision'] == expected
    assert captured['parser_version'] == parser_version(expected)
    assert captured['timeout_seconds'] == 10800
    assert 10790 < (datetime.fromisoformat(captured['deadline']) - datetime.now(timezone.utc)).total_seconds() <= 10800


def test_unknown_profile_cannot_enqueue(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    rejected = client.post('/api/v1/documents/doc_fixture/parse', json={
        'source_asset_id': 'source_pdf', 'parser_profile_revision': 'unknown'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'bad-profile'})
    assert rejected.status_code == 422


def environment_report(cfg, cuda_profiles=()):
    import time
    from packages.ir import canonical_bytes
    body = {'timestamp': time.time(), 'models_verified': True, 'environment': {
        'detected_at': time.time(), 'system': 'Linux', 'architecture': 'x86_64',
        'cpu_count': 4, 'memory_bytes': 8 * 1024 ** 3, 'default': 'cpu',
        'options': [{'id': 'cpu', 'profiles': ['docling-v1', 'granite-docling-v1', 'paddleocr-vl-1.6-v1']},
            {'id': 'cuda', 'profiles': list(cuda_profiles)}, {'id': 'mlx', 'profiles': []}]}}
    (cfg.parser_outputs / 'heartbeat.json').write_bytes(canonical_bytes(body))


def test_environment_selection_persists_and_rejects_unavailable_runtime(client, database):
    _, cfg = database
    environment_report(cfg, ['docling-v1'])
    detected = client.get('/api/v1/settings/parser-environment')
    assert detected.status_code == 200
    assert detected.json()['online'] is True
    assert detected.json()['memory_bytes'] == 8 * 1024 ** 3
    before = client.get('/api/v1/settings/preferences')
    for choice, status in [('cuda', 409), ('mlx', 409), ('arbitrary', 422)]:
        result = client.patch('/api/v1/settings/preferences', json={'parser_accelerator': choice},
            headers={'If-Match': before.headers['etag']})
        assert result.status_code == status, result.text
        assert client.get('/api/v1/settings/preferences').json() == before.json()
    saved = client.patch('/api/v1/settings/preferences', json={'parser_accelerator': 'cuda', 'parser_profile_revision': 'docling-v1'},
        headers={'If-Match': before.headers['etag']})
    assert saved.status_code == 200, saved.text
    assert client.get('/api/v1/settings/preferences').json()['parser_accelerator'] == 'cuda'
    assert client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'paddleocr-vl-1.6-v1'},
        headers={'If-Match': saved.headers['etag']}).status_code == 409
    assert client.patch('/api/v1/settings/preferences', json={'parser_accelerator': 'cpu'},
        headers={'If-Match': before.headers['etag']}).status_code == 412
    (cfg.parser_outputs / 'heartbeat.json').unlink()
    assert client.get('/api/v1/settings/parser-environment').json()['online'] is False
    assert client.patch('/api/v1/settings/preferences', json={'parser_accelerator': 'cpu'},
        headers={'If-Match': saved.headers['etag']}).status_code == 409


@pytest.mark.parametrize('choice', ['deployment', 'cpu'])
def test_runtime_is_frozen_through_queue_and_spool(client, database, monkeypatch, choice):
    db, cfg = database
    seed_editor(db, cfg)
    environment_report(cfg, ['docling-v1'])
    prefs = client.get('/api/v1/settings/preferences')
    saved = client.patch('/api/v1/settings/preferences', json={'parser_accelerator': choice, 'parser_profile_revision': 'docling-v1'},
        headers={'If-Match': prefs.headers['etag']})
    assert saved.status_code == 200, saved.text
    parsed = client.post('/api/v1/documents/doc_fixture/parse', json={'source_asset_id': 'source_pdf'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'runtime-choice'})
    assert parsed.status_code == 202, parsed.text
    assert client.get('/api/v1/jobs/' + parsed.json()['job_id']).json()['config_snapshot']['parser_accelerator'] == 'cpu'
    changed = client.patch('/api/v1/settings/preferences', json={'parser_accelerator': 'cuda'},
        headers={'If-Match': saved.headers['etag']})
    assert changed.status_code == 200, changed.text
    with db.transaction() as session:
        task = session.scalar(select(Task).where(Task.job_id == parsed.json()['job_id']))
        assert task.payload['parser_accelerator'] == 'cpu'
    from packages.jobs.queue import claim
    from workers.main import parse_spool
    lease = claim(db)
    captured = {}
    def stop_at_spool(root, descriptor, source):
        captured.update(descriptor)
        raise RuntimeError('Captured before inference')
    monkeypatch.setattr('workers.main.write_request', stop_at_spool)
    with pytest.raises(RuntimeError, match='Captured before inference'):
        parse_spool(db, cfg, lease)
    assert captured['accelerator'] == 'cpu'
