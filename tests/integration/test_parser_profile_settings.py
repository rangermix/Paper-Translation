"""Real PostgreSQL persistence and immutable queued selection; no model calls."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from packages.domain.models import Settings, Task
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_preferences_default_cas_and_provider_independence(client, database):
    prefs = client.get('/api/v1/settings/preferences')
    assert prefs.json()['parser_profile_revision'] == 'docling-v1'
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
