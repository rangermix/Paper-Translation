from datetime import timedelta
import hashlib
import os
from pathlib import Path
import re
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import Field, field_validator
from sqlalchemy import case, or_, select, text
from urllib.parse import urlencode

from packages.translation.languages import canonical_locale
from packages.parsers.profiles import ParserProfile, selected_profile
from packages.parsers.timeouts import selected_timeout_seconds
from packages.domain.config import provider_profile
from packages.domain.workflow import TERMINAL_STATES
from packages.translation.pipeline import PipelineOptions, freeze_pipeline
from packages.domain.db import get_document, get_entity, writable
from packages.domain.errors import match_generation, require
from packages.domain.models import (Artifact, Document, Draft, Edition, Export, Job,
    Settings, SourceAsset, SourceDraft, SourceRevision, Task, Upload, new_id, now)
from packages.storage import atomic_write, file_hash, safe_path
from .common import StrictModel, command, page, response, session_dependency


router = APIRouter(prefix='/api/v1')
# Commit or roll back before response headers are sent. Request-scoped yield
# teardown can acknowledge a mutation whose transaction has not committed yet.
Session = Depends(session_dependency, scope='function')


def upload_view(session, upload):
    asset = session.get(SourceAsset, upload.source_asset_id) if upload.source_asset_id else None
    duplicates = list(session.scalars(select(Document).where(Document.source_asset_id == asset.id, Document.deleted_at.is_(None)))) if asset else []
    return {'id': upload.id, 'upload_id': upload.id, 'filename': upload.filename, 'byte_size': upload.byte_size,
        'doi_discovery': upload.doi_discovery, 'metadata_status': asset.metadata_status if asset else None,
        'received_bytes': upload.received_bytes, 'status': upload.status, 'generation': upload.generation,
        'sha256': upload.sha256, 'page_count': asset.page_count if asset else None, 'error': upload.error,
        'expires_at': upload.expires_at, 'job_id': upload.job_id, 'source_asset_id': upload.source_asset_id,
        'chunk_limit': 4 * 1024 * 1024, 'duplicates': [{'id': d.id, 'title': d.title} for d in duplicates]}


def edition_view(session, edition):
    return {'id': edition.id, 'target_locale': edition.target_locale, 'generation': edition.generation,
        'current_artifact_id': edition.current_artifact_id, 'draft_id': edition.current_draft_id}


def document_view(session, doc):
    asset = session.get(SourceAsset, doc.source_asset_id)
    source_draft = session.scalar(select(SourceDraft).where(SourceDraft.document_id == doc.id, SourceDraft.asset_id == doc.source_asset_id).order_by(SourceDraft.created_at.desc()).limit(1))
    job = session.scalar(select(Job).where(Job.document_id == doc.id).order_by(
        case((Job.status.not_in(TERMINAL_STATES), 0), else_=1),
        case((Job.stage.in_(['parse', 'translate', 'publish']), 0), else_=1),
        Job.created_at.desc()).limit(1))
    return {'id': doc.id, 'title': doc.title, 'tags': doc.tags, 'starred': doc.starred,
        'original_filename': doc.original_filename, 'title_origin': doc.title_origin,
        'bibliography': asset.bibliography, 'metadata_status': asset.metadata_status,
        'doi_discovery': asset.doi_discovery,
        'lifecycle': doc.lifecycle, 'archived': doc.lifecycle == 'archived', 'generation': doc.generation,
        'status': doc.status, 'created_at': doc.created_at, 'source_asset_id': doc.source_asset_id,
        'source_revision_id': doc.current_source_id, 'source_language': doc.source_language,
        'original_url': f'/api/v1/documents/{doc.id}/original', 'sha256': asset.sha256, 'page_count': asset.page_count,
        'byte_size': asset.byte_size, 'import_id': source_draft.id if source_draft else None,
        'current_job_id': job.id if job else None,
        'editions': [edition_view(session, e) for e in session.scalars(select(Edition).where(Edition.document_id == doc.id).order_by(Edition.target_locale))]}


def enqueue(session, stage, payload, document_id=None):
    job = Job(id=new_id('job'), document_id=document_id, stage=stage, payload=payload)
    session.add(job)
    session.flush()
    session.add(Task(id=new_id('task'), job_id=job.id, kind=stage, payload=payload))
    session.flush()
    return job


