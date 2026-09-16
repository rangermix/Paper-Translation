"""Historical PDF identity across the real API and PostgreSQL (no Provider)."""
import copy
from datetime import timedelta
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select

from packages.domain.errors import DomainError
from packages.domain.models import Document, Job, SourceAsset, SourceDraft, SourceRevision, Upload, now
from packages.ir import block_hash, canonical_bytes, digest
from packages.jobs.queue import assert_current, claim
from packages.privacy import cleanup_document
from packages.storage import atomic_write, file_hash, write_snapshot
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def replacement(db, cfg):
    writer = PdfWriter()
    writer.append(PdfReader(cfg.data / 'fixtures/sample.pdf'))
    writer.add_metadata({'/Title': 'Explicit replacement PDF bytes'})
    stream = BytesIO()
    writer.write(stream)
    atomic_write(cfg.data, 'sources/asset_new/original.pdf', stream.getvalue())
    sha = file_hash(cfg.data / 'sources/asset_new/original.pdf')
    with db.transaction() as session:
        session.add(SourceAsset(id='asset_new', sha256=sha, byte_size=len(stream.getvalue()), page_count=1,
            storage_key='sources/asset_new/original.pdf'))
        session.flush()
        session.add(Upload(id='upload_new', filename='sample.pdf', byte_size=len(stream.getvalue()),
            received_bytes=len(stream.getvalue()), status='verified', sha256=sha, source_asset_id='asset_new',
            expires_at=now()+timedelta(hours=1)))
    return sha


def replace_api(client):
    return client.post('/api/v1/imports', json={'source': {'kind': 'pdf_upload', 'upload_id': 'upload_new'},
        'document_id': 'doc_fixture', 'source_language': 'en'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'replace-source'})


def test_replacement_keeps_ancestry_and_fences_old_worker(client, database):
    from apps.api.library import enqueue
    from apps.api.workflow import seal_source
    db, cfg = database
    ir = seed_editor(db, cfg)
    sha = replacement(db, cfg)
    before = (cfg.data / 'documents/doc_fixture/sources/src_fixture/document.json').read_bytes()
    with db.transaction() as session:
        job_id = enqueue(session, 'translate', {}, 'doc_fixture').id
        session.add(SourceDraft(id='stale_preflight', document_id='doc_fixture', asset_id='source_pdf',
            source=ir['source_revision'], coverage={'can_translate': True, 'unresolved': []}))
    lease = claim(db)
    updated = replace_api(client)
    assert updated.status_code == 201, updated.text
    assert updated.json()['source_revision_id'] == 'src_fixture'
    with db.transaction() as session:
        assert session.get(Job, job_id).status == 'cancelled'
        assert session.get(Job, job_id).progress['source_superseded']
        assert session.get(SourceDraft, 'stale_preflight').evidence['superseded_by']
        with pytest.raises(DomainError) as rejected:
            assert_current(session, lease)
        assert rejected.value.code == 'CONTROL_CHANGED'
    assert client.get('/api/v1/imports/stale_preflight/preflight').json()['can_translate'] is False
    source = copy.deepcopy(ir['source_revision'])
    source.update(id='src_new', original_asset_id='asset_new', sha256=sha)
    source['assets'][0].update(id='asset_new', sha256=sha, storage_key='sources/asset_new/original.pdf',
        byte_size=(cfg.data / 'sources/asset_new/original.pdf').stat().st_size)
    for block in source['blocks']:
        for locator in block['provenance']:
            locator['asset_id'] = 'asset_new'
        block['source_hash'] = block_hash(block, source['protected_atoms'])
    with db.transaction() as session:
        draft = SourceDraft(id='new_preflight', document_id='doc_fixture', asset_id='asset_new',
            source=source, base_revision_id='src_fixture', coverage={'can_translate': True, 'unresolved': []})
        session.add(draft)
        session.flush()
        revision, _ = seal_source(session, cfg, draft)
        assert revision.parent_id == 'src_fixture'
    assert (cfg.data / 'documents/doc_fixture/sources/src_fixture/document.json').read_bytes() == before
    assert client.get('/api/v1/drafts/draft_fixture').json()['source_revision_id'] == 'src_fixture'


