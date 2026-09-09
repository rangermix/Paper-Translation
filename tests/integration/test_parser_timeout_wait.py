from types import SimpleNamespace

import pytest
from sqlalchemy import select

from packages.domain.errors import DomainError
from packages.domain.models import Task
from packages.ir import canonical_bytes
from packages.jobs.queue import claim
from tests.support import seed_editor
from workers import main as worker

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('timeout,expected', [(7200, 'TEST_PARSER_FINISHED'), (60, 'PARSER_TIMEOUT'), (None, 'PARSER_TIMEOUT')])
def test_worker_waits_beyond_fifteen_minutes_using_frozen_timeout(client, database, monkeypatch, timeout, expected):
    db, cfg = database
    seed_editor(db, cfg)
    response = client.post('/api/v1/documents/doc_fixture/parse', json={'source_asset_id': 'source_pdf'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'timeout-wait'})
    assert response.status_code == 202
    with db.transaction() as session:
        task = session.scalar(select(Task).where(Task.job_id == response.json()['job_id']))
        assert task.payload['parser_timeout_seconds'] == 7200
        payload = dict(task.payload)
        if timeout is None:
            payload.pop('parser_timeout_seconds')  # Existing task from before the upgrade.
        else:
            payload['parser_timeout_seconds'] = timeout
        task.payload = payload
    lease = claim(db)
    clock = SimpleNamespace(elapsed=0)
    captured = {}
    def capture(root, descriptor, source):
        captured.update(descriptor)
    def finish_after_old_limit(_):
        clock.elapsed = 1000
        directory = cfg.parser_outputs / lease.task_id / str(lease.fence)
        directory.mkdir(parents=True)
        result = {key: captured[key] for key in ('task_id', 'fence', 'source_sha256')}
        result.update(status='failed', operation='parse', files=[], error={'code': 'TEST_PARSER_FINISHED'})
        (directory / 'result.json').write_bytes(canonical_bytes(result))
    monkeypatch.setattr(worker, 'write_request', capture)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic=lambda: clock.elapsed, sleep=finish_after_old_limit))
    with pytest.raises(DomainError) as error:
        worker.parse_spool(db, cfg, lease)
    assert error.value.code == expected
    assert captured['timeout_seconds'] == (timeout or 900)
