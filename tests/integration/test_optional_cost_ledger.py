"""Real PostgreSQL accounting without mandatory monetary controls."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select

from packages.billing.ledger import authorize, budget_totals, mark_unknown, release_unsent, settle
from packages.domain.errors import DomainError
from packages.domain.models import Attempt, Job, Permit, Settings, Task
from packages.jobs.queue import claim
from tests.integration.test_budget import PRICE

pytestmark = pytest.mark.postgres


def setup(db, count=1, price=None):
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.instance_budget_micro = 0; settings.dispatch_disabled = False
        for i in range(count):
            profile = {'cost_control_enabled': False}
            if price is not None: profile['price'] = price
            session.add(Job(id=f'off-job-{i}', stage='translate', budget_micro=None,
                payload={'profile': profile, 'external_processing_confirmed': True}))
            session.flush()
            session.add(Task(id=f'off-task-{i}', job_id=f'off-job-{i}', kind='translate'))
    return [claim(db) for _ in range(count)]


@pytest.mark.parametrize('usage', [None, {'input_tokens': 10, 'output_tokens': 20}, {'input_tokens': 'unknown'}])
def test_missing_price_or_usage_is_not_free_and_does_not_lose_attempt(database, usage):
    db, _ = database; lease, = setup(db)
    with db.transaction() as session:
        permit = authorize(session, lease, None, None)
        assert permit.reserved_micro is None and permit.price_snapshot['cost_control_enabled'] is False
        assert budget_totals(session)['reserved_micro'] is None
    for _ in range(2):
        with db.transaction() as session: settle(session, lease.attempt_id, usage, 'synthetic-known-response')
    with db.transaction() as session:
        permit = session.scalar(select(Permit)); attempt = session.get(Attempt, lease.attempt_id)
        assert permit.state == 'settled' and permit.actual_micro is None
        assert attempt.usage == usage and attempt.request_id == 'synthetic-known-response'
        assert budget_totals(session) == {'actual_micro': None, 'reserved_micro': 0, 'unknown_micro': 0}
        assert not session.get(Settings, 'singleton').dispatch_disabled


def test_optional_complete_prices_report_actual_cost_without_budget_enforcement(database):
    db, _ = database; lease, = setup(db, price=PRICE)
    with db.transaction() as session: authorize(session, lease, None, PRICE)
    with db.transaction() as session: settle(session, lease.attempt_id, {'input_tokens': 10, 'output_tokens': 20}, 'priced')
    with db.transaction() as session:
        assert budget_totals(session)['actual_micro'] == 30
        assert not session.get(Settings, 'singleton').dispatch_disabled


def test_unknown_network_outcome_still_has_single_permit_and_late_usage(database):
    db, _ = database; lease, = setup(db)
    with db.transaction() as session: authorize(session, lease, None, None)
    with db.transaction() as session: mark_unknown(session, lease.attempt_id, 'read_timeout')
    with db.transaction() as session:
        assert budget_totals(session)['unknown_micro'] is None
        assert session.get(Attempt, lease.attempt_id).state == 'outcome_unknown'
    with pytest.raises(DomainError):
        with db.transaction() as session: authorize(session, lease, None, None)
    for _ in range(2):
        with db.transaction() as session: settle(session, lease.attempt_id, {'input_tokens': 1, 'output_tokens': 2}, 'late')
    with db.transaction() as session:
        assert len(list(session.scalars(select(Permit)))) == 1
        assert budget_totals(session) == {'actual_micro': None, 'reserved_micro': 0, 'unknown_micro': 0}


def test_off_requests_still_enforce_two_concurrent_dispatches(database):
    db, _ = database; leases = setup(db, 3); barrier = Barrier(3)
    def dispatch(lease):
        barrier.wait(timeout=10)
        try:
            with db.transaction() as session: authorize(session, lease, None, None)
            return 'authorized'
        except DomainError as error: return error.code
    with ThreadPoolExecutor(3) as executor:
        assert sorted(executor.map(dispatch, leases)) == ['INSTANCE_CONCURRENCY_LIMIT', 'authorized', 'authorized']


def test_enabling_control_does_not_reprice_historical_unpriced_usage(database):
    db, _ = database; first, = setup(db)
    with db.transaction() as session: authorize(session, first, None, None)
    with db.transaction() as session:
        settle(session, first.attempt_id, {'input_tokens': 1, 'output_tokens': 2}, 'off')
        session.get(Settings, 'singleton').instance_budget_micro = 100
        session.add(Job(id='on-job', stage='translate', budget_micro=100,
            payload={'profile': {'price': PRICE}, 'external_processing_confirmed': True}))
        session.flush(); session.add(Task(id='on-task', job_id='on-job', kind='translate'))
    second = claim(db)
    with db.transaction() as session:
        authorize(session, second, 80, PRICE)
        assert budget_totals(session) == {'actual_micro': None, 'reserved_micro': 80, 'unknown_micro': 0}
        original = session.scalar(select(Permit).where(Permit.attempt_id == first.attempt_id))
        assert original.actual_micro is None and original.price_snapshot['cost_control_enabled'] is False
