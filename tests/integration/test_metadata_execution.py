import httpx
from sqlalchemy import select
from packages.domain.models import SourceAsset, Document, Job, MetadataCache
from packages.jobs.queue import claim
from packages.metadata.execution import enqueue_metadata, execute_metadata
from tests.support import seed_editor


def prepare(database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        asset = session.get(SourceAsset, 'source_pdf')
        asset.doi_discovery = {'selected': '10.1234/x', 'status': 'found', 'header_text': 'A Controlled Paper Alice Example',
            'title_hint': 'A Controlled Paper', 'candidates': [{'doi': '10.1234/x', 'confidence': 90, 'method': 'header'}]}
        session.get(Document, 'doc_fixture').title_user_edited = False
        return enqueue_metadata(session, asset, document_id='doc_fixture').id


def transport(callback=None):
    def respond(request):
        if callback: callback()
        return httpx.Response(200, json={'DOI': '10.1234/x', 'title': 'A Controlled Paper', 'author': [{'given': 'Alice', 'family': 'Example'}], 'issued': {'date-parts': [[2020]]}})
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_success_updates_catalog_and_cache_but_keeps_filename_and_job_snapshot(database, client):
    db, cfg = database
    identifier = prepare(database)
    with db.transaction() as session:
        session.get(Document, 'doc_fixture').original_filename = 'uploaded.pdf'
    with transport() as service: execute_metadata(db, cfg, claim(db), client=service)
    doc = client.get('/api/v1/documents/doc_fixture').json()
    assert doc['title'] == 'A Controlled Paper' and doc['original_filename'] == 'uploaded.pdf'
    assert doc['bibliography']['year'] == 2020 and doc['metadata_status'] == 'succeeded'
    with db.transaction() as session:
        assert session.get(Job, identifier).title_snapshot == 'Publication fixture'
        assert session.scalar(select(MetadataCache)).response_snapshot['DOI'] == '10.1234/x'
        enqueue_metadata(session, session.get(SourceAsset, 'source_pdf'), document_id='doc_fixture')
    def no_request(request): raise AssertionError('positive cache must avoid network')
    with httpx.Client(transport=httpx.MockTransport(no_request)) as service: execute_metadata(db, cfg, claim(db), client=service)


def test_late_metadata_cannot_overwrite_user_rename(database, client):
    db, cfg = database
    prepare(database)
    lease = claim(db)
    def rename():
        response = client.patch('/api/v1/documents/doc_fixture', json={'title': 'My chosen title'}, headers={'If-Match': '"1"'})
        assert response.status_code == 200
    with transport(rename) as service: execute_metadata(db, cfg, lease, client=service)
    assert client.get('/api/v1/documents/doc_fixture').json()['title'] == 'My chosen title'


def test_stale_generation_cannot_replace_newer_lookup(database):
    db, cfg = database
    old = prepare(database)
    lease = claim(db)
    def refresh():
        with db.transaction() as session:
            enqueue_metadata(session, session.get(SourceAsset, 'source_pdf'), document_id='doc_fixture', force=True)
    with transport(refresh) as service: execute_metadata(db, cfg, lease, client=service)
    with db.transaction() as session:
        assert session.get(Job, old).status == 'cancelled'
        assert session.get(SourceAsset, 'source_pdf').bibliography is None
        assert session.get(Document, 'doc_fixture').title == 'Publication fixture'
