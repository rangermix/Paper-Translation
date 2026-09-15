import copy
import json
from typing import Literal

from fastapi import APIRouter, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator
from sqlalchemy import and_, func, or_, select, tuple_, update

from packages.billing.ledger import budget_totals
from packages.billing.price import cost_control_enabled, reserve_cost, validate_profile
from packages.domain.config import provider_profile
from packages.domain.db import get_document, get_entity, lock_singleton, writable
from packages.domain.errors import DomainError, match_generation, require
from packages.domain.models import (Attempt, Document, Draft, Edition, Event, Job, Permit, Settings, TaskLog,
    SourceDraft, SourceRevision, Task, Upload, new_id, now)
from packages.editorial.drafts import create_draft
from packages.ir import block_hash, digest, validate_source
from packages.jobs.queue import emit
from packages.jobs.history import log_view, time_view
from packages.jobs.visibility import clearable_history, visible_history
from packages.storage import read_snapshot, write_snapshot
from packages.translation.languages import canonical_locale, translation_profile
from .common import StrictModel, command, page, response
from .library import Session, enqueue, source_url

router = APIRouter(prefix='/api/v1')


def job_identity(session, job):
    """Resolve existing jobs from catalog metadata; never copy content into payloads."""
    document = session.get(Document, job.document_id) if job.document_id else None
    upload_id = job.payload.get('upload_id') if job.stage == 'inspect' else None
    upload = session.get(Upload, upload_id) if upload_id else None
    title = document.title.strip() if document and not document.deleted_at else ''
    filename = upload.filename if upload else None
    locale = job.payload.get('locale')
    if not locale and job.payload.get('edition_id'):
        edition = session.get(Edition, job.payload['edition_id'])
        locale = edition.target_locale if edition else None
    return {'title': title or filename or '未命名 PDF', 'filename': filename, 'target_locale': locale}


def job_content_deleted(session, job):
    doc = session.get(Document, job.document_id) if job.document_id else None
    return bool(doc and doc.deleted_at or job.progress.get('content_deleted'))


