"""Explicit model preparation uses the same durable admission queue as work."""
import time

import httpx
from sqlalchemy import select

from packages.domain.db import lock_lifecycle
from packages.domain.errors import DomainError, require
from packages.domain.models import Job, Task, new_id
from packages.jobs.queue import assert_current, finish


def enqueue(session, kind, payload):
    lock_lifecycle(session)
    existing = session.scalar(select(Job).where(Job.stage == kind,
        Job.status.in_(['pending', 'running']), Job.payload == payload).limit(1))
    if existing is None:
        existing = Job(id=new_id('job'), stage=kind, payload=payload,
                       title_snapshot='准备解析模型' if kind == 'prepare_parser_model' else '准备本地模型')
        session.add(existing)
        session.flush()
        session.add(Task(id=new_id('task'), job_id=existing.id, kind=kind, payload=payload))
    return {'status': 'queued', 'job_id': existing.id}


def queued(session, kind):
    return list(session.scalars(select(Job).where(Job.stage == kind, Job.status.in_(['pending', 'running']))))


def execute(db, lease):
    if lease.kind == 'prepare_parser_model':
        from packages.parsers.model_service import CONTROL_URL
        root, identifier = CONTROL_URL, lease.payload['parser_profile_revision']
    else:
        from packages.local_models.catalog import ENDPOINT
        root, identifier = ENDPOINT.rsplit('/v1/', 1)[0], lease.payload['model_id']
    params = {'backend': lease.payload['backend']}
    url = root + '/models/' + identifier
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        response = client.post(url + '/prepare', params=params)
        response.raise_for_status()
        deadline = time.monotonic() + 86400
        while time.monotonic() < deadline:
            with db.transaction() as session:
                assert_current(session, lease)
            response = client.get(url, params=params)
            response.raise_for_status()
            state = response.json()
            if state.get('status') == 'ready':
                with db.transaction() as session:
                    finish(session, lease, {'status': 'ready'})
                return
            require(state.get('status') != 'failed', state.get('code', 'MODEL_PREPARATION_FAILED'))
            time.sleep(1)
    raise DomainError('MODEL_PREPARATION_TIMEOUT')
