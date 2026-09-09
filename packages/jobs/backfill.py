"""One-way, evidence-only history enrichment; never schedules external work."""
from sqlalchemy import select

from packages.domain.models import Attempt, Document, Event, Job, Task, Upload
from packages.domain.workflow import TERMINAL_STATES
from .history import MODEL_TASKS, config_snapshot, record_log


def backfill_history(db):
    counts = {'jobs': 0, 'attempts': 0, 'filenames': 0}
    with db.transaction() as session:
        # Suppress modern lifecycle timestamps for old rows. Each recovered
        # field is based on a persisted event or attempt, not this migration.
        session.info['nb_history_enabled'] = False
        for job in session.scalars(select(Job).where(Job.config_snapshot.is_(None)).order_by(Job.id)):
            attempts = session.scalars(select(Attempt).where(Attempt.job_id == job.id).order_by(Attempt.created_at)).all()
            tasks = session.scalars(select(Task).where(Task.job_id == job.id)).all()
            events = session.scalars(select(Event).where(Event.job_id == job.id).order_by(Event.created_at)).all()
            job.config_snapshot = config_snapshot(job.stage, job.payload) | {
                'evidence_source': 'historical_job_payload' if job.payload else 'historical_job_record'}
            facts = ['config']
            for attempt in attempts:
                if attempt.started_at is None:
                    attempt.started_at = attempt.created_at
                    counts['attempts'] += 1
            if attempts and job.started_at is None:
                job.started_at = attempts[0].created_at
                facts.append('attempt_created_at')
            queued = next((event for event in events if event.payload.get('status') == 'pending'), None)
            if queued and job.queued_at is None:
                job.queued_at = queued.created_at
                facts.append('pending_event')
            ended = next((event for event in reversed(events) if event.payload.get('status') == job.status), None)
            complete = tasks and all(task.status in TERMINAL_STATES for task in tasks)
            if ended and complete and job.finished_at is None and job.status in TERMINAL_STATES | {'needs_review', 'ready'}:
                job.finished_at = ended.created_at
                facts.append('terminal_event')
            if attempts and job.stage not in MODEL_TASKS and all(task.kind not in MODEL_TASKS for task in tasks):
                identity = {'kind': 'none', 'models': [], 'evidence_source': 'historical_task_kind'}
                job.actual_model = job.actual_model or identity
                for task in tasks: task.actual_model = task.actual_model or identity
                for attempt in attempts: attempt.actual_model = attempt.actual_model or identity
                facts.append('task_kind')
            if facts:
                job.config_snapshot = job.config_snapshot | {'history_evidence': facts}
                counts['jobs'] += 1
                record_log(session, job, event_key='history-backfill-v1', operation='history_backfill', details={'count': len(facts)})
        for doc in session.scalars(select(Document).where(Document.original_filename.is_(None), Document.deleted_at.is_(None))):
            names = set(session.scalars(select(Upload.filename).where(Upload.source_asset_id == doc.source_asset_id))) if doc.source_asset_id else set()
            if len(names) == 1:
                doc.original_filename = names.pop()
                counts['filenames'] += 1
            # A matching filename does not prove the user never renamed it.
            # title_user_edited remains unknown, preserving the current title.
    return counts
