"""Full API confirmation/worker authorization chains; no external Provider calls.

The accepted source is an authored internal fixture. Parsing accuracy is covered
by the separately bound real-PDF corpus, not inferred from these API predicates.
"""
import copy
from datetime import datetime
import json

import httpx
import pytest
from sqlalchemy import func, select

from packages.billing.ledger import budget_totals
from packages.domain.models import Attempt, Document, Draft, Job, Permit, SegmentVersion, Settings, SourceDraft, SourceRevision, Task
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.openai_responses import ENDPOINT, OpenAIResponses
from packages.storage import file_hash, read_snapshot
from packages.translation.execution import execute_translation
from packages.translation.planner import plan_units
from tests.integration.test_edition_translation import configure
from tests.integration.test_source_revisions import evidence
from tests.support import seed_editor
from workers.main import execute

pytestmark = pytest.mark.postgres


def preflight_fixture(client, database, monkeypatch, tmp_path, coverage=None):
    db, cfg = database
    ir = seed_editor(db, cfg)
    profile = configure(monkeypatch, tmp_path)
    source = ir['source_revision']
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
        session.add(SourceDraft(id='literal_preflight', document_id='doc_fixture', asset_id='source_pdf',
            source=copy.deepcopy(source), coverage=coverage or {'can_translate': True, 'unresolved': [], 'pages': [{'page': 1}]},
            evidence={'origin': 'controlled_internal_fixture'}))
    before = client.get('/api/v1/imports/literal_preflight/preflight')
    assert before.status_code == 200
    body = {'source_hash': before.json()['source_hash'], 'preflight_generation': before.json()['generation'],
        'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile), 'locale': 'zh-Hans',
        'budget_micro': 10_000_000, 'external_processing_confirmed': True, 'publish_policy': 'manual_approval'}
    return source, profile, body, {'If-Match': before.headers['etag'], 'Idempotency-Key': 'literal-confirm'}


def test_confirm_records_exact_scope_and_source_change_invalidates_old_authorization(client, database, monkeypatch, tmp_path):
    db, cfg = database
    source, profile, body, headers = preflight_fixture(client, database, monkeypatch, tmp_path)
    confirmed = client.post('/api/v1/imports/literal_preflight/confirm', json=body, headers=headers)
    assert confirmed.status_code == 202, confirmed.text
    result = confirmed.json()
    with db.transaction() as session:
        job = session.get(Job, result['job_id'])
        payload = copy.deepcopy(job.payload)
        revision = session.get(SourceRevision, payload['source_revision_id'])
        path, old_hash = cfg.data / revision.storage_key, revision.snapshot_hash
        approved_source = read_snapshot(cfg.data, revision)
        assert payload['source_hash'] == revision.snapshot_hash == digest(approved_source)
        assert payload['source_revision_id'] == session.get(Draft, result['draft_id']).source_revision_id
        assert payload['locale'] == 'zh-Hans' and payload['external_processing_confirmed'] is True
        assert payload['profile_hash'] == digest(profile) and payload['origin'] == 'manual_ui'
        assert datetime.fromisoformat(payload['confirmed_at']).tzinfo is not None
        assert revision.metadata_json['origin'] == 'manual_ui' and revision.metadata_json['sealed_at']
        approved_id = revision.id
    # An evidence-bound source operation creates a new immutable revision through
    # the public source workbench. Historical consent stays auditable, not reusable.
    order = list(approved_source['reading_order'])
    order[1], order[2] = order[2], order[1]
    current_document = client.get('/api/v1/documents/doc_fixture')
    changed = client.post(f'/api/v1/sources/{approved_id}/corrections', json={
        'operations': [{'kind': 'reorder', 'block_ids': order}], 'evidence': evidence(approved_source),
        'reason': 'Controlled source order correction checked against original PDF'},
        headers={'If-Match': current_document.headers['etag'], 'Idempotency-Key': 'literal-source-change'})
    assert changed.status_code == 201, changed.text
    sealed = client.post('/api/v1/sources/drafts/' + changed.json()['id'] + '/confirm',
        json={'source_hash': changed.json()['source_hash']},
        headers={'If-Match': changed.headers['etag'], 'Idempotency-Key': 'literal-source-seal'})
    assert sealed.status_code == 201, sealed.text
    assert sealed.json()['source_revision_id'] != approved_id
    lease = claim(db)
    assert lease and lease.job_id == result['job_id']
    execute(db, cfg, lease)
    with db.transaction() as session:
        assert session.get(Job, result['job_id']).error['code'] == 'SOURCE_STALE'
        assert session.get(Job, result['job_id']).payload == payload
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
        assert session.scalar(select(func.count()).select_from(SegmentVersion).where(SegmentVersion.draft_id == result['draft_id'])) == 0
    assert file_hash(path) == old_hash
    replay = client.post('/api/v1/imports/literal_preflight/confirm', json=body,
        headers={**headers, 'Idempotency-Key': 'old-preflight-new-request'})
    assert replay.status_code in (409, 412)


@pytest.mark.parametrize('reason', ['unresolved_body', 'OCR_REQUIRED'])
def test_force_confirm_unresolved_or_ocr_has_no_dispatch(client, database, monkeypatch, tmp_path, reason):
    coverage = {'can_translate': False, 'unresolved': [{'page': 1, 'reason': reason}], 'pages': [{'page': 1}]}
    _, _, body, headers = preflight_fixture(client, database, monkeypatch, tmp_path, coverage)
    result = client.post('/api/v1/imports/literal_preflight/confirm', json=body, headers=headers)
    assert result.status_code == 202
    assert claim(database[0]).kind == 'translate'
    with database[0].transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        assert session.scalar(select(func.count()).select_from(Permit)) == 0


