"""One explicit, durable connection test using the production wire adapters."""
import time

from sqlalchemy import select

from packages.billing.ledger import authorize, budget_totals, mark_unknown, release_unsent, settle
from packages.billing.price import reserve_cost
from packages.domain.config import provider_profile
from packages.domain.db import lock_lifecycle
from packages.domain.errors import DomainError
from packages.domain.models import Job, now
from packages.jobs.queue import assert_current, emit, finish
from .contract import ProviderFailure, normalize_request_id, validate_output
from .native import NativeProvider
from .openai_responses import OpenAIResponses
from .registry import request_body
from .settings import resolve_provider_credentials

TEST_UNIT = {'unit_id': 'connection-test', 'source_language': 'en', 'target_locale': 'zh-Hans',
    'source_inline': [{'type': 'text', 'text': 'Hello.'}], 'protected_atoms': {}, 'context': {}}


def test_profile(profile):
    # The saved profile/key binding is unchanged. Only this request is smaller.
    return {**profile, 'max_input_tokens': min(profile['max_input_tokens'], 8192),
        'max_output_tokens': min(profile['max_output_tokens'], 256)}


def provider_for(profile):
    endpoint, protocol, auth_mode, key_file = resolve_provider_credentials(profile)
    if protocol == 'local_translation':
        from .local_translation import LocalTranslation
        return LocalTranslation()
    if protocol in ('gemini_interactions', 'claude_messages'):
        return NativeProvider(profile, key_file, timeout=30)
    return OpenAIResponses(key_file, endpoint=endpoint, api_protocol=protocol, auth_mode=auth_mode, timeout=30)


def latest_test(session, profile_hash):
    return session.scalar(select(Job).where(Job.stage == 'provider_test',
        Job.payload['profile_hash'].astext == profile_hash).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))


def has_unknown_test(session, profile_hash):
    from packages.domain.models import Permit
    return session.scalar(select(Permit.id).join(Job, Job.id == Permit.job_id).where(
        Job.stage == 'provider_test', Permit.state == 'unknown',
        Job.payload['profile_hash'].astext == profile_hash).limit(1)) is not None


def test_view(session, job):
    if job is None:
        return None
    return {'id': job.id, 'profile_hash': job.payload['profile_hash'], 'status': job.status,
        'code': (job.error or {}).get('code'), 'created_at': job.created_at.isoformat(),
        'completed_at': job.progress.get('completed_at'), 'elapsed_ms': job.progress.get('elapsed_ms'),
        **budget_totals(session, job.id)}


def execute_test(db, cfg, lease):
    started = time.monotonic()

    def stop(code, outcome=None):
        with db.transaction() as session:
            # Settings commands take lifecycle before the billing singleton.
            # Late accounting uses the same order even after control changes.
            lock_lifecycle(session, allow_maintenance=True)
            if outcome == 'unknown': mark_unknown(session, lease.attempt_id, code)
            elif outcome in ('not_sent', 'not_executed'): release_unsent(session, lease.attempt_id, code)
            try:
                job, task = assert_current(session, lease)
            except DomainError as exc:
                if exc.code in ('CONTROL_CHANGED', 'FENCE_EXPIRED'): return
                raise
            job.status = task.status = 'outcome_unknown' if outcome == 'unknown' else 'failed'
            job.error = {'code': code}
            job.progress = {'completed_at': now().isoformat(), 'elapsed_ms': int((time.monotonic() - started) * 1000)}
            emit(session, job)

    with db.transaction() as session:
        job, _ = assert_current(session, lease)
        profile = job.payload['profile']
    if provider_profile() != profile:
        stop('PROVIDER_PROFILE_STALE'); return
    try:
        bounded = test_profile(profile)
        request_body([TEST_UNIT], bounded, [])
        provider = provider_for(profile)
        if profile.get('api_protocol') == 'local_translation':
            def check_current():
                with db.transaction() as session:
                    assert_current(session, lease)
                if provider_profile() != profile:
                    raise ProviderFailure('PROVIDER_PROFILE_STALE', 'not_sent')
            provider.prepare(profile, check_current)
    except (ProviderFailure, ValueError):
        stop('PROVIDER_CONFIG'); return
    try:
        with db.transaction() as session:
            # Serialize with settings saves; a queued test cannot adopt a new key.
            assert_current(session, lease)
            if provider_profile() != profile:
                raise DomainError('PROVIDER_PROFILE_STALE')
            authorize(session, lease, reserve_cost(bounded), profile.get('price'))
    except DomainError as exc:
        stop(exc.code); return
    try:
        from packages.jobs.history import record_api_model
        record_api_model(db, lease, profile)
        result = provider.translate([TEST_UNIT], bounded, [])
    except ProviderFailure as failure:
        code = {401: 'PROVIDER_AUTH', 403: 'PROVIDER_FORBIDDEN', 404: 'PROVIDER_ENDPOINT_OR_MODEL',
            400: 'PROVIDER_REQUEST_REJECTED', 422: 'PROVIDER_REQUEST_REJECTED'}.get(failure.http_status, failure.code)
        stop(code, failure.outcome); return
    record_api_model(db, lease, profile, result)
    if result.get('failure_code') == 'PROVIDER_MODEL_MISMATCH':
        stop('PROVIDER_MODEL_MISMATCH', 'unknown'); return
    try:
        # Do not retain provider-generated text, error bodies or arbitrary metadata.
        tracking = normalize_request_id(result.get('request_id'))
        with db.transaction() as session:
            settle(session, lease.attempt_id, result.get('usage'), tracking)
    except ValueError:
        stop('USAGE_MISSING', 'unknown'); return
    try:
        if result.get('failure_code'): raise ProviderFailure(result['failure_code'])
        if result.get('refusal'): raise ProviderFailure('PROVIDER_REFUSAL')
        if result.get('status') != 'completed': raise ProviderFailure('PROVIDER_TRUNCATED')
        validate_output(result.get('output_text'), [TEST_UNIT])
    except ProviderFailure as failure:
        stop(failure.code); return
    with db.transaction() as session:
        job, _ = assert_current(session, lease)
        job.error = None
        job.progress = {'completed_at': now().isoformat(), 'elapsed_ms': int((time.monotonic() - started) * 1000)}
        finish(session, lease, {'connection_verified': True})
