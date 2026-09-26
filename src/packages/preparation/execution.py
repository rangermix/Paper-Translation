"""One accounted preparation attempt, then fenced translation fan-out."""
from copy import deepcopy

from sqlalchemy import select

from packages.billing.ledger import authorize, dispatch_profile, settle
from packages.billing.price import reserve_cost, validate_profile
from packages.domain.config import provider_profile
from packages.domain.db import get_entity
from packages.domain.errors import DomainError, require
from packages.domain.models import Attempt, Candidate, Document, Draft, Task, new_id
from packages.ir import digest
from packages.jobs.queue import assert_current, emit, finish
from packages.providers.contract import ProviderFailure
from packages.translation.languages import public_profile
from .analysis import INSTRUCTIONS, SCHEMA, make_request, request_body, validate_analysis
from .collection import collect
from .context import freeze, translation_context_mode


def save_preparation(session, job, draft, pack, kind):
    job.payload = job.payload | {'preparation': pack}
    job.progress = job.progress | {'preparation_status': 'completed',
        'preparation_revision': pack['revision'], 'preparation_warnings': pack['warnings'],
        'preparation_terms': sum(bool(c.get('target')) for c in pack['concepts'])}
    if kind == 'candidate':
        candidate = get_entity(session, Candidate, job.payload['candidate_id'], lock=True)
        candidate.base = candidate.base | {'preparation': pack}
    else:
        draft = get_entity(session, Draft, draft.id, lock=True)
        draft.profile = draft.profile | {'preparation': pack}
        draft.generation += 1
        draft.qa_id = None


def prepare_or_schedule(session, job, draft, source, lease):
    """Called by the existing planning transaction. Returns True if work deferred."""
    mode = job.payload.get('preparation_options', {}).get('mode', 'off')
    if mode == 'off' or lease.kind == 'semantic_review' or job.payload.get('preparation'):
        return False
    collection = collect(source)
    args = (collection, job.payload['locale'], job.payload.get('glossary_revision', 'empty-v1'), job.payload.get('glossary', []))
    context_mode = translation_context_mode(job.payload['profile'])
    if mode == 'extractive':
        save_preparation(session, job, draft, freeze(*args, context_mode=context_mode), lease.kind)
        return False
    profile = validate_profile(job.payload['analysis_profile'] if mode == 'local' else job.payload['profile'])
    require(profile.get('api_protocol') != 'local_translation', 'PREPARATION_ANALYST_REQUIRED')
    try:
        request = make_request(collection, job.payload['locale'], profile, job.payload.get('glossary', []))
    except ProviderFailure as failure:
        if failure.code not in {'UNIT_TOO_LARGE', 'ANALYSIS_TOO_LARGE'}:
            raise
        save_preparation(session, job, draft, freeze(*args, warnings=['PREPARATION_CONTEXT_LIMIT'], context_mode=context_mode), lease.kind)
        return False
    if not request['content']['evidence']:
        save_preparation(session, job, draft, freeze(*args, warnings=['PREPARATION_NO_EVIDENCE'], context_mode=context_mode), lease.kind)
        return False
    job.payload = job.payload | {'preparation_collection': collection}
    job.progress = job.progress | {'preparation_status': 'pending', 'preparation_requests': 0}
    session.add(Task(id=new_id('task'), job_id=job.id, kind=lease.kind,
                     payload={'phase': 'preparation', 'request': request}))
    session.flush()
    finish(session, lease, {'preparation_scheduled': True})
    return True


def _commit(db, cfg, lease, result):
    from packages.translation.execution import snapshot
    with db.transaction() as session:
        job, task, draft, source = snapshot(session, cfg, lease, allow_pending=True)
        collection = deepcopy(job.payload['preparation_collection'])
        collection['concepts'] += result.get('additional_concepts', [])
        pack = freeze(collection, job.payload['locale'], job.payload.get('glossary_revision', 'empty-v1'),
                      job.payload.get('glossary', []), proposals=result.get('proposals'), summary=result.get('summary'),
                      analysis={'request_hash': digest(task.payload['request']), 'profile': public_profile(dispatch_profile(job, task))},
                      warnings=result.get('warnings'), context_mode=translation_context_mode(job.payload['profile']))
        save_preparation(session, job, draft, pack, lease.kind)
        session.add(Task(id=new_id('task'), job_id=job.id, kind=lease.kind, payload={'phase': 'fanout'}))
        session.flush()
        finish(session, lease, {'preparation_revision': pack['revision']})


