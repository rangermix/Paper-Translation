from sqlalchemy import select
from packages.domain.db import lock_lifecycle, lock_singleton
from packages.domain.errors import require
from packages.domain.models import Attempt,Permit,Job,Task,new_id
from packages.jobs.queue import assert_current,emit
from .price import actual_cost,validate_price,cost_control_enabled


def budget_totals(session,job_id=None,*,controlled_only=False):
    query=select(Permit)
    if job_id:query=query.where(Permit.job_id==job_id)
    result={'actual_micro':0,'reserved_micro':0,'unknown_micro':0}
    for permit in session.scalars(query):
        if controlled_only and not cost_control_enabled(permit.price_snapshot): continue
        field = {'settled': 'actual_micro', 'unknown': 'unknown_micro', 'reserved': 'reserved_micro'}.get(permit.state)
        if field is None: continue
        amount = permit.actual_micro if permit.state == 'settled' else permit.reserved_micro
        result[field] = None if amount is None or result[field] is None else result[field] + amount
    return result


def dispatch_profile(job, task):
    if task.payload.get('phase') == 'preparation' and job.payload.get('preparation_options', {}).get('mode') == 'local':
        profile = job.payload.get('analysis_profile', {})
        from packages.providers.local_analysis import profile as local_profile
        require(profile == local_profile(profile.get('model_id')), 'PROVIDER_PROFILE_STALE')
        return profile
    return job.payload.get('profile', {})


def authorize(session,lease,reserved_micro,price):
    lock_lifecycle(session);settings=lock_singleton(session)
    job,task=assert_current(session,lease)
    require(not settings.dispatch_disabled,'DISPATCH_DISABLED')
    require(job.payload.get('external_processing_confirmed') is True,'EXTERNAL_PROCESSING_UNCONFIRMED')
    profile = dispatch_profile(job, task)
    require(profile.get('price')==price,'PRICE_SNAPSHOT_STALE')
    controlled = cost_control_enabled(profile)
    if controlled:
        validate_price(price)
        free = all(price[key] == 0 for key in ('input_micro_per_million', 'cached_input_micro_per_million', 'output_micro_per_million'))
        require(type(reserved_micro) is int and (reserved_micro > 0 or (reserved_micro == 0 and free)), 'PRICE_BOUND_REQUIRED')
    else:
        require(reserved_micro is None, 'PRICE_BOUND_REQUIRED')
    existing=session.scalar(select(Permit).where(Permit.attempt_id==lease.attempt_id))
    require(existing is None,'DISPATCH_ALREADY_AUTHORIZED')
    active=session.scalars(select(Permit).where(Permit.state=='reserved')).all()
    require(len(active)<2,'INSTANCE_CONCURRENCY_LIMIT',retryable=True)
    if controlled:
        for limit,totals in [(settings.instance_budget_micro,budget_totals(session,controlled_only=True)),(job.budget_micro,budget_totals(session,job.id,controlled_only=True))]:
            require(type(limit) is int and all(value is not None for value in totals.values()) and limit-sum(totals.values())>=reserved_micro,'BUDGET_PAUSED')
    attempt=session.get(Attempt,lease.attempt_id)
    require(attempt.state=='created','ATTEMPT_ALREADY_SENT')
    attempt.state='dispatching'
    snapshot = {**(price or {}), 'cost_control_enabled': controlled}
    permit=Permit(id=new_id('permit'),attempt_id=attempt.id,job_id=job.id,control_epoch=lease.control_epoch,price_snapshot=snapshot,reserved_micro=reserved_micro,state='reserved')
    session.add(permit);session.flush();return permit


def mark_unknown(session,attempt_id,reason):
    lock_singleton(session)
    attempt=session.scalar(select(Attempt).where(Attempt.id==attempt_id).with_for_update().execution_options(populate_existing=True))
    permit=session.scalar(select(Permit).where(Permit.attempt_id==attempt_id).with_for_update().execution_options(populate_existing=True))
    require(permit is not None,'PERMIT_MISSING')
    if permit.state=='settled':return
    permit.state='unknown';attempt.state='outcome_unknown'
    attempt.evidence=attempt.evidence+[{'kind':'uncertainty','reason':reason}]


def release_unsent(session,attempt_id,reason):
    lock_singleton(session)
    attempt=session.scalar(select(Attempt).where(Attempt.id==attempt_id).with_for_update().execution_options(populate_existing=True))
    permit=session.scalar(select(Permit).where(Permit.attempt_id==attempt_id).with_for_update().execution_options(populate_existing=True))
    require(permit and permit.state=='reserved','PERMIT_NOT_RESERVED')
    permit.state='released';attempt.state='not_executed';attempt.evidence=attempt.evidence+[{'kind':'not_executed','reason':reason}]


def settle(session,attempt_id,usage,request_id):
    lock_singleton(session)
    attempt=session.scalar(select(Attempt).where(Attempt.id==attempt_id).with_for_update().execution_options(populate_existing=True))
    permit=session.scalar(select(Permit).where(Permit.attempt_id==attempt_id).with_for_update().execution_options(populate_existing=True))
    require(permit is not None,'PERMIT_MISSING')
    controlled = cost_control_enabled(permit.price_snapshot)
    if controlled:
        cost=actual_cost(permit.price_snapshot,usage)
    else:
        try: cost=actual_cost(permit.price_snapshot,usage)
        except ValueError: cost=None
    if permit.state=='settled':
        require(attempt.usage==usage and attempt.request_id==request_id and permit.actual_micro==cost,'USAGE_EVIDENCE_CONFLICT')
        return permit
    require(permit.state in {'reserved','unknown'},'PERMIT_NOT_SETTLEABLE')
    permit.state='settled';permit.actual_micro=cost;attempt.usage=usage;attempt.request_id=request_id;attempt.state='settled'
    if controlled and cost>permit.reserved_micro:
        settings=lock_singleton(session)
        if not settings.dispatch_disabled:
            settings.dispatch_disabled=True
            settings.generation+=1
        attempt.evidence=attempt.evidence+[{'kind':'reservation_exceeded','actual_micro':cost,'reserved_micro':permit.reserved_micro}]
    return permit
