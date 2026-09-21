"""Real PDF intake/native inspection plus controlled Crossref HTTP responses."""
from datetime import timedelta
from io import BytesIO

import httpx
import pytest
from sqlalchemy import select

from packages.domain.models import Document, Job, MetadataCache, SourceAsset, Task, now
from packages.ir import digest
from packages.jobs.queue import claim
from packages.metadata.execution import enqueue_metadata, execute_metadata
from tests.support import seed_editor
from tests.unit.test_crossref_search import DISCOVERY, RECORD, TITLE


def service(items=None, callback=None, response=None):
    def respond(request):
        if callback: callback(request)
        return response or httpx.Response(200, json={'status': 'ok', 'message': {
            'items': [RECORD] if items is None else items}})
    return httpx.Client(transport=httpx.MockTransport(respond))


def prepare_search(database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        asset = session.get(SourceAsset, 'source_pdf')
        asset.doi_discovery = DISCOVERY
        session.get(Document, 'doc_fixture').title_user_edited = False
        job = enqueue_metadata(session, asset, document_id='doc_fixture')
        assert job is not None, 'A PDF title must enqueue a Crossref lookup without a DOI'
        return job.id


def test_title_match_persists_provenance_and_reuses_doi_cache(database, client):
    db, cfg = database
    prepare_search(database)
    with service() as crossref: execute_metadata(db, cfg, claim(db), client=crossref)
    doc = client.get('/api/v1/documents/doc_fixture').json()
    assert doc['title'] == TITLE and doc['bibliography']['service'] == 'crossref'
    assert doc['bibliography']['match'] == 'crossref_title_and_author'
    assert doc['doi_discovery']['selected'] == RECORD['DOI']
    assert doc['doi_discovery']['candidates'][-1]['method'] == 'crossref_search'
    with db.transaction() as session:
        assert session.scalar(select(MetadataCache)).doi == RECORD['DOI']
        enqueue_metadata(session, session.get(SourceAsset, 'source_pdf'), document_id='doc_fixture')
    with service(callback=lambda _: pytest.fail('Repeat lookup should use the cache')) as crossref:
        execute_metadata(db, cfg, claim(db), client=crossref)
    assert client.get('/api/v1/documents/doc_fixture').json()['title'] == TITLE


@pytest.mark.parametrize('items,status', [([], 'not_found'),
    ([RECORD, RECORD | {'DOI': '10.1234/another'}], 'ambiguous'),
    ([RECORD | {'title': ['Wrong scientific paper']}], 'unverified')])
def test_no_reliable_match_preserves_the_document(database, client, items, status):
    db, cfg = database
    job_id = prepare_search(database)
    with service(items=items) as crossref: execute_metadata(db, cfg, claim(db), client=crossref)
    doc = client.get('/api/v1/documents/doc_fixture').json()
    assert doc['title'] == 'Publication fixture' and doc['bibliography'] is None
    assert doc['metadata_status'] == status
    with db.transaction() as session:
        assert session.get(Job, job_id).status == 'completed_with_warnings'
        assert session.scalar(select(MetadataCache)) is None


def test_search_result_keeps_a_title_renamed_while_lookup_runs(database, client):
    db, cfg = database
    prepare_search(database)
    def rename(_):
        assert client.patch('/api/v1/documents/doc_fixture', json={'title': 'My title'},
            headers={'If-Match': '"1"'}).status_code == 200
    with service(callback=rename) as crossref: execute_metadata(db, cfg, claim(db), client=crossref)
    doc = client.get('/api/v1/documents/doc_fixture').json()
    assert doc['title'] == 'My title' and doc['bibliography']['title'] == TITLE


def test_new_doi_evidence_supersedes_an_inflight_title_search(database):
    db, cfg = database
    old = prepare_search(database)
    lease = claim(db)
    def discover(_):
        with db.transaction() as session:
            asset = session.get(SourceAsset, 'source_pdf')
            asset.doi_discovery = DISCOVERY | {'selected': '10.1234/new', 'status': 'found'}
            new = enqueue_metadata(session, asset, document_id='doc_fixture')
            assert new.id != old
    with service(callback=discover) as crossref: execute_metadata(db, cfg, lease, client=crossref)
    with db.transaction() as session:
        assert session.get(Job, old).status == 'cancelled'
        assert session.get(SourceAsset, 'source_pdf').bibliography is None


def test_rate_limit_retries_are_bounded_and_do_not_change_document_state(database):
    db, cfg = database
    job_id = prepare_search(database)
    for attempt in range(3):
        with service(response=httpx.Response(429, headers={'Retry-After': '60'})) as crossref:
            execute_metadata(db, cfg, claim(db), client=crossref)
        with db.transaction() as session:
            task = session.scalar(select(Task).where(Task.job_id == job_id))
            if attempt < 2:
                assert task.available_at > now() + timedelta(seconds=50)
                task.available_at = now() - timedelta(seconds=1)
    with db.transaction() as session:
        assert session.get(Job, job_id).status == 'failed'
        assert session.get(SourceAsset, 'source_pdf').metadata_status == 'failed'
        assert session.get(Document, 'doc_fixture').title == 'Publication fixture'
    assert claim(db) is None


def paper_pdf(embedded_title):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 20 Tf 40 720 Td (A Controlled Research Paper) Tj '
        b'0 -24 Td (about Reliable Metadata) Tj /F1 10 Tf 0 -30 Td (Alice Example) Tj '
        b'/F1 12 Tf 0 -40 Td (Abstract) Tj 0 -20 Td (Private body text.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_metadata({'/Title': TITLE if embedded_title else 'main.pdf', '/Author': 'Alice Example'})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parser_container
@pytest.mark.parametrize('legacy_discovery', [False, True])
@pytest.mark.parametrize('complete_before_import', [False, True])
@pytest.mark.parametrize('embedded_title', [False, True])
def test_upload_enriches_before_or_after_import_without_waiting_for_full_parse(
        database, client, monkeypatch, complete_before_import, embedded_title, legacy_discovery):
    import workers.main as worker
    from workers.parser.main import run_once
    db, cfg = database
    original_write = worker.write_request
    def inspect(input_root, request, pdf):
        result = original_write(input_root, request, pdf)
        assert request['operation'] == 'inspect'
        assert run_once(cfg.parser_inputs, cfg.parser_outputs)
        return result
    monkeypatch.setattr(worker, 'write_request', inspect)
    content = paper_pdf(embedded_title)
    if legacy_discovery:
        # An earlier upload predates first-page title discovery.
        (cfg.data / 'old.pdf').write_bytes(content)
        with db.transaction() as session:
            session.add(SourceAsset(id='old_asset', sha256=digest(content), byte_size=len(content), page_count=1,
                storage_key='old.pdf', doi_discovery={'version': 'doi-discovery-v1', 'status': 'no_doi',
                    'selected': None, 'candidates': [], 'title_hint': 'main.pdf'}, metadata_status='no_doi'))
    receipt = client.post('/api/v1/uploads', json={'filename': 'uploaded.pdf',
        'media_type': 'application/pdf', 'byte_size': len(content)}, headers={'Idempotency-Key': 'receipt'})
    assert receipt.status_code == 201
    route = '/api/v1/uploads/' + receipt.json()['id']
    uploaded = client.put(route + '/chunks/0', content=content, headers={'If-Match': receipt.headers['etag'],
        'X-Chunk-SHA256': digest(content), 'Content-Range': f'bytes 0-{len(content)-1}/{len(content)}',
        'Content-Type': 'application/octet-stream'})
    assert uploaded.status_code == 200
    finalized = client.post(route + '/finalize', json={'expected_sha256': digest(content), 'total_bytes': len(content)},
        headers={'If-Match': uploaded.headers['etag'], 'Idempotency-Key': 'finalize'})
    assert finalized.status_code == 202
    worker.execute(db, cfg, claim(db))
    inspected = client.get(route).json()
    assert inspected['status'] == 'verified' and inspected['metadata_status'] == 'pending'
    assert inspected['doi_discovery']['selected'] is None
    lease = claim(db)
    assert lease.kind == 'metadata_lookup'
    assert lease.payload['search'] == {'title': TITLE, 'author': 'Alice Example'}
    if complete_before_import:
        with service() as crossref: execute_metadata(db, cfg, lease, client=crossref)
    imported = client.post('/api/v1/imports', json={'source': {'kind': 'pdf_upload', 'upload_id': receipt.json()['id']}},
        headers={'Idempotency-Key': 'import'})
    assert imported.status_code == 201
    assert imported.json()['title'] == (TITLE if complete_before_import else 'uploaded')
    if not complete_before_import:
        with service() as crossref: execute_metadata(db, cfg, lease, client=crossref)
    doc = client.get('/api/v1/documents/' + imported.json()['id']).json()
    assert doc['title'] == TITLE and doc['original_filename'] == 'uploaded.pdf'
    assert doc['bibliography']['authors'][0]['name'] == 'Alice Example'
    state = client.get(route).json()
    assert state['status'] == 'verified' and state['bibliography']['doi'] == RECORD['DOI']
    assert state['doi_discovery']['selected'] == RECORD['DOI']


@pytest.mark.parametrize('version', ['doi-discovery-v1', 'doi-discovery-v2', 'doi-discovery-v3'])
def test_refresh_reinspects_old_discovery_without_a_usable_doi(database, client, version):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.get(SourceAsset, 'source_pdf').doi_discovery = {'version': version,
            'status': 'no_doi', 'selected': None, 'candidates': [], 'title_hint': 'main.pdf'}
    response = client.post('/api/v1/documents/doc_fixture/metadata/refresh', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'refresh-old-discovery'})
    assert response.status_code == 202
    assert response.json()['job_id'] is not None
    with db.transaction() as session:
        assert session.get(Job, response.json()['job_id']).stage == 'inspect'


