from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
import pytest
from packages.domain.models import Job,Task,Settings,Permit,new_id
from packages.jobs.queue import claim
from packages.billing.ledger import authorize,mark_unknown,settle,budget_totals
from packages.domain.errors import DomainError

pytestmark=pytest.mark.postgres


PRICE={'revision':'fixture-v1','currency':'USD','input_micro_per_million':1000000,'cached_input_micro_per_million':1000000,'output_micro_per_million':1000000,'output_includes_reasoning':True,'input_bound_rule':'utf8-byte-ceiling-v1'}


def setup(db):
    with db.transaction() as session:
        settings=session.get(Settings,'singleton');settings.instance_budget_micro=100;settings.dispatch_disabled=False
        for _ in range(2):
            job=Job(id=new_id('job'),stage='translate',budget_micro=100,payload={'external_processing_confirmed':True,'profile':{'price':PRICE},'source_hash':'a'*64})
            session.add(job);session.flush();session.add(Task(id=new_id('task'),job_id=job.id,kind='translate'))
    return claim(db),claim(db)


def test_two_jobs_only_one_wins_final_budget(database):
    db,_=database;a,b=setup(db)
    def reserve(lease):
        try:
            with db.transaction() as session:authorize(session,lease,80,PRICE)
            return True
        except DomainError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(reserve,[a,b]))==[False,True]
    with db.transaction() as session:assert budget_totals(session)['reserved_micro']==80


def test_unknown_risk_single_count_and_late_usage_idempotent(database):
    db,_=database;a,b=setup(db)
    with db.transaction() as session:authorize(session,a,80,PRICE)
    with db.transaction() as session:mark_unknown(session,a.attempt_id,'read_timeout')
    with db.transaction() as session:
        total=budget_totals(session);assert total['reserved_micro']==0 and total['unknown_micro']==80
    for _ in range(2):
        with db.transaction() as session:settle(session,a.attempt_id,{'input_tokens':10,'output_tokens':20},'request-fixture')
    with db.transaction() as session:
        total=budget_totals(session);assert total['actual_micro']==30 and total['unknown_micro']==0


@pytest.mark.parametrize('operation',['unknown','different_usage','release'])
def test_ledger_lock_refreshes_cached_state_after_other_transaction_settles(database,operation):
    from packages.domain.models import Attempt
    from packages.billing.ledger import release_unsent
    db,_=database;a,b=setup(db)
    with db.transaction() as session:authorize(session,a,80,PRICE)
    with db.transaction() as stale:
        permit=stale.scalar(select(Permit).where(Permit.attempt_id==a.attempt_id))
        attempt=stale.get(Attempt,a.attempt_id)
        assert permit.state=='reserved' and attempt.state=='dispatching'
        with db.transaction() as winner:settle(winner,a.attempt_id,{'input_tokens':10,'output_tokens':20},'settled-request')
        if operation=='unknown':mark_unknown(stale,a.attempt_id,'old timeout callback')
        else:
            with pytest.raises(DomainError) as error:
                if operation=='different_usage':settle(stale,a.attempt_id,{'input_tokens':1,'output_tokens':2},'other-request')
                else:release_unsent(stale,a.attempt_id,'old not-sent callback')
            assert error.value.code==('USAGE_EVIDENCE_CONFLICT' if operation=='different_usage' else 'PERMIT_NOT_RESERVED')
    with db.transaction() as session:
        final=session.scalar(select(Permit).where(Permit.attempt_id==a.attempt_id))
        assert final.state=='settled' and final.actual_micro==30
        assert session.get(Attempt,a.attempt_id).request_id=='settled-request'


@pytest.mark.parametrize('free', [False, True])
def test_three_simultaneous_dispatch_reservations_enforce_two_active_limit(database, free):
    from threading import Barrier
    from packages.domain.models import Attempt
    db, _ = database
    price = PRICE | {key: 0 for key in ('input_micro_per_million', 'cached_input_micro_per_million', 'output_micro_per_million')} if free else PRICE
    bound, charged = (0, 0) if free else (80, 30)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.instance_budget_micro, settings.dispatch_disabled = 1000, False
        for index in range(3):
            job = Job(id=f'cap_job{index}', stage='translate', budget_micro=1000,
                payload={'external_processing_confirmed': True, 'profile': {'price': price}})
            session.add(job)
            session.flush()
            session.add(Task(id=f'cap_task{index}', job_id=job.id, kind='translate'))
    leases = [claim(db) for _ in range(3)]
    barrier = Barrier(3)
    def reserve(lease):
        barrier.wait(timeout=10)
        try:
            with db.transaction() as session:
                authorize(session, lease, bound, price)
            return lease, 'authorized'
        except DomainError as error:
            return lease, error.code
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(reserve, leases))
    assert sorted(code for _, code in results) == ['INSTANCE_CONCURRENCY_LIMIT', 'authorized', 'authorized']
    waiting = next(lease for lease, code in results if code != 'authorized')
    completed = next(lease for lease, code in results if code == 'authorized')
    with db.transaction() as session:
        assert len(list(session.scalars(select(Permit)))) == 2
        assert session.get(Attempt, waiting.attempt_id).state == 'created'
        assert budget_totals(session)['reserved_micro'] == bound * 2
        settle(session, completed.attempt_id, {'input_tokens': 10, 'output_tokens': 20}, 'capacity-released')
    with db.transaction() as session:
        authorize(session, waiting, bound, price)
        assert len(list(session.scalars(select(Permit).where(Permit.state == 'reserved')))) == 2
        assert budget_totals(session) == {'actual_micro': charged, 'reserved_micro': bound * 2, 'unknown_micro': 0}


@pytest.mark.parametrize('invalid_bound', [0, -1, False])
def test_paid_profile_cannot_use_zero_or_invalid_reservation(database, invalid_bound):
    db, _ = database
    lease, _ = setup(db)
    with pytest.raises(DomainError) as error:
        with db.transaction() as session:
            authorize(session, lease, invalid_bound, PRICE)
    assert error.value.code == 'PRICE_BOUND_REQUIRED'
    with db.transaction() as session:
        assert session.scalar(select(Permit)) is None


def test_maintenance_still_classifies_late_unknown_and_settlement(database):
    from packages.domain.models import Attempt
    from packages.providers.contract import ProviderFailure
    from packages.translation.execution import retry_or_stop
    db, _ = database
    lease, _ = setup(db)
    with db.transaction() as session:
        authorize(session, lease, 80, PRICE)
    with db.transaction() as session:
        session.get(Settings, 'singleton').maintenance = True
    retry_or_stop(db, lease, ProviderFailure('READ_TIMEOUT', 'unknown'))
    with db.transaction() as session:
        assert session.get(Attempt, lease.attempt_id).state == 'outcome_unknown'
        assert budget_totals(session)['unknown_micro'] == 80
        assert session.get(Job, lease.job_id).status == 'outcome_unknown'
    assert claim(db) is None
    for _ in range(2):
        with db.transaction() as session:
            settle(session, lease.attempt_id, {'input_tokens': 10, 'output_tokens': 20}, 'late-confirmed-usage')
    with db.transaction() as session:
        assert budget_totals(session) == {'actual_micro': 30, 'reserved_micro': 0, 'unknown_micro': 0}
        assert session.get(Settings, 'singleton').maintenance
    assert claim(db) is None