def job_view(session, job, *, details=True):
    if job.stage != 'cleanup' and job_content_deleted(session, job):
        return {'id': job.id, 'job_id': job.id, 'stage': job.stage, 'status': job.status,
            'document_id': None, 'title': '已删除文档', 'title_snapshot': None, 'content_deleted': True,
            'parent_job_id': job.parent_job_id, 'created_at': job.created_at, 'generation': job.generation,
            'control_epoch': job.control_epoch, **time_view(job), 'actual_model': job.actual_model,
            'config_snapshot': job.config_snapshot, 'progress': {}, 'result': {}, 'issues': [],
            'error': {'code': job.error.get('code')} if job.error else None,
            'attempts': [{'id': a.id, 'status': a.state, 'state': a.state, **time_view(a), 'actual_model': a.actual_model}
                for a in session.scalars(select(Attempt).where(Attempt.job_id == job.id).order_by(Attempt.created_at, Attempt.id))] if details else []}
    if job.stage == 'cleanup':
        # A tombstone exposes only this receipt, never retained job payloads,
        # task results, provider evidence, or historical progress events.
        files = {'pending': 'pending', 'running': 'running', 'succeeded': 'completed'}.get(job.status, 'failed')
        costs = {'actual_micro': 0, 'reserved_micro': 0, 'unknown_micro': 0}
        return {'id': job.id, 'job_id': job.id, 'document_id': job.document_id, 'stage': 'cleanup',
            'title': '已删除文档', 'filename': None, 'target_locale': None,
            'status': job.status, 'generation': job.generation, 'control_epoch': job.control_epoch,
            'created_at': job.created_at, 'progress': {},
            **time_view(job), 'actual_model': job.actual_model, 'config_snapshot': job.config_snapshot,
            'error': {'code': 'CLEANUP_FAILED', 'message': 'File cleanup failed.'} if files == 'failed' else None,
            'budget_micro': 0, 'cost_control_enabled': None, 'inflight_requests': 0, 'request_count': 0, 'currency': 'USD',
            **costs, 'costs': costs, 'usage': costs,
            'attempts': [{'id': a.id, 'status': a.state, 'state': a.state, **time_view(a), 'actual_model': a.actual_model}
                for a in session.scalars(select(Attempt).where(Attempt.job_id == job.id).order_by(Attempt.created_at, Attempt.id))], 'issues': [],
            'draft_id': None, 'import_id': None, 'result': {'deleted': True} if files == 'completed' else {},
            'cleanup': {'online_content': 'unavailable', 'files': files,
                'shared_assets': 'retained_while_referenced', 'backups': 'retained_until_expiry',
                'downloaded_copies': 'outside_instance'}}
    attempts = list(session.scalars(select(Attempt).where(Attempt.job_id == job.id).order_by(Attempt.created_at))) if details else []
    permits = {p.attempt_id: p for p in session.scalars(select(Permit).where(Permit.job_id == job.id))}
    costs = budget_totals(session, job.id)
    progress = job.progress or {}
    tasks = list(session.scalars(select(Task).where(Task.job_id == job.id)))
    results = [t.result for t in tasks if t.status == 'succeeded' and t.result]
    result = {k: v for item in results for k, v in item.items() if k in ('artifact_id', 'export_id', 'import_id', 'document_id')}
    error = job.error and {**job.error, 'message': job.error.get('message', job.error.get('code', 'Job error').replace('_', ' ').capitalize())}
    return {'id': job.id, 'job_id': job.id, 'document_id': job.document_id, 'stage': job.stage,
        **job_identity(session, job),
        **time_view(job), 'config_snapshot': job.config_snapshot, 'actual_model': job.actual_model,
        'title_snapshot': job.title_snapshot, 'parent_job_id': job.parent_job_id, 'quality_summary': job.quality_summary,
        'child_jobs': [{'id': child.id, 'stage': child.stage, 'status': child.status} for child in session.scalars(
            select(Job).where(Job.parent_job_id == job.id).order_by(Job.created_at, Job.id).limit(100))] if details else [],
        'status': job.status, 'generation': job.generation, 'control_epoch': job.control_epoch,
        'progress': progress, 'error': error, 'budget_micro': job.budget_micro,
        'cost_control_enabled': cost_control_enabled(job.payload['profile']) if job.payload.get('profile') else None,
        **{key: progress.get(key, 0) for key in ('verified_blocks', 'total_blocks', 'verified_units', 'total_units', 'checked_pages', 'total_pages')},
        'inflight_requests': sum(p.state == 'reserved' for p in permits.values()),
        'request_count': len(permits), 'currency': 'USD', **costs, 'result': result,
        'import_id': result.get('import_id'), 'issues': [{**finding, 'message': finding.get('explanation', finding.get('rule', 'Semantic risk'))} for finding in progress.get('semantic_issues', [])],
        'costs': costs, 'usage': costs,
        'draft_id': job.payload.get('draft_id') or progress.get('draft_id'), 'created_at': job.created_at,
        'attempts': [{'id': a.id, 'state': a.state, 'status': a.state, 'request_id': a.request_id, 'usage': a.usage, 'evidence': a.evidence,
            **time_view(a), 'actual_model': a.actual_model,
            'actual_micro': permits[a.id].actual_micro if a.id in permits else None,
            'reserved_micro': permits[a.id].reserved_micro if a.id in permits else None,
            'cost_control_enabled': permits[a.id].price_snapshot.get('cost_control_enabled', True) if a.id in permits else None,
            'unknown_micro': permits[a.id].reserved_micro if a.id in permits and permits[a.id].state == 'unknown' else 0} for a in attempts]}


def readable_job(session, job_id):
    job = session.get(Job, job_id)
    require(job is not None, 'NOT_FOUND', status=404)
    return job


