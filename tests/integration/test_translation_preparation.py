import copy
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from packages.domain.models import Attempt, Document, Draft, Job, Permit, ReviewRecord, SegmentVersion, Settings, Task, new_id, now
from packages.ir import digest
from packages.jobs.queue import claim, recover_expired
from packages.providers.contract import ProviderFailure
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from test_translation_execution import setup_library

pytestmark = pytest.mark.postgres


def enable(db, mode):
    with db.transaction() as session:
        job = session.get(Job, 'job')
        from packages.preparation import freeze_options
        job.payload = job.payload | freeze_options({'mode': mode}, job.payload['profile'])


class Analyst:
    def __init__(self, callback=None):
        self.calls = 0
        self.callback = callback

    def translate(self, units, profile, glossary):
        self.calls += 1
        if self.callback:
            value = self.callback(units)
        else:
            evidence = units[0]['content']['evidence'][0]
            value = {'summary': [{'text': 'The paper describes a publication contract.', 'evidence_ids': [evidence['id']]}], 'terms': []}
        return {'status': 'completed', 'output_text': json.dumps(value), 'usage': {'input_tokens': 100, 'output_tokens': 50},
                'request_id': 'analysis-fixture', 'response_model': profile['model_id']}

    def analyze(self, content, profile, instructions, schema):
        return self.translate([{'content': content}], profile, [])


def test_extractive_freezes_context_without_extra_model_call(database):
    db, cfg = database
    source = setup_library(db, cfg)
    before = copy.deepcopy(source)
    enable(db, 'extractive')
    provider = FakeProvider()
    execute_translation(db, cfg, claim(db), provider)
    assert provider.calls == [] and source == before
    with db.transaction() as session:
        job, draft = session.get(Job, 'job'), session.get(Draft, 'draft')
        pack = job.payload['preparation']
        assert pack['source_hash'] == digest(source)
        assert pack == draft.profile['preparation']
        units = [t.payload['unit'] for t in session.scalars(select(Task)) if 'unit' in t.payload]
        assert all(u['preparation_revision'] == pack['revision'] for u in units)
        assert all(u['context']['paper']['revision'] == pack['revision'] for u in units)
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    with db.transaction() as session:
        assert all(s.provenance_json['preparation_revision'] == pack['revision'] for s in session.scalars(select(SegmentVersion)))


def test_model_preparation_is_accounted_before_fanout(database):
    db, cfg = database
    setup_library(db, cfg); enable(db, 'provider')
    execute_translation(db, cfg, claim(db))
    lease = claim(db)
    assert lease.payload['phase'] == 'preparation'
    analyst = Analyst()
    execute_translation(db, cfg, lease, analyst)
    execute_translation(db, cfg, claim(db), FakeProvider())
    with db.transaction() as session:
        job = session.get(Job, 'job')
        assert job.payload['preparation']['summary']
        assert job.progress['preparation_status'] == 'completed'
        assert job.progress['requests'] == 1
        assert session.scalar(select(Permit)).state == 'settled'
        assert list(session.scalars(select(Task).where(Task.status == 'pending')))
    assert analyst.calls == 1


def test_invalid_suggestion_falls_back_but_unknown_dispatch_does_not(database):
    db, cfg = database
    setup_library(db, cfg); enable(db, 'provider')
    execute_translation(db, cfg, claim(db))
    execute_translation(db, cfg, claim(db), Analyst(lambda _: {'summary': [{'text': 'Invented', 'evidence_ids': ['missing']}], 'terms': []}))
    with db.transaction() as session:
        pack = session.get(Job, 'job').payload['preparation']
        assert pack['summary'] == [] and 'PREPARATION_EVIDENCE' in pack['warnings']
        assert session.scalar(select(Permit)).state == 'settled'


def test_preparation_unknown_response_blocks_resend(database):
    db, cfg = database
    setup_library(db, cfg); enable(db, 'provider')
    execute_translation(db, cfg, claim(db))
    def timeout(_):
        raise ProviderFailure('OUTCOME_UNKNOWN', 'unknown')
    analyst = Analyst(timeout)
    execute_translation(db, cfg, claim(db), analyst)
    assert claim(db) is None and analyst.calls == 1
    with db.transaction() as session:
        assert session.get(Job, 'job').status == 'outcome_unknown'
        assert session.scalar(select(Permit)).state == 'unknown'


def test_paid_preparation_checkpoint_survives_pause_without_resend(database):
    db, cfg = database
    setup_library(db, cfg); enable(db, 'provider')
    execute_translation(db, cfg, claim(db))
    lease = claim(db)
    def pause(_):
        with db.transaction() as session:
            job = session.get(Job, 'job'); job.status = 'paused'; job.control_epoch += 1
        return {'summary': [], 'terms': []}
    analyst = Analyst(pause)
    execute_translation(db, cfg, lease, analyst)
    with db.transaction() as session:
        assert 'preparation' not in session.get(Job, 'job').payload
        assert any(e['kind'] == 'validated_preparation' for e in session.get(Attempt, lease.attempt_id).evidence)
        session.get(Task, lease.task_id).lease_expires = now() - timedelta(seconds=1)
    recover_expired(db)
    with db.transaction() as session:
        session.get(Job, 'job').status = 'pending'
    execute_translation(db, cfg, claim(db), analyst)
    assert analyst.calls == 1
    with db.transaction() as session:
        assert 'preparation' in session.get(Job, 'job').payload


