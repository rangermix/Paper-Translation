from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import select

from packages.domain.db import get_document, get_entity
from packages.domain.errors import match_generation, require
from packages.domain.models import Document, Draft, Edition, Glossary, SourceRevision, new_id
from packages.editorial.drafts import current_review, current_segments
from packages.glossaries import MATCHER_VERSION, effective_glossary, merge_entries, term_matches
from packages.ir import digest
from packages.storage import read_snapshot
from packages.translation.languages import canonical_locale
from packages.translation_memory import get_memory, list_memories, memory_view, save_reviewed_memory
from .common import StrictModel, command, page, response
from .library import Session

router = APIRouter(prefix='/api/v1')


def glossary_view(row):
    return {'id': row.id, 'source_language': row.source_language, 'target_language': row.target_language,
        'scope': 'document' if row.document_id else 'global', 'document_id': row.document_id,
        'parent_id': row.parent_id, 'entries': row.entries, 'snapshot_hash': row.snapshot_hash,
        'matcher_version': MATCHER_VERSION, 'created_at': row.created_at}


@router.get('/glossaries')
def glossaries(limit: int = Query(30, ge=1, le=100), cursor: str | None = None, session=Session):
    rows = list(session.scalars(select(Glossary).outerjoin(Document, Glossary.document_id == Document.id).where(
        (Glossary.document_id.is_(None)) | (Document.deleted_at.is_(None))).order_by(Glossary.created_at.desc(), Glossary.id.desc())))
    if cursor:
        index = next((i for i, row in enumerate(rows) if row.id == cursor), None)
        require(index is not None, 'CURSOR_INVALID', status=422)
        rows = rows[index+1:]
    return page([glossary_view(row) for row in rows[:limit]], rows[limit-1].id if len(rows) > limit else None)


@router.get('/glossaries/effective')
def effective(document_id: str, source_language: str, target_language: str, session=Session):
    return effective_glossary(session, document_id, source_language, target_language)


class GlossaryBody(StrictModel):
    source_language: str = Field(min_length=2, max_length=32)
    target_language: str = Field(min_length=2, max_length=32)
    scope: Literal['global', 'document']
    document_id: str | None = None
    entries: list[dict] = Field(max_length=10000)

    @field_validator('source_language', 'target_language')
    @classmethod
    def normalize_language(cls, value):
        return canonical_locale(value)


@router.post('/glossaries/revisions', status_code=201)
def create_glossary(body: GlossaryBody, request: Request, session=Session):
    def execute():
        require((body.scope == 'global' and body.document_id is None) or (body.scope == 'document' and body.document_id), 'GLOSSARY_SCOPE_INVALID', status=422)
        if body.document_id:
            get_document(session, body.document_id, lock=True)
        entries = merge_entries([], body.entries)
        base_query = select(Glossary).where(Glossary.document_id == body.document_id, Glossary.source_language == body.source_language, Glossary.target_language == body.target_language).order_by(Glossary.created_at.desc(), Glossary.id.desc()).limit(1)
        base = session.scalar(base_query)
        row = Glossary(id=new_id('glossary'), document_id=body.document_id, source_language=body.source_language,
            target_language=body.target_language, parent_id=base.id if base else None, entries=entries,
            snapshot_hash=digest({'entries': entries, 'source': body.source_language, 'target': body.target_language, 'matcher': MATCHER_VERSION}))
        session.add(row)
        session.flush()
        return glossary_view(row)
    return command(session, request, body.model_dump(), execute, 201)


class ImpactBody(StrictModel):
    document_id: str | None = None