@router.get('/jobs')
def list_jobs(status: str | None = None, document_id: str | None = None, cursor: str | None = None,
              q: str = Query('', max_length=255), group: Literal['all', 'active', 'attention', 'completed', 'cancelled'] = 'all',
              stage: str | None = Query(None, max_length=40), parent_job_id: str | None = None,
              model: str | None = Query(None, max_length=256),
              include_cleared: bool = False,
              limit: int = Query(30, ge=1, le=100), session=Session):
    query = select(Job).outerjoin(Document).outerjoin(Upload,
        and_(Job.stage == 'inspect', Upload.id == Job.payload['upload_id'].astext)
    )
    if not include_cleared:
        query = query.where(visible_history())
    if stage:
        query = query.where(Job.stage == stage)
    if parent_job_id:
        query = query.where(Job.parent_job_id == parent_job_id)
    if model:
        from sqlalchemy import cast, Text
        query = query.where(cast(Job.actual_model, Text).icontains(model, autoescape=True))
    groups = {
        'active': ['pending', 'queued', 'running', 'translating', 'cancel_requested'],
        'attention': ['failed', 'outcome_unknown', 'paused', 'waiting_config', 'waiting_configuration', 'waiting_budget', 'needs_review'],
        'completed': ['succeeded', 'completed', 'completed_with_warnings', 'partially_completed'], 'cancelled': ['cancelled'],
    }
    if group != 'all':
        query = query.where(Job.status.in_(groups[group]))
    if q.strip():
        term = q.strip()
        query = query.where(or_(
            and_(Document.deleted_at.is_(None), Job.stage != 'cleanup', Document.title.icontains(term, autoescape=True)),
            Upload.filename.icontains(term, autoescape=True), Job.id.icontains(term, autoescape=True)))
    if status:
        query = query.where(Job.status == status)
    if document_id:
        require(session.get(Document, document_id) is not None, 'NOT_FOUND', status=404)
        query = query.where(Job.document_id == document_id)
    if cursor:
        anchor = session.get(Job, cursor)
        require(anchor is not None, 'CURSOR_INVALID', status=422)
        query = query.where(tuple_(Job.created_at, Job.id) < tuple_(anchor.created_at, anchor.id))
    jobs = list(session.scalars(query.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)))
    return page([job_view(session, j, details=False) for j in jobs[:limit]], jobs[limit-1].id if len(jobs) > limit else None)


@router.get('/jobs/history')
def task_history(session=Session):
    settings = session.get(Settings, 'singleton')
    count = session.scalar(select(func.count()).select_from(Job).where(clearable_history()))
    return response({'generation': settings.generation, 'clearable_count': count})


class ClearTaskHistory(StrictModel):
    confirm: Literal[True]

    @field_validator('confirm', mode='before')
    @classmethod
    def require_confirmation(cls, value):
        if value is not True:
            raise ValueError('Explicit confirmation is required')
        return value


@router.post('/jobs/history/clear')
def clear_task_history(body: ClearTaskHistory, request: Request, session=Session):
    def execute():
        settings = lock_singleton(session)
        match_generation(settings, request.headers.get('If-Match'))
        result = session.execute(update(Job).where(clearable_history())
            .values(history_cleared_generation=Job.generation))
        settings.generation += 1
        return {'generation': settings.generation, 'cleared_count': result.rowcount}
    return command(session, request, body.model_dump(), execute)


@router.get('/jobs/{job_id}')
def get_job(job_id: str, session=Session):
    return response(job_view(session, readable_job(session, job_id)))


@router.get('/jobs/{job_id}/logs')
def job_logs(job_id: str, cursor: int | None = Query(None, ge=0), limit: int = Query(50, ge=1, le=200),
             level: Literal['info', 'warning', 'error'] | None = None, stage: str | None = None, session=Session):
    job = readable_job(session, job_id)
    query = select(TaskLog).where(TaskLog.job_id == job.id)
    if cursor is not None:
        query = query.where(TaskLog.sequence > cursor)
    if level:
        query = query.where(TaskLog.level == level)
    if stage:
        query = query.where(TaskLog.stage == stage)
    rows = list(session.scalars(query.order_by(TaskLog.sequence).limit(limit + 1)))
    return page([log_view(row, content_deleted=job_content_deleted(session, job)) for row in rows[:limit]], rows[limit-1].sequence if len(rows) > limit else None)


@router.get('/jobs/{job_id}/logs/download')
def download_job_logs(job_id: str, request: Request, session=Session):
    job = readable_job(session, job_id)
    database = request.app.state.db
    def stream():
        cursor = 0
        while True:
            with database.transaction() as read:
                current = readable_job(read, job_id)
                rows = list(read.scalars(select(TaskLog).where(TaskLog.job_id == job_id, TaskLog.sequence > cursor)
                                        .order_by(TaskLog.sequence).limit(200)))
                lines = [json.dumps(jsonable_encoder(log_view(row, content_deleted=job_content_deleted(read, current))), ensure_ascii=False) + '\n' for row in rows]
                if rows:
                    cursor = rows[-1].sequence
            yield from lines
            if len(rows) < 200:
                break
    return StreamingResponse(stream(), media_type='application/x-ndjson',
        headers={'Content-Disposition': f'attachment; filename="{job.id}-logs.jsonl"', 'Cache-Control': 'no-store'})