def test_confirmed_source_only_is_sent_by_production_adapter(client, database, monkeypatch, tmp_path):
    db, cfg = database
    _, profile, body, headers = preflight_fixture(client, database, monkeypatch, tmp_path)
    confirmed = client.post('/api/v1/imports/literal_preflight/confirm', json=body, headers=headers)
    assert confirmed.status_code == 202, confirmed.text
    result = confirmed.json()
    with db.transaction() as session:
        job = session.get(Job, result['job_id'])
        approved = read_snapshot(cfg.data, session.get(SourceRevision, job.payload['source_revision_id']))
        job_payload = copy.deepcopy(job.payload)
        # A separate document proves neither the library nor another source leaks
        # into the actual serialized HTTP request context.
        session.add(Document(id='unrelated_secret_doc', title='UNRELATED_DOCUMENT_MUST_NOT_BE_SENT'))
    expected = {u['unit_id']: u for u in plan_units(approved, 'zh-Hans', job_payload['profile'])}
    sent = []
    key_file = tmp_path / 'synthetic-key'
    key_file.write_text('TEST_ONLY_NO_NETWORK', encoding='utf-8')
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(key_file))

    def wire(request):
        assert str(request.url) == ENDPOINT
        assert b'UNRELATED_DOCUMENT_MUST_NOT_BE_SENT' not in request.content
        request_body = json.loads(request.content)
        assert request_body['tools'] == [] and request_body['tool_choice'] == 'none'
        content = json.loads(request_body['input'][0]['content'][0]['text'])
        assert content['target_locale'] == 'zh-Hans' and content['glossary'] == []
        rows = []
        for actual in content['units']:
            expected_unit = expected[actual['unit_id']]
            assert actual == {k: expected_unit[k] for k in ('unit_id', 'source_language', 'source_inline', 'protected_atoms', 'context')}
            sent.append(actual['unit_id'])
            rows.append({'unit_id': actual['unit_id'], 'target_inline': actual['source_inline']})
        return httpx.Response(200, headers={'x-request-id': 'scope-' + str(len(sent))}, json={
            'status': 'completed', 'model': profile['model_id'], 'usage': {'input_tokens': 100, 'output_tokens': 50},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'results': rows})}]}]})

    # Keep production profile/key selection enabled; inject only the HTTP wire.
    monkeypatch.setattr('packages.translation.execution.OpenAIResponses', lambda key: OpenAIResponses(key, httpx.MockTransport(wire)))
    while lease := claim(db):
        execute_translation(db, cfg, lease)
    assert sorted(sent) == sorted(expected)
    with db.transaction() as session:
        assert session.get(Job, result['job_id']).payload == job_payload
        permits = list(session.scalars(select(Permit)))
        assert len(permits) == len(sent) and all(p.state == 'settled' for p in permits)
        assert all(session.get(Attempt, p.attempt_id).request_id.startswith('scope-') for p in permits)


@pytest.mark.parametrize('failure', ['missing_price_bound', 'insufficient_budget', 'changed_price'])
def test_untrusted_or_changed_price_and_insufficient_balance_stop_before_http(client, database, monkeypatch, tmp_path, failure):
    db, cfg = database
    _, profile, body, headers = preflight_fixture(client, database, monkeypatch, tmp_path)
    if failure == 'missing_price_bound':
        invalid = copy.deepcopy(profile)
        invalid['price'].pop('output_includes_reasoning')
        (tmp_path / 'profile.json').write_text(json.dumps(invalid), encoding='utf-8')
        result = client.post('/api/v1/imports/literal_preflight/confirm', json=body, headers=headers)
        assert result.status_code == 409 and result.json()['error']['code'] == 'PROVIDER_CONFIG'
        assert claim(db) is None
    else:
        result = client.post('/api/v1/imports/literal_preflight/confirm', json=body, headers=headers)
        assert result.status_code == 202, result.text
        execute_translation(db, cfg, claim(db))  # Local planner requires no key.
        if failure == 'changed_price':
            changed = copy.deepcopy(profile)
            changed['price']['output_micro_per_million'] += 1
            (tmp_path / 'profile.json').write_text(json.dumps(changed), encoding='utf-8')
        else:
            with db.transaction() as session:
                session.get(Settings, 'singleton').instance_budget_micro = 1
        key_file = tmp_path / 'unused-key'
        key_file.write_text('SYNTHETIC_UNUSED', encoding='utf-8')
        monkeypatch.setenv('PROVIDER_KEY_FILE', str(key_file))
        def forbidden_wire(request):
            pytest.fail('Blocked dispatch reached the HTTP transport')
        monkeypatch.setattr('packages.translation.execution.OpenAIResponses', lambda key: OpenAIResponses(key, httpx.MockTransport(forbidden_wire)))
        execute_translation(db, cfg, claim(db))
        with db.transaction() as session:
            job = session.get(Job, result.json()['job_id'])
            assert job.status == ('waiting_config' if failure == 'changed_price' else 'waiting_budget')
            assert job.error['code'] == ('PROVIDER_PROFILE_STALE' if failure == 'changed_price' else 'BUDGET_PAUSED')
            assert job.payload['profile']['price'] == profile['price']
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
        assert budget_totals(session) == {'actual_micro': 0, 'reserved_micro': 0, 'unknown_micro': 0}
