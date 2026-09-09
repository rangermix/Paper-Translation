from datetime import timedelta

from sqlalchemy import select

from packages.domain.models import Attempt, Event, Job, Task, TaskLog, now
from packages.jobs.backfill import backfill_history
from packages.jobs.stages import record_recovery
from packages.maintenance.history import operation_receipt


def test_recovery_keeps_actual_times_models_and_no_text_in_logs(database):
    from types import SimpleNamespace
    db, _ = database
    start = now() - timedelta(seconds=10)
    with db.transaction() as session:
        parent = Job(id='parse', stage='parse', payload={})
        session.add(parent); session.flush()
        audit = [{'page': 14, 'rule_version': 'native-page-recovery-v1', 'action': 'native_page_recovery',
            'started_at': start.isoformat(), 'finished_at': (start + timedelta(seconds=2)).isoformat(),
            'before': ['private old text'], 'after': ['private new text'], 'elapsed_ms': 2000, 'model': None}]
        ids = record_recovery(session, parent, SimpleNamespace(id='source_draft'), audit)
        job = session.get(Job, ids[0])
        assert job.started_at == job.queued_at == start
        assert job.finished_at - job.started_at == timedelta(seconds=2)
        assert job.actual_model['kind'] == 'none'
        assert job.payload['evidence_index'] == 0 and job.parent_job_id == 'parse'
        logs = session.scalars(select(TaskLog).where(TaskLog.job_id == job.id)).all()
        assert 'private' not in str([row.details for row in logs]) + str(job.payload)


def test_historical_backfill_uses_own_events_and_never_guesses_model(database):
    db, _ = database
    created = now() - timedelta(days=3)
    with db.transaction() as session:
        session.info['nb_history_enabled'] = False
        session.add(Job(id='historical', stage='translate', status='succeeded', created_at=created,
            payload={'profile': {'model_id': 'selected-only', 'endpoint': 'https://example.test/api?key=secret'}}))
        session.flush()
        session.add(Task(id='historic-task', job_id='historical', kind='translate', status='succeeded'))
        session.flush()
        session.add(Attempt(id='historic-attempt', task_id='historic-task', job_id='historical',
            fence=1, control_epoch=0, state='committed', created_at=created + timedelta(seconds=5)))
        session.add(Event(id='end-event', job_id='historical', generation=2,
            payload={'status': 'succeeded'}, created_at=created + timedelta(seconds=12)))
    assert backfill_history(db)['jobs'] == 1
    assert backfill_history(db)['jobs'] == 0
    with db.transaction() as session:
        job = session.get(Job, 'historical')
        assert job.actual_model is None
        assert job.config_snapshot['model_id'] == 'selected-only'
        assert job.config_snapshot['endpoint'] == 'https://example.test/api'
        assert job.started_at == created + timedelta(seconds=5)
        assert job.finished_at == created + timedelta(seconds=12)
        assert job.status == 'succeeded' and job.queued_at is None
        assert session.get(Attempt, 'historic-attempt').finished_at is None


def test_failed_maintenance_records_error_code_without_raw_exception(database):
    import pytest
    db, _ = database
    with pytest.raises(RuntimeError):
        with operation_receipt(db, 'backup'):
            raise RuntimeError('password and private filename')
    with db.transaction() as session:
        job = session.scalar(select(Job).where(Job.stage == 'backup'))
        assert job.status == 'failed' and job.started_at <= job.finished_at
        assert job.actual_model['kind'] == 'none'
        assert job.error == {'code': 'MAINTENANCE_FAILED'}
        assert 'private' not in str(job.payload) + str(job.error)