class UploadCreate(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    media_type: Literal['application/pdf']
    byte_size: int = Field(gt=0, le=50 * 1024 * 1024)


@router.post('/uploads', status_code=201)
def create_upload(body: UploadCreate, request: Request, session=Session):
    def execute():
        require(body.filename.lower().endswith('.pdf'), 'UNSUPPORTED_FORMAT', status=415)
        upload = Upload(id=new_id('upl'), filename=body.filename, byte_size=body.byte_size, expires_at=now() + timedelta(hours=24))
        session.add(upload)
        session.flush()
        return upload_view(session, upload)
    return command(session, request, body.model_dump(), execute, 201)


@router.get('/uploads/{upload_id}')
def get_upload(upload_id: str, session=Session):
    return response(upload_view(session, get_entity(session, Upload, upload_id)))


@router.put('/uploads/{upload_id}/chunks/{index}')
async def put_chunk(upload_id: str, index: int, request: Request, session=Session):
    writable(session)
    cfg = request.app.state.config
    # Consume a bounded chunk before locking metadata. A lying Content-Length cannot bypass this.
    chunk = bytearray()
    async for part in request.stream():
        require(len(chunk) + len(part) <= cfg.chunk_bytes, 'UPLOAD_TOO_LARGE', status=413)
        chunk.extend(part)
    require(0 <= index < 1024 and len(chunk) > 0, 'CHUNK_INVALID', status=422)
    actual_hash = hashlib.sha256(chunk).hexdigest()
    require(request.headers.get('X-Chunk-SHA256') == actual_hash, 'CHUNK_HASH_MISMATCH', status=422)
    upload = get_entity(session, Upload, upload_id, lock=True)
    require(upload.expires_at > now(), 'UPLOAD_EXPIRED', status=409)
    matched = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', request.headers.get('Content-Range', ''))
    require(matched is not None, 'CONTENT_RANGE_INVALID', status=422)
    start, end, total = map(int, matched.groups())
    require(total == upload.byte_size and end - start + 1 == len(chunk), 'CONTENT_RANGE_INVALID', status=422)
    if index < len(upload.chunks):
        old = upload.chunks[index]
        require(old == {'sha256': actual_hash, 'start': start, 'size': len(chunk)}, 'CHUNK_CONFLICT')
        return response(upload_view(session, upload))
    match_generation(upload, request.headers.get('If-Match'))
    require(upload.status == 'receiving', 'UPLOAD_CLOSED')
    require(index == len(upload.chunks) and start == upload.received_bytes, 'CHUNK_ORDER')
    require(end < upload.byte_size and end < cfg.max_pdf_bytes, 'UPLOAD_TOO_LARGE', status=413)
    if index == 0:
        require(bytes(chunk[:5]) == b'%PDF-', 'UNSUPPORTED_FORMAT', status=415)
    atomic_write(cfg.uploads, f'{upload.id}/chunks/{index}.bin', bytes(chunk))
    upload.chunks = [*upload.chunks, {'sha256': actual_hash, 'start': start, 'size': len(chunk)}]
    upload.received_bytes += len(chunk)
    upload.generation += 1
    return response(upload_view(session, upload))


class Finalize(StrictModel):
    expected_sha256: str = Field(pattern='^[0-9a-f]{64}$')
    total_bytes: int = Field(gt=0, le=50 * 1024 * 1024)


@router.post('/uploads/{upload_id}/finalize', status_code=202)
def finalize(upload_id: str, body: Finalize, request: Request, session=Session):
    def execute():
        upload = get_entity(session, Upload, upload_id, lock=True)
        if upload.status in ('inspecting', 'verified'):
            require(upload.sha256 == body.expected_sha256 and upload.received_bytes == body.total_bytes, 'FINALIZE_CONFLICT')
            return upload_view(session, upload)
        match_generation(upload, request.headers.get('If-Match'))
        require(upload.status == 'receiving' and upload.expires_at > now(), 'UPLOAD_EXPIRED')
        require(upload.received_bytes == upload.byte_size == body.total_bytes, 'UPLOAD_INCOMPLETE')
        cfg = request.app.state.config
        target = safe_path(cfg.uploads, f'{upload.id}/original.pdf')
        temp = target.with_suffix('.tmp')
        h = hashlib.sha256()
        with temp.open('wb') as output:
            for i, meta in enumerate(upload.chunks):
                path = safe_path(cfg.uploads, f'{upload.id}/chunks/{i}.bin', must_exist=True)
                data = path.read_bytes()
                require(len(data) == meta['size'] and hashlib.sha256(data).hexdigest() == meta['sha256'], 'CHUNK_CORRUPT')
                h.update(data)
                output.write(data)
            output.flush()
            os.fsync(output.fileno())
        require(h.hexdigest() == body.expected_sha256, 'UPLOAD_HASH_MISMATCH', status=422)
        os.replace(temp, target)
        upload.sha256 = h.hexdigest()
        job = enqueue(session, 'inspect', {'upload_id': upload.id, 'source_sha256': upload.sha256})
        upload.status, upload.job_id = 'inspecting', job.id
        upload.generation += 1
        return upload_view(session, upload)
    return command(session, request, body.model_dump(), execute, 202)


class PDFSource(StrictModel):
    kind: Literal['pdf_upload']
    upload_id: str = Field(max_length=160)


class ImportCreate(StrictModel):
    source: PDFSource
    document_id: str | None = None
    source_language: str = 'auto'
    target_language: str = 'zh-Hans'
    parser_profile_revision: ParserProfile | None = None
    workflow: PipelineOptions | None = None

    @field_validator('source_language')
    @classmethod
    def normalize_source(cls, value):
        return value if value in ('auto', 'und') else canonical_locale(value)

    @field_validator('target_language')
    @classmethod
    def normalize_target(cls, value):
        return canonical_locale(value)


@router.post('/imports', status_code=201)
def create_import(body: ImportCreate, request: Request, session=Session):
    def execute():
        # Serializes attachment creation with last-reference physical cleanup.
        session.execute(text('SELECT pg_advisory_xact_lock(798205425)'))
        upload = get_entity(session, Upload, body.source.upload_id, lock=True)
        require(upload.status == 'verified' and upload.source_asset_id, 'UPLOAD_INCOMPLETE')
        if body.document_id:
            doc = get_document(session, body.document_id, lock=True)
            match_generation(doc, request.headers.get('If-Match'))
            doc.source_asset_id = upload.source_asset_id
            doc.original_filename = upload.filename
            if doc.title_user_edited is False:
                doc.title = Path(upload.filename).stem
                doc.title_origin = 'filename'
            # Keep the frozen parent until the replacement has passed preflight.
            # Its published editions continue to refer to their original bytes.
            from packages.jobs.queue import emit
            for job in session.scalars(select(Job).where(Job.document_id == doc.id,
                    Job.stage.not_in(['export', 'index', 'cleanup']),
                    Job.status.not_in(TERMINAL_STATES)).with_for_update()):
                job.control_epoch += 1
                job.progress = {**job.progress, 'source_superseded': True}
                if job.status != 'outcome_unknown':
                    job.status = 'cancelled'
                emit(session, job)
            for draft in session.scalars(select(SourceDraft).where(SourceDraft.document_id == doc.id).with_for_update()):
                if not draft.evidence.get('sealed_revision_id') and not draft.evidence.get('superseded_by'):
                    draft.evidence = {**draft.evidence, 'superseded_by': 'upload:' + upload.id}
                    draft.generation += 1
            doc.source_language = body.source_language
            doc.status = 'source_only'
            doc.generation += 1
        else:
            doc = Document(id=new_id('doc'), title=Path(upload.filename).stem, source_asset_id=upload.source_asset_id,
                source_language=body.source_language, original_filename=upload.filename, title_origin='filename', title_user_edited=False)
            session.add(doc)
        session.flush()
        from packages.metadata.execution import apply_title
        apply_title(doc, session.get(SourceAsset, upload.source_asset_id))
        if body.workflow:
            preferences = session.get(Settings, 'singleton').preferences
            job = enqueue(session, 'parse', {'source_asset_id': doc.source_asset_id,
                'parser_profile_revision': body.parser_profile_revision or selected_profile(preferences),
                'parser_timeout_seconds': selected_timeout_seconds(preferences), 'base_revision_id': doc.current_source_id,
                'source_language': doc.source_language, 'document_generation': doc.generation,
                'workflow': freeze_pipeline(body.workflow, doc.source_asset_id)}, doc.id)
            doc.status = 'parsing'; doc.generation += 1
        return document_view(session, doc)
    return command(session, request, body.model_dump(), execute, 201)


@router.get('/documents')
def list_documents(q: str = '', tag: str | None = None, starred: bool | None = None, lifecycle: str = 'active', cursor: str | None = None, limit: int = Query(30, ge=1, le=100), session=Session):
    query = select(Document).where(Document.deleted_at.is_(None))
    if lifecycle != 'all':
        query = query.where(Document.lifecycle == lifecycle)
    if q:
        query = query.where(Document.title.ilike('%' + q.replace('%', '\\%').replace('_', '\\_') + '%'))
    if tag:
        query = query.where(Document.tags.contains([tag]))
    if starred is not None:
        query = query.where(Document.starred == starred)
    if cursor:
        query = query.where(Document.id > cursor)
    docs = list(session.scalars(query.order_by(Document.id).limit(limit + 1)))
    return page([document_view(session, d) for d in docs[:limit]], docs[limit-1].id if len(docs) > limit else None)


@router.get('/documents/{document_id}')
def get_doc(document_id: str, session=Session):
    return response(document_view(session, get_document(session, document_id)))


class DocumentPatch(StrictModel):
    title: str | None = Field(None, min_length=1, max_length=1000)
    tags: list[str] | None = Field(None, max_length=100)
    starred: bool | None = None
    archived: bool | None = None


@router.patch('/documents/{document_id}')
def patch_doc(document_id: str, body: DocumentPatch, request: Request, session=Session):
    writable(session)
    doc = get_document(session, document_id, lock=True)
    match_generation(doc, request.headers.get('If-Match'))
    for name in ('title', 'tags', 'starred'):
        if name in body.model_fields_set and getattr(body, name) is not None:
            setattr(doc, name, getattr(body, name))
    if body.title is not None:
        doc.title_user_edited, doc.title_origin = True, 'user'
    if body.archived is not None:
        doc.lifecycle = 'archived' if body.archived else 'active'
    doc.generation += 1
    return response(document_view(session, doc))


class MetadataRefresh(StrictModel):
    doi: str | None = Field(None, max_length=2048)


@router.post('/documents/{document_id}/metadata/refresh', status_code=202)
def refresh_metadata(document_id: str, body: MetadataRefresh, request: Request, session=Session):
    def execute():
        session.execute(text('SELECT pg_advisory_xact_lock(798205425)'))
        doc = get_document(session, document_id, lock=True)
        match_generation(doc, request.headers.get('If-Match'))
        asset = session.scalar(select(SourceAsset).where(SourceAsset.id == doc.source_asset_id).with_for_update())
        require(asset is not None, 'SOURCE_REQUIRED')
        if body.doi is not None:
            from packages.metadata.discovery import normalize_doi, VERSION
            identifier = normalize_doi(body.doi)
            require(identifier, 'DOI_INVALID', status=422)
            asset.doi_discovery = {'version': VERSION, 'status': 'found', 'selected': identifier,
                'candidates': [{'doi': identifier, 'method': 'manual', 'confidence': 100, 'reference': False}]}
        if asset.doi_discovery:
            from packages.metadata.execution import enqueue_metadata
            job = enqueue_metadata(session, asset, document_id=doc.id, force=True)
        else:
            job = enqueue(session, 'inspect', {'source_asset_id': asset.id, 'source_sha256': asset.sha256}, doc.id)
        return {'metadata_status': asset.metadata_status, 'job_id': job.id if job else None}
    return command(session, request, body.model_dump(), execute, 202)


@router.get('/documents/{document_id}/original')
@router.head('/documents/{document_id}/original', include_in_schema=False)
def original(document_id: str, request: Request, source_revision_id: str | None = None,
        source_draft_id: str | None = None, session=Session):
    doc = get_document(session, document_id)
    require(not (source_revision_id and source_draft_id), 'SOURCE_SELECTOR_CONFLICT', status=422)
    asset_id = doc.source_asset_id
    if source_revision_id or source_draft_id:
        source = get_entity(session, SourceRevision if source_revision_id else SourceDraft, source_revision_id or source_draft_id)
        require(source.document_id == doc.id, 'NOT_FOUND', status=404)
        asset_id = source.asset_id
    asset = get_entity(session, SourceAsset, asset_id)
    path = safe_path(request.app.state.config.data, asset.storage_key, must_exist=True)
    require(file_hash(path) == asset.sha256, 'ASSET_CORRUPT')
    return FileResponse(path, media_type='application/pdf', headers={'Content-Security-Policy': "sandbox; default-src 'none'", 'ETag': f'"{asset.sha256}"'})


class DeleteDocument(StrictModel):
    confirm: Literal[True]


@router.delete('/documents/{document_id}', status_code=202)
def delete_doc(document_id: str, body: DeleteDocument, request: Request, session=Session):
    writable(session)
    session.execute(text('SELECT pg_advisory_xact_lock(798205425)'))
    doc = get_document(session, document_id, lock=True)
    match_generation(doc, request.headers.get('If-Match'))
    doc.deleted_at, doc.lifecycle = now(), 'deleted'
    doc.generation += 1
    for job in session.scalars(select(Job).where(Job.document_id == doc.id).with_for_update()):
        job.control_epoch += 1
        if job.status not in TERMINAL_STATES:
            job.status = 'cancelled'
        job.generation += 1
    cleanup = enqueue(session, 'cleanup', {'document_id': doc.id}, doc.id)
    return response({'id': doc.id, 'generation': doc.generation, 'job_id': cleanup.id, 'status': 'deleted',
        'notice': 'Online access is disabled. Downloaded copies cannot be recalled; backups expire by retention policy.'}, 202)


class ParseRequest(StrictModel):
    source_asset_id: str
    parser_profile_revision: ParserProfile | None = None
    workflow: PipelineOptions | None = None


@router.post('/documents/{document_id}/parse', status_code=202)
def parse(document_id: str, body: ParseRequest, request: Request, session=Session):
    def execute():
        require(request.app.state.config.phase != 'M0', 'PHASE_UNAVAILABLE')
        doc = get_document(session, document_id, lock=True)
        match_generation(doc, request.headers.get('If-Match'))
        require(doc.source_asset_id == body.source_asset_id, 'SOURCE_STALE')
        preferences = session.get(Settings, 'singleton').preferences
        selection = body.parser_profile_revision or selected_profile(preferences)
        pending = session.scalar(select(Job).where(Job.document_id == doc.id, Job.stage == 'parse', Job.status.in_(['pending', 'running'])))
        require(pending is None, 'PARSE_IN_PROGRESS')
        job = enqueue(session, 'parse', {**body.model_dump(), 'parser_profile_revision': selection, 'document_generation': doc.generation,
            'parser_timeout_seconds': selected_timeout_seconds(preferences), 'base_revision_id': doc.current_source_id,
            'source_language': doc.source_language,
            'workflow': freeze_pipeline(body.workflow, doc.source_asset_id) if body.workflow else None}, doc.id)
        doc.status = 'parsing'
        doc.generation += 1
        return {'job_id': job.id, 'id': job.id, 'status': job.status, 'generation': doc.generation}
    return command(session, request, body.model_dump(), execute, 202)


@router.get('/documents/{document_id}/pages/{page_number}.png')
def page_image(document_id: str, page_number: int, request: Request, source_revision_id: str | None = None,
        source_draft_id: str | None = None, session=Session):
    doc = get_document(session, document_id)
    require(not (source_revision_id and source_draft_id), 'SOURCE_SELECTOR_CONFLICT', status=422)
    if source_draft_id:
        draft = get_entity(session, SourceDraft, source_draft_id)
        require(draft.document_id == doc.id, 'NOT_FOUND', status=404)
        key = draft.evidence.get('page_images', {}).get(str(page_number))
    elif source_revision_id:
        rev = get_entity(session, SourceRevision, source_revision_id)
        require(rev.document_id == doc.id, 'NOT_FOUND', status=404)
        key = rev.metadata_json.get('page_images', {}).get(str(page_number))
    else:
        draft = session.scalar(select(SourceDraft).where(SourceDraft.document_id == doc.id,
            SourceDraft.asset_id == doc.source_asset_id).order_by(SourceDraft.created_at.desc()).limit(1))
        key = draft.evidence.get('page_images', {}).get(str(page_number)) if draft else None
        if not key and doc.current_source_id:
            rev = get_entity(session, SourceRevision, doc.current_source_id)
            if rev.asset_id == doc.source_asset_id:
                key = rev.metadata_json.get('page_images', {}).get(str(page_number))
    require(key, 'PAGE_NOT_AVAILABLE', status=404)
    path = safe_path(request.app.state.config.data, key, must_exist=True)
    return FileResponse(path, media_type='image/png')


def source_url(document_id, kind, source_id, page=None):
    suffix = 'original' if page is None else f'pages/{page}.png'
    return f'/api/v1/documents/{document_id}/{suffix}?' + urlencode({kind: source_id})
