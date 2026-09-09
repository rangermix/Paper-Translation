"""Native protocol dispatch through real PostgreSQL jobs, using synthetic HTTP."""
from copy import deepcopy
import json

import httpx
import pytest
from sqlalchemy import func, select

from packages.domain.models import Job, Permit, SegmentVersion, Task
from packages.jobs.queue import claim
from packages.providers.native import NativeProvider
from packages.providers.settings import managed_profile, save_configuration
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import PROFILE, setup_library
from tests.unit.test_claude_messages import PRICE, response as claude_response
from tests.unit.test_gemini_interactions import response as gemini_response

pytestmark = pytest.mark.postgres


def prepare(database, monkeypatch, tmp_path, protocol, auth='api_key'):
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path/'native-config'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(tmp_path/'no-external-profile'))
    profile = deepcopy(PROFILE) | {'provider': 'gemini' if protocol == 'gemini_interactions' else 'anthropic',
        'api_protocol': protocol, 'auth_mode': auth, 'endpoint': 'http://127.0.0.1:19009/native-A', 'price': PRICE, 'cost_control_enabled': True}
    save_configuration(profile, 'synthetic-native-A' if auth == 'api_key' else None, auth == 'none', '"0"', 'initial')
    frozen = managed_profile()
    setup_library(db, cfg)
    with db.transaction() as session:
        job = session.get(Job, 'job'); job.payload = job.payload | {'profile': frozen}
    execute_translation(db, cfg, claim(db))
    return db, cfg, frozen


def intercept(monkeypatch, handler, after_bind=None):
    def factory(profile, key_file):
        instance = NativeProvider(profile, key_file, httpx.MockTransport(handler))
        if after_bind: after_bind()
        return instance
    monkeypatch.setattr('packages.translation.execution.NativeProvider', factory)


def response_for(request, protocol):
    body = json.loads(request.content)
    payload = json.loads(body['input'] if protocol == 'gemini_interactions' else body['messages'][0]['content'])
    unit = payload['units'][0]
    output = json.dumps({'results': [{'unit_id': unit['unit_id'], 'target_inline': unit['source_inline']}]})
    if protocol == 'gemini_interactions':
        value = gemini_response(model=body['model'], steps=[{'type': 'model_output', 'content': [{'type': 'text', 'text': output}]}])
    else:
        value = claude_response(model=body['model'], content=[{'type': 'text', 'text': output}])
    return value


@pytest.mark.parametrize('protocol', ['gemini_interactions', 'claude_messages'])
@pytest.mark.parametrize('auth', ['api_key', 'none'])
def test_native_job_uses_matching_header_schema_and_settles_cached_thinking_usage(database, monkeypatch, tmp_path, protocol, auth):
    db, cfg, frozen = prepare(database, monkeypatch, tmp_path, protocol, auth); calls = []
    def wire(request):
        calls.append(request)
        assert str(request.url) == frozen['endpoint'] and 'authorization' not in request.headers
        own = 'x-goog-api-key' if protocol == 'gemini_interactions' else 'x-api-key'
        other = 'x-api-key' if protocol == 'gemini_interactions' else 'x-goog-api-key'
        assert request.headers.get(own) == ('synthetic-native-A' if auth == 'api_key' else None)
        assert other not in request.headers
        if protocol == 'claude_messages': assert request.headers['anthropic-version'] == '2023-06-01'
        return httpx.Response(200, json=response_for(request, protocol), headers={'request-id': 'claude-wire-id', 'x-request-id': 'gemini-wire-id'})
    intercept(monkeypatch, wire)
    lease = claim(db); execute_translation(db, cfg, lease)
    with db.transaction() as session:
        permit = session.scalar(select(Permit))
        assert permit.state == 'settled' and permit.actual_micro == (157 if protocol == 'gemini_interactions' else 164)
        assert session.get(Task, lease.task_id).status == 'succeeded'
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 1
    assert len(calls) == 1


@pytest.mark.parametrize('protocol', ['gemini_interactions', 'claude_messages'])
def test_native_rotation_keeps_inflight_key_and_blocks_later_stale_unit(database, monkeypatch, tmp_path, protocol):
    db, cfg, frozen = prepare(database, monkeypatch, tmp_path, protocol); calls = []
    def rotate():
        new = {k: v for k, v in frozen.items() if k not in ('config_revision', 'credential_revision')}
        new['endpoint'] = 'http://127.0.0.1:19009/native-B'
        save_configuration(new, 'synthetic-native-B', False, '"1"', 'rotate')
    def wire(request):
        calls.append(request)
        assert str(request.url) == frozen['endpoint']
        assert request.headers['x-goog-api-key' if protocol == 'gemini_interactions' else 'x-api-key'] == 'synthetic-native-A'
        return httpx.Response(200, json=response_for(request, protocol))
    intercept(monkeypatch, wire, rotate)
    execute_translation(db, cfg, claim(db))
    execute_translation(db, cfg, claim(db))
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.get(Job, 'job').error['code'] == 'PROVIDER_PROFILE_STALE'
        assert session.scalar(select(func.count()).select_from(Permit)) == 1
    assert len(calls) == 1


