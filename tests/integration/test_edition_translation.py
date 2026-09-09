import copy
import json
from sqlalchemy import func, select
import pytest

from packages.domain.models import Document, Draft, Edition, Job, Settings, SourceDraft, SourceRevision, Task
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.storage import read_snapshot
from packages.translation.execution import execute_translation
from tests.support import seed_editor
from tests.integration.test_translation_execution import PROFILE

pytestmark = pytest.mark.postgres


def configure(monkeypatch, tmp_path, locales=('zh-Hans',)):
    profile = copy.deepcopy(PROFILE)
    profile['enabled_pairs'] = [['en', locale] for locale in locales]
    file = tmp_path/'profile.json'
    file.write_text(json.dumps(profile), encoding='utf-8')
    monkeypatch.setenv('PROVIDER_PROFILE_FILE', str(file))
    return profile


def prepared(client, database, monkeypatch, tmp_path):
    db, cfg = database
    seed_editor(db, cfg)
    configure(monkeypatch, tmp_path)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled = False
        settings.instance_budget_micro = 10_000_000
        # Existing fixture edition is renamed only inside this test's database to
        # simulate an existing translation of another locale without duplicating its targets.
        session.get(Edition, 'edition_fixture').target_locale = 'en'
        session.flush()
        session.add(Edition(id='new_edition', document_id='doc_fixture', target_locale='zh-Hans'))
        source = session.get(SourceRevision, 'src_fixture')
        body = {'source_revision_id': source.id, 'source_hash': source.snapshot_hash, 'profile_revision': PROFILE['profile_revision'], 'profile_hash': digest(PROFILE),
            'budget_micro': 10_000_000, 'external_processing_confirmed': True, 'publish_policy': 'manual_approval'}
    return body


def test_existing_source_starts_new_locale_without_parser_or_source_revision(client, database, monkeypatch, tmp_path):
    body = prepared(client, database, monkeypatch, tmp_path)
    db, cfg = database
    fetched = client.get('/api/v1/editions/new_edition/preflight')
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()['source_hash'] == body['source_hash']
    assert fetched.json()['estimated_cost_micro'] > 0
    headers = {'If-Match': fetched.headers['etag'], 'Idempotency-Key': 'new-locale'}
    started = client.post('/api/v1/editions/new_edition/translate', json=body, headers=headers)
    assert started.status_code == 202, started.text
    replay = client.post('/api/v1/editions/new_edition/translate', json=body, headers=headers)
    assert replay.json() == started.json()
    stale = client.post('/api/v1/editions/new_edition/translate', json=body, headers={**headers, 'Idempotency-Key': 'other-request'})
    assert stale.status_code == 412
    provider = FakeProvider()
    key_file = tmp_path/'test-provider-key'
    key_file.write_text('test-only-never-sent', encoding='utf-8')
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(key_file))
    factories = []
    def fake_factory(key):
        factories.append(key)
        return provider
    monkeypatch.setattr('packages.translation.execution.OpenAIResponses', fake_factory)
    while lease := claim(db):
        execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(SourceRevision)) == 1
        assert session.scalar(select(func.count()).select_from(SourceDraft)) == 0
        assert all(task.kind in {'translate', 'quality_check'} for task in session.scalars(select(Task)))
        draft = session.get(Draft, started.json()['draft_id'])
        assert draft.source_revision_id == 'src_fixture'
        assert session.get(Job, started.json()['job_id']).status in ('succeeded', 'completed_with_warnings')
    assert provider.calls
    assert factories, 'The exact production profile/secret selection path must accept derived glossary fields.'


@pytest.mark.parametrize('changed,expected', [({'source_hash': '0'*64}, 'SOURCE_STALE'),
    ({'external_processing_confirmed': False}, 'EXTERNAL_PROCESSING_UNCONFIRMED'),
    ({'profile_revision': 'stale'}, 'PROFILE_STALE')])
def test_existing_source_translation_rejects_stale_authorization(client, database, monkeypatch, tmp_path, changed, expected):
    body = prepared(client, database, monkeypatch, tmp_path)
    rejected = client.post('/api/v1/editions/new_edition/translate', json=body|changed,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'invalid'})
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == expected, rejected.text
    with database[0].transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize('marker,expected', [({'superseded_by': 'new-source-draft'}, 'SOURCE_BASE_STALE'),
    ({'sealed_revision_id': 'already-sealed'}, 'SOURCE_ALREADY_SEALED'), ({'document_generation': 999}, 'SOURCE_BASE_STALE')])
def test_import_confirmation_rejects_reused_or_stale_draft(client, database, monkeypatch, tmp_path, marker, expected):
    db, cfg = database
    seed_editor(db, cfg)
    configure(monkeypatch, tmp_path)
    with db.transaction() as session:
        source = read_snapshot(cfg.data, session.get(SourceRevision, 'src_fixture'))
        doc = session.get(Document, 'doc_fixture')
        session.add(SourceDraft(id='parsed_draft', document_id=doc.id, asset_id=doc.source_asset_id,
            source=source, coverage={'can_translate': True, 'unresolved': []}, evidence=marker))
    body = {'source_hash': digest(source), 'preflight_generation': 1, 'profile_revision': PROFILE['profile_revision'], 'profile_hash': digest(PROFILE),
        'locale': 'zh-Hans', 'budget_micro': 10_000_000, 'external_processing_confirmed': True}
    rejected = client.post('/api/v1/imports/parsed_draft/confirm', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'stale-source'})
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == expected, rejected.text
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(SourceRevision)) == 1