def execute_preparation(db, cfg, lease, provider=None):
    from packages.translation.execution import snapshot, wait_without_dispatch, retry_or_stop
    request = lease.payload['request']
    request_hash = digest(request)
    with db.transaction() as session:
        job, task, draft, source = snapshot(session, cfg, lease)
        profile = dispatch_profile(job, task)
        translation_profile = job.payload['profile']
        checkpoint = next((e['result'] for a in session.scalars(select(Attempt).where(Attempt.task_id == task.id, Attempt.state == 'settled'))
                           for e in a.evidence if e.get('kind') == 'validated_preparation' and e.get('request_hash') == request_hash), None)
    if checkpoint is not None:
        _commit(db, cfg, lease, checkpoint)
        return
    managed = provider is None
    if managed:
        if provider_profile() != public_profile(translation_profile):
            wait_without_dispatch(db, lease, 'PROVIDER_PROFILE_STALE'); return
        try:
            if profile.get('api_protocol') == 'local_analysis':
                from packages.providers.local_analysis import LocalAnalysis
                provider = LocalAnalysis()
                def check_current():
                    with db.transaction() as session:
                        snapshot(session, cfg, lease)
                    if provider_profile() != public_profile(translation_profile):
                        raise ProviderFailure('PROVIDER_PROFILE_STALE', 'not_sent')
                provider.prepare(profile, check_current)
            else:
                from packages.providers.settings import resolve_provider_credentials
                endpoint, protocol, auth_mode, key = resolve_provider_credentials(profile)
                if protocol in {'gemini_interactions', 'claude_messages'}:
                    from packages.providers.native import NativeProvider
                    provider = NativeProvider(profile, key)
                else:
                    from packages.providers.openai_responses import OpenAIResponses
                    provider = OpenAIResponses(key, endpoint=endpoint, api_protocol=protocol, auth_mode=auth_mode)
        except ProviderFailure as failure:
            wait_without_dispatch(db, lease, failure.code); return
    try:
        request_body(request, profile)
        with db.transaction() as session:
            snapshot(session, cfg, lease)
            if managed and provider_profile() != public_profile(translation_profile):
                raise ProviderFailure('PROVIDER_PROFILE_STALE', 'not_sent')
            authorize(session, lease, reserve_cost(profile), profile.get('price'))
            job, _ = assert_current(session, lease)
            job.progress = job.progress | {'requests': job.progress.get('requests', 0) + 1,
                'preparation_requests': job.progress.get('preparation_requests', 0) + 1, 'preparation_status': 'running'}
            emit(session, job)
    except DomainError as error:
        if error.code in {'BUDGET_PAUSED', 'INSTANCE_CONCURRENCY_LIMIT', 'DISPATCH_DISABLED'}:
            wait_without_dispatch(db, lease, error.code); return
        raise
    except (ProviderFailure, ValueError) as error:
        wait_without_dispatch(db, lease, getattr(error, 'code', 'PROVIDER_CONFIG')); return
    from packages.jobs.history import record_api_model
    record_api_model(db, lease, profile)
    try:
        response = (provider.analyze(request['content'], profile, INSTRUCTIONS, SCHEMA)
                    if profile.get('api_protocol') == 'local_analysis' else provider.translate([request], profile, []))
    except ProviderFailure as failure:
        retry_or_stop(db, lease, failure, cfg); return
    record_api_model(db, lease, profile, response)
    reported, expected = response.get('response_model'), profile['model_id']
    if profile.get('api_protocol') == 'gemini_interactions':
        reported = reported.removeprefix('models/') if isinstance(reported, str) else reported
        expected = expected.removeprefix('models/')
    if reported != expected or response.get('failure_code') == 'PROVIDER_MODEL_MISMATCH':
        retry_or_stop(db, lease, ProviderFailure('PROVIDER_MODEL_MISMATCH', 'unknown'), cfg); return
    try:
        with db.transaction() as session:
            settle(session, lease.attempt_id, response.get('usage'), response.get('request_id'))
    except ValueError:
        retry_or_stop(db, lease, ProviderFailure('USAGE_MISSING', 'unknown'), cfg); return
    if response.get('status') == 'unsupported' or response.get('failure_code') in {'PROVIDER_CONFIG', 'PROVIDER_UNSUPPORTED_RESPONSE'}:
        retry_or_stop(db, lease, ProviderFailure(response.get('failure_code') or 'PROVIDER_UNSUPPORTED_RESPONSE'), cfg)
        return
    try:
        if response.get('failure_code'):
            raise ProviderFailure(response['failure_code'])
        if response.get('status') != 'completed' or response.get('refusal'):
            raise ProviderFailure('PREPARATION_INCOMPLETE')
        result = validate_analysis(response['output_text'], request)
    except ProviderFailure as error:
        # Known settled but unusable optional content is a warning. Unknown
        # transport and usage outcomes were handled above and never reach here.
        result = {'summary': [], 'proposals': {}, 'additional_concepts': [], 'warnings': [error.code]}
    with db.transaction() as session:
        document = session.scalar(select(Document).where(Document.id == lease.document_id).with_for_update().execution_options(populate_existing=True))
        if document is None or document.deleted_at is not None:
            return
        attempt = session.get(Attempt, lease.attempt_id)
        attempt.output_hash = digest(result)
        attempt.evidence = attempt.evidence + [{'kind': 'validated_preparation', 'request_hash': request_hash, 'result': result}]
    try:
        _commit(db, cfg, lease, result)
    except DomainError as error:
        if error.code not in {'CONTROL_CHANGED', 'FENCE_EXPIRED', 'DOCUMENT_DELETED', 'MAINTENANCE', 'SOURCE_STALE'}:
            raise