@pytest.mark.parametrize('mode', ['missing_usage', 'cache_write', 'empty_refusal', 'server_tool'])
def test_unconfirmed_native_billing_stops_without_target_or_retry(database, monkeypatch, tmp_path, mode):
    db, cfg, _ = prepare(database, monkeypatch, tmp_path, 'claude_messages'); calls = []
    def wire(request):
        calls.append(request); value = response_for(request, 'claude_messages')
        if mode == 'missing_usage': value.pop('usage')
        elif mode == 'cache_write': value['usage']['cache_creation_input_tokens'] = 40
        elif mode == 'empty_refusal': value.update(content=[], stop_reason='refusal')
        else: value['usage']['server_tool_use'] = {'web_search_requests': 1}
        return httpx.Response(200, json=value)
    intercept(monkeypatch, wire)
    execute_translation(db, cfg, claim(db))
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'unknown'
        assert session.get(Job, 'job').status == 'outcome_unknown'
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
    assert len(calls) == 1
    assert claim(db) is None  # Unknown billing stops all further dispatch.


@pytest.mark.parametrize('protocol', ['gemini_interactions', 'claude_messages'])
@pytest.mark.parametrize('reported', [None, 'different-model'])
def test_unbound_response_model_is_unknown_and_stops_later_dispatch(database, monkeypatch, tmp_path, protocol, reported):
    db, cfg, _ = prepare(database, monkeypatch, tmp_path, protocol); calls = []
    def wire(request):
        calls.append(request); value = response_for(request, protocol); value['model'] = reported
        return httpx.Response(200, json=value)
    intercept(monkeypatch, wire)
    execute_translation(db, cfg, claim(db))
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'unknown'
        assert session.get(Job, 'job').error['code'] == 'PROVIDER_MODEL_MISMATCH'
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
    assert len(calls) == 1
    assert claim(db) is None  # An unbound model response remains unknown.


@pytest.mark.parametrize('protocol', ['gemini_interactions', 'claude_messages'])
def test_native_semantic_review_uses_native_schema_without_rewriting_targets(client, database, monkeypatch, tmp_path, protocol):
    from packages.domain.models import Settings
    from packages.ir import digest
    from tests.support import seed_editor
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path/'native-review'))
    p = deepcopy(PROFILE) | {'provider':'gemini' if protocol == 'gemini_interactions' else 'anthropic',
        'endpoint':'http://127.0.0.1:19009/native-review', 'api_protocol':protocol,
        'auth_mode':'none', 'semantic_review_enabled':True, 'price':PRICE}
    save_configuration(p, None, True, '"0"', 'native-review-config')
    frozen = managed_profile(); seed_editor(db, cfg)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton'); settings.dispatch_disabled = False
        settings.instance_budget_micro = 1_000_000
        before = {s.id:digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
    started = client.post('/api/v1/drafts/draft_fixture/semantic-review', json={'block_ids':['p1'],
        'profile_revision':frozen['profile_revision'], 'profile_hash':digest(frozen),
        'glossary_revision':'empty-v1', 'budget_micro':1_000_000, 'external_processing_confirmed':True},
        headers={'If-Match':'"1"','Idempotency-Key':'native-review'})
    assert started.status_code == 202, started.text
    calls = []
    def wire(request):
        calls.append(request); body = json.loads(request.content)
        if protocol == 'gemini_interactions':
            assert 'issues' in body['response_format']['schema']['properties']
            assert json.loads(body['input'])['units'][0]['target_text']
            value = gemini_response(model=body['model'], steps=[{'type':'model_output','content':[{'type':'text','text':'{"issues":[]}'}]}])
        else:
            assert 'issues' in body['output_config']['format']['schema']['properties']
            assert json.loads(body['messages'][0]['content'])['units'][0]['target_text']
            value = claude_response(model=body['model'], content=[{'type':'text','text':'{"issues":[]}'}])
        return httpx.Response(200, json=value)
    intercept(monkeypatch, wire)
    while lease := claim(db): execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.get(Job, started.json()['job_id']).progress['review_completed'] is True
        assert before == {s.id:digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
        assert session.scalar(select(Permit)).actual_micro == (157 if protocol == 'gemini_interactions' else 164)
    assert len(calls) == 1


@pytest.mark.parametrize('protocol', ['gemini_interactions','claude_messages'])
def test_invalid_tracking_header_does_not_prevent_real_job_settlement(database, monkeypatch, tmp_path, protocol):
    from packages.domain.models import Attempt
    db,cfg,_=prepare(database,monkeypatch,tmp_path,protocol)
    header='x-request-id' if protocol=='gemini_interactions' else 'request-id'
    intercept(monkeypatch,lambda request:httpx.Response(200,json=response_for(request,protocol),headers={header:'r'*201}))
    lease=claim(db);execute_translation(db,cfg,lease)
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state=='settled'
        assert session.get(Attempt,lease.attempt_id).request_id is None
        assert session.get(Task,lease.task_id).status=='succeeded'


def test_nonempty_native_refusal_settles_but_never_repairs_or_falls_back(database, monkeypatch, tmp_path):
    db, cfg, _ = prepare(database, monkeypatch, tmp_path, 'claude_messages'); calls = []
    def wire(request):
        calls.append(request)
        return httpx.Response(200, json=claude_response(model=json.loads(request.content)['model'], stop_reason='refusal', content=[{'type': 'text', 'text': 'Synthetic refusal'}]))
    intercept(monkeypatch, wire)
    execute_translation(db, cfg, claim(db))
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.get(Job, 'job').status == 'pending'
        assert session.get(Job, 'job').error['code'] == 'PROVIDER_REFUSAL'
    assert len(calls) == 1
    next_unit = claim(db)
    assert next_unit is not None  # The refused unit is settled; unrelated units may continue.
