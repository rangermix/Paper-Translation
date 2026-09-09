"""Explicit human-reviewed memory, separate from the machine exact cache."""
from difflib import SequenceMatcher, ndiff

from sqlalchemy import select

from packages.domain.db import get_document, get_entity
from packages.domain.errors import require
from packages.domain.models import Document, Draft, SourceRevision, TranslationMemory, new_id
from packages.editorial.drafts import current_review, current_segments, segment_fingerprint
from packages.ir import flatten_inline
from packages.storage import read_snapshot


def memory_view(session, memory, query=None):
    doc = session.get(Document, memory.document_id) if memory.document_id else None
    view = {'id': memory.id, 'generation': memory.generation, 'independent': memory.independent,
        'document_id': memory.document_id if doc and doc.deleted_at is None else None,
        'source_language': memory.source_language, 'target_language': memory.target_language,
        'source_text': memory.source_text, 'target_inline': memory.target_inline,
        'target_text': flatten_inline(memory.target_inline, memory.evidence.get('protected_atoms', {})),
        'context_hash': memory.context_hash, 'reviewed': True, 'evidence': memory.evidence, 'created_at': memory.created_at}
    if query:
        view.update({'exact_match': query == memory.source_text,
            'similarity': SequenceMatcher(a=query, b=memory.source_text, autojunk=False).ratio(),
            'difference': '\n'.join(ndiff([query], [memory.source_text])) if query != memory.source_text else ''})
    return view


def get_memory(session, memory_id, lock=False):
    statement = select(TranslationMemory).where(TranslationMemory.id == memory_id)
    row = session.scalar(statement.with_for_update() if lock else statement)
    require(row is not None, 'NOT_FOUND', status=404)
    if not row.independent:
        get_document(session, row.document_id)
    return row


def save_reviewed_memory(session, config, draft_id, block_id, version, independent=False):
    draft = get_entity(session, Draft, draft_id, lock=True)
    get_document(session, draft.document_id, lock=True)
    segment = current_segments(session, draft.id).get(block_id)
    require(segment is not None and segment.sequence == version, 'MEMORY_SEGMENT_STALE')
    review = current_review(session, draft, segment)
    require(review is not None, 'MEMORY_REVIEW_REQUIRED', 'Explicit current human review is required before saving memory.')
    source_revision = get_entity(session, SourceRevision, draft.source_revision_id)
    source = read_snapshot(config.data, source_revision)
    block = next(b for b in source['blocks'] if b['id'] == block_id)
    # Independent memory retains this reviewed sentence only. Keeping the whole
    # source atom map would retain private material from unrelated paragraphs.
    refs = {node['ref'] for node in (*block['source_inline'], *segment.target_inline)
        if node['type'] == 'protected_ref'}
    protected_atoms = {ref: source['protected_atoms'][ref] for ref in sorted(refs)}
    from packages.domain.models import Edition
    edition = get_entity(session, Edition, draft.edition_id)
    row = TranslationMemory(id=new_id('memory'), document_id=draft.document_id, independent=independent,
        source_language=block['language'], target_language=edition.target_locale,
        source_text=block['normalized_text'], target_inline=segment.target_inline, context_hash=segment.context_hash,
        evidence={'origin': 'manual_ui', 'draft_id': draft.id, 'source_revision_id': source_revision.id,
            'block_id': block_id, 'segment_version': segment.sequence, 'review_record_id': review.id,
            'review_fingerprint': segment_fingerprint(draft, segment), 'protected_atoms': protected_atoms,
            'locators': block['provenance']})
    session.add(row)
    session.flush()
    return row


def list_memories(session, query='', source_language=None, target_language=None):
    # The source tombstone is consulted in the query, before content can be returned.
    statement = select(TranslationMemory).outerjoin(Document, TranslationMemory.document_id == Document.id).where(
        (TranslationMemory.independent.is_(True)) | ((Document.id.is_not(None)) & (Document.deleted_at.is_(None))))
    if source_language:
        statement = statement.where(TranslationMemory.source_language == source_language)
    if target_language:
        statement = statement.where(TranslationMemory.target_language == target_language)
    rows = list(session.scalars(statement.order_by(TranslationMemory.created_at.desc(), TranslationMemory.id)))
    views = [memory_view(session, row, query) for row in rows]
    if query:
        views = [v for v in views if query.casefold() in v['source_text'].casefold() or v['similarity'] >= .35]
        views.sort(key=lambda v: (-v['similarity'], v['id']))
    return views


__all__ = ['get_memory', 'list_memories', 'memory_view', 'save_reviewed_memory']
