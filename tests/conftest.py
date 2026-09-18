import os
import uuid
from pathlib import Path

import pytest


def pytest_runtest_setup(item):
    if item.get_closest_marker('parser_container'):
        from packages.parsers.inspect import PDFError
        from workers.parser.main import verify_memory_envelope
        try:
            verify_memory_envelope()
        except PDFError:
            pytest.skip('Requires the real parser in a Linux container with a finite memory limit <= 16 GiB; run tests from compose.example.yaml in a dedicated project.')


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('A dedicated PostgreSQL TEST_DATABASE_URL is required; SQLite is not a substitute.')
    monkeypatch.setenv('LIBRARY_TEST_MODE', '1')
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('UPLOADS_DIR', str(tmp_path / 'uploads'))
    monkeypatch.setenv('PARSER_INPUTS_DIR', str(tmp_path / 'inputs'))
    monkeypatch.setenv('PARSER_OUTPUTS_DIR', str(tmp_path / 'outputs'))
    from packages.domain.config import Config
    from packages.domain.db import Database
    from sqlalchemy import create_engine, text
    # Explicit opt-in test URL only; production configuration is never reset.
    assert 'test' in url.rsplit('/', 1)[-1], 'Use a database explicitly named for tests'
    schema = 'library_test_' + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    monkeypatch.setenv('TEST_DATABASE_SCHEMA', schema)
    cfg = Config.load()
    db = Database(cfg)
    db.migrate()
    for p in (cfg.data, cfg.uploads, cfg.parser_inputs, cfg.parser_outputs):
        p.mkdir(parents=True, exist_ok=True)
    yield db, cfg
    db.engine.dispose()
    with admin.begin() as conn:
        conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    admin.dispose()


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    db, cfg = database
    with TestClient(create_app(cfg, db)) as http:
        http.headers['X-Library-Request'] = '1'
        yield http