@pytest.mark.parametrize('language,expected', [('und', 'SOURCE_LANGUAGE_REQUIRED')])
def test_undetermined_source_language_cannot_dispatch(client, database, monkeypatch, tmp_path, language, expected):
    from packages.storage import write_snapshot
    body = prepared(client, database, monkeypatch, tmp_path)
    db, cfg = database
    with db.transaction() as session:
        revision = session.get(SourceRevision, 'src_fixture')
        source = read_snapshot(cfg.data, revision)
        source['language'] = language
        source['id'] = f'src_{language}'
        key = f'test-language-{language}.json'
        sha = write_snapshot(cfg.data, key, source)
        session.add(SourceRevision(id=source['id'], document_id=revision.document_id, asset_id=revision.asset_id,
            snapshot_hash=sha, storage_key=key, parent_id=revision.id))
        session.get(Document, revision.document_id).current_source_id = source['id']
        body['source_hash'], body['source_revision_id'] = sha, source['id']
    preflight = client.get('/api/v1/editions/new_edition/preflight')
    assert preflight.json()['can_translate'] is True
    rejected = client.post('/api/v1/editions/new_edition/translate', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'unknown-language'})
    assert rejected.status_code == 202
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_cancel_during_provider_return_settles_but_cannot_write_or_resume(client, database, monkeypatch, tmp_path):
    from packages.domain.models import Permit, SegmentVersion
    body = prepared(client, database, monkeypatch, tmp_path)
    db, cfg = database
    started = client.post('/api/v1/editions/new_edition/translate', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'will-cancel'}).json()
    execute_translation(db, cfg, claim(db), FakeProvider())
    lease = claim(db)
    def cancel_then_return(units):
        fetched = client.get('/api/v1/jobs/'+started['job_id'])
        cancelled = client.post('/api/v1/jobs/'+started['job_id']+'/cancel', json={},
            headers={'If-Match': fetched.headers['etag'], 'Idempotency-Key': 'cancel'})
        assert cancelled.status_code == 202
        return {'results': [{'unit_id': u['unit_id'], 'target_inline': u['source_inline']} for u in units]}
    provider = FakeProvider([cancel_then_return])
    execute_translation(db, cfg, lease, provider)
    assert claim(db) is None and len(provider.calls) == 1
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.scalar(select(func.count()).select_from(SegmentVersion).where(SegmentVersion.draft_id == started['draft_id'])) == 0
        assert session.get(Job, started['job_id']).status == 'cancelled'
    fetched = client.get('/api/v1/jobs/'+started['job_id'])
    resumed = client.post('/api/v1/jobs/'+started['job_id']+'/resume', json={},
        headers={'If-Match': fetched.headers['etag'], 'Idempotency-Key': 'resume-cancelled'})
    assert resumed.status_code == 409


