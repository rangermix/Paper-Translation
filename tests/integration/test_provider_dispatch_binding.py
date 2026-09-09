"""Real PG jobs and accounting, synthetic HTTP transport only."""
import copy
import json

import httpx
import pytest
from sqlalchemy import func, select

from packages.domain.models import Job, Permit, SegmentVersion, Task, Settings
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.openai_responses import OpenAIResponses
from packages.providers.settings import managed_profile, save_configuration
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import PROFILE, setup_library

pytestmark = pytest.mark.postgres


def prepare(database, monkeypatch, tmp_path, protocol='chat_completions', auth='bearer'):
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path/'provider-settings'))
    p = copy.deepcopy(PROFILE) | {'endpoint': 'http://127.0.0.1:11434/synthetic-A',
        'api_protocol': protocol, 'auth_mode': auth, 'model_id': 'local-fixture:latest', 'cost_control_enabled': True}
    save_configuration(p, 'synthetic-key-A' if auth == 'bearer' else None, auth == 'none', '"0"', 'initial')
    frozen = managed_profile()
    setup_library(db, cfg)
    with db.transaction() as session:
        job = session.get(Job, 'job'); job.payload = job.payload | {'profile': frozen}
    execute_translation(db, cfg, claim(db))
    return db, cfg, frozen


def wire_response(request, protocol, usage=True):
    body = json.loads(request.content)
    unit = json.loads(body['messages'][1]['content'] if protocol == 'chat_completions'
        else body['input'][0]['content'][0]['text'])['units'][0]
    output = json.dumps({'results': [{'unit_id': unit['unit_id'], 'target_inline': unit['source_inline']}]})
    if protocol == 'chat_completions':
        return httpx.Response(200, json={'id': 'synthetic-chat', 'choices': [{'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': output}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 40},
                'completion_tokens_details': {'reasoning_tokens': 7}} if usage else None})
    return httpx.Response(200, json={'id': 'synthetic-response', 'status': 'completed',
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}],
        'usage': {'input_tokens': 100, 'output_tokens': 20} if usage else None})


def intercept(monkeypatch, handler, *, after_bind=None):
    def factory(key_file=None, **kwargs):
        instance = OpenAIResponses(key_file, httpx.MockTransport(handler), **kwargs)
        if after_bind: after_bind()
        return instance
    monkeypatch.setattr('packages.translation.execution.OpenAIResponses', factory)


@pytest.mark.parametrize('protocol,auth', [('responses', 'bearer'), ('chat_completions', 'bearer'),
    ('chat_completions', 'none')])
def test_real_worker_dispatches_frozen_endpoint_and_accounts_both_protocols(database, monkeypatch, tmp_path, protocol, auth):
    db, cfg, frozen = prepare(database, monkeypatch, tmp_path, protocol, auth); calls = []
    def wire(request):
        calls.append(request)
        assert str(request.url) == frozen['endpoint']
        assert request.headers.get('authorization') == ('Bearer synthetic-key-A' if auth == 'bearer' else None)
        return wire_response(request, protocol)
    intercept(monkeypatch, wire)
    lease = claim(db); execute_translation(db, cfg, lease)
    with db.transaction() as session:
        permit = session.scalar(select(Permit))
        assert permit.state == 'settled' and permit.actual_micro == 120
        assert session.get(Task, lease.task_id).status == 'succeeded'
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 1
    assert len(calls) == 1