def test_historical_original_and_draft_page_urls_use_bound_revision(client, database):
    db, cfg = database
    ir = seed_editor(db, cfg)
    replacement(db, cfg)
    old_pdf = (cfg.data / 'fixtures/sample.pdf').read_bytes()
    old_png = (cfg.data / 'fixtures/figure.png').read_bytes()
    # A separate revision provides page metadata without modifying a frozen row.
    with db.transaction() as session:
        session.add(SourceRevision(id='src_page', document_id='doc_fixture', asset_id='source_pdf',
            snapshot_hash=digest(ir['source_revision']), storage_key='documents/doc_fixture/sources/src_fixture/document.json',
            metadata_json={'page_images': {'1': 'fixtures/figure.png'}}))
        from packages.domain.models import Draft
        session.get(Draft, 'draft_fixture').source_revision_id = 'src_page'
    assert replace_api(client).status_code == 201
    assert client.get('/api/v1/documents/doc_fixture/original').content != old_pdf
    fetched = client.get('/api/v1/drafts/draft_fixture').json()
    assert 'source_revision_id=src_page' in fetched['original_url']
    assert client.get(fetched['original_url']).content == old_pdf
    for segment in fetched['segments']:
        for locator in segment['locators']:
            assert 'source_revision_id=src_page' in locator['page_image_url']
            assert client.get(locator['page_image_url']).content == old_png
    with db.transaction() as session:
        session.add(Document(id='doc_other', title='Separate source', source_asset_id='asset_new'))
    assert client.get('/api/v1/documents/doc_other/original?source_revision_id=src_page').status_code == 404