@router.post('/glossaries/{glossary_id}/impact')
def impact(glossary_id: str, body: ImpactBody, request: Request, session=Session):
    def execute():
        glossary = get_entity(session, Glossary, glossary_id)
        if body.document_id:
            get_document(session, body.document_id)
        require(not glossary.document_id or body.document_id in (None, glossary.document_id), 'GLOSSARY_SCOPE_MISMATCH')
        query = select(Document).where(Document.deleted_at.is_(None), Document.current_source_id.is_not(None))
        chosen = glossary.document_id or body.document_id
        if chosen:
            query = query.where(Document.id == chosen)
        items = []
        for doc in session.scalars(query):
            source = read_snapshot(request.app.state.config.data, get_entity(session, SourceRevision, doc.current_source_id))
            if source['language'] != glossary.source_language:
                continue
            # The selected revision is the preview input. Current doc overrides apply to global previews.
            if glossary.document_id:
                terms = merge_entries([], glossary.entries)
            else:
                latest_doc = session.scalar(select(Glossary).where(Glossary.document_id == doc.id,
                    Glossary.source_language == glossary.source_language, Glossary.target_language == glossary.target_language).order_by(Glossary.created_at.desc(), Glossary.id.desc()).limit(1))
                terms = merge_entries(glossary.entries, latest_doc.entries if latest_doc else [])
            edition = session.scalar(select(Edition).where(Edition.document_id == doc.id, Edition.target_locale == glossary.target_language))
            draft = session.get(Draft, edition.current_draft_id) if edition and edition.current_draft_id else None
            # Block IDs are local to a frozen source revision. A previous
            # edition may intentionally retain its old source after replacement;
            # its review cannot label a new source's reused block ID as locked.
            segments = current_segments(session, draft.id) if draft and draft.source_revision_id == doc.current_source_id else {}
            for block in source['blocks']:
                matched = [e['source'] for e in terms if term_matches(block['normalized_text'], e)]
                if block['translatable'] and matched:
                    segment = segments.get(block['id'])
                    items.append({'document_id': doc.id, 'block_id': block['id'], 'source_text': block['normalized_text'],
                        'matched_terms': matched, 'locked': bool(segment and current_review(session, draft, segment))})
        return {'items': items, 'glossary_revision': glossary.id, 'matcher_version': MATCHER_VERSION, 'provider_calls': 0}
    return command(session, request, body.model_dump(), execute)


@router.get('/translation-memory')
def memories(q: str = Query('', max_length=10000), source_language: str | None = None, target_language: str | None = None,
        limit: int = Query(30, ge=1, le=100), cursor: str | None = None, session=Session):
    rows = list_memories(session, q, source_language, target_language)
    if cursor:
        index = next((i for i, row in enumerate(rows) if row['id'] == cursor), None)
        require(index is not None, 'CURSOR_INVALID', status=422)
        rows = rows[index+1:]
    return page(rows[:limit], rows[limit-1]['id'] if len(rows) > limit else None)


@router.get('/translation-memory/{memory_id}')
def memory(memory_id: str, session=Session):
    return response(memory_view(session, get_memory(session, memory_id)))


class MemoryBody(StrictModel):
    draft_id: str
    block_id: str
    segment_version: int = Field(ge=1)
    independent: bool = False


@router.post('/translation-memory', status_code=201)
def save_memory(body: MemoryBody, request: Request, session=Session):
    def execute():
        row = save_reviewed_memory(session, request.app.state.config, body.draft_id, body.block_id, body.segment_version, body.independent)
        return memory_view(session, row)
    return command(session, request, body.model_dump(), execute, 201)


class MemoryPreserve(StrictModel):
    independent: Literal[True]


@router.patch('/translation-memory/{memory_id}')
def preserve_memory(memory_id: str, body: MemoryPreserve, request: Request, session=Session):
    def execute():
        row = get_memory(session, memory_id, lock=True)
        match_generation(row, request.headers.get('If-Match'))
        row.independent = True
        row.generation += 1
        return memory_view(session, row)
    return command(session, request, body.model_dump(), execute)


@router.delete('/translation-memory/{memory_id}')
def delete_memory(memory_id: str, request: Request, session=Session):
    def execute():
        row = get_memory(session, memory_id, lock=True)
        match_generation(row, request.headers.get('If-Match'))
        session.delete(row)
        return {'id': memory_id, 'deleted': True}
    return command(session, request, {}, execute)