def test_rotation_after_adapter_binding_cannot_mix_endpoint_A_and_key_B(database, monkeypatch, tmp_path):
    db, cfg, frozen = prepare(database, monkeypatch, tmp_path); calls = []
    def rotate():
        new = {k: v for k, v in frozen.items() if k not in {'config_revision', 'credential_revision'}}
        new['endpoint'] = 'http://127.0.0.1:11434/synthetic-B'
        save_configuration(new, 'synthetic-key-B', False, '"1"', 'rotation')
    def wire(request):
        calls.append(request)
        assert str(request.url) == frozen['endpoint'] and request.headers['authorization'] == 'Bearer synthetic-key-A'
        return wire_response(request, 'chat_completions')
    intercept(monkeypatch, wire, after_bind=rotate)
    lease = claim(db); execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.get(Task, lease.task_id).status == 'succeeded'
        assert session.scalar(select(Permit)).state == 'settled'
    assert managed_profile()['endpoint'].endswith('synthetic-B') and len(calls) == 1
    # A later queued unit is stale; it cannot pick up B or silently retry A.
    later = claim(db); execute_translation(db, cfg, later)
    with db.transaction() as session:
        assert session.get(Job, 'job').error['code'] == 'PROVIDER_PROFILE_STALE'
        assert session.scalar(select(func.count()).select_from(Permit)) == 1
    assert len(calls) == 1


def test_missing_chat_usage_is_unknown_and_has_no_validated_segment(database, monkeypatch, tmp_path):
    db, cfg, _ = prepare(database, monkeypatch, tmp_path)
    intercept(monkeypatch, lambda request: wire_response(request, 'chat_completions', usage=False))
    execute_translation(db, cfg, claim(db))
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'unknown'
        assert session.get(Job, 'job').status == 'outcome_unknown'
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0


def test_unsupported_chat_actions_settle_usage_without_repair_or_tool_execution(database, monkeypatch, tmp_path):
    db, cfg, _ = prepare(database, monkeypatch, tmp_path); calls = []
    def wire(request):
        calls.append(request)
        return httpx.Response(200, json={'id': 'unsupported-action', 'choices': [{'finish_reason': 'tool_calls',
            'message': {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'inert-only'}]}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    intercept(monkeypatch, wire)
    lease = claim(db); execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.scalar(select(Permit)).actual_micro == 120
        assert session.get(Job, 'job').status == 'waiting_config'
        assert session.get(Job, 'job').error['code'] == 'PROVIDER_UNSUPPORTED_RESPONSE'
        assert session.get(Task, lease.task_id).status == 'failed'
        assert session.get(Task, lease.task_id).payload['repair_count'] == 0
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
    assert len(calls) == 1 and claim(db) is None


def test_semantic_review_uses_chat_schema_and_preserves_actual_target_versions(client, database, monkeypatch, tmp_path):
    from tests.support import seed_editor
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path/'semantic-config'))
    p = copy.deepcopy(PROFILE) | {'endpoint': 'http://127.0.0.1:11434/synthetic-review',
        'api_protocol': 'chat_completions', 'auth_mode': 'none', 'semantic_review_enabled': True}
    save_configuration(p, None, True, '"0"', 'review-config')
    frozen = managed_profile(); seed_editor(db, cfg)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton'); settings.dispatch_disabled = False
        settings.instance_budget_micro = 1_000_000
        before = {s.id: digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
    started = client.post('/api/v1/drafts/draft_fixture/semantic-review', json={'block_ids': ['p1'],
        'profile_revision': frozen['profile_revision'], 'profile_hash': digest(frozen),
        'glossary_revision': 'empty-v1', 'budget_micro': 1_000_000, 'external_processing_confirmed': True},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'chat-review'})
    assert started.status_code == 202, started.text
    calls = []
    def wire(request):
        calls.append(request); body = json.loads(request.content)
        assert str(request.url) == frozen['endpoint'] and 'authorization' not in request.headers
        assert body['response_format']['json_schema']['name'] == 'semantic_issues'
        assert json.loads(body['messages'][1]['content'])['units'][0]['target_text']
        return httpx.Response(200, json={'id': 'synthetic-review', 'choices': [{'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': '{"issues":[]}'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    intercept(monkeypatch, wire)
    while lease := claim(db): execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.get(Job, started.json()['job_id']).progress['review_completed'] is True
        assert before == {s.id: digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
        assert session.scalar(select(Permit)).actual_micro == 120
    assert len(calls) == 1