@pytest.mark.parser_container
@pytest.mark.parametrize('stamp_y,old_version,method', [
    (360, 'doi-discovery-v2', 'arxiv_header'),
    (200, 'doi-discovery-v3', 'arxiv_margin'),
])
def test_refresh_recovers_arxiv_preprint_from_native_pdf_stamp(database, client, monkeypatch, stamp_y, old_version, method):
    import workers.main as worker
    from workers.parser.main import run_once
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    from packages.metadata.discovery import VERSION
    title = 'PipeDream: Fast and Efficient Pipeline Parallel DNN Training'
    doi = '10.48550/arxiv.1806.03377'
    writer = PdfWriter(clone_from=PdfReader(BytesIO(paper_pdf(True))))
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 20 Tf 40 720 Td (PipeDream: Fast and Efficient) Tj '
        b'0 -24 Td (Pipeline Parallel DNN Training) Tj /F1 10 Tf 0 -30 Td (Amar Phanishayee) Tj '
        b'/F1 12 Tf 0 -140 Td (Abstract) Tj 0 -20 Td (Training contents.) Tj ET '
        + f'BT /F1 12 Tf 0 1 -1 0 30 {stamp_y} Tm (arXiv:1806.03377v1 [cs.DC] 8 Jun 2018) Tj ET'.encode())
    writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
    writer.add_metadata({'/Title': title + ' -0.22in', '/Author': 'Amar Phanishayee'})
    output = BytesIO()
    writer.write(output)
    content = output.getvalue()
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        doc = session.get(Document, 'doc_fixture')
        doc.title = 'Narayanan-et-al-2019-PipeDream-SOSP'
        doc.title_user_edited = False
        asset = session.get(SourceAsset, doc.source_asset_id)
        (cfg.data / asset.storage_key).write_bytes(content)
        asset.sha256, asset.byte_size = digest(content), len(content)
        asset.doi_discovery = {'version': old_version, 'status': 'no_doi',
            'selected': None, 'candidates': [], 'title_hint': title + ' -0.22in'}
        asset.metadata_status = 'unverified'
    original_write = worker.write_request
    def inspect(input_root, request, pdf):
        result = original_write(input_root, request, pdf)
        assert request['operation'] == 'inspect'
        assert run_once(cfg.parser_inputs, cfg.parser_outputs)
        return result
    monkeypatch.setattr(worker, 'write_request', inspect)
    response = client.post('/api/v1/documents/doc_fixture/metadata/refresh', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'refresh-preprint'})
    assert response.status_code == 202
    lease = claim(db)
    assert lease.kind == 'inspect'
    worker.execute(db, cfg, lease)
    lease = claim(db)
    assert lease.kind == 'metadata_lookup'
    assert lease.payload['doi'] == doi
    assert not lease.payload.get('search')
    hosts = []
    def respond(request):
        hosts.append(request.url.host)
        if request.url.host == 'api.crossref.org': return httpx.Response(404)
        assert request.url.params['doi'] == doi
        return httpx.Response(200, json={'DOI': doi, 'title': title,
            'author': [{'given': 'Amar', 'family': 'Phanishayee'}],
            'issued': {'date-parts': [[2018]]}, 'publisher': 'arXiv'})
    with httpx.Client(transport=httpx.MockTransport(respond)) as crossref:
        execute_metadata(db, cfg, lease, client=crossref)
    assert hosts == ['api.crossref.org', 'citation.doi.org']
    result = client.get('/api/v1/documents/doc_fixture').json()
    assert result['metadata_status'] == 'succeeded'
    assert result['title'] == title
    assert result['bibliography']['doi'] == doi
    assert result['bibliography']['year'] == 2018
    assert result['bibliography']['service'] == 'doi'
    assert result['doi_discovery']['version'] == VERSION
    assert result['doi_discovery']['candidates'][0]['method'] == method