@router.get('/jobs/{job_id}/events')
def events(job_id: str, last_event_id: str | None = Header(None), session=Session):
    job = readable_job(session, job_id)
    if job.stage == 'cleanup' or job_content_deleted(session, job):
        snapshot = 'event: snapshot\ndata: ' + json.dumps(jsonable_encoder(job_view(session, job))) + '\n\n'
        return StreamingResponse(iter([snapshot]), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})
    query = select(Event).where(Event.job_id == job.id)
    after = session.get(Event, last_event_id) if last_event_id else None
    output = []
    if last_event_id and (after is None or after.job_id != job.id):
        output.append('event: snapshot_required\ndata: {}\n\n')
    elif after:
        query = query.where(Event.generation > after.generation)
    for event in session.scalars(query.order_by(Event.generation).limit(100)):
        output.append(f'id: {event.id}\nevent: progress\ndata: {json.dumps(event.payload)}\n\n')
    output.append('event: snapshot\ndata: ' + json.dumps(jsonable_encoder(job_view(session, job))) + '\n\n')
    # Finite replay closes its DB transaction. EventSource reconnects; clients also poll snapshots.
    return StreamingResponse(iter(output), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})


@router.get('/imports/{import_id}/preflight')
def preflight(import_id: str, session=Session):
    draft = get_entity(session, SourceDraft, import_id)
    source = draft.source
    profile = provider_profile()
    coverage = draft.coverage
    unresolved = coverage.get('unresolved', [])
    from packages.quality.issues import aggregate_source_issues
    diagnostics = aggregate_source_issues(coverage, source)
    execution = session.get(Job, draft.evidence.get('job_id')) if draft.evidence.get('job_id') else session.scalar(
        select(Job).join(Task, Task.job_id == Job.id).where(Task.result['import_id'].astext == draft.id).limit(1))
    ready = bool(source.get('blocks')) and not draft.evidence.get('superseded_by') and not draft.evidence.get('sealed_revision_id')
    planning = {'estimated_cost_micro': None, 'estimate_micro': None, 'currency': 'USD'}
    estimate_locale = session.get(Settings, 'singleton').preferences.get('locale', 'zh-Hans')
    if ready:
        try:
            planning.update(source_plan(source, estimate_locale, profile))
            planning['estimate_micro'] = planning['estimated_cost_micro']
            planning['estimate_locale'] = estimate_locale
        except (DomainError, ValueError):
            # Missing provider configuration or unresolved source language leaves no estimate.
            pass
    pages = []
    for page in coverage.get('pages', []):
        number = page.get('page', page.get('page_number'))
        count = sum(r.get('page') == number for r in diagnostics['issues'])
        pages.append({**page, 'page': number, 'status': 'with_warnings' if count else 'extracted',
            'page_image_url': source_url(draft.document_id, 'source_draft_id', draft.id, number),
            'covered_blocks': len([b for b in source.get('blocks', []) if any(loc['page'] == number for loc in b.get('provenance', []))]),
            'unresolved_regions': count})
    return response({'id': draft.id, 'import_id': draft.id, 'document_id': draft.document_id,
        'generation': draft.generation, 'preflight_generation': draft.generation, 'source_hash': digest(source),
        'source_revision_id': source.get('id'), 'source_asset_id': draft.asset_id,
        'original_url': source_url(draft.document_id, 'source_draft_id', draft.id),
        'source_language': source.get('language', 'und'), 'coverage': draft.coverage,
        'page_count': draft.evidence.get('inspection', {}).get('page_count', len(draft.coverage.get('pages', []))),
        'blocks': [{**b, 'provenance': [{**loc, 'page_image_url': source_url(draft.document_id,
            'source_draft_id', draft.id, loc['page'])} for loc in b.get('provenance', [])]} for b in source.get('blocks', [])],
        'block_count': len(source.get('blocks', [])),
        'unresolved': unresolved, 'unresolved_blocks': len(diagnostics['issues']), 'can_translate': ready,
        'issues': diagnostics['issues'], 'quality': diagnostics['quality'], 'diagnostic_count': len(unresolved),
        'actual_model': execution.actual_model if execution else None,
        'status': 'superseded' if draft.evidence.get('superseded_by') else 'sealed' if draft.evidence.get('sealed_revision_id') else 'ready' if ready else 'unavailable', 'pages': pages,
        'required_blocks': sum(bool(b.get('translatable')) for b in source.get('blocks', [])),
        'retained_blocks': sum(not b.get('translatable') for b in source.get('blocks', [])),
        'assets': [{'id': a['id'], 'kind': a.get('kind', a.get('media_type', 'asset')), 'status': 'available'} for a in source.get('assets', [])],
        'sha256': source.get('sha256'), 'profile': profile, 'profile_hash': digest(profile), **planning,
        'estimate_note': planning.get('estimate_note', 'Cost estimate is unavailable until the service configuration is complete.')})


