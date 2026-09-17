"""Database-owned dispatch state, shared by the settings page and maintenance CLI."""
from sqlalchemy import func, select

from packages.domain.db import lock_lifecycle, lock_singleton
from packages.domain.errors import require
from packages.domain.models import Attempt, Permit, Settings, now


def dispatch_view(session):
    settings = session.get(Settings, 'singleton')
    uncertain = list(session.scalars(select(Permit).where(Permit.state == 'unknown')))
    return {'generation': settings.generation, 'dispatch_disabled': settings.dispatch_disabled,
        'maintenance': settings.maintenance, 'unknown_attempts': len(uncertain),
        'unknown_micro': None if any(p.reserved_micro is None for p in uncertain) else sum(p.reserved_micro for p in uncertain),
        'inflight_requests': session.scalar(select(func.count()).select_from(Permit).where(Permit.state == 'reserved')),
        'unknown_tasks_resumed': 0}


def update_dispatch(session, disabled, *, accept_unknown_risk=False, reason=None, origin='manual_ui'):
    # Same ordering as authorize/settle: pausing and a new permit are serialized.
    lock_lifecycle(session)
    settings = lock_singleton(session)
    require(type(disabled) is bool, 'REQUEST_INVALID', status=422)
    if not disabled:
        uncertain = list(session.scalars(select(Permit).where(Permit.state == 'unknown').with_for_update()))
        require(not uncertain or (accept_unknown_risk is True and isinstance(reason, str) and reason.strip()), 'UNRESOLVED_BILLING_RISK')
        for permit in uncertain:
            attempt = session.get(Attempt, permit.attempt_id, with_for_update=True)
            attempt.evidence = [*attempt.evidence, {'kind': 'operator_risk_acknowledgment', 'origin': origin,
                'at': now().isoformat(), 'reason': reason.strip(), 'unknown_micro': permit.reserved_micro}]
    # Unknown tasks/permits, in-flight requests and provider credentials are untouched.
    settings.dispatch_disabled = disabled
    settings.generation += 1
    return dispatch_view(session)