@pytest.mark.parametrize('tamper_after_verification', [False, True])
def test_reparse_worker_binds_parent_and_explicit_preflight_images(client, database, monkeypatch, tamper_after_verification):
    """Real worker/spool verification, with authored parser output, not Docling gold."""
    import workers.main as worker
    db, cfg = database
    ir = seed_editor(db, cfg)
    sha = replacement(db, cfg)
    assert replace_api(client).status_code == 201
    # This authored output fixture represents Docling; freeze that explicit
    # choice rather than depending on the default for newly queued parses.
    parsed = client.post('/api/v1/documents/doc_fixture/parse', json={
        'source_asset_id': 'asset_new', 'parser_profile_revision': 'docling-v1'},
        headers={'If-Match': '"2"', 'Idempotency-Key': 'parse-replacement'})
    assert parsed.status_code == 202, parsed.text
    lease = claim(db)
    assert lease.payload['base_revision_id'] == 'src_fixture'
    original_write = worker.write_request

    def authored_parser(input_root, request, source_pdf):
        original_write(input_root, request, source_pdf)
        out = cfg.parser_outputs / request['task_id'] / str(request['fence'])
        out.mkdir(parents=True)
        source = copy.deepcopy(ir['source_revision'])
        source.update(id='src_reparsed', sha256=sha, original_asset_id='asset_new')
        original = source_pdf.read_bytes()
        figure = (cfg.data / 'fixtures/figure.png').read_bytes()
        source['assets'][0].update(id='asset_new', sha256=sha, byte_size=len(original), storage_key='original.pdf')
        source['assets'][1]['storage_key'] = 'figure.png'
        for block in source['blocks']:
            for loc in block['provenance']:
                loc['asset_id'] = 'asset_new'
            block['source_hash'] = block_hash(block, source['protected_atoms'])
        payload = {'source_revision': source, 'coverage': {'can_translate': True, 'unresolved': [], 'pages': [{'page': 1}]},
            'inspection': {'page_count': 1, 'pages': [{'page': 1, 'page_image': 'page-1.png'}]}}
        outputs = {'payload.json': canonical_bytes(payload), 'original.pdf': original, 'figure.png': figure, 'page-1.png': figure}
        for name, data in outputs.items():
            (out / name).write_bytes(data)
        (out / 'result.json').write_bytes(canonical_bytes({
            'task_id': request['task_id'], 'fence': request['fence'], 'source_sha256': sha,
            'operation': 'parse', 'status': 'succeeded',
            'files': [{'path': name, 'byte_size': len(data), 'sha256': digest(data)} for name, data in outputs.items()]}))

    monkeypatch.setattr(worker, 'write_request', authored_parser)
    if tamper_after_verification:
        original_verify = worker.verify_result
        def change_verified_bytes(directory, request):
            result = original_verify(directory, request)
            payload_path = directory / 'payload.json'
            payload_path.write_bytes(payload_path.read_bytes() + b' ')
            return result
        monkeypatch.setattr(worker, 'verify_result', change_verified_bytes)
        with pytest.raises(DomainError) as error:
            worker.parse_spool(db, cfg, lease)
        assert error.value.code == 'PARSER_OUTPUT_HASH_MISMATCH'
        with db.transaction() as session:
            assert not list(session.scalars(select(SourceDraft)))
        assert not (cfg.data / 'documents/doc_fixture/parser').exists()
        return
    worker.parse_spool(db, cfg, lease)
    with db.transaction() as session:
        draft = session.scalar(select(SourceDraft).where(SourceDraft.document_id == 'doc_fixture'))
        draft_id = draft.id
        assert draft.base_revision_id == 'src_fixture'
        assert draft.evidence['document_generation'] == session.get(Document, 'doc_fixture').generation
    preflight = client.get('/api/v1/imports/' + draft_id + '/preflight').json()
    assert f'source_draft_id={draft_id}' in preflight['original_url']
    assert client.get(preflight['original_url']).content == (cfg.data / 'sources/asset_new/original.pdf').read_bytes()
    assert f'source_draft_id={draft_id}' in preflight['pages'][0]['page_image_url']
    assert client.get(preflight['pages'][0]['page_image_url']).status_code == 200
    assert client.get('/api/v1/documents/doc_fixture/pages/1.png?source_revision_id=src_fixture&source_draft_id='+draft_id).status_code == 422


@pytest.mark.parametrize('shared_kind', [None, 'revision', 'draft'])
def test_cleanup_all_historical_assets_respects_other_history(client, database, shared_kind):
    db, cfg = database
    ir = seed_editor(db, cfg)
    replacement(db, cfg)
    assert replace_api(client).status_code == 201
    with db.transaction() as session:
        if shared_kind:
            session.add(Document(id='doc_other', title='Other active PDF', source_asset_id='asset_new'))
            session.flush()
            if shared_kind == 'revision':
                key = 'documents/doc_other/sources/history/document.json'
                h = write_snapshot(cfg.data, key, ir['source_revision'])
                session.add(SourceRevision(id='src_other', document_id='doc_other', asset_id='source_pdf', snapshot_hash=h, storage_key=key))
            else:
                session.add(SourceDraft(id='draft_other', document_id='doc_other', asset_id='source_pdf',
                    source=ir['source_revision'], coverage={}))
    removed = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True}, headers={'If-Match': '"2"'})
    assert removed.status_code == 202, removed.text
    cleanup_document(db, cfg, claim(db))
    with db.transaction() as session:
        assert bool(session.get(SourceAsset, 'source_pdf')) == bool(shared_kind)
        assert bool(session.get(SourceAsset, 'asset_new')) == bool(shared_kind)
    assert (cfg.data / 'fixtures/sample.pdf').exists() == bool(shared_kind)
    if shared_kind:
        assert client.request('DELETE', '/api/v1/documents/doc_other', json={'confirm': True}, headers={'If-Match': '"1"'}).status_code == 202
        cleanup_document(db, cfg, claim(db))
        with db.transaction() as session:
            assert not list(session.scalars(select(SourceAsset)))
        assert not (cfg.data / 'fixtures/sample.pdf').exists()
