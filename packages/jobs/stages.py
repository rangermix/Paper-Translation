"""Receipts for automatic stages executed within a fenced parent operation."""
from collections import defaultdict
from datetime import datetime

from packages.domain.models import Attempt, Job, Task, new_id
from packages.domain.workflow import ModelIdentity
from .history import record_log


def completed_stage(session, *, stage, started_at, finished_at, status='succeeded', document_id=None,
                    parent_job_id=None, payload=None, result=None, model=None, code=None):
    identity = ModelIdentity.model_validate(model or {'kind': 'none'}).model_dump(exclude_none=True)
    job = Job(id=new_id('job'), stage=stage, document_id=document_id, parent_job_id=parent_job_id,
        status=status, payload=payload or {}, progress=result or {}, queued_at=started_at,
        started_at=started_at, finished_at=finished_at, actual_model=identity, error={'code': code} if code else None)
    session.add(job); session.flush()
    task = Task(id=new_id('task'), job_id=job.id, kind=stage, status=status, fence=1, attempts=1,
        started_at=started_at, finished_at=finished_at, actual_model=identity, result=result or {})
    session.add(task); session.flush()
    attempt = Attempt(id=new_id('attempt'), job_id=job.id, task_id=task.id, fence=1, control_epoch=0,
        state=status, started_at=started_at, finished_at=finished_at, actual_model=identity)
    session.add(attempt); session.flush()
    record_log(session, job, event_key='stage-start', operation='started', task_id=task.id,
        attempt_id=attempt.id, at=started_at)
    record_log(session, job, event_key='stage-finish', operation='finished', task_id=task.id,
        attempt_id=attempt.id, at=finished_at, details={'status': status, 'code': code})
    return job


def record_recovery(session, parent, source_draft, audit):
    """Keep before/after text in source evidence, with content-free history links."""
    groups = defaultdict(list)
    for index, entry in enumerate(audit):
        groups[entry['page']].append((index, entry))
    jobs = []
    for page, records in groups.items():
        # Each page gets a distinct result. Model attempts retain the actual
        # identity reported by the parser, never the current settings.
        for index, entry in records:
            start, end = datetime.fromisoformat(entry['started_at']), datetime.fromisoformat(entry['finished_at'])
            model = entry.get('model')
            result = entry.get('result', 'recovered')
            job = completed_stage(session, stage='recovery', started_at=start, finished_at=end,
                status='completed_with_warnings' if result in {'failed', 'retained_page'} else 'succeeded',
                document_id=parent.document_id, parent_job_id=parent.id, model=model,
                payload={'source_draft_id': source_draft.id, 'evidence_index': index, 'page': page,
                    'rule_version': entry['rule_version'], 'action': entry['action']},
                result={'page': page, 'result': result, 'elapsed_ms': entry['elapsed_ms'],
                    'local_retries': entry.get('attempts', 0)})
            record_log(session, job, event_key='recovery-result', operation='recovery_completed', page=page,
                at=end, details={'result': result, 'elapsed_ms': entry['elapsed_ms']})
            jobs.append(job.id)
    return jobs