def test_local_analyst_has_separate_frozen_billing_profile(database):
    db, cfg = database
    setup_library(db, cfg); enable(db, 'local')
    execute_translation(db, cfg, claim(db))
    lease = claim(db)
    execute_translation(db, cfg, lease, Analyst())
    with db.transaction() as session:
        job = session.get(Job, 'job')
        assert job.payload['profile']['provider'] == 'openai'
        assert job.payload['analysis_profile']['provider'] == 'local'
        permit = session.scalar(select(Permit))
        assert permit.state == 'settled' and permit.price_snapshot['cost_control_enabled'] is False
        assert session.get(Attempt, lease.attempt_id).actual_model['kind'] == 'local'


@pytest.mark.parametrize('control', ['cancel', 'delete', 'maintenance', 'source'])
def test_late_preparation_obeys_content_fences_and_still_settles(database, control):
    db, cfg = database
    setup_library(db, cfg); enable(db, 'provider')
    execute_translation(db, cfg, claim(db))
    lease = claim(db)
    def changed(_):
        with db.transaction() as session:
            if control == 'cancel':
                job = session.get(Job, 'job'); job.status = 'cancelled'; job.control_epoch += 1
            elif control == 'delete':
                session.get(Document, 'doc').deleted_at = now()
            elif control == 'maintenance':
                session.get(Settings, 'singleton').maintenance = True
            else:
                session.get(Document, 'doc').current_source_id = None
        return {'summary': [], 'terms': []}
    analyst = Analyst(changed)
    execute_translation(db, cfg, lease, analyst)
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'settled'
        assert 'preparation' not in session.get(Draft, 'draft').profile
        assert 'preparation' not in session.get(Job, 'job').payload
        assert not any('unit' in t.payload for t in session.scalars(select(Task)))
        if control == 'delete':
            assert not any(e.get('kind') == 'validated_preparation' for e in session.get(Attempt, lease.attempt_id).evidence)
    assert analyst.calls == 1


def test_preparation_budget_wait_happens_before_any_request(database):
    db, cfg = database
    setup_library(db, cfg); enable(db, 'provider')
    with db.transaction() as session:
        session.get(Job, 'job').budget_micro = 1
    execute_translation(db, cfg, claim(db))
    analyst = Analyst()
    execute_translation(db, cfg, claim(db), analyst)
    assert analyst.calls == 0
    with db.transaction() as session:
        assert session.get(Job, 'job').status == 'waiting_budget'
        assert not list(session.scalars(select(Permit)))


@pytest.mark.parametrize('poll', [False, True])
def test_source_change_during_local_model_preparation_cannot_dispatch(database, monkeypatch, poll):
    from packages.domain.errors import DomainError
    from packages.providers.local_analysis import LocalAnalysis
    from tests.integration.test_translation_execution import PROFILE
    db, cfg = database
    setup_library(db, cfg); enable(db, 'local')
    execute_translation(db, cfg, claim(db))
    analyst = Analyst()
    def prepare(self, profile, check_current):
        with db.transaction() as session:
            session.get(Document, 'doc').current_source_id = None
        if poll:
            check_current()
    monkeypatch.setattr('packages.preparation.execution.provider_profile', lambda: PROFILE)
    monkeypatch.setattr(LocalAnalysis, 'prepare', prepare)
    monkeypatch.setattr(LocalAnalysis, 'analyze', lambda self, *args: analyst.analyze(*args))
    with pytest.raises(DomainError) as error:
        execute_translation(db, cfg, claim(db))
    assert error.value.code == 'SOURCE_STALE'
    assert analyst.calls == 0
    with db.transaction() as session:
        assert not list(session.scalars(select(Permit)))


def test_no_preparation_model_call_when_all_translation_units_already_exist(database):
    db, cfg = database
    source = setup_library(db, cfg); enable(db, 'provider')
    with db.transaction() as session:
        for block in source['blocks']:
            if block['translatable']:
                session.add(SegmentVersion(id=new_id('seg'), draft_id='draft', block_id=block['id'], sequence=1,
                    target_inline=block['source_inline'], origin='manual_ui', context_hash='a'*64,
                    source_hash=block['source_hash'], reason='Existing translation'))
    execute_translation(db, cfg, claim(db))
    with db.transaction() as session:
        assert not any(t.payload.get('phase') == 'preparation' for t in session.scalars(select(Task)))
        assert session.get(Job, 'job').status in {'succeeded', 'completed_with_warnings'}


def test_generated_terms_have_source_evidence_and_nonblocking_quality_findings(database):
    from packages.editorial.drafts import run_quality, seal
    db, cfg = database
    setup_library(db, cfg); enable(db, 'provider')
    execute_translation(db, cfg, claim(db))
    def proposed(units):
        evidence = next(e for e in units[0]['content']['evidence'] if 'tokens' in e['quote'])
        return {'summary': [], 'terms': [{'concept_id': '', 'source': 'tokens', 'target': '词元',
            'evidence_ids': [evidence['id']]}]}
    execute_translation(db, cfg, claim(db), Analyst(proposed))
    provider = FakeProvider()
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    with db.transaction() as session:
        draft = session.get(Draft, 'draft')
        qa = run_quality(session, cfg, draft)
        findings = [i for i in qa.issues if i['code'] == 'TERM_PREFERRED']
        assert findings and all(not i['blocking'] for i in findings)
        assert all(i['evidence']['term']['concept_id'] and i['evidence']['term']['evidence_ids'] for i in findings)
        assert not list(session.scalars(select(ReviewRecord)))
        assert seal(session, cfg, draft, qa.id, qa.fingerprint)