from packages.editorial.source_sealing import seal_source


class ConfirmPreflight(StrictModel):
    source_hash: str
    preflight_generation: int
    profile_revision: str
    profile_hash: str = Field(pattern='^[0-9a-f]{64}$')
    locale: str
    source_language: str | None = None
    budget_micro: int | None = Field(None, gt=0)
    external_processing_confirmed: bool
    publish_policy: Literal['manual_approval', 'auto_publish'] = 'auto_publish'

    @field_validator('locale', 'source_language')
    @classmethod
    def normalize_locale(cls, value):
        return canonical_locale(value) if value is not None else None


def checked_profile(revision, source_language, locale, profile_hash=None):
    profile = provider_profile()
    require(profile.get('configured'), 'PROVIDER_CONFIG')
    require(profile.get('profile_revision') == revision and profile.get('model_id'), 'PROFILE_STALE')
    require(profile_hash is None or digest(profile) == profile_hash, 'PROFILE_STALE')
    try:
        if source_language not in ('auto', 'und', None):
            canonical_locale(source_language)
        canonical_locale(locale)
    except ValueError as exc:
        require(False, str(exc))
    try:
        validate_profile(profile)
    except ValueError:
        require(False, 'PROVIDER_CONFIG')
    return profile


def language_profile(profile, source, locale):
    try:
        return translation_profile(profile, source, locale)
    except ValueError as exc:
        require(False, str(exc))


def checked_budget(profile, budget):
    if not cost_control_enabled(profile):
        return None
    require(type(budget) is int and budget > 0, 'BUDGET_REQUIRED', status=422)
    return budget


def source_plan(source, locale, profile):
    from packages.translation.planner import plan_units
    try:
        units = plan_units(source, locale, profile, nonblocking=True)
    except ValueError as exc:
        require(False, str(exc))
    ceiling = reserve_cost(profile)
    return {'planned_units': len(units), 'estimated_cost_micro': len(units) * ceiling if ceiling is not None else None,
        'cost_control_enabled': cost_control_enabled(profile),
        'estimate_note': 'Conservative request ceilings for the frozen profile; cache hits may lower actual cost.' if ceiling is not None else 'Cost control is disabled; no monetary budget is enforced.'}


@router.get('/editions/{edition_id}/preflight')
def edition_preflight(edition_id: str, request: Request, session=Session):
    edition = get_entity(session, Edition, edition_id)
    doc = get_document(session, edition.document_id)
    require(doc.current_source_id is not None, 'SOURCE_REQUIRED')
    revision = get_entity(session, SourceRevision, doc.current_source_id)
    require(revision.asset_id == doc.source_asset_id, 'SOURCE_STALE')
    source = read_snapshot(request.app.state.config.data, revision)
    profile = provider_profile()
    planning = {'planned_units': None, 'estimated_cost_micro': None}
    blocked = None
    try:
        checked_profile(profile.get('profile_revision'), source['language'], edition.target_locale)
        planning = source_plan(source, edition.target_locale, profile)
    except DomainError as exc:
        blocked = exc.code
    return response({'edition_id': edition.id, 'document_id': doc.id, 'generation': edition.generation,
        'source_revision_id': revision.id, 'source_hash': revision.snapshot_hash, 'source_language': source['language'],
        'locale': edition.target_locale, 'profile': profile, 'profile_hash': digest(profile), 'current_draft_id': edition.current_draft_id,
        'can_translate': blocked is None and edition.current_draft_id is None,
        'blocked_reason': blocked or ('DRAFT_ALREADY_EXISTS' if edition.current_draft_id else None), **planning})


