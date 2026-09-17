"""Explicit continuation of local/legacy results creates new execution history."""
import copy

from fastapi import APIRouter, Request
from sqlalchemy import select

from packages.domain.db import get_document, get_entity
from packages.domain.errors import DomainError, match_generation, require
from packages.domain.models import Draft, Edition, Job, Permit, SegmentVersion, Settings, SourceRevision, Task, new_id, now
from packages.editorial.drafts import create_draft, current_segments, validate_target
from packages.ir import digest
from packages.jobs.queue import emit
from packages.storage import read_snapshot
from .common import command, response
from .library import Session, enqueue
from .workflow import TranslateEdition, checked_budget, checked_profile, job_view, language_profile, source_plan

router = APIRouter(prefix='/api/v1')


def continuation_context(session, cfg, draft):
    doc = get_document(session, draft.document_id)
    edition = get_entity(session, Edition, draft.edition_id)
    revision = get_entity(session, SourceRevision, draft.source_revision_id)
    require(doc.current_source_id == revision.id and doc.source_asset_id == revision.asset_id, 'SOURCE_STALE')
    require(edition.current_draft_id == draft.id, 'DRAFT_STALE')
    return doc, edition, revision, read_snapshot(cfg.data, revision)


def previous_jobs(session, draft):
    # Include unknown paid work for this source/language, even if another draft
    # was created in the meantime. New history must never evade unknown permits.
    return session.scalars(select(Job).where(Job.document_id == draft.document_id,
        Job.payload['source_revision_id'].astext == draft.source_revision_id,
        Job.payload['locale'].astext == session.get(Edition, draft.edition_id).target_locale)
        .order_by(Job.created_at.desc()).with_for_update()).all()


def assert_no_active_requests(session, jobs):
    ids = [job.id for job in jobs]
    require(not session.scalar(select(Permit.id).where(Permit.job_id.in_(ids),
        Permit.state == 'unknown').limit(1)), 'OUTCOME_UNKNOWN')
    require(not session.scalar(select(Permit.id).where(Permit.job_id.in_(ids),
        Permit.state == 'reserved').limit(1)), 'REQUEST_IN_FLIGHT')
    require(not any(job.status in {'pending', 'running', 'paused', 'outcome_unknown'} for job in jobs), 'JOB_ACTIVE')
    require(not session.scalar(select(Task.id).where(Task.job_id.in_(ids), Task.status == 'leased').limit(1)), 'JOB_ACTIVE')


@router.get('/drafts/{draft_id}/translation-preflight')
def preflight(draft_id: str, request: Request, session=Session):
    from packages.domain.config import provider_profile
    draft = get_entity(session, Draft, draft_id)
    doc, edition, revision, source = continuation_context(session, request.app.state.config, draft)
    profile = provider_profile()
    blocked, planning = None, {}
    try:
        assert_no_active_requests(session, previous_jobs(session, draft))
        require(not session.get(Settings, 'singleton').dispatch_disabled, 'DISPATCH_DISABLED')
        profile = checked_profile(profile.get('profile_revision'), source['language'], edition.target_locale)
        planning = source_plan(source, edition.target_locale, profile)
    except DomainError as exc:
        blocked = exc.code
    return response({'generation': draft.generation, 'source_revision_id': revision.id,
        'source_hash': revision.snapshot_hash, 'source_language': source['language'], 'locale': edition.target_locale,
        'profile': profile, 'profile_hash': digest(profile), 'can_translate': blocked is None,
        'blocked_reason': blocked, **planning})


@router.post('/drafts/{draft_id}/translate', status_code=202)
def continue_translation(draft_id: str, body: TranslateEdition, request: Request, session=Session):
    def execute():
        info = get_entity(session, Draft, draft_id)
        get_document(session, info.document_id, lock=True)
        get_entity(session, Edition, info.edition_id, lock=True)
        old = get_entity(session, Draft, draft_id, lock=True)
        match_generation(old, request.headers.get('If-Match'))
        doc, edition, revision, source = continuation_context(session, request.app.state.config, old)
        require(body.source_revision_id == revision.id and body.source_hash == revision.snapshot_hash, 'SOURCE_STALE')
        require(body.external_processing_confirmed, 'EXTERNAL_PROCESSING_UNCONFIRMED')
        jobs = previous_jobs(session, old)
        assert_no_active_requests(session, jobs)
        require(not session.get(Settings, 'singleton').dispatch_disabled, 'DISPATCH_DISABLED')
        profile = language_profile(checked_profile(body.profile_revision, source['language'], edition.target_locale,
            body.profile_hash), source, edition.target_locale)
        budget = checked_budget(profile, body.budget_micro)
        from packages.glossaries import effective_glossary
        glossary = effective_glossary(session, doc.id, source['language'], edition.target_locale)
        profile = {**profile, 'glossary_revision': glossary['revision'], 'glossary_entries': glossary['entries']}
        draft = create_draft(session, request.app.state.config, edition, revision, profile)
        blocks = {b['id']: b for b in source['blocks']}
        for segment in current_segments(session, old.id).values():
            block = blocks.get(segment.block_id)
            if not block or segment.source_hash != block['source_hash']:
                continue
            try:
                validate_target(segment.target_inline, source, block)
            except (DomainError, ValueError, KeyError):
                continue
            lineage = {'glossary_revision': old.glossary_revision, 'glossary_entries': old.profile.get('glossary_entries', [])}
            lineage.update(copy.deepcopy(segment.provenance_json))
            session.add(SegmentVersion(id=new_id('seg'), draft_id=draft.id, block_id=segment.block_id, sequence=1,
                target_inline=copy.deepcopy(segment.target_inline), source_hash=segment.source_hash,
                context_hash=segment.context_hash, origin=segment.origin, reason='Continued from existing draft',
                provenance_json=lineage | {'copied_from_segment_id': segment.id}))
        for previous in jobs:
            if previous.status in {'waiting_config', 'waiting_budget'}:
                previous.control_epoch += 1
                previous.status = 'cancelled'
                previous.progress = previous.progress | {'continued_draft_id': draft.id}
                emit(session, previous)
        payload = {**body.model_dump(), 'draft_id': draft.id, 'profile': profile, 'locale': edition.target_locale,
            'glossary_revision': glossary['revision'], 'glossary': glossary['entries'],
            'source_language': source['language'], 'confirmed_at': now().isoformat(), 'origin': 'explicit_continuation',
            'continued_from_draft_id': old.id}
        job = enqueue(session, 'translate', payload, doc.id)
        job.parent_job_id = next((row.id for row in jobs if row.payload.get('draft_id') == old.id), None)
        job.budget_micro = budget
        return {**job_view(session, job), 'draft_id': draft.id, 'edition_id': edition.id}
    return command(session, request, body.model_dump(), execute, 202)
