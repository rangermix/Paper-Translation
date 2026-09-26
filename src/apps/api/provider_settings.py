"""Secret writes intentionally bypass DB-backed command/idempotency receipts."""
from typing import Literal
from fastapi import APIRouter, Request
from pydantic import Field, SecretStr
from sqlalchemy import select

from packages.domain.db import lock_lifecycle, lock_singleton
from packages.domain.errors import DomainError, require
from packages.providers.settings import save_configuration
from .common import StrictModel
from .library import Session

router = APIRouter(prefix='/api/v1')


@router.get('/settings/local-models')
def local_models(purpose: Literal['translation', 'analysis'] = 'translation'):
    import httpx
    from packages.local_models.catalog import ENDPOINT, public_models
    from .common import response
    try:
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            result = client.get(ENDPOINT.rsplit('/v1/', 1)[0] + '/models',
                                **({'params': {'purpose': purpose}} if purpose != 'translation' else {}))
            result.raise_for_status()
            states = {row['id']: row for row in result.json()['models']}
        # Metadata is always our pinned catalog; the service reports status only.
        return response({'models': [{**m, **{k: states.get(m['id'], {}).get(k) for k in
            ('status', 'code', 'backend', 'downloaded_bytes', 'total_bytes')}} for m in public_models(purpose=purpose)]})
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return response({'models': [{**m, 'status': 'unavailable', 'code': 'LOCAL_MODEL_SERVICE_UNAVAILABLE'} for m in public_models(purpose=purpose)]})


@router.post('/settings/local-models/{identifier}/prepare', status_code=202)
def prepare_local_model(identifier: str, request: Request, session=Session):
    import httpx
    from packages.local_models.catalog import ENDPOINT, get_model
    from .common import command
    try:
        model = get_model(identifier)
    except ValueError:
        raise DomainError('LOCAL_MODEL_UNKNOWN', status=404) from None
    def execute():
        lock_lifecycle(session)
        try:
            with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
                result = client.post(ENDPOINT.rsplit('/v1/', 1)[0] + '/models/' + model['id'] + '/prepare')
                result.raise_for_status()
                state = result.json()
            return {k: state[k] for k in ('status', 'code', 'downloaded_bytes', 'total_bytes') if k in state}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DomainError('LOCAL_MODEL_SERVICE_UNAVAILABLE', status=503) from None
    return command(session, request, {}, execute, 202)


class ProviderSettings(StrictModel):
    profile: dict
    api_key: SecretStr | None = None
    clear_api_key: bool = False


@router.put('/settings/provider')
def put_provider_settings(body: ProviderSettings, request: Request, session=Session):
    # Only guards are transactional. No body, key or secret-derived hash ever
    # enters SQL, Idempotency.response, an ORM entity or the content directory.
    lock_lifecycle(session)
    try:
        public = save_configuration(body.profile, body.api_key.get_secret_value() if body.api_key else None,
            body.clear_api_key, request.headers.get('If-Match'), request.headers.get('Idempotency-Key'))
    except (OSError, ValueError, TypeError, KeyError):
        raise DomainError('PROVIDER_CONFIG_STORAGE', status=503) from None
    from .catalog import provider_view
    # Keep costs/capabilities shape compatible, but retain the original public
    # result/generation when replaying a completed idempotent operation.
    from .common import response
    return response(provider_view(session, public))


class ProviderTest(StrictModel):
    profile_hash: str = Field(pattern='^[a-f0-9]{64}$')
    external_processing_confirmed: bool
    budget_micro: int | None = Field(None, gt=0, le=9007199254740991)
    duplicate_charge_risk_confirmed: bool = False


@router.post('/settings/provider/test', status_code=202)
def test_provider(body: ProviderTest, request: Request, session=Session):
    from packages.billing.price import cost_control_enabled, reserve_cost
    from packages.domain.config import provider_profile
    from packages.domain.models import Job
    from packages.providers.connection import TEST_UNIT, has_unknown_test, test_profile, test_view
    from packages.providers.registry import request_body
    from packages.providers.settings import configuration_view
    from .common import command
    from .library import enqueue

    def execute():
        settings = lock_singleton(session)
        require(not settings.dispatch_disabled, 'DISPATCH_DISABLED')
        public = configuration_view()
        require(request.headers.get('If-Match') is not None, 'PRECONDITION_REQUIRED', status=428)
        require(request.headers['If-Match'] == f'"{public["generation"]}"', 'PRECONDITION_FAILED', status=412)
        require(body.profile_hash == public['profile_hash'], 'PROVIDER_PROFILE_STALE')
        require(public.get('dispatch_configuration_ready'), 'PROVIDER_CONFIG')
        require(body.external_processing_confirmed, 'EXTERNAL_PROCESSING_UNCONFIRMED')
        profile = provider_profile()
        from packages.ir import digest
        require(digest(profile) == body.profile_hash, 'PROVIDER_PROFILE_STALE')
        try:
            bounded = test_profile(profile)
            request_body([TEST_UNIT], bounded, [])
            reserve = reserve_cost(bounded)
        except ValueError:
            raise DomainError('PROVIDER_TEST_LIMITS', status=422) from None
        controlled = cost_control_enabled(profile)
        require(not controlled or (body.budget_micro is not None and body.budget_micro >= reserve), 'BUDGET_PAUSED')
        active = session.scalar(select(Job.id).where(Job.stage == 'provider_test',
            Job.status.in_(('pending', 'running', 'paused', 'waiting_config', 'waiting_budget'))).limit(1))
        require(active is None, 'PROVIDER_TEST_IN_PROGRESS')
        require(not has_unknown_test(session, body.profile_hash) or body.duplicate_charge_risk_confirmed, 'DUPLICATE_CHARGE_CONFIRMATION_REQUIRED')
        payload = {**body.model_dump(), 'profile': profile, 'origin': 'manual_ui'}
        job = enqueue(session, 'provider_test', payload)
        job.budget_micro = body.budget_micro if controlled else None
        return test_view(session, job)
    return command(session, request, body.model_dump(), execute, 202)


@router.get('/settings/provider/test/{job_id}')
def get_provider_test(job_id: str, session=Session):
    from packages.domain.models import Job
    from packages.providers.connection import test_view
    from .common import response
    job = session.get(Job, job_id)
    require(job is not None and job.stage == 'provider_test', 'NOT_FOUND', status=404)
    return response(test_view(session, job))
