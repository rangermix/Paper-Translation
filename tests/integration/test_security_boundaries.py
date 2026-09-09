"""Regression cases that exercise hostile input and post-deletion receipts."""
import json

import pytest
from sqlalchemy import select

from packages.domain.config import provider_profile
from packages.domain.models import Document, Heartbeat, Idempotency
from packages.jobs.queue import claim
from packages.privacy import cleanup_document
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_duplicate_json_and_oversized_body_rejected_before_mutation(client):
    headers = {'Content-Type': 'application/json', 'Idempotency-Key': 'malformed'}
    body = '{"filename":"a.pdf","filename":"b.pdf","media_type":"application/pdf","byte_size":10}'
    assert client.post('/api/v1/uploads', content=body, headers=headers).status_code == 422
    assert client.post('/api/v1/uploads', content='{"x":"' + 'a' * (8 * 1024 * 1024) + '"}', headers=headers).status_code == 413


def test_provider_metadata_rejects_unknown_nested_secrets(tmp_path, monkeypatch):
    path = tmp_path / 'provider.json'
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(path))
    for value in ({'configured': True, 'price': {'secret': 'do-not-leak'}}, [], {'configured': False, 'password': 'do-not-leak'}):
        path.write_text(json.dumps(value))
        result = provider_profile()
        assert result['configured'] is False
        assert 'do-not-leak' not in json.dumps(result)
    path.write_text('{"configured":true,"configured":false}')
    assert provider_profile()['configured'] is False


def test_tombstone_blocks_old_editor_receipt_and_cleanup_erases_it(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    body = {'target_inline': [{'type': 'text', 'text': 'private translation sentinel'}], 'base_segment_version': 1, 'reason': 'Compared with source'}
    headers = {'If-Match': '"1"', 'Idempotency-Key': 'private-editor'}
    url = '/api/v1/drafts/draft_fixture/segments/item'
    assert client.patch(url, json=body, headers=headers).status_code == 200
    assert client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True}, headers={'If-Match': '"1"'}).status_code == 202
    assert client.patch(url, json=body, headers=headers).status_code == 410
    cleanup_document(db, cfg, claim(db))
    assert client.patch(url, json=body, headers=headers).status_code == 410
    with db.transaction() as session:
        receipt = session.scalar(select(Idempotency).where(Idempotency.key == 'private-editor'))
        assert receipt.document_ids == ['doc_fixture']
        assert receipt.response == {'body': {}, 'status': 410}


def test_ready_detects_missing_dependency_and_referenced_data_corruption(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    assert client.get('/health/ready').status_code == 503
    with db.transaction() as session:
        session.add_all([Heartbeat(id='worker'), Heartbeat(id='parser')])
    healthy = client.get('/health/ready')
    assert healthy.status_code == 200, healthy.text
    (cfg.data / 'fixtures/figure.png').write_bytes(b'corrupt raster')
    failed = client.get('/health/ready')
    assert failed.status_code == 503
    assert failed.json()['error']['code'] == 'SOURCE_DERIVATIVE_CORRUPT'


def test_ready_requires_parser_manifest_before_accepting_parse_work(client, database, monkeypatch, tmp_path):
    from packages.parsers import models
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.add_all([Heartbeat(id='worker'), Heartbeat(id='parser')])
    assert client.get('/health/ready').status_code == 200
    monkeypatch.setattr(models, 'LOCK_PATH', tmp_path / 'missing-parser-manifest.json')
    failed = client.get('/health/ready')
    assert failed.status_code == 503
    assert failed.json()['error']['code'] == 'DEPENDENCY_INTEGRITY_FAILURE'


def test_candidate_cannot_apply_after_new_source_is_selected(client, database):
    from tests.integration.test_candidates import candidate_fixture
    db, cfg = database
    candidate_fixture(db, cfg, client)
    with db.transaction() as session:
        session.get(Document, 'doc_fixture').current_source_id = 'src_new_current'
    answer = client.post('/api/v1/candidates/candidate_fixture/accept', json={}, headers={'If-Match': '"1"', 'Idempotency-Key': 'stale-source'})
    assert answer.status_code == 409
    assert answer.json()['error']['code'] == 'SOURCE_STALE'


def test_transaction_failure_never_acknowledges_success(database):
    from fastapi.testclient import TestClient
    from sqlalchemy import event, func
    from apps.api.main import create_app
    from packages.domain.models import Upload
    db, cfg = database
    def fail_commit(_session):
        raise RuntimeError('Controlled commit failure')
    event.listen(db.session_factory, 'before_commit', fail_commit)
    try:
        with TestClient(create_app(cfg, db), raise_server_exceptions=False) as http:
            failed = http.post('/api/v1/uploads', json={'filename': 'fixture.pdf', 'media_type': 'application/pdf', 'byte_size': 20},
                headers={'X-Library-Request': '1', 'Idempotency-Key': 'commit-failure'})
            assert failed.status_code == 500, failed.text
    finally:
        event.remove(db.session_factory, 'before_commit', fail_commit)
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Upload)) == 0