class TranslateEdition(StrictModel):
    source_revision_id: str
    source_hash: str = Field(pattern='^[0-9a-f]{64}$')
    profile_revision: str
    profile_hash: str = Field(pattern='^[0-9a-f]{64}$')
    budget_micro: int | None = Field(None, gt=0)
    external_processing_confirmed: bool
    publish_policy: Literal['manual_approval', 'auto_publish'] = 'auto_publish'


@router.post('/editions/{edition_id}/translate', status_code=202)
def translate_edition(edition_id: str, body: TranslateEdition, request: Request, session=Session):
    def execute():
        info = get_entity(session, Edition, edition_id)
        doc = get_document(session, info.document_id, lock=True)
        edition = get_entity(session, Edition, edition_id, lock=True)
        match_generation(edition, request.headers.get('If-Match'))
        revision = get_entity(session, SourceRevision, body.source_revision_id)
        require(revision.document_id == doc.id and doc.current_source_id == revision.id
            and revision.asset_id == doc.source_asset_id and body.source_hash == revision.snapshot_hash, 'SOURCE_STALE')
        require(body.external_processing_confirmed, 'EXTERNAL_PROCESSING_UNCONFIRMED')
        require(edition.current_draft_id is None, 'DRAFT_ALREADY_EXISTS')
        source = read_snapshot(request.app.state.config.data, revision)
        profile = language_profile(checked_profile(body.profile_revision, source['language'], edition.target_locale, body.profile_hash),
            source, edition.target_locale)
        budget = checked_budget(profile, body.budget_micro)
        planning = source_plan(source, edition.target_locale, profile)
        from packages.glossaries import effective_glossary
        glossary = effective_glossary(session, doc.id, source['language'], edition.target_locale)
        profile = {**profile, 'glossary_revision': glossary['revision'], 'glossary_entries': glossary['entries']}
        draft = create_draft(session, request.app.state.config, edition, revision, profile)
        payload = {**body.model_dump(), 'budget_micro': budget, 'draft_id': draft.id, 'locale': edition.target_locale, 'profile': profile,
            'glossary_revision': glossary['revision'], 'glossary': glossary['entries'], 'source_language': source['language'],
            'confirmed_at': now().isoformat(), 'origin': 'manual_ui'}
        job = enqueue(session, 'translate', payload, doc.id)
        job.budget_micro = budget
        return {**job_view(session, job), 'edition_id': edition.id, 'draft_id': draft.id,
            'edition_generation': edition.generation, 'source_revision_id': revision.id, **planning}
    return command(session, request, body.model_dump(), execute, 202)


@router.post('/imports/{import_id}/confirm', status_code=202)
def confirm(import_id: str, body: ConfirmPreflight, request: Request, session=Session):
    def execute():
        source_draft = get_entity(session, SourceDraft, import_id, lock=True)
        match_generation(source_draft, request.headers.get('If-Match'))
        require(body.preflight_generation == source_draft.generation and body.source_hash == digest(source_draft.source), 'PREFLIGHT_STALE')
        require(source_draft.source and source_draft.source.get('blocks'), 'SOURCE_REQUIRED')
        require(body.external_processing_confirmed, 'EXTERNAL_PROCESSING_UNCONFIRMED')
        source_language = body.source_language or source_draft.source.get('language')
        if source_draft.source.get('language') not in (None, 'und', 'auto'):
            require(source_language == source_draft.source['language'], 'SOURCE_LANGUAGE_MISMATCH')
        profile = checked_profile(body.profile_revision, source_language, body.locale, body.profile_hash)
        budget = checked_budget(profile, body.budget_micro)
        revision, source = seal_source(session, request.app.state.config, source_draft, source_language)
        profile = language_profile(profile, source, body.locale)
        source_plan(source, body.locale, profile)
        edition = session.scalar(select(Edition).where(Edition.document_id == revision.document_id, Edition.target_locale == body.locale).with_for_update())
        if edition is None:
            edition = Edition(id=new_id('edition'), document_id=revision.document_id, target_locale=body.locale)
            session.add(edition)
            session.flush()
        from packages.glossaries import effective_glossary
        glossary = effective_glossary(session, revision.document_id, source_language, body.locale)
        profile = {**profile, 'glossary_revision': glossary['revision'], 'glossary_entries': glossary['entries']}
        draft = create_draft(session, request.app.state.config, edition, revision, profile)
        payload = {**body.model_dump(), 'budget_micro': budget, 'draft_id': draft.id, 'source_revision_id': revision.id, 'source_hash': digest(source),
            'profile': profile, 'glossary_revision': glossary['revision'], 'glossary': glossary['entries'],
            'confirmed_at': now().isoformat(), 'origin': 'manual_ui'}
        job = enqueue(session, 'translate', payload, revision.document_id)
        job.budget_micro = budget
        return {**job_view(session, job), 'edition_id': edition.id, 'draft_id': draft.id}
    return command(session, request, body.model_dump(), execute, 202)


