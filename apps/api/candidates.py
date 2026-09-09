from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import select

from packages.domain.db import get_document, get_entity
from packages.domain.errors import match_generation, require
from packages.domain.models import Candidate, Draft, Edition, SourceRevision, new_id
from packages.editorial.drafts import context_hash, current_review, current_segments, edit_segment
from packages.ir import digest
from packages.storage import read_snapshot
from .common import StrictModel, command, page, response
from .editorial import draft_view
from .library import Session, enqueue
from .workflow import checked_budget, checked_profile, job_view, language_profile

router = APIRouter(prefix='/api/v1')


def current_source(session, draft):
    source = get_entity(session, SourceRevision, draft.source_revision_id)
    doc = get_document(session, draft.document_id)
    require(doc.current_source_id == source.id and doc.source_asset_id == source.asset_id, 'SOURCE_STALE')
    return source


class CandidateRequest(StrictModel):
    block_ids: list[str] = Field(min_length=1, max_length=10000)
    profile_revision: str
    profile_hash: str = Field(pattern='^[0-9a-f]{64}$')
    glossary_revision: str
    budget_micro: int | None = Field(None, gt=0)
    external_processing_confirmed: bool


@router.post('/drafts/{draft_id}/candidates', status_code=202)
def create_candidate(draft_id: str, body: CandidateRequest, request: Request, session=Session):
    def execute():
        draft = get_entity(session, Draft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        require(body.external_processing_confirmed, 'EXTERNAL_PROCESSING_UNCONFIRMED')
        source_entity = current_source(session, draft)
        source = read_snapshot(request.app.state.config.data, source_entity)
        edition = session.get(Edition, draft.edition_id)
        profile = language_profile(checked_profile(body.profile_revision, source['language'], edition.target_locale, body.profile_hash),
            source, edition.target_locale)
        budget = checked_budget(profile, body.budget_micro)
        from packages.glossaries import effective_glossary
        glossary = effective_glossary(session, draft.document_id, source['language'], edition.target_locale)
        require(glossary['revision'] == body.glossary_revision, 'GLOSSARY_STALE')
        blocks = {b['id']: b for b in source['blocks'] if b['translatable']}
        require(len(set(body.block_ids)) == len(body.block_ids) and set(body.block_ids) <= blocks.keys(), 'BLOCK_SELECTION_INVALID')
        segments = current_segments(session, draft.id)
        candidate = Candidate(id=new_id('candidate'), draft_id=draft.id, base={'source_revision_id': source_entity.id,
            'source_hash': digest(source), 'glossary_revision': draft.glossary_revision,
            'requested_glossary_revision': glossary['revision'], 'glossary_entries': glossary['entries'], 'profile': profile,
            'segments': {bid: {'version': segments[bid].sequence if bid in segments else 0,
                'source_hash': blocks[bid]['source_hash'], 'context_hash': context_hash(source, bid),
                'reviewed': bool(current_review(session, draft, segments[bid])) if bid in segments else False} for bid in body.block_ids}})
        session.add(candidate)
        session.flush()
        payload = {**body.model_dump(), 'budget_micro': budget, 'candidate_id': candidate.id, 'draft_id': draft.id, 'source_revision_id': source_entity.id,
            'source_hash': digest(source), 'profile': profile, 'locale': edition.target_locale,
            'base_glossary_revision': draft.glossary_revision, 'glossary': glossary['entries'], 'publish_policy': 'manual_approval'}
        job = enqueue(session, 'candidate', payload, draft.document_id)
        job.budget_micro = budget
        candidate.job_id = job.id
        return {'id': candidate.id, 'candidate_id': candidate.id, 'generation': candidate.generation, 'job_id': job.id, 'status': 'pending'}
    return command(session, request, body.model_dump(), execute, 202)


@router.get('/candidates')
def candidates(draft_id: str, session=Session):
    get_entity(session, Draft, draft_id)
    return page([{'id': c.id, 'generation': c.generation, 'status': c.status, 'base': c.base, 'results': c.results, 'job_id': c.job_id}
        for c in session.scalars(select(Candidate).where(Candidate.draft_id == draft_id))])


class AcceptCandidate(StrictModel):
    block_ids: list[str] | None = None
    allow_reviewed: bool = False
    base_segment_version: int | None = None
    base_source_hash: str | None = None
    base_context_hash: str | None = None
    glossary_revision: str | None = None


@router.post('/candidates/{candidate_id}/accept')
def accept_candidate(candidate_id: str, body: AcceptCandidate, request: Request, session=Session):
    def execute():
        candidate_info = get_entity(session, Candidate, candidate_id)
        draft = get_entity(session, Draft, candidate_info.draft_id, lock=True)
        source_entity = current_source(session, draft)
        candidate = get_entity(session, Candidate, candidate_id, lock=True)
        match_generation(candidate, request.headers.get('If-Match'))
        require(candidate.status == 'ready', 'CANDIDATE_NOT_READY')
        source = read_snapshot(request.app.state.config.data, source_entity)
        base = candidate.base
        require(base['source_revision_id'] == draft.source_revision_id and base['source_hash'] == digest(source)
            and base['glossary_revision'] == draft.glossary_revision, 'CANDIDATE_CONFLICT')
        selected = body.block_ids or list(base['segments'])
        require(selected and len(selected) == len(set(selected)) and set(selected) <= base['segments'].keys(), 'BLOCK_SELECTION_INVALID')
        require(set(selected) <= candidate.results.keys(), 'CANDIDATE_INCOMPLETE')
        segments = current_segments(session, draft.id)
        blocks = {b['id']: b for b in source['blocks']}
        conflicts, locked = [], []
        for bid in selected:
            expected = base['segments'][bid]
            current = segments.get(bid)
            if (current.sequence if current else 0) != expected['version'] or blocks[bid]['source_hash'] != expected['source_hash'] or context_hash(source, bid) != expected['context_hash']:
                conflicts.append(bid)
            if current and current_review(session, draft, current) and not body.allow_reviewed:
                locked.append(bid)
        require(not conflicts, 'CANDIDATE_CONFLICT', details={'blocks': conflicts})
        require(not locked, 'REVIEWED_BLOCKS_LOCKED', details={'blocks': locked})
        if len(selected) == 1:
            expected = base['segments'][selected[0]]
            for supplied, real in ((body.base_segment_version, expected['version']), (body.base_source_hash, expected['source_hash']), (body.base_context_hash, expected['context_hash'])):
                require(supplied is None or supplied == real, 'CANDIDATE_CONFLICT')
        require(body.glossary_revision is None or body.glossary_revision == base['requested_glossary_revision'], 'GLOSSARY_STALE')
        for bid in selected:
            edit_segment(session, request.app.state.config, draft, bid, candidate.results[bid], base['segments'][bid]['version'],
                'Explicitly accepted translation candidate', origin='candidate_accepted',
                provenance={'candidate_id': candidate.id, 'glossary_revision': base['requested_glossary_revision'],
                    'glossary_entries': base.get('glossary_entries', []), 'profile': base.get('profile', {})})
        remaining = {bid: value for bid, value in base['segments'].items() if bid not in selected}
        candidate.base = {**base, 'segments': remaining}
        candidate.status = 'ready' if remaining else 'accepted'
        candidate.generation += 1
        session.flush()
        return {'id': candidate.id, 'generation': candidate.generation, 'status': candidate.status,
            'draft_id': draft.id, 'draft_generation': draft.generation, 'accepted_blocks': selected}
    return command(session, request, body.model_dump(), execute)


@router.post('/drafts/{draft_id}/semantic-review', status_code=202)
def semantic_review(draft_id: str, body: CandidateRequest, request: Request, session=Session):
    def execute():
        draft = get_entity(session, Draft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        require(body.external_processing_confirmed, 'EXTERNAL_PROCESSING_UNCONFIRMED')
        source = read_snapshot(request.app.state.config.data, current_source(session, draft))
        edition = session.get(Edition, draft.edition_id)
        profile = language_profile(checked_profile(body.profile_revision, source['language'], edition.target_locale, body.profile_hash),
            source, edition.target_locale)
        budget = checked_budget(profile, body.budget_micro)
        require(profile.get('semantic_review_enabled') is True, 'SEMANTIC_REVIEW_DISABLED')
        require(body.glossary_revision == draft.glossary_revision, 'GLOSSARY_STALE')
        selected = {b['id'] for b in source['blocks'] if b['translatable']}
        require(set(body.block_ids) <= selected and len(body.block_ids) == len(set(body.block_ids)), 'BLOCK_SELECTION_INVALID')
        job = enqueue(session, 'semantic_review', {**body.model_dump(), 'budget_micro': budget, 'draft_id': draft.id, 'source_revision_id': draft.source_revision_id,
            'source_hash': digest(source), 'profile': profile, 'locale': edition.target_locale, 'glossary': [], 'publish_policy': 'manual_approval'}, draft.document_id)
        job.budget_micro = budget
        return job_view(session, job)
    return command(session, request, body.model_dump(), execute, 202)
