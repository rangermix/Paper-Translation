from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import select

from packages.domain.db import get_document, get_entity, writable
from packages.domain.errors import match_generation, require
from packages.domain.models import (Candidate, Draft, Edition, IssueResolution, QA, ReviewRecord,
    SourceRevision, TranslationRevision, new_id)
from packages.editorial.drafts import (context_hash, create_draft, current_review, current_segments,
    edit_segment, quality_fingerprint, run_quality, seal, segment_fingerprint, semantic_evidence)
from packages.ir import digest
from packages.ir.retention import original_only_blocks
from packages.storage import read_snapshot
from .common import StrictModel, command, page, response
from .library import Session, edition_view, source_url

router = APIRouter(prefix='/api/v1')


def qa_view(qa, *, stale=False):
    from packages.editorial.drafts import quality_summary
    quality = quality_summary(qa)
    if stale: quality['state'] = 'stale'
    return {'id': qa.id, 'qa_id': qa.id, 'fingerprint': qa.fingerprint, 'qa_fingerprint': qa.fingerprint,
        'generation': qa.draft_generation, 'valid': qa.valid, 'stale': stale, 'issues': qa.issues,
        'quality': quality, 'state': quality['state'], 'created_at': qa.created_at}


def draft_view(session, config, draft):
    source = read_snapshot(config.data, get_entity(session, SourceRevision, draft.source_revision_id))
    original_only = original_only_blocks(source)
    segments = current_segments(session, draft.id)
    qa = session.get(QA, draft.qa_id) if draft.qa_id else None
    edition = session.get(Edition, draft.edition_id)
    semantic = semantic_evidence(session, draft, source, segments)
    qa_current = bool(qa and qa.draft_generation == draft.generation
        and qa.fingerprint == quality_fingerprint(draft, source, segments, semantic))
    semantic_status = ('not_requested' if not semantic else 'completed' if semantic[-1]['completed']
        else 'stale' if semantic[-1]['status'] == 'stale' else 'incomplete')
    return {'id': draft.id, 'document_id': draft.document_id, 'edition_id': draft.edition_id, 'target_locale': edition.target_locale,
        'original_url': source_url(draft.document_id, 'source_revision_id', draft.source_revision_id),
        'generation': draft.generation, 'source_revision_id': draft.source_revision_id, 'source_hash': digest(source),
        'glossary_revision': draft.glossary_revision, 'source': source,
        'semantic_review_status': semantic_status,
        'semantic_reviews': [{key: value for key, value in review.items() if key != 'findings'} for review in semantic],
        'segments': [{'block_id': b['id'], 'kind': b['kind'], 'translatable': b['translatable'] and b['id'] not in original_only and b.get('language', source['language']) != edition.target_locale,
            'source_text': b['normalized_text'], 'raw_text': b['raw_text'], 'normalization_edits': b['normalization_edits'],
            'source_inline': b['source_inline'], 'target_inline': segments[b['id']].target_inline if b['id'] in segments and b['id'] not in original_only else [],
            'version': segments[b['id']].sequence if b['id'] in segments else 0, 'source_hash': b['source_hash'],
            'context_hash': context_hash(source, b['id']), 'locators': [{**loc,
                'page_image_url': source_url(draft.document_id, 'source_revision_id', draft.source_revision_id, loc['page'])} for loc in b['provenance']],
            'glossary_revision': segments[b['id']].provenance_json.get('glossary_revision', draft.glossary_revision) if b['id'] in segments else draft.glossary_revision,
            'review_status': ('human_reviewed' if current_review(session, draft, segments[b['id']]) else ('machine_checked' if qa_current and qa.valid else 'not_reviewed')) if b['id'] in segments else 'not_reviewed'} for b in source['blocks']],
        'qa': qa_view(qa, stale=not qa_current) if qa else None, 'issues': qa.issues if qa else [],
        'candidates': [{'id': c.id, 'generation': c.generation, 'status': c.status, 'base': c.base, 'results': c.results, 'job_id': c.job_id}
            for c in session.scalars(select(Candidate).where(Candidate.draft_id == draft.id).order_by(Candidate.created_at.desc()))]}


@router.get('/drafts/{draft_id}')
def get_draft(draft_id: str, request: Request, session=Session):
    return response(draft_view(session, request.app.state.config, get_entity(session, Draft, draft_id)))


class SegmentEdit(StrictModel):
    target_inline: list[dict] = Field(max_length=10000)
    reason: str = Field(min_length=1, max_length=2000)
    base_segment_version: int = Field(ge=0)


