from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import select

from packages.domain.models import Attempt, Job, Settings, Task
from packages.jobs.queue import claim, finish
from packages.resources.models import GIB
from packages.resources.policy import policy
from packages.resources.preparation import execute

pytestmark = pytest.mark.postgres
CAPACITY = {'ram_total_bytes': 64 * GIB, 'ram_used_bytes': 4 * GIB,
            'vram_total_bytes': 24 * GIB, 'vram_used_bytes': 2 * GIB, 'resident_models': []}


def jobs(db, *, masters=1, children=2):
    with db.transaction() as session:
        session.get(Settings, 'singleton').preferences = {'resources': policy() | {
            'master_concurrency': masters, 'subjob_concurrency': children, 'auto_concurrency': False}}
        for name in ('a', 'b'):
            session.add(Job(id=name, stage='translate'))
            session.flush()
            for index in range(3):
                session.add(Task(id=f'{name}{index}', job_id=name, kind='translate'))


def test_preferences_roundtrip_defaults_conflict_and_no_model_io(client, monkeypatch):
    monkeypatch.setattr(httpx, 'Client', lambda **_: pytest.fail('Settings must not contact model services'))
    current = client.get('/api/v1/settings/preferences')
    assert current.json()['resources'] == policy()
    saved = policy() | {'max_ram_percent': 70, 'max_vram_percent': 65, 'master_concurrency': 3, 'subjob_concurrency': 4, 'auto_concurrency': False}
    response = client.patch('/api/v1/settings/preferences', json={'resources': saved}, headers={'If-Match': current.headers['etag']})
    assert response.status_code == 200 and response.json()['resources'] == saved
    assert client.get('/api/v1/settings/preferences').json()['resources'] == saved
    assert client.patch('/api/v1/settings/preferences', json={'resources': policy()}, headers={'If-Match': current.headers['etag']}).status_code == 412
    assert client.patch('/api/v1/settings/preferences', json={'resources': saved | {'max_ram_percent': 101}}, headers={'If-Match': response.headers['etag']}).status_code == 422
    partial = client.patch('/api/v1/settings/preferences', json={'resources': {'max_ram_percent': 75}}, headers={'If-Match': response.headers['etag']})
    assert partial.status_code == 200 and partial.json()['resources'] == saved | {'max_ram_percent': 75}


def test_concurrent_claims_cannot_exceed_master_or_child_limit(database):
    db, _ = database
    jobs(db)
    with ThreadPoolExecutor(max_workers=6) as pool:
        leases = list(pool.map(lambda _: claim(db, capacity=CAPACITY), range(6)))
    admitted = [lease for lease in leases if lease]
    assert len(admitted) == 2
    assert len({lease.job_id for lease in admitted}) == 1
    with db.transaction() as session:
        for lease in admitted:
            finish(session, lease)
    assert claim(db, capacity=CAPACITY).job_id != admitted[0].job_id


def test_memory_wait_consumes_no_attempt_and_recovers_when_capacity_returns(database):
    db, _ = database
    jobs(db)
    assert claim(db, capacity=CAPACITY | {'ram_used_bytes': 55 * GIB}) is None
    with db.transaction() as session:
        assert not list(session.scalars(select(Attempt)))
        assert session.get(Job, 'a').progress['resource_wait'] == 'RAM_BUDGET_LIMIT'
    lease = claim(db, capacity=CAPACITY)
    assert lease is not None
    with db.transaction() as session:
        assert 'resource_wait' not in session.get(Job, lease.job_id).progress
        assert session.get(Task, lease.task_id).attempts == 1


def test_explicit_preparation_waits_for_budget_then_calls_exact_backend(client, database, monkeypatch):
    db, _ = database
    calls = []
    def wire(request):
        calls.append(request)
        assert request.url.params['backend'] == 'llama.cpp'
        return httpx.Response(202 if request.method == 'POST' else 200, json={'status': 'ready'})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(wire), **kwargs))
    response = client.post('/api/v1/settings/local-models/hy-mt2-7b-q4-k-m-gguf/prepare?backend=llama.cpp',
        headers={'Idempotency-Key': 'queued-prepare'})
    assert response.status_code == 202 and response.json()['status'] == 'queued'
    assert not calls
    assert claim(db, capacity=CAPACITY | {'vram_used_bytes': 20 * GIB}) is None
    lease = claim(db, capacity=CAPACITY)
    execute(db, lease)
    assert [(call.method, call.url.path) for call in calls] == [('POST', '/models/hy-mt2-7b-q4-k-m-gguf/prepare'), ('GET', '/models/hy-mt2-7b-q4-k-m-gguf')]
    with db.transaction() as session:
        assert session.get(Job, lease.job_id).status == 'succeeded'


@pytest.mark.parametrize('available', [True, False])
def test_resource_status_reports_capacity_counts_references_and_outage(client, database, monkeypatch, available):
    db, _ = database
    jobs(db)
    claim(db, capacity=CAPACITY)
    original = httpx.Client
    def wire(request):
        assert request.url.path == '/resources' and request.method == 'GET'
        return httpx.Response(200, json=CAPACITY) if available else httpx.Response(503)
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(wire), **kwargs))
    response = client.get('/api/v1/settings/resources')
    assert response.status_code == 200
    result = response.json()
    assert result['active_master_jobs'] == result['active_subjobs'] == 1
    assert result['vram_total_bytes'] == (24 * GIB if available else None)
    assert len(result['model_references']) == 16
    assert all(row['memory_reference']['weights_bytes'] > 0 for row in result['model_references'])
