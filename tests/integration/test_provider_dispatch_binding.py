"""Real PG jobs and accounting, synthetic HTTP transport only."""
import copy
import json

import httpx
import pytest
from sqlalchemy import func, select

from packages.domain.models import Attempt, Edition, Job, Permit, SegmentVersion, Task, Settings
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.openai_responses import OpenAIResponses
from packages.providers.settings import managed_profile, resolve_provider_credentials, save_configuration
from packages.preparation import freeze_options
from packages.translation.execution import execute_translation
from packages.translation.languages import public_profile
from tests.integration.test_translation_execution import PROFILE, setup_library
from tests.support import seed_editor

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


def test_api_created_jobs_keep_their_own_settings_snapshot(client, database, monkeypatch, tmp_path):
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'provider-settings'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(tmp_path / 'absent-profile'))
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.get(Settings, 'singleton').dispatch_disabled = False
        session.get(Edition, 'edition_fixture').target_locale = 'en'
        session.flush()
        session.add_all([Edition(id='old_settings_edition', document_id='doc_fixture', target_locale='zh-Hans'),
            Edition(id='new_settings_edition', document_id='doc_fixture', target_locale='ja')])
    base = copy.deepcopy(PROFILE) | {'endpoint': 'http://127.0.0.1:11434/synthetic-A',
        'api_protocol': 'chat_completions', 'auth_mode': 'bearer', 'cost_control_enabled': False}
    save_configuration(base, 'synthetic-key-A', False, '"0"', 'snapshot-A')
    first = managed_profile()

    def start(edition_id, key):
        preflight = client.get('/api/v1/editions/' + edition_id + '/preflight')
        assert preflight.status_code == 200, preflight.text
        view = preflight.json()
        body = {'source_revision_id': view['source_revision_id'], 'source_hash': view['source_hash'],
            'profile_revision': view['profile']['profile_revision'], 'profile_hash': view['profile_hash'],
            'external_processing_confirmed': True, 'publish_policy': 'manual_approval'}
        created = client.post('/api/v1/editions/' + edition_id + '/translate', json=body,
            headers={'If-Match': preflight.headers['etag'], 'Idempotency-Key': key})
        assert created.status_code == 202, created.text
        return created.json()['job_id']

    old_id = start('old_settings_edition', 'start-A')
    updated = base | {'endpoint': 'http://127.0.0.1:11434/synthetic-B', 'model_id': 'model-B'}
    save_configuration(updated, 'synthetic-key-B', False, '"1"', 'snapshot-B')
    second = managed_profile()
    new_id = start('new_settings_edition', 'start-B')
    with db.transaction() as session:
        old, new = session.get(Job, old_id), session.get(Job, new_id)
        assert public_profile(old.payload['profile']) == first
        assert public_profile(new.payload['profile']) == second
        assert old.config_snapshot['config_revision'] == first['config_revision']
        assert new.config_snapshot['config_revision'] == second['config_revision']
        assert old.config_snapshot['model_id'] == first['model_id']
        assert new.config_snapshot['model_id'] == second['model_id']
        assert 'synthetic-key-' not in json.dumps([old.payload, new.payload, old.config_snapshot, new.config_snapshot])
        endpoint, protocol, auth, key = resolve_provider_credentials(old.payload['profile'])
        assert (endpoint, protocol, auth, key.read_text()) == (first['endpoint'], 'chat_completions', 'bearer', 'synthetic-key-A')


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


@pytest.mark.parametrize('protocol', ['responses', 'chat_completions'])
@pytest.mark.parametrize('location', ['header', 'body'])
def test_invalid_tracking_metadata_does_not_prevent_known_usage_settlement(
        database, monkeypatch, tmp_path, protocol, location):
    db, cfg, _ = prepare(database, monkeypatch, tmp_path, protocol)
    def wire(request):
        response = wire_response(request, protocol)
        data = response.json()
        headers = {'x-request-id': 'r' * 201} if location == 'header' else {}
        if location == 'body':
            data['id'] = {'unexpected': 'provider metadata'}
        return httpx.Response(200, json=data, headers=headers)
    intercept(monkeypatch, wire)
    lease = claim(db); execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.get(Attempt, lease.attempt_id).request_id is None
        assert session.get(Task, lease.task_id).status == 'succeeded'
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.scalar(select(Permit)).actual_micro == 120


