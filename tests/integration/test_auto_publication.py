"""Actual durable auto-publication workflow; FakeProvider tests mechanics only."""
import copy
from datetime import timedelta

import pytest
from sqlalchemy import select

from packages.domain.models import Artifact, Attempt, Edition, Job, Permit, Publication, Settings, SourceDraft, SourceRevision, Task, now
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.providers.contract import ProviderFailure
from packages.storage import file_hash, read_snapshot
from packages.translation.execution import execute_translation
from tests.integration.test_edition_translation import configure
from tests.integration.test_publication_lifecycle import drain, seal_and_publish
from tests.support import seed_editor
from workers.main import execute

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('blocked,retry,risk', [(False, False, False), (True, False, False), (False, True, False), (False, False, True)])
def test_authorized_auto_publish_changes_pointer_only_after_valid_full_result(client, database, monkeypatch, tmp_path, blocked, retry, risk, unknown=False):
    db, cfg = database
    if risk:
        from tests.integration.test_optional_review import seed_risk
        seed_risk(db, cfg)
    else:
        seed_editor(db, cfg)
    original_artifact, original_path = seal_and_publish(client, db, cfg, 1, 1, 'auto-original')
    original_hash = file_hash(original_path)
    drain(db, cfg)
    profile = configure(monkeypatch, tmp_path)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
        source = read_snapshot(cfg.data, session.get(SourceRevision, 'src_fixture'))
        session.add(SourceDraft(id='auto_source', document_id='doc_fixture', asset_id='source_pdf',
            source=copy.deepcopy(source), coverage={'can_translate': True, 'unresolved': []},
            evidence={'kind': 'controlled_internal_source_fixture'}))
    confirmed = client.post('/api/v1/imports/auto_source/confirm', json={'source_hash': digest(source),
        'preflight_generation': 1, 'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile), 'locale': 'zh-Hans',
        'budget_micro': 10_000_000, 'external_processing_confirmed': True, 'publish_policy': 'auto_publish'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'auto-source-confirm'})
    assert confirmed.status_code == 202, confirmed.text
    if unknown:
        with db.transaction() as session:
            planner = session.scalar(select(Task).where(Task.job_id == confirmed.json()['job_id']))
            session.add(Attempt(id='historical_unknown', task_id=planner.id, job_id=planner.job_id,
                fence=-1, control_epoch=0, state='outcome_unknown'))
            session.flush()
            session.add(Permit(id='historical_unknown_permit', attempt_id='historical_unknown', job_id=planner.job_id,
                control_epoch=0, price_snapshot=profile['price'], reserved_micro=20480, state='unknown'))
    def response(units):
        results = []
        for unit in units:
            nodes = copy.deepcopy(unit['source_inline'])
            if blocked and unit['owner_block_id'] == 'p1':
                nodes.append({'type': 'text', 'text': ' 32'})
            results.append({'unit_id': unit['unit_id'], 'target_inline': nodes})
        return {'results': results}
    provider = FakeProvider(([ProviderFailure('PROVIDER_RATE_LIMIT', 'not_executed', 2)] if retry else []) + [response] * 50)
    for _ in range(100):
        lease = claim(db)
        if lease is None:
            break
        if lease.kind == 'translate':
            execute_translation(db, cfg, lease, provider)
            if retry:
                with db.transaction() as session:
                    for task in session.scalars(select(Task).where(Task.job_id == confirmed.json()['job_id'],
                            Task.status == 'pending', Task.available_at > now())):
                        task.available_at = now() - timedelta(seconds=1)
        else:
            execute(db, cfg, lease)
    else:
        raise AssertionError('Unbounded automatic publication work.')
    with db.transaction() as session:
        edition = session.get(Edition, 'edition_fixture')
        job = session.get(Job, confirmed.json()['job_id'])
        events = list(session.scalars(select(Publication)))
        assert job.payload['publish_policy'] == 'auto_publish' and job.payload['external_processing_confirmed'] is True
        assert job.payload['confirmed_at'] and job.payload['origin'] == 'manual_ui'
        if retry:
            assert not job.error
            assert any(item['error']['code'] == 'PROVIDER_RATE_LIMIT' for item in job.progress['recovered_errors'])
            assert any(item.get('kind') == 'provider_failure' and item['code'] == 'PROVIDER_RATE_LIMIT'
                for attempt in session.scalars(select(Attempt).where(Attempt.job_id == job.id)) for item in attempt.evidence)
        if unknown:
            assert job.status == 'outcome_unknown'
            assert edition.current_artifact_id == original_artifact and len(events) == 1
            if unknown:
                assert job.error['code'] == 'OUTCOME_UNKNOWN' and session.get(Permit, 'historical_unknown_permit').state == 'unknown'
        else:
            assert job.status == ('completed_with_warnings' if blocked or risk else 'succeeded')
            assert edition.current_artifact_id != original_artifact and len(events) == 2
            published = session.get(Artifact, edition.current_artifact_id)
            assert (cfg.data / published.storage_key / 'index.html').is_file()
            assert client.get(f'/artifacts/{published.id}/index.html').status_code == 200
            if risk:
                from packages.domain.models import ReviewRecord
                assert not list(session.scalars(select(ReviewRecord)))
                assert '条件、否定或数量关系' in (cfg.data / published.storage_key / 'index.html').read_text(encoding='utf-8')
        assert job.progress['verified_blocks'] == job.progress['total_blocks']
    assert file_hash(original_path) == original_hash


def test_unknown_cost_blocks_automatic_publication_even_without_a_current_error(client, database, monkeypatch, tmp_path):
    test_authorized_auto_publish_changes_pointer_only_after_valid_full_result(client, database, monkeypatch, tmp_path,
        blocked=False, retry=False, risk=False, unknown=True)
