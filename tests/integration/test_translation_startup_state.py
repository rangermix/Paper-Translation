import pytest
from sqlalchemy import select

from packages.domain.models import Attempt, Job, Permit, Settings, Task
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.providers.contract import ProviderFailure
from packages.translation.execution import execute_translation, wait_without_dispatch
from tests.integration.test_translation_execution import setup_library
from workers.main import execute


@pytest.mark.parametrize('code,status', [('DISPATCH_DISABLED', 'waiting_config'),
    ('PROVIDER_PROFILE_STALE', 'waiting_config'), ('BUDGET_PAUSED', 'waiting_budget'),
    ('INSTANCE_CONCURRENCY_LIMIT', 'pending')])
def test_sibling_configuration_wait_is_not_overwritten_as_control_failure(database, monkeypatch, code, status):
    db, cfg = database
    setup_library(db, cfg)
    provider = FakeProvider()
    execute_translation(db, cfg, claim(db), provider)
    first, second = claim(db), claim(db)
    assert first and second
    wait_without_dispatch(db, first, code)
    monkeypatch.setattr('packages.translation.execution.execute_translation',
        lambda db, cfg, lease: execute_translation(db, cfg, lease, provider))
    execute(db, cfg, second)
    with db.transaction() as session:
        job = session.get(Job, 'job')
        assert job.status == status and job.error['code'] == code
        for lease in (first, second):
            assert session.get(Task, lease.task_id).status == 'pending'
            assert session.get(Task, lease.task_id).attempts == 0
            attempt = session.get(Attempt, lease.attempt_id)
            assert attempt.state == 'not_executed' and attempt.finished_at is not None
        assert session.scalar(select(Permit)) is None
    assert provider.calls == []


def test_true_cancellation_remains_cancelled(database, monkeypatch):
    db, cfg = database
    setup_library(db, cfg)
    provider = FakeProvider()
    execute_translation(db, cfg, claim(db), provider)
    lease = claim(db)
    with db.transaction() as session:
        job = session.get(Job, 'job'); job.status = 'cancelled'; job.control_epoch += 1
    monkeypatch.setattr('packages.translation.execution.execute_translation',
        lambda db, cfg, current: execute_translation(db, cfg, current, provider))
    execute(db, cfg, lease)
    with db.transaction() as session:
        assert session.get(Job, 'job').status == 'cancelled'
        assert session.scalar(select(Permit)) is None
    assert provider.calls == []


def test_sibling_unknown_outcome_remains_resolvable(database, monkeypatch):
    db, cfg = database
    setup_library(db, cfg)
    provider = FakeProvider([ProviderFailure('PROVIDER_TIMEOUT', 'unknown')])
    execute_translation(db, cfg, claim(db), provider)
    first, second = claim(db), claim(db)
    execute_translation(db, cfg, first, provider)
    monkeypatch.setattr('packages.translation.execution.execute_translation',
        lambda db, cfg, lease: execute_translation(db, cfg, lease, provider))
    execute(db, cfg, second)
    with db.transaction() as session:
        job = session.get(Job, 'job')
        assert job.status == 'outcome_unknown' and job.error['code'] == 'PROVIDER_TIMEOUT'
        assert session.scalar(select(Permit)).state == 'unknown'
        assert session.get(Task, second.task_id).status == 'pending'
        attempt = session.get(Attempt, second.attempt_id)
        assert attempt.state == 'not_executed' and attempt.finished_at is not None
    assert len(provider.calls) == 1
    assert claim(db) is None