def test_rotation_after_adapter_binding_cannot_mix_endpoint_A_and_key_B(database, monkeypatch, tmp_path):
    db, cfg, frozen = prepare(database, monkeypatch, tmp_path); calls = []
    rotated = False
    def rotate():
        nonlocal rotated
        if rotated:
            return
        rotated = True
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
    # Queued units keep the original endpoint and credential after a settings edit.
    while later := claim(db):
        execute_translation(db, cfg, later)
    with db.transaction() as session:
        assert session.get(Job, 'job').status in {'succeeded', 'completed_with_warnings'}
        assert all(permit.state == 'settled' for permit in session.scalars(select(Permit)))
        assert session.scalar(select(func.count()).select_from(Permit)) == len(calls)
    assert len(calls) > 1


def test_old_profile_wait_resumes_only_with_its_saved_revision(database, monkeypatch, tmp_path):
    db, cfg, frozen = prepare(database, monkeypatch, tmp_path)
    updated = {k: v for k, v in frozen.items() if k not in {'config_revision', 'credential_revision'}}
    updated['endpoint'] = 'http://127.0.0.1:11434/synthetic-B'
    save_configuration(updated, 'synthetic-key-B', False, '"1"', 'rotation')
    with db.transaction() as session:
        job = session.get(Job, 'job')
        job.status = 'waiting_config'
        job.error = {'code': 'PROVIDER_PROFILE_STALE'}
    calls = []
    def wire(request):
        calls.append(request)
        assert str(request.url) == frozen['endpoint']
        assert request.headers['authorization'] == 'Bearer synthetic-key-A'
        return wire_response(request, 'chat_completions')
    intercept(monkeypatch, wire)
    lease = claim(db)
    assert lease is not None and lease.job_id == 'job'
    execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.get(Task, lease.task_id).status == 'succeeded'
        assert session.get(Job, 'job').status != 'waiting_config'
        assert session.scalar(select(Permit)).state == 'settled'
    assert len(calls) == 1


def test_provider_preparation_uses_frozen_settings_after_rotation(database, monkeypatch, tmp_path):
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'provider-settings'))
    base = copy.deepcopy(PROFILE) | {'endpoint': 'http://127.0.0.1:11434/synthetic-A',
        'api_protocol': 'chat_completions', 'auth_mode': 'bearer', 'cost_control_enabled': True}
    save_configuration(base, 'synthetic-key-A', False, '"0"', 'prepare-A')
    frozen = managed_profile()
    setup_library(db, cfg)
    with db.transaction() as session:
        job = session.get(Job, 'job')
        job.payload = job.payload | {'profile': frozen} | freeze_options({'mode': 'provider'}, frozen)
    execute_translation(db, cfg, claim(db))
    preparation = claim(db)
    assert preparation.payload['phase'] == 'preparation'
    updated = base | {'endpoint': 'http://127.0.0.1:11434/synthetic-B'}
    save_configuration(updated, 'synthetic-key-B', False, '"1"', 'prepare-B')
    calls = []
    def wire(request):
        calls.append(request)
        assert str(request.url) == frozen['endpoint']
        assert request.headers['authorization'] == 'Bearer synthetic-key-A'
        return httpx.Response(200, json={'model': frozen['model_id'], 'choices': [{'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': '{"summary":[],"terms":[]}'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    def factory(key_file=None, **kwargs):
        return OpenAIResponses(key_file, httpx.MockTransport(wire), **kwargs)
    monkeypatch.setattr('packages.providers.openai_responses.OpenAIResponses', factory)
    execute_translation(db, cfg, preparation)
    with db.transaction() as session:
        job = session.get(Job, 'job')
        assert job.progress['preparation_status'] == 'completed'
        assert session.scalar(select(Permit)).state == 'settled'
        assert job.status != 'waiting_config'
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