@router.patch('/drafts/{draft_id}/segments/{block_id}')
def patch_segment(draft_id: str, block_id: str, body: SegmentEdit, request: Request, session=Session):
    def execute():
        draft = get_entity(session, Draft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        edit_segment(session, request.app.state.config, draft, block_id, body.target_inline, body.base_segment_version, body.reason)
        return draft_view(session, request.app.state.config, draft)
    return command(session, request, body.model_dump(), execute)


class ReviewConfirm(StrictModel):
    source_hash: str
    base_segment_version: int
    context_hash: str
    glossary_revision: str
    reason: str = Field(min_length=1, max_length=2000)


@router.post('/drafts/{draft_id}/segments/{block_id}/confirm-review')
def confirm_review(draft_id: str, block_id: str, body: ReviewConfirm, request: Request, session=Session):
    def execute():
        draft = get_entity(session, Draft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        segment = current_segments(session, draft.id).get(block_id)
        require(segment is not None, 'NOT_FOUND', status=404)
        require((body.source_hash, body.base_segment_version, body.context_hash, body.glossary_revision) ==
            (segment.source_hash, segment.sequence, segment.context_hash, segment.provenance_json.get('glossary_revision', draft.glossary_revision)), 'REVIEW_STALE')
        session.add(ReviewRecord(id=new_id('review'), draft_id=draft.id, block_id=block_id, segment_version=segment.sequence,
            fingerprint=segment_fingerprint(draft, segment), reason=body.reason, origin='manual_ui'))
        draft.generation += 1
        draft.qa_id = None
        session.flush()
        return draft_view(session, request.app.state.config, draft)
    return command(session, request, body.model_dump(), execute)


class EmptyBody(StrictModel):
    pass


@router.post('/drafts/{draft_id}/validate')
def validate(draft_id: str, body: EmptyBody, request: Request, session=Session):
    def execute():
        draft = get_entity(session, Draft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        return qa_view(run_quality(session, request.app.state.config, draft))
    return command(session, request, {}, execute)


class SealBody(StrictModel):
    qa_id: str | None = None
    qa_fingerprint: str | None = None
    generation: int


@router.post('/drafts/{draft_id}/seal', status_code=201)
def seal_draft(draft_id: str, body: SealBody, request: Request, session=Session):
    def execute():
        draft = get_entity(session, Draft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        require(body.generation == draft.generation, 'DRAFT_STALE', status=412)
        revision = seal(session, request.app.state.config, draft, body.qa_id, body.qa_fingerprint)
        return {'id': revision.id, 'translation_revision_id': revision.id, 'snapshot_hash': revision.snapshot_hash,
            'generation': draft.generation, 'edition_id': draft.edition_id}
    return command(session, request, body.model_dump(), execute, 201)


class IssueResolve(StrictModel):
    reason: str = Field(min_length=1, max_length=2000)
    evidence: dict


@router.post('/drafts/{draft_id}/issues/{issue_fingerprint}/resolve')
def resolve_issue(draft_id: str, issue_fingerprint: str, body: IssueResolve, request: Request, session=Session):
    def execute():
        draft = get_entity(session, Draft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        qa = session.get(QA, draft.qa_id)
        require(qa is not None and qa.draft_generation == draft.generation, 'QA_STALE')
        issue = next((i for i in qa.issues if i['fingerprint'] == issue_fingerprint), None)
        require(issue is not None, 'NOT_FOUND', status=404)
        source = read_snapshot(request.app.state.config.data, get_entity(session, SourceRevision, draft.source_revision_id))
        block = next((b for b in source['blocks'] if b['id'] == issue['block_id']), None)
        quote, page_number = body.evidence.get('quote'), body.evidence.get('page')
        require(block is not None and isinstance(quote, str) and quote.strip() and type(page_number) is int
            and any(p['page'] == page_number for p in block['provenance'])
            and ' '.join(quote.split()) in ' '.join(block['normalized_text'].split()), 'SOURCE_EVIDENCE_REQUIRED')
        session.add(IssueResolution(id=new_id('resolution'), draft_id=draft.id, issue_fingerprint=issue_fingerprint,
            reason=body.reason, evidence=body.evidence))
        draft.generation += 1
        draft.qa_id = None
        session.flush()
        return draft_view(session, request.app.state.config, draft)
    return command(session, request, body.model_dump(), execute)


class NewDraft(StrictModel):
    translation_revision_id: str


@router.post('/editions/{edition_id}/drafts', status_code=201)
def from_revision(edition_id: str, body: NewDraft, request: Request, session=Session):
    def execute():
        edition = get_entity(session, Edition, edition_id, lock=True)
        match_generation(edition, request.headers.get('If-Match'))
        revision = get_entity(session, TranslationRevision, body.translation_revision_id)
        source = get_entity(session, SourceRevision, revision.source_revision_id)
        tr = read_snapshot(request.app.state.config.data, revision)
        draft = create_draft(session, request.app.state.config, edition, source,
            {'profile_revision': tr['profile_version'], 'glossary_revision': tr['glossary_revision'],
                'provider': tr['engine']['provider'], 'model_id': tr['engine']['model'], 'prompt_version': tr['engine']['prompt_version']}, base=revision)
        return draft_view(session, request.app.state.config, draft)
    return command(session, request, body.model_dump(), execute, 201)