class Empty(StrictModel):
    pass


@router.post('/jobs/{job_id}/{action}', status_code=202)
def control(job_id: str, action: Literal['pause', 'resume', 'cancel'], body: Empty, request: Request, session=Session):
    def execute():
        job = get_entity(session, Job, job_id, lock=True)
        match_generation(job, request.headers.get('If-Match'))
        from packages.domain.workflow import TERMINAL_STATES
        require(job.status not in TERMINAL_STATES, 'JOB_TERMINAL')
        if action == 'resume':
            require(not job.progress.get('source_superseded'), 'SOURCE_STALE')
            require(job.status in ('paused', 'waiting_config', 'waiting_budget'), 'JOB_NOT_RESUMABLE')
            require(not session.scalar(select(Permit.id).where(Permit.job_id == job.id, Permit.state == 'unknown').limit(1)), 'OUTCOME_UNKNOWN')
            job.status = 'pending'
        else:
            job.control_epoch += 1
            job.status = 'paused' if action == 'pause' else 'cancelled'
        emit(session, job)
        return job_view(session, job)
    return command(session, request, {}, execute, 202)


class ResolveAttempt(StrictModel):
    decision: Literal['record_evidence', 'retry_accept_risk', 'stop']
    reason: str = Field(min_length=1, max_length=2000)
    budget_micro: int | None = Field(None, gt=0)
    duplicate_charge_risk_confirmed: bool = False


@router.post('/attempts/{attempt_id}/resolve')
def resolve_attempt(attempt_id: str, body: ResolveAttempt, request: Request, session=Session):
    def execute():
        lock_singleton(session)
        attempt = get_entity(session, Attempt, attempt_id, lock=True)
        job = get_entity(session, Job, attempt.job_id, lock=True)
        match_generation(job, request.headers.get('If-Match'))
        require(attempt.state == 'outcome_unknown', 'ATTEMPT_NOT_UNKNOWN')
        attempt.evidence = [*attempt.evidence, {'kind': body.decision, 'origin': 'manual_ui', 'reason': body.reason, 'at': now().isoformat()}]
        if body.decision == 'stop':
            job.status = 'cancelled'
            job.control_epoch += 1
        elif body.decision == 'retry_accept_risk':
            require(not job.progress.get('source_superseded'), 'SOURCE_STALE')
            require(body.duplicate_charge_risk_confirmed and (not cost_control_enabled(job.payload.get('profile', {})) or body.budget_micro is not None), 'DUPLICATE_CHARGE_CONFIRMATION_REQUIRED')
            require(job.payload.get('external_processing_confirmed') is True, 'EXTERNAL_PROCESSING_UNCONFIRMED')
            require(job.status == 'outcome_unknown', 'JOB_NOT_RESUMABLE')
            task = get_entity(session, Task, attempt.task_id, lock=True)
            require(task.attempts < 3 and task.status == 'outcome_unknown', 'ATTEMPT_LIMIT')
            # The old unknown Permit remains in the risk total. A new fence gets a new permit.
            task.status, job.status, job.budget_micro = 'pending', 'pending', checked_budget(job.payload.get('profile', {}), body.budget_micro)
        emit(session, job)
        return job_view(session, job)
    return command(session, request, body.model_dump(), execute)
