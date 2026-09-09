"""Retention plans first; all database checks use isolated real PostgreSQL schemas."""
from datetime import timedelta
import json
import os

import pytest
from sqlalchemy import select, text

from packages.domain.errors import DomainError
from packages.domain.models import Artifact, Idempotency, Job, Task, TranslationMemory, Upload, now
from packages.maintenance.__main__ import maintenance_window
from packages.maintenance.retention import retention_locked
from packages.publisher import Publisher
from packages.ir import digest
from tests.support import seed_editor


def aged(root, key, days=2, value=b'old orphan'):
    file = root / key
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(value)
    timestamp = (now() - timedelta(days=days)).timestamp()
    os.utime(file, (timestamp, timestamp))
    return file


def test_retention_requires_exclusive_lock_and_default_plan_never_deletes(database, tmp_path):
    db, cfg = database
    orphan = aged(cfg.data, 'staging/old/result.tmp')
    with db.engine.connect() as connection:
        with pytest.raises(DomainError, match='lock'):
            retention_locked(db, cfg, tmp_path / 'backups', connection)
    with maintenance_window(db) as connection:
        plan = retention_locked(db, cfg, tmp_path / 'backups', connection)
    assert plan['mode'] == 'dry_run'
    assert any(f['key'] == 'staging/old/result.tmp' for f in plan['files'])
    assert orphan.exists()


def test_retention_keeps_registered_history_independent_memory_and_live_fences(database, tmp_path):
    db, cfg = database
    ir = seed_editor(db, cfg)
    key = 'documents/doc_fixture/artifacts/art_history'
    manifest = Publisher().build(ir, cfg.data, cfg.data / key)
    with db.transaction() as session:
        session.add(Artifact(id='art_history', document_id='doc_fixture', edition_id='edition_fixture', template_id='reader-v1', storage_key=key, manifest_hash=digest(manifest), legacy=False))
        session.add(TranslationMemory(id='tm_independent', document_id='doc_fixture', independent=True, source_language='en', target_language='zh-Hans', source_text='Preserved', target_inline=[{'type': 'text', 'text': '保留'}], context_hash='a' * 64, evidence={}))
        session.add(Job(id='job_live', document_id='doc_fixture', stage='parse', status='paused'))
        session.flush()
        session.add(Task(id='task_live', job_id='job_live', kind='parse', status='pending', fence=2, payload={}))
    historical_extra = aged(cfg.data, key + '/registered-extra.txt')
    live_old_fence = aged(cfg.parser_inputs, 'task_live/1/original.pdf')
    live_current = aged(cfg.parser_outputs, 'task_live/2/payload.json')
    orphan = aged(cfg.data, 'documents/doc_fixture/artifacts/unregistered/index.html')
    recent = aged(cfg.data, 'exports/recent/document.tmp', days=0)
    with maintenance_window(db) as connection:
        result = retention_locked(db, cfg, tmp_path / 'backups', connection, apply=True)
    assert result['mode'] == 'apply' and not orphan.exists()
    assert historical_extra.exists() and live_old_fence.exists() and live_current.exists() and recent.exists()
    with db.transaction() as session:
        assert session.get(Artifact, 'art_history') and session.get(TranslationMemory, 'tm_independent')


def test_expired_upload_receipts_and_backups_have_explicit_independent_deadlines(database, tmp_path):
    db, cfg = database
    backups = tmp_path / 'backups'
    with db.transaction() as session:
        session.add(Upload(id='upload_expired', filename='expired.pdf', byte_size=10, received_bytes=10, chunks=[{'bytes': 10}], expires_at=now()-timedelta(hours=1)))
        session.add(Upload(id='upload_current', filename='current.pdf', byte_size=10, received_bytes=10, chunks=[{'bytes': 10}], expires_at=now()+timedelta(hours=1)))
        for key, expiry in [('expired-key', now()-timedelta(seconds=1)), ('live-key', now()+timedelta(days=6))]:
            session.add(Idempotency(key=key, method='POST', path='/uploads', body_hash='a'*64, response={}, expires_at=expiry))
    expired = aged(cfg.uploads, 'upload_expired/chunks/0.bin')
    current = aged(cfg.uploads, 'upload_current/chunks/0.bin')
    old = aged(backups, 'backup_' + 'a'*32 + '/manifest.json', days=31, value=json.dumps({'format':'bilingual-compose-backup-v1', 'created_at': (now()-timedelta(days=31)).isoformat(), 'files': []}).encode())
    old_dump = aged(backups, 'backup_' + 'a'*32 + '/database.dump', days=31)
    new = aged(backups, 'backup_' + 'b'*32 + '/manifest.json', days=29, value=json.dumps({'format':'bilingual-compose-backup-v1', 'created_at': (now()-timedelta(days=29)).isoformat(), 'files': []}).encode())
    old_spool = aged(cfg.parser_outputs, 'task_finished/1/result.json')
    with maintenance_window(db) as connection:
        result = retention_locked(db, cfg, backups, connection, apply=True)
    assert not expired.exists() and current.exists()
    assert not old.exists() and not old_dump.exists() and new.exists() and not old_spool.exists()
    assert result['policy']['backup_days'] == 30
    with db.transaction() as session:
        assert session.get(Upload, 'upload_expired').status == 'expired'
        assert [r.key for r in session.scalars(select(Idempotency))] == ['live-key']


def test_cleanup_is_bounded_and_cannot_follow_symlinks(database, tmp_path):
    db, cfg = database
    for i in range(5):
        aged(cfg.data, f'staging/{i}.tmp')
    outside = tmp_path / 'outside'
    outside.mkdir()
    survivor = aged(outside, 'keep.txt')
    link = cfg.data / 'staging' / 'escape'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('This OS session cannot create symlinks; containment case not executed.')
    with maintenance_window(db) as connection:
        result = retention_locked(db, cfg, tmp_path / 'backups', connection, apply=True, limit=2)
    assert len(result['files']) <= 2 and result['truncated']
    assert survivor.exists() and link.is_symlink()


def test_maintenance_lock_excludes_backup_cleanup_concurrency(database, tmp_path):
    db, cfg = database
    with maintenance_window(db) as connection:
        with db.engine.connect() as other:
            assert not other.scalar(text('SELECT pg_try_advisory_lock(798205424)'))
        assert retention_locked(db, cfg, tmp_path / 'backups', connection)['mode'] == 'dry_run'


def test_large_backup_keeps_manifest_until_final_bounded_pass(database, tmp_path):
    db, cfg = database
    backups = tmp_path / 'backups'
    prefix = 'backup_' + 'c' * 32
    manifest = aged(backups, prefix + '/manifest.json', days=31, value=json.dumps({'format':'bilingual-compose-backup-v1', 'created_at': (now()-timedelta(days=31)).isoformat(), 'files': []}).encode())
    for i in range(3):
        aged(backups, f'{prefix}/data/{i}.bin', days=31)
    with maintenance_window(db) as connection:
        first = retention_locked(db, cfg, backups, connection, apply=True, limit=2)
        assert first['truncated'] and manifest.exists()
        retention_locked(db, cfg, backups, connection, apply=True, limit=2)
    assert not manifest.exists() and not (backups / prefix).exists()
