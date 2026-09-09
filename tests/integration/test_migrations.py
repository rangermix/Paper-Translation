from dataclasses import replace
import uuid

import pytest
from sqlalchemy import select, text

from packages.billing.ledger import budget_totals
from packages.domain.db import Database
from packages.domain.errors import DomainError
from packages.domain.models import Attempt, Job, Permit, Settings, SourceRevision, Task, TranslationMemory
from packages.jobs.queue import claim
from packages.maintenance.__main__ import enable_dispatch
from packages.storage import file_hash
from tests.support import legacy_insert, seed_editor
from tests.integration.test_budget import PRICE

pytestmark = pytest.mark.postgres


def test_m1_frozen_schema_upgrades_without_losing_source_or_unknown_risk(database, monkeypatch):
    admin, cfg = database
    schema = 'library_test_' + uuid.uuid4().hex
    with admin.engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
    monkeypatch.setenv('TEST_DATABASE_SCHEMA', schema)
    db = Database(cfg)
    try:
        db.migrate(3)
        with db.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND table_name='exports' AND column_name='draft_snapshot_key'"), {'schema': schema}) == 0
            assert connection.scalar(text("SELECT to_regclass(:name)"), {'name': schema + '.translation_memory'}) is None
        seed_editor(db, cfg, legacy_schema=True)
        with db.transaction() as session:
            source = session.get(SourceRevision, 'src_fixture')
            before = file_hash(cfg.data / source.storage_key)
            legacy_insert(session, Job, id='uncertain_job', document_id='doc_fixture', stage='translate', status='outcome_unknown', budget_micro=100)
            session.flush()
            legacy_insert(session, Task, id='uncertain_task', job_id='uncertain_job', kind='translate', status='outcome_unknown', fence=1, attempts=1)
            session.flush()
            legacy_insert(session, Attempt, id='uncertain_attempt', job_id='uncertain_job', task_id='uncertain_task', fence=1, control_epoch=0, state='outcome_unknown')
            session.flush()
            session.add(Permit(id='uncertain_permit', attempt_id='uncertain_attempt', job_id='uncertain_job', control_epoch=0,
                price_snapshot=PRICE, reserved_micro=80, state='unknown'))
        db.migrate()
        db.ready()
        assert claim(db) is None
        with db.transaction() as session:
            assert file_hash(cfg.data / session.get(SourceRevision, 'src_fixture').storage_key) == before
            assert budget_totals(session) == {'actual_micro': 0, 'reserved_micro': 0, 'unknown_micro': 80}
            assert session.get(Settings, 'singleton').dispatch_disabled
        with pytest.raises(DomainError, match='Unresolved billing risk'):
            enable_dispatch(db)
        acknowledged = enable_dispatch(db, accept_unknown_risk=True, reason='Inspected fixed request evidence; retain conservative unknown budget')
        assert acknowledged['unknown_micro'] == 80 and acknowledged['unknown_tasks_resumed'] == 0
        assert claim(db) is None
        with db.transaction() as session:
            assert session.get(Permit, 'uncertain_permit').state == 'unknown'
            assert session.get(Attempt, 'uncertain_attempt').evidence[-1]['origin'] == 'maintenance_cli'
    finally:
        db.engine.dispose()
        with admin.engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))


def test_installed_migration_checksum_and_downgrade_are_enforced(database):
    db, _ = database
    with pytest.raises(DomainError, match='Migration downgrade forbidden'):
        db.migrate(3)
    with db.engine.begin() as connection:
        connection.execute(text("UPDATE schema_migrations SET checksum=:bad WHERE version=1"), {'bad': '0' * 64})
    with pytest.raises(DomainError, match='Migration hash mismatch'):
        db.migrate()


def test_legacy_independent_memory_migration_discards_unrelated_source_atoms(database, monkeypatch):
    admin, cfg = database
    schema = 'library_test_' + uuid.uuid4().hex
    with admin.engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
    monkeypatch.setenv('TEST_DATABASE_SCHEMA', schema)
    db = Database(cfg)
    try:
        db.migrate(8)
        with db.transaction() as session:
            session.add(TranslationMemory(id='legacy_independent_memory', document_id=None,
                independent=True, generation=4, source_language='en', target_language='zh-Hans',
                source_text='The batch contains 64 tokens.', context_hash='a' * 64,
                target_inline=[{'type': 'text', 'text': '批次包含 '},
                    {'type': 'protected_ref', 'ref': 'n64'}, {'type': 'text', 'text': ' 个词元。'}],
                evidence={'origin': 'manual_ui', 'protected_atoms': {
                    'n64': {'kind': 'number', 'value': '64'},
                    'unrelated': {'kind': 'url', 'value': 'https://private.example/other-paragraph'}}}))
        db.migrate()
        db.ready()
        with db.transaction() as session:
            memory = session.get(TranslationMemory, 'legacy_independent_memory')
            assert memory.evidence == {'origin': 'manual_ui', 'protected_atoms': {
                'n64': {'kind': 'number', 'value': '64'}}}
            assert memory.source_text == 'The batch contains 64 tokens.'
            assert memory.generation == 5 and memory.independent and memory.document_id is None
            assert memory.target_inline[1] == {'type': 'protected_ref', 'ref': 'n64'}
        db.migrate()
        with db.transaction() as session:
            assert session.get(TranslationMemory, 'legacy_independent_memory').generation == 5
    finally:
        db.engine.dispose()
        with admin.engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
