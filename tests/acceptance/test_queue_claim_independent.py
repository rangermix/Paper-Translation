"""Independent PostgreSQL concurrent claiming and measured history-query scope."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import threading
import time

import pytest
from sqlalchemy import event, select, text

from packages.domain.models import Attempt, Job, Task, now
from packages.jobs.queue import claim

pytestmark = pytest.mark.postgres


def test_concurrent_fair_claims_never_duplicate_tasks(database):
    db, _ = database
    with db.transaction() as session:
        for i in range(8):
            session.add(Job(id=f'job_{i}', stage='translate'))
        session.flush()
        for i in range(24):
            session.add(Task(id=f'task_{i}', job_id=f'job_{i//3}', kind='unit'))
    found = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for _ in range(8):
            barrier = threading.Barrier(6)
            def one():
                barrier.wait(timeout=10)
                return claim(db)
            found.extend(lease for lease in pool.map(lambda _: one(), range(6)) if lease)
            if len(found) == 24:
                break
    assert len(found) == len({lease.task_id for lease in found}) == 24
    assert all(lease.fence == 1 for lease in found)
    with db.transaction() as session:
        assert len(list(session.scalars(select(Attempt)))) == 24
    assert claim(db) is None


def test_history_claim_query_measured_against_fifty_thousand_prior_attempts(database):
    db, _ = database
    with db.transaction() as session:
        session.add(Job(id='history_job', stage='translate', status='succeeded'))
        session.add(Job(id='current_job', stage='translate'))
        session.flush()
        session.add(Task(id='history_task', job_id='history_job', kind='unit', status='succeeded'))
        session.add(Task(id='current_task', job_id='current_job', kind='unit'))
        session.add(Task(id='current_task_2', job_id='current_job', kind='unit'))
        session.flush()
        session.execute(text("""INSERT INTO attempts
            (id, task_id, job_id, fence, control_epoch, state, evidence, created_at)
            SELECT 'past_' || n, 'history_task', 'history_job', n, 0, 'succeeded', '[]'::jsonb,
                now() - interval '1 day' + n * interval '1 millisecond'
            FROM generate_series(1, 50000) AS n"""))
        session.execute(text('ANALYZE attempts'))
    queries = []
    def capture(conn, cursor, statement, parameters, context, many):
        if 'FOR UPDATE OF jobs SKIP LOCKED' in statement:
            queries.append((statement, parameters))
    event.listen(db.engine, 'before_cursor_execute', capture)
    started = time.monotonic()
    try:
        lease = claim(db)
    finally:
        event.remove(db.engine, 'before_cursor_execute', capture)
    duration = time.monotonic()-started
    assert lease.task_id == 'current_task'
    assert len(queries) == 1
    with db.engine.begin() as conn:
        plan = conn.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+queries[0][0], queries[0][1]).scalar()
    record = Path('.agent/tmp/evidence/reviews') / f'queue-history-query-{time.time_ns()}.json'
    result = {
        'scope': 'One current job and 50000 completed historical attempts in a fresh PostgreSQL schema; observed latency is not a cross-host performance guarantee.',
        'history_attempts': 50000, 'claim_duration_seconds': duration, 'query': queries[0][0], 'explain': plan,
        'record_path': record.as_posix(),
    }
    record.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    Path('.agent/tmp/evidence/reviews/queue-history-query-measurement.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
