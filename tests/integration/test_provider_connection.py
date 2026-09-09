"""M1-G03/G05/G06/G09 local connection-test contracts; no live provider."""
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from packages.domain.models import Attempt, Document, Job, Permit, Settings, Task, now
from packages.jobs.queue import claim, recover_expired
from packages.providers.settings import configuration_view
from tests.integration.test_provider_settings_api import settings_store, put
from tests.unit.test_provider_settings_store import complete

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def allow_synthetic_dispatch(database):
    db, _ = database
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled = False
        settings.instance_budget_micro = 1000000


def configure(client, **changes):
    saved = put(client, complete(cost_control_enabled=False, **changes), 'SYNTHETIC_CONNECTION_KEY')
    assert saved.status_code == 200, saved.text
    return saved.json()


def start(client, saved, key='test-once', **changes):
    return client.post('/api/v1/settings/provider/test', headers={'If-Match': f'"{saved["generation"]}"',
        'Idempotency-Key': key}, json={'profile_hash': saved['profile_hash'],
        'external_processing_confirmed': True, **changes})


def test_confirmation_cas_idempotency_and_no_secret_or_document(client, database, settings_store):
    saved = configure(client)
    assert start(client, saved, external_processing_confirmed=False).status_code == 409
    assert start(client, {**saved, 'generation': 0}).status_code == 412
    assert start(client, {**saved, 'profile_hash': 'a' * 64}).status_code == 409
    result = start(client, saved)
    assert result.status_code == 202, result.text
    assert start(client, saved).json()['id'] == result.json()['id']
    assert start(client, saved, key='second-click').status_code == 409
    db, _ = database
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
        assert 'SYNTHETIC_CONNECTION_KEY' not in json.dumps(session.scalar(select(Job)).payload)


@pytest.mark.parametrize('protocol,provider,auth', [
    ('responses', 'openai', 'bearer'), ('chat_completions', 'openai', 'bearer'),
    ('gemini_interactions', 'gemini', 'api_key'), ('claude_messages', 'anthropic', 'api_key'),
])
def test_four_protocols_through_worker_with_one_http_attempt(client, database, settings_store, monkeypatch, protocol, provider, auth):
    from packages.providers import connection
    from packages.providers.native import NativeProvider
    from packages.providers.openai_responses import OpenAIResponses
    from workers.main import execute
    saved = configure(client, api_protocol=protocol, provider=provider, auth_mode=auth,
        endpoint='http://test.invalid/v1/probe', model_id='test-model')
    calls = []
    output = json.dumps({'results': [{'unit_id': 'connection-test', 'target_inline': [{'type': 'text', 'text': '你好。'}]}]})

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body['model'] == 'test-model'
        assert 'SYNTHETIC_CONNECTION_KEY' not in request.content.decode()
        header = 'authorization' if auth == 'bearer' else 'x-goog-api-key' if provider == 'gemini' else 'x-api-key'
        assert request.headers[header].endswith('SYNTHETIC_CONNECTION_KEY')
        if protocol == 'responses':
            value = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}]}
        elif protocol == 'chat_completions':
            value = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': output}}]}
        elif protocol == 'gemini_interactions':
            value = {'status': 'completed', 'steps': [{'type': 'model_output', 'content': [{'type': 'text', 'text': output}]}]}
        else:
            assert request.headers['anthropic-version'] == '2023-06-01'
            value = {'type': 'message', 'role': 'assistant', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': output}]}
        return httpx.Response(200, json={**value, 'id': 'synthetic-request', 'model': 'test-model'})

    def factory(profile):
        from packages.providers.settings import resolve_provider_credentials
        endpoint, wire, mode, key_file = resolve_provider_credentials(profile)
        transport = httpx.MockTransport(handler)
        return NativeProvider(profile, key_file, transport=transport) if provider != 'openai' else OpenAIResponses(key_file, transport=transport, endpoint=endpoint, api_protocol=wire, auth_mode=mode)
    monkeypatch.setattr(connection, 'provider_for', factory)
    result = start(client, saved).json()
    db, cfg = database
    execute(db, cfg, claim(db))
    final = client.get('/api/v1/settings/provider/test/' + result['id']).json()
    assert final['status'] == 'succeeded', final
    assert final['actual_micro'] is None  # Missing usage is not zero cost.
    assert len(calls) == 1
    assert configuration_view()['profile_hash'] == saved['profile_hash']
    assert client.get('/api/v1/settings/provider').json()['connection_test']['id'] == result['id']
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Permit)) == 1
        assert session.scalar(select(func.count()).select_from(Document)) == 0


