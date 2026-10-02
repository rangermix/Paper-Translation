"""Real PostgreSQL persistence and immutable queued selection; no model calls."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from packages.domain.models import Settings, Task
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_preferences_default_cas_and_provider_independence(client, database):
    prefs = client.get('/api/v1/settings/preferences')
    assert prefs.json()['parser_profile_revision'] == 'surya-ocr-2-v1'
    assert prefs.json()['parser_timeout_seconds'] == 7200
    with database[0].transaction() as session:
        assert 'parser_timeout_seconds' not in session.get(Settings, 'singleton').preferences
    provider = client.get('/api/v1/settings/provider').json()
    saved = client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'chandra-ocr-2-v1', 'parser_timeout_seconds': 10800},
        headers={'If-Match': prefs.headers['etag']})
    assert saved.status_code == 200, saved.text
    assert client.get('/api/v1/settings/preferences').json()['parser_profile_revision'] == 'chandra-ocr-2-v1'
    assert client.get('/api/v1/settings/preferences').json()['parser_timeout_seconds'] == 10800
    assert all(saved.json()[key] == value for key, value in prefs.json().items()
        if key not in {'generation', 'parser_profile_revision', 'parser_timeout_seconds'})
    after = client.get('/api/v1/settings/provider').json()
    assert after['parser_profile_revision'] == 'chandra-ocr-2-v1'
    for key in ('profile_hash', 'config_revision', 'credential_revision', 'dispatch_disabled'):
        assert provider.get(key) == after.get(key)
    assert client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'infinity-parser2-flash-v1', 'parser_timeout_seconds': 60},
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


@pytest.mark.parametrize('override,expected', [(None, 'chandra-ocr-2-v1'), ('infinity-parser2-flash-v1', 'infinity-parser2-flash-v1'), ('surya-ocr-2-v1', 'surya-ocr-2-v1')])
def test_enqueue_freezes_default_or_explicit_override(client, database, monkeypatch, override, expected):
    db, cfg = database
    seed_editor(db, cfg)
    prefs = client.get('/api/v1/settings/preferences')
    saved = client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'chandra-ocr-2-v1', 'parser_timeout_seconds': 10800},
        headers={'If-Match': prefs.headers['etag']})
    body = {'source_asset_id': 'source_pdf'}
    if override:
        body['parser_profile_revision'] = override
    parsed = client.post('/api/v1/documents/doc_fixture/parse', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'parse-choice'})
    assert parsed.status_code == 202, parsed.text
    client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'infinity-parser2-flash-v1', 'parser_timeout_seconds': 60},
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


def environment_report(cfg, profiles=(), device='dmr', backend='vllm'):
    import time
    from packages.ir import canonical_bytes
    from packages.parsers.profiles import PROFILE_IDS
    body = {'timestamp': time.time(), 'models_verified': True, 'environment': {
        'detected_at': time.time(), 'system': 'Linux', 'architecture': 'x86_64',
        'cpu_count': 4, 'memory_bytes': 8 * 1024 ** 3, 'default': device,
        'backend': backend,
        'options': [{'id': 'dmr', 'profiles': list(profiles or PROFILE_IDS)}]}}
    (cfg.parser_outputs / 'heartbeat.json').write_bytes(canonical_bytes(body))


def test_device_is_deployment_owned_and_legacy_override_is_retired(client, database):
    db, cfg = database
    environment_report(cfg)
    detected = client.get('/api/v1/settings/parser-environment')
    assert detected.status_code == 200
    assert detected.json()['online'] is True
    assert detected.json()['memory_bytes'] == 8 * 1024 ** 3
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.preferences = {**settings.preferences, 'parser_accelerator': 'cuda'}
    before = client.get('/api/v1/settings/preferences')
    assert 'parser_accelerator' not in before.json()
    with db.transaction() as session:
        assert session.get(Settings, 'singleton').preferences['parser_accelerator'] == 'cuda'
    for choice in ('deployment', 'cpu', 'cuda', 'mlx', 'arbitrary'):
        result = client.patch('/api/v1/settings/preferences', json={'parser_accelerator': choice},
            headers={'If-Match': before.headers['etag']})
        assert result.status_code == 422, result.text
        assert client.get('/api/v1/settings/preferences').json() == before.json()
    saved = client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'surya-ocr-2-v1'},
        headers={'If-Match': before.headers['etag']})
    assert saved.status_code == 200, saved.text
    assert 'parser_accelerator' not in saved.json()
    with db.transaction() as session:
        assert 'parser_accelerator' not in session.get(Settings, 'singleton').preferences
    assert client.patch('/api/v1/settings/preferences', json={'parser_timeout_seconds': 60},
        headers={'If-Match': before.headers['etag']}).status_code == 412
    (cfg.parser_outputs / 'heartbeat.json').unlink()
    assert client.get('/api/v1/settings/parser-environment').json()['online'] is False
    assert client.patch('/api/v1/settings/preferences', json={'parser_timeout_seconds': 60},
        headers={'If-Match': saved.headers['etag']}).status_code == 200


@pytest.mark.parametrize('device,legacy_choice', [('dmr', 'cuda'), ('dmr', 'cpu'), ('dmr', 'mlx')])
def test_compose_runtime_ignores_legacy_preferences_and_is_frozen_through_queue_and_spool(client, database, monkeypatch, device, legacy_choice):
    db, cfg = database
    seed_editor(db, cfg)
    environment_report(cfg, device=device)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.preferences = {**settings.preferences, 'parser_accelerator': legacy_choice}
    parsed = client.post('/api/v1/documents/doc_fixture/parse', json={'source_asset_id': 'source_pdf'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'runtime-choice'})
    assert parsed.status_code == 202, parsed.text
    assert client.get('/api/v1/jobs/' + parsed.json()['job_id']).json()['config_snapshot']['parser_accelerator'] == device
    # A later deployment change cannot rewrite an already queued task.
    environment_report(cfg, backend='mlx')
    with db.transaction() as session:
        task = session.scalar(select(Task).where(Task.job_id == parsed.json()['job_id']))
        assert task.payload['parser_accelerator'] == device
        assert task.payload['parser_backend'] == 'vllm'
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
    assert captured['accelerator'] == device
    assert captured['backend'] == 'vllm'


def test_unavailable_compose_device_cannot_be_overridden_by_saved_cpu_preference(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    environment_report(cfg, ['infinity-parser2-flash-v1'])
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.preferences = {**settings.preferences, 'parser_accelerator': 'cpu'}
    before = client.get('/api/v1/settings/preferences')
    saved = client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': 'surya-ocr-2-v1'},
        headers={'If-Match': before.headers['etag']})
    assert saved.status_code == 409, saved.text
    assert client.get('/api/v1/settings/preferences').json() == before.json()
    parsed = client.post('/api/v1/documents/doc_fixture/parse', json={'source_asset_id': 'source_pdf'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'unavailable-runtime'})
    assert parsed.status_code == 409, parsed.text
    assert parsed.json()['error']['code'] == 'PARSER_ACCELERATOR_UNAVAILABLE'


@pytest.mark.parametrize('profile,status', [('docling-v1', 'removed'), ('granite-docling-v1', 'removed'), ('paddleocr-vl-1.6-v1', 'archived'), ('xiaomi-ocr-0-v1', 'archived'), ('teleocr-v1', 'archived')])
def test_retired_saved_choice_is_readable_without_new_execution(client, database, profile, status):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.preferences = {**settings.preferences, 'parser_profile_revision': profile}
    before = client.get('/api/v1/settings/preferences')
    assert before.json()['parser_profile_revision'] == profile
    assert before.json()['parser_profile_status'] == status
    parsed = client.post('/api/v1/documents/doc_fixture/parse', json={'source_asset_id': 'source_pdf'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'retired-choice'})
    assert parsed.status_code == 409
    assert parsed.json()['error']['code'] == 'PARSER_PROFILE_UNAVAILABLE'
    rejected = client.patch('/api/v1/settings/preferences', json={'parser_profile_revision': profile},
        headers={'If-Match': before.headers['etag']})
    assert rejected.status_code == 422
    assert client.get('/api/v1/settings/preferences').json() == before.json()
