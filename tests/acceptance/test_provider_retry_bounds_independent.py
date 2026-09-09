"""Actual worker retry/ledger behavior with explicit scripted transport only."""
from datetime import datetime, timezone
import time

import pytest
from sqlalchemy import func, select

from packages.billing.ledger import budget_totals
from packages.billing.price import reserve_cost
from packages.domain.models import Attempt, Job, Permit, SegmentVersion, Settings, Task, TranslationCache
from packages.jobs.queue import claim
from packages.providers.contract import ProviderFailure
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import PROFILE, setup_library

pytestmark = pytest.mark.postgres


def one_unit(database, budget_requests):
    db, cfg = database
    setup_library(db, cfg)
    with db.transaction() as session:
        job = session.get(Job, 'job')
        job.payload = job.payload | {'block_ids': ['p1']}
        job.budget_micro = reserve_cost(PROFILE) * budget_requests
        session.get(Settings, 'singleton').instance_budget_micro = job.budget_micro
    execute_translation(db, cfg, claim(db), FakeProvider())
    lease = claim(db)
    assert lease.kind == 'translate' and lease.payload['unit']['owner_block_id'] == 'p1'
    return db, cfg, lease


def due_lease(db, available_at):
    # Actual persisted clock eligibility is observed; do not edit available_at.
    assert claim(db) is None
    seconds = max(0, (available_at - datetime.now(timezone.utc)).total_seconds())
    time.sleep(seconds + .03)
    lease = claim(db)
    assert lease is not None
    return lease


@pytest.mark.parametrize('transport', ['scripted', 'http_mock'])
def test_two_explicit_unexecuted_429_then_success_obeys_retry_after(database, tmp_path, transport):
    db, cfg, lease = one_unit(database, 1)
    provider = FakeProvider([ProviderFailure('PROVIDER_RATE_LIMIT', 'not_executed', retry_after=3),
        ProviderFailure('PROVIDER_RATE_LIMIT', 'not_executed', retry_after=5)])
    if transport == 'http_mock':
        import httpx
        import json
        from packages.providers.openai_responses import ENDPOINT, OpenAIResponses
        requests = []
        key_file = tmp_path / 'synthetic-key'
        key_file.write_text('INDEPENDENT_TEST_ONLY_NOT_A_REAL_KEY', encoding='utf-8')

        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            assert str(request.url) == ENDPOINT and body['tools'] == [] and body['tool_choice'] == 'none'
            assert body['model'] == PROFILE['model_id']
            if len(requests) <= 2:
                return httpx.Response(429, headers={'Retry-After': str([3, 5][len(requests)-1])})
            content = json.loads(body['input'][0]['content'][0]['text'])
            output = {'results': [{'unit_id': u['unit_id'], 'target_inline': u['source_inline']} for u in content['units']]}
            return httpx.Response(200, headers={'x-request-id': 'independent-mock-wire-success'}, json={
                'status': 'completed', 'model': PROFILE['model_id'], 'usage': {'input_tokens': 100, 'output_tokens': 50},
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(output)}]}]})

        provider = OpenAIResponses(key_file, httpx.MockTransport(handle))
        provider.calls = requests
    for retry_after in [3, 5]:
        started = datetime.now(timezone.utc)
        execute_translation(db, cfg, lease, provider)
        with db.transaction() as session:
            task, job = session.get(Task, lease.task_id), session.get(Job, lease.job_id)
            available = task.available_at
            assert (available - started).total_seconds() >= retry_after
            assert task.status == job.status == 'pending'
            assert job.error == {'code': 'PROVIDER_RATE_LIMIT', 'retryable': True}
            assert session.get(Attempt, lease.attempt_id).state == 'not_executed'
            permits = list(session.scalars(select(Permit)))
            assert len(permits) == len(provider.calls) and all(p.state == 'released' and p.actual_micro is None for p in permits)
            assert budget_totals(session) == {'actual_micro': 0, 'reserved_micro': 0, 'unknown_micro': 0}
            assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
        lease = due_lease(db, available)
    execute_translation(db, cfg, lease, provider)
    assert len(provider.calls) == 3 and claim(db) is None
    with db.transaction() as session:
        permits = list(session.scalars(select(Permit)))
        assert sorted(p.state for p in permits) == ['released', 'released', 'settled']
        assert budget_totals(session) == {'actual_micro': 150, 'reserved_micro': 0, 'unknown_micro': 0}
        assert budget_totals(session)['actual_micro'] <= session.get(Settings, 'singleton').instance_budget_micro
        assert session.get(Task, lease.task_id).attempts == 3 and session.get(Task, lease.task_id).status == 'succeeded'
        assert session.get(Job, lease.job_id).status == 'partially_completed'
        assert session.get(Job, lease.job_id).progress['requests'] == 3
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 1


