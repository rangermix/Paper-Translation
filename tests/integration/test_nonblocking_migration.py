"""NB-AT01: schema 11 upgrade preserves legacy facts without inventing history."""
import uuid

import pytest
from sqlalchemy import inspect, text

from packages.domain.db import Database
from packages.domain.models import Document, Job, Settings

pytestmark = pytest.mark.postgres


def test_upgrade_from_11_preserves_unknown_times_titles_and_dispatch(database, monkeypatch):
    admin, cfg = database
    schema = 'library_test_' + uuid.uuid4().hex
    with admin.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    monkeypatch.setenv('TEST_DATABASE_SCHEMA', schema)
    db = Database(cfg)
    try:
        db.migrate(11)
        with db.engine.begin() as conn:
            conn.execute(text("INSERT INTO documents (id,title,tags,starred,lifecycle,source_language,status,generation,created_at) VALUES ('legacy_doc','My chosen title','[]',false,'active','en','needs_review',7,now())"))
            conn.execute(text("INSERT INTO jobs (id,document_id,stage,status,control_epoch,payload,progress,budget_micro,generation,created_at) VALUES ('legacy_job','legacy_doc','translate','outcome_unknown',3,'{}','{}',null,5,now())"))
        db.migrate()
        db.migrate()
        db.ready()
        with db.transaction() as session:
            doc, job = session.get(Document, 'legacy_doc'), session.get(Job, 'legacy_job')
            assert doc.title == 'My chosen title' and doc.generation == 7
            assert doc.original_filename is None and doc.title_user_edited is None
            assert job.status == 'outcome_unknown' and job.control_epoch == 3
            assert job.started_at is None and job.finished_at is None
            assert job.config_snapshot is None and job.actual_model is None
            assert session.get(Settings, 'singleton').dispatch_disabled
        tables = inspect(db.engine).get_table_names(schema=schema)
        assert 'task_logs' in tables and 'metadata_cache' in tables
        assert not {'users', 'workspaces', 'tenants', 'roles', 'sessions'} & set(tables)
    finally:
        db.engine.dispose()
        with admin.engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