@pytest.mark.parametrize('failure,status,code', [('auth', 'failed', 'PROVIDER_AUTH'), ('timeout', 'outcome_unknown', 'OUTCOME_UNKNOWN'), ('model', 'outcome_unknown', 'PROVIDER_MODEL_MISMATCH')])
def test_failures_never_retry_and_unknown_survives_reload(client, database, settings_store, monkeypatch, failure, status, code):
    from packages.providers import connection
    from packages.providers.contract import ProviderFailure
    from workers.main import execute
    saved = configure(client)
    calls = []
    class Provider:
        def translate(self, *args):
            calls.append(1)
            if failure == 'model': return {'failure_code': 'PROVIDER_MODEL_MISMATCH'}
            raise ProviderFailure('PROVIDER_CONFIG' if failure == 'auth' else 'OUTCOME_UNKNOWN',
                'not_executed' if failure == 'auth' else 'unknown', http_status=401 if failure == 'auth' else None)
    monkeypatch.setattr(connection, 'provider_for', lambda _: Provider())
    result = start(client, saved).json()
    db, cfg = database
    execute(db, cfg, claim(db))
    final = client.get('/api/v1/settings/provider/test/' + result['id']).json()
    assert (final['status'], final['code']) == (status, code)
    recover_expired(db)
    assert claim(db) is None and len(calls) == 1
    if status == 'outcome_unknown':
        assert start(client, saved, key='new').status_code == 409
        assert start(client, saved, key='accepted-risk', duplicate_charge_risk_confirmed=True).status_code == 202
        with db.transaction() as session:
            assert session.scalar(select(Permit)).state == 'unknown'


def test_stale_before_worker_and_dispatch_disabled_never_send(client, database, settings_store, monkeypatch):
    from packages.providers import connection
    from workers.main import execute
    saved = configure(client)
    db, cfg = database
    with db.transaction() as session: session.get(Settings, 'singleton').dispatch_disabled = True
    assert start(client, saved).status_code == 409
    with db.transaction() as session: session.get(Settings, 'singleton').dispatch_disabled = False
    result = start(client, saved).json()
    assert put(client, complete(cost_control_enabled=False, model_id='changed'), generation=1, operation='rotate').status_code == 200
    monkeypatch.setattr(connection, 'provider_for', lambda _: pytest.fail('Stale credentials must not be read'))
    execute(db, cfg, claim(db))
    assert client.get('/api/v1/settings/provider/test/' + result['id']).json()['code'] == 'PROVIDER_PROFILE_STALE'


def test_controlled_budget_and_crash_recovery(client, database, settings_store):
    saved = put(client, complete(), 'SYNTHETIC_CONNECTION_KEY').json()
    assert start(client, saved).status_code == 409
    result = start(client, saved, budget_micro=100000).json()
    from packages.billing.ledger import authorize
    from packages.billing.price import reserve_cost
    from packages.providers.connection import test_profile
    db, _ = database
    lease = claim(db)
    with db.transaction() as session:
        profile = session.get(Job, lease.job_id).payload['profile']
        authorize(session, lease, reserve_cost(test_profile(profile)), profile['price'])
        session.get(Task, lease.task_id).lease_expires = now() - timedelta(seconds=1)
    recover_expired(db)
    assert claim(db) is None
    assert client.get('/api/v1/settings/provider/test/' + result['id']).json()['status'] == 'outcome_unknown'


def test_crash_after_settlement_never_sends_a_second_request(client, database, settings_store):
    from packages.billing.ledger import authorize, settle
    saved = configure(client)
    result = start(client, saved).json()
    db, _ = database
    lease = claim(db)
    with db.transaction() as session:
        profile = session.get(Job, lease.job_id).payload['profile']
        authorize(session, lease, None, profile['price'])
        settle(session, lease.attempt_id, None, None)
        session.get(Task, lease.task_id).lease_expires = now() - timedelta(seconds=1)
    recover_expired(db)
    assert claim(db) is None
    final = client.get('/api/v1/settings/provider/test/' + result['id']).json()
    assert final['status'] == 'failed' and final['code'] == 'PROVIDER_TEST_INTERRUPTED'


def test_two_tabs_can_enqueue_only_one_test(client, database, settings_store):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    saved = configure(client)
    db, cfg = database
    barrier = Barrier(2)
    def submit(index):
        with TestClient(create_app(cfg, db)) as peer:
            peer.headers['X-Library-Request'] = '1'
            barrier.wait()
            return start(peer, saved, key=f'tab-{index}').status_code
    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(submit, [1, 2])) == [202, 409]


@pytest.mark.parametrize('status', [200, 401])
def test_actual_loopback_http_with_production_credentials_binding(client, database, settings_store, status):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from workers.main import execute
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            assert self.headers['Authorization'] == 'Bearer SYNTHETIC_CONNECTION_KEY'
            payload = {'model': 'fixture-model', 'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                'content': json.dumps({'results': [{'unit_id': 'connection-test', 'target_inline': [{'type': 'text', 'text': '你好。'}]}]})}}]}
            data = json.dumps(payload if status == 200 else {'error': 'SYNTHETIC_CONNECTION_KEY'}).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        saved = configure(client, endpoint=f'http://127.0.0.1:{server.server_port}/v1/chat/completions')
        queued = start(client, saved)
        assert queued.status_code == 202, queued.text
        db, cfg = database
        execute(db, cfg, claim(db))
        final = client.get('/api/v1/settings/provider/test/' + queued.json()['id'])
        assert final.json()['status'] == ('succeeded' if status == 200 else 'failed'), final.text
        assert 'SYNTHETIC_CONNECTION_KEY' not in final.text
        assert len(requests) == 1
        assert requests[0]['max_completion_tokens'] == 256
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