@pytest.mark.parametrize('new_glossary', [False, True])
def test_new_semantic_evidence_invalidates_old_qa_without_editing_text(client, database, monkeypatch, tmp_path, new_glossary):
    from packages.domain.models import Candidate, ReviewRecord, SegmentVersion
    from packages.ir import flatten_inline
    db, cfg = database
    seed_editor(db, cfg)
    profile = configure(monkeypatch, tmp_path) | {'semantic_review_enabled': True}
    (tmp_path/'profile.json').write_text(json.dumps(profile), encoding='utf-8')
    terms = [{'source': 'tokens', 'target': 'token', 'mode': 'must', 'variants': []}] if new_glossary else []
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
        if new_glossary:
            segment = session.get(SegmentVersion, 'seg_p1')
            source = session.get(SourceRevision, 'src_fixture')
            session.add(Candidate(id='candidate_review', draft_id='draft_fixture', status='ready',
                base={'source_revision_id': source.id, 'source_hash': source.snapshot_hash, 'glossary_revision': 'empty-v1',
                    'requested_glossary_revision': 'new-terms-v1', 'glossary_entries': terms, 'profile': profile,
                    'segments': {'p1': {'version': 1, 'source_hash': segment.source_hash, 'context_hash': segment.context_hash, 'reviewed': False}}},
                results={'p1': segment.target_inline}))
    generation = 1
    if new_glossary:
        accepted = client.post('/api/v1/candidates/candidate_review/accept', json={'block_ids': ['p1']},
            headers={'If-Match': '"1"', 'Idempotency-Key': 'accept-new-terms'})
        assert accepted.status_code == 200, accepted.text
        generation = accepted.json()['draft_generation']
    etag = f'"{generation}"'
    with db.transaction() as session:
        before = {s.id: digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': etag, 'Idempotency-Key': 'qa-before-review'})
    assert qa.status_code == 200 and qa.json()['valid']
    review = client.post('/api/v1/drafts/draft_fixture/semantic-review', json={'block_ids': ['p1'],
        'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile), 'glossary_revision': 'empty-v1',
        'budget_micro': 10_000_000, 'external_processing_confirmed': True},
        headers={'If-Match': etag, 'Idempotency-Key': 'semantic-review'})
    assert review.status_code == 202, review.text
    class IssueProvider(FakeProvider):
        def review(self, units, profile, glossary):
            assert glossary == terms
            result = super().review(units, profile, glossary)
            unit = units[0]
            result['output_text'] = json.dumps({'issues': [{'unit_id': unit['unit_id'], 'rule': 'quantity',
                'severity': 'high', 'source_quote': flatten_inline(unit['source_inline'], unit['protected_atoms']),
                'target_quote': unit['review_target_text'], 'explanation': 'Controlled test issue requiring source comparison.'}]})
            return result
    provider = IssueProvider()
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    old_seal = client.post('/api/v1/drafts/draft_fixture/seal', json={'qa_id': qa.json()['id'],
        'qa_fingerprint': qa.json()['fingerprint'], 'generation': generation},
        headers={'If-Match': etag, 'Idempotency-Key': 'old-qa-cannot-seal'})
    assert old_seal.status_code == 201, old_seal.text
    current = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': etag, 'Idempotency-Key': 'qa-after-review'})
    assert current.status_code == 200 and current.json()['quality']['state'] == 'completed', current.text
    assert 'SEMANTIC_QUANTITY' in {i['code'] for i in current.json()['issues']}
    with db.transaction() as session:
        assert before == {s.id: digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
        assert session.scalar(select(func.count()).select_from(ReviewRecord)) == 0


def test_mixed_document_retains_declared_target_language_block_without_dispatch(client, database, monkeypatch, tmp_path):
    from packages.domain.models import SegmentVersion
    from packages.editorial.drafts import run_quality, translation_snapshot
    from packages.ir import block_hash
    from packages.storage import write_snapshot
    body = prepared(client, database, monkeypatch, tmp_path)
    db, cfg = database
    with db.transaction() as session:
        old = session.get(SourceRevision, 'src_fixture')
        source = read_snapshot(cfg.data, old)
        source['id'] = 'src_mixed'
        block = next(b for b in source['blocks'] if b['id'] == 'p2')
        block['language'] = 'zh-Hans'
        block['source_hash'] = block_hash(block, source['protected_atoms'])
        key = 'test-mixed-source.json'
        sha = write_snapshot(cfg.data, key, source)
        session.add(SourceRevision(id=source['id'], document_id=old.document_id, asset_id=old.asset_id,
            snapshot_hash=sha, storage_key=key, parent_id=old.id))
        session.get(Document, old.document_id).current_source_id = source['id']
        body['source_hash'], body['source_revision_id'] = sha, source['id']
    started = client.post('/api/v1/editions/new_edition/translate', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'mixed-source'})
    assert started.status_code == 202, started.text
    provider = FakeProvider()
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    assert not any(u['owner_block_id'] == 'p2' for units in provider.calls for u in units)
    with db.transaction() as session:
        draft = session.get(Draft, started.json()['draft_id'])
        result = next(r for r in translation_snapshot(session, cfg, draft)['results'] if r['block_id'] == 'p2')
        assert result['status'] == 'retained' and result['reason'] == 'same_language' and result['target_inline'] == []
        assert not session.scalar(select(SegmentVersion).where(SegmentVersion.draft_id == draft.id, SegmentVersion.block_id == 'p2'))
        qa = run_quality(session, cfg, draft)
        assert not any(i['code'] == 'MISSING_TRANSLATION' and i['block_id'] == 'p2' for i in qa.issues)


def test_delete_before_late_response_cannot_resurrect_checkpoint(client, database, monkeypatch, tmp_path):
    from packages.domain.models import Attempt, Permit
    from workers.main import execute
    body = prepared(client, database, monkeypatch, tmp_path)
    db, cfg = database
    started = client.post('/api/v1/editions/new_edition/translate', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'will-delete'}).json()
    execute_translation(db, cfg, claim(db), FakeProvider())
    lease = claim(db)
    def delete_then_return(units):
        document = client.get('/api/v1/documents/doc_fixture')
        deleted = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True},
            headers={'If-Match': document.headers['etag']})
        assert deleted.status_code == 202, deleted.text
        cleanup = claim(db)
        assert cleanup.kind == 'cleanup'
        execute(db, cfg, cleanup)
        return {'results': [{'unit_id': u['unit_id'], 'target_inline': u['source_inline']} for u in units]}
    provider = FakeProvider([delete_then_return])
    execute_translation(db, cfg, lease, provider)
    with db.transaction() as session:
        attempt = session.get(Attempt, lease.attempt_id)
        assert not any(e.get('kind') == 'validated_unit' for e in attempt.evidence)
        assert session.scalar(select(Permit).where(Permit.attempt_id == attempt.id)).state == 'settled'
        assert session.get(Document, 'doc_fixture').deleted_at is not None
    assert len(provider.calls) == 1