@pytest.mark.parametrize('invalid,expected', [('missing', 'PROVIDER_UNIT_BIJECTION'), ('duplicate', 'PROVIDER_UNIT_BIJECTION'),
    ('truncated', 'PROVIDER_TRUNCATED'), ('path', 'PROVIDER_OUTPUT_SCHEMA')])
def test_invalid_paid_response_has_only_one_repair_then_stops(database, invalid, expected):
    db, cfg, lease = one_unit(database, 2)

    class InvalidProvider(FakeProvider):
        def translate(self, units, profile, glossary):
            response = super().translate(units, profile, glossary)
            if invalid == 'truncated':
                response['status'] = 'incomplete'
            else:
                import json
                parsed = json.loads(response['output_text'])
                if invalid == 'missing':
                    parsed['results'] = []
                elif invalid == 'duplicate':
                    parsed['results'] *= 2
                else:
                    parsed['output_file'] = '../../must-not-be-created.txt'
                response['output_text'] = json.dumps(parsed)
            return response

    provider = InvalidProvider()
    for attempt in [1, 2]:
        execute_translation(db, cfg, lease, provider)
        with db.transaction() as session:
            task, job = session.get(Task, lease.task_id), session.get(Job, lease.job_id)
            assert job.error['code'] == expected
            assert session.get(Attempt, lease.attempt_id).state == 'settled'
            assert all(p.state == 'settled' and p.actual_micro == 150 for p in session.scalars(select(Permit)))
            assert budget_totals(session) == {'actual_micro': attempt * 150, 'reserved_micro': 0, 'unknown_micro': 0}
            assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
            assert session.scalar(select(func.count()).select_from(TranslationCache)) == 0
            available = task.available_at
            if attempt == 1:
                assert task.status == job.status == 'pending'
                assert task.payload['repair_count'] == 1 and task.payload['repair_reason'] == expected
                assert job.error['retryable'] is True
            else:
                assert task.status == 'failed' and job.status == 'partially_completed' and job.error['retryable'] is False
                assert task.attempts == 2
        if attempt == 1:
            lease = due_lease(db, available)
    assert len(provider.calls) == 2
    assert provider.calls[1][0]['repair_reason'] == expected
    assert claim(db) is None
    assert not list(cfg.data.parent.rglob('must-not-be-created.txt'))


def test_permanent_mock_http_401_stops_worker_without_retry(database, tmp_path):
    import httpx
    from packages.providers.openai_responses import OpenAIResponses
    db, cfg, lease = one_unit(database, 1)
    key_file = tmp_path / 'synthetic-key'
    key_file.write_text('INDEPENDENT_TEST_ONLY_NOT_A_REAL_KEY', encoding='utf-8')
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(401)

    execute_translation(db, cfg, lease, OpenAIResponses(key_file, httpx.MockTransport(handle)))
    assert calls == ['/v1/responses'] and claim(db) is None
    with db.transaction() as session:
        job, task = session.get(Job, lease.job_id), session.get(Task, lease.task_id)
        assert job.status == 'waiting_config' and task.status == 'failed'
        assert job.error == {'code': 'PROVIDER_CONFIG', 'retryable': False}
        assert session.get(Attempt, lease.attempt_id).state == 'not_executed'
        permit = session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id))
        assert permit.state == 'released' and permit.actual_micro is None
        assert budget_totals(session) == {'actual_micro': 0, 'reserved_micro': 0, 'unknown_micro': 0}
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
