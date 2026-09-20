"""Independent PostgreSQL review of maintenance unlock; never calls a Provider."""
import pytest
from sqlalchemy import select

from packages.billing.ledger import authorize, budget_totals
from packages.domain.errors import DomainError
from packages.domain.models import Attempt, Job, Permit, Settings, Task
from packages.jobs.queue import claim
from packages.maintenance.__main__ import enable_dispatch
from tests.integration.test_budget import PRICE

pytestmark=pytest.mark.postgres


def test_risk_ack_preserves_unknown_and_only_allows_other_work_within_remaining_budget(database):
    db,_=database
    with db.transaction() as session:
        settings=session.get(Settings,'singleton');settings.instance_budget_micro=100
        settings.dispatch_disabled=True
        session.add(Job(id='old_uncertain',stage='translate',status='outcome_unknown',budget_micro=100));session.flush()
        session.add(Task(id='old_task',job_id='old_uncertain',kind='translate',status='outcome_unknown',attempts=1,fence=1));session.flush()
        session.add(Attempt(id='old_attempt',task_id='old_task',job_id='old_uncertain',fence=1,control_epoch=0,state='outcome_unknown'));session.flush()
        session.add(Permit(id='old_permit',attempt_id='old_attempt',job_id='old_uncertain',control_epoch=0,price_snapshot=PRICE,reserved_micro=80,state='unknown'))
        session.add(Job(id='new_approved',stage='translate',budget_micro=100,payload={
            'external_processing_confirmed':True,'profile':{'price':PRICE}}));session.flush()
        session.add(Task(id='new_task',job_id='new_approved',kind='translate'))
    lease=claim(db)
    assert lease.job_id=='new_approved'
    with pytest.raises(DomainError,match='Dispatch disabled'):
        with db.transaction() as session:authorize(session,lease,20,PRICE)
    for confirmed,reason in ((False,'inspected'),(True,None),(True,'  ')):
        with pytest.raises(DomainError,match='Unresolved billing risk'):
            enable_dispatch(db,accept_unknown_risk=confirmed,reason=reason)
    result=enable_dispatch(db,accept_unknown_risk=True,reason='Independent agent checked uncertainty; retain the full 80-micro risk.')
    assert result['unknown_micro']==80 and result['unknown_tasks_resumed']==0
    with pytest.raises(DomainError,match='Budget paused'):
        with db.transaction() as session:authorize(session,lease,21,PRICE)
    with db.transaction() as session:authorize(session,lease,20,PRICE)
    with db.transaction() as session:
        assert budget_totals(session)=={'actual_micro':0,'reserved_micro':20,'unknown_micro':80}
        old=session.get(Permit,'old_permit');attempt=session.get(Attempt,'old_attempt')
        assert old.state=='unknown' and old.actual_micro is None
        assert attempt.state=='outcome_unknown' and attempt.usage is None and attempt.request_id is None
        assert attempt.evidence[-1]['kind']=='operator_risk_acknowledgment'
        assert attempt.evidence[-1]['origin']=='maintenance_cli'
        assert session.get(Task,'old_task').status=='outcome_unknown'
        assert session.get(Job,'old_uncertain').status=='outcome_unknown'
        assert len(list(session.scalars(select(Permit))))==2
    assert claim(db) is None
