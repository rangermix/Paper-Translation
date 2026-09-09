"""Upgrade a real schema-10 ledger without changing its controlled history."""
import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from packages.domain.db import Database
from packages.domain.models import Attempt,Job,Permit,Task
from packages.maintenance.__main__ import enable_dispatch
from tests.integration.test_budget import PRICE
from tests.support import legacy_insert

pytestmark=pytest.mark.postgres


def test_schema_11_preserves_old_budgets_and_supports_uncontrolled_unknown_amounts(database,monkeypatch):
    admin,cfg=database;schema='library_test_'+uuid.uuid4().hex
    with admin.engine.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
    monkeypatch.setenv('TEST_DATABASE_SCHEMA',schema);db=Database(cfg)
    try:
        db.migrate(10)
        with db.transaction() as session:
            legacy_insert(session,Job,id='old',stage='translate',status='outcome_unknown',budget_micro=100)
            legacy_insert(session,Task,id='old-task',job_id='old',kind='translate',status='outcome_unknown')
            legacy_insert(session,Attempt,id='old-attempt',task_id='old-task',job_id='old',fence=1,control_epoch=0,state='outcome_unknown')
            session.add(Permit(id='old-permit',attempt_id='old-attempt',job_id='old',control_epoch=0,price_snapshot=PRICE,reserved_micro=80,state='unknown'))
        with pytest.raises(IntegrityError),db.transaction() as session:
            session.execute(text("UPDATE jobs SET budget_micro=NULL WHERE id='old'"))
        db.migrate();db.ready()
        with db.transaction() as session:
            assert session.get(Job,'old').budget_micro==100
            old=session.get(Permit,'old-permit');assert old.reserved_micro==80 and old.price_snapshot==PRICE and old.state=='unknown'
            session.add(Job(id='off',stage='translate',status='outcome_unknown',budget_micro=None));session.flush()
            session.add(Task(id='off-task',job_id='off',kind='translate',status='outcome_unknown'));session.flush()
            session.add(Attempt(id='off-attempt',task_id='off-task',job_id='off',fence=1,control_epoch=0,state='outcome_unknown'));session.flush()
            session.add(Permit(id='off-permit',attempt_id='off-attempt',job_id='off',control_epoch=0,price_snapshot={'cost_control_enabled':False},reserved_micro=None,state='unknown'))
        result=enable_dispatch(db,accept_unknown_risk=True,reason='Synthetic migration test: explicitly retain both unknown attempts')
        assert result['unknown_micro'] is None and result['unknown_tasks_resumed']==0
        with db.transaction() as session:
            assert session.get(Job,'off').budget_micro is None
            assert session.get(Job,'old').budget_micro==100
            assert all(row.state=='unknown' for row in session.scalars(select(Permit)))
    finally:
        db.engine.dispose()
        with admin.engine.begin() as connection:connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
