from datetime import timedelta
import hashlib
import json

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text

from packages.domain.db import get_document, writable
from packages.domain.errors import require
from packages.domain.models import Artifact, Candidate, Document, Draft, Edition, Export, Idempotency, Job, SourceDraft, SourceRevision, TranslationMemory, TranslationRevision, now


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def session_dependency(request: Request):
    db = request.app.state.db
    require(db is not None, 'DATABASE_CONFIG', status=503)
    with db.transaction() as session:
        yield session


def response(value, status=200):
    data = jsonable_encoder(value)
    headers = {}
    if isinstance(data, dict) and 'generation' in data:
        headers['ETag'] = f'"{data["generation"]}"'
    return JSONResponse(data, status_code=status, headers=headers)


def command(session, request, payload, execute, status=200):
    """Idempotency and business writes commit in the same PostgreSQL transaction."""
    from packages.domain.db import lock_lifecycle
    # Before even deleting an expired receipt: cleanup also updates receipts,
    # so taking lifecycle only inside execute would invert those row locks.
    lock_lifecycle(session)
    key = request.headers.get('Idempotency-Key')
    require(key is not None and 1 <= len(key) <= 128 and key.isascii(), 'IDEMPOTENCY_REQUIRED', status=428)
    path = request.url.path
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    lock_key = int.from_bytes(hashlib.sha256((request.method + path + key).encode()).digest()[:8], 'big', signed=True)
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
    old = session.get(Idempotency, (key, request.method, path))
    if old is not None and old.expires_at > now():
        for document_id in old.document_ids:
            get_document(session, document_id)
        require(old.body_hash == body_hash, 'IDEMPOTENCY_CONFLICT')
        return response(old.response['body'], old.response['status'])
    if old is not None:
        session.delete(old)
        session.flush()
    data = jsonable_encoder(execute())
    session.add(Idempotency(key=key, method=request.method, path=path, body_hash=body_hash,
        response={'body': data, 'status': status}, document_ids=receipt_documents(session, request.path_params, payload, data),
        expires_at=now() + timedelta(days=7)))
    return response(data, status)


def receipt_documents(session, *values):
    """Bind receipts to their resource ancestry, including candidate/editor replies."""
    identities = set()
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {'id', 'document_id', 'draft_id', 'edition_id', 'artifact_id', 'export_id', 'job_id',
                        'source_revision_id', 'translation_revision_id', 'candidate_id', 'memory_id'} and isinstance(item, str):
                    identities.add(item)
    for value in values:
        collect(value)
    documents = set()
    for identifier in identities:
        for model in (Document, Draft, Edition, Artifact, Export, Job, SourceDraft, SourceRevision, TranslationRevision, TranslationMemory, Candidate):
            entity = session.get(model, identifier)
            if entity is None:
                continue
            if isinstance(entity, Document):
                documents.add(entity.id)
            elif isinstance(entity, Candidate):
                documents.add(session.get(Draft, entity.draft_id).document_id)
            elif getattr(entity, 'document_id', None):
                documents.add(entity.document_id)
            break
    return sorted(documents)


def page(items, cursor=None):
    return {'items': items, 'next_cursor': cursor}
