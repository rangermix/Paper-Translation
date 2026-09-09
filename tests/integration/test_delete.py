import pytest
from sqlalchemy import select

from packages.domain.models import Attempt, Document, Draft, Event, Job, SourceAsset, Task, TranslationMemory
from packages.jobs.queue import claim
from packages.privacy import cleanup_document
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_tombstone_immediate_then_cleanup_keeps_shared_original(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as s:
        s.add(Document(id='doc_shared', title='Independent same source', source_asset_id='source_pdf', source_language='en'))
    removed = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True}, headers={'If-Match': '"1"'})
    assert removed.status_code == 202, removed.text
    assert client.get('/api/v1/documents/doc_fixture/original').status_code == 410
    assert client.get('/api/v1/drafts/draft_fixture').status_code == 410
    lease = claim(db)
    assert lease.kind == 'cleanup'
    cleanup_document(db, cfg, lease)
    with db.transaction() as s:
        assert s.get(Document, 'doc_fixture').source_asset_id is None
        assert s.get(Draft, 'draft_fixture') is None
        assert s.get(SourceAsset, 'source_pdf') is not None
    assert client.get('/api/v1/documents/doc_shared/original').status_code == 200


def test_last_reference_cleanup_removes_original(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    removed = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True}, headers={'If-Match': '"1"'})
    assert removed.status_code == 202
    cleanup_document(db, cfg, claim(db))
    with db.transaction() as s:
        assert s.get(SourceAsset, 'source_pdf') is None
    assert not (cfg.data / 'fixtures/sample.pdf').exists()


def test_cleanup_erases_checkpoint_events_and_parser_spool_content(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.add(Job(id='job_prior', document_id='doc_fixture', stage='parse', status='succeeded',
            payload={'private': 'source sentinel'}, progress={'semantic_issues': [{'source_quote': 'source sentinel'}]}))
        session.flush()
        session.add(Task(id='task_prior', job_id='job_prior', kind='parse', status='succeeded', payload={'private': 'source sentinel'}))
        session.flush()
        session.add(Attempt(id='attempt_prior', task_id='task_prior', job_id='job_prior', fence=1, control_epoch=0,
            evidence=[{'kind': 'validated_unit', 'unit_hash': 'fixedhash', 'target_inline': [{'type': 'text', 'text': 'private sentinel'}]}]))
        session.add(Event(id='event_prior', job_id='job_prior', generation=1, payload={'semantic_issues': [{'target_quote': 'private sentinel'}]}))
    for root in (cfg.parser_inputs, cfg.parser_outputs):
        folder = root / 'task_prior/1'
        folder.mkdir(parents=True)
        (folder / 'original.pdf').write_bytes(b'private sentinel')
    assert client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True}, headers={'If-Match': '"1"'}).status_code == 202
    cleanup_document(db, cfg, claim(db))
    assert (cfg.parser_inputs / 'task_prior/cancelled.json').is_file()
    assert not (cfg.parser_inputs / 'task_prior/1').exists()
    assert not (cfg.parser_outputs / 'task_prior').exists()
    with db.transaction() as session:
        assert session.get(Attempt, 'attempt_prior').evidence == [{'kind': 'validated_unit', 'unit_hash': 'fixedhash'}]
        assert session.get(Event, 'event_prior').payload['content_deleted']
        assert session.get(Task, 'task_prior').payload == {}
