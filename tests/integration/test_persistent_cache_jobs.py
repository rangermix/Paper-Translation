"""New real API jobs use durable cache only for equivalent frozen inputs.

FakeProvider proves local identity/accounting behavior, never model quality.
"""
import copy
import json

import pytest
from sqlalchemy import func, select

from packages.domain.models import (Attempt, Candidate, Document, Draft, Edition, Job,
    Permit, Settings, SourceRevision, Task, TranslationCache)
from packages.ir import block_hash, digest, validate_source
from packages.jobs.queue import claim
from packages.privacy import cleanup_document
from packages.providers.fake import FakeProvider
from packages.storage import write_snapshot
from packages.translation.execution import execute_translation
from tests.integration.test_edition_translation import configure
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def candidate_job(client, db, cfg, draft_id, document_id, profile, provider, key):
    terms = client.get('/api/v1/glossaries/effective', params={'document_id': document_id,
        'source_language': 'en', 'target_language': 'zh-Hans'}).json()
    draft = client.get('/api/v1/drafts/' + draft_id)
    created = client.post('/api/v1/drafts/' + draft_id + '/candidates', json={
        'block_ids': ['p1'], 'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile),
        'glossary_revision': terms['revision'], 'budget_micro': 1_000_000,
        'external_processing_confirmed': True}, headers={'If-Match': draft.headers['etag'], 'Idempotency-Key': key})
    assert created.status_code == 202, created.text
    while lease := claim(db):
        assert lease.kind == 'candidate'
        execute_translation(db, cfg, lease, provider)
    with db.transaction() as session:
        candidate = session.get(Candidate, created.json()['id'])
        job = session.get(Job, candidate.job_id)
        assert candidate.status == 'ready' and set(candidate.results) == {'p1'}
        return {'candidate_id': candidate.id, 'job_id': job.id, 'progress': dict(job.progress),
            'results': copy.deepcopy(candidate.results), 'terms': terms,
            'tasks': {t.id for t in session.scalars(select(Task).where(Task.job_id == job.id))},
            'permits': session.scalar(select(func.count()).select_from(Permit).where(Permit.job_id == job.id))}


def clone_source(db, cfg, source, change):
    source = copy.deepcopy(source)
    source['id'] = 'src_cache_second'
    if change == 'context':
        heading = source['blocks'][0]
        heading.update(raw_text='Different heading', normalized_text='Different heading', normalization_edits=[],
            source_inline=[{'type': 'text', 'text': 'Different heading'}])
        heading['source_hash'] = block_hash(heading, source['protected_atoms'])
    elif change == 'atoms':
        source['protected_atoms']['n64']['value'] = '32'
        paragraph = next(b for b in source['blocks'] if b['id'] == 'p1')
        paragraph['raw_text'] = paragraph['raw_text'].replace('64', '32')
        paragraph['normalized_text'] = paragraph['normalized_text'].replace('64', '32')
        paragraph['source_hash'] = block_hash(paragraph, source['protected_atoms'])
    validate_source(source, asset_root=cfg.data)
    key = 'documents/cache_second/sources/src_cache_second/document.json'
    sha = write_snapshot(cfg.data, key, source)
    with db.transaction() as session:
        session.add(Document(id='cache_second', title='Authored equivalent cache fixture',
            source_asset_id='source_pdf', current_source_id=source['id'], source_language='en'))
        session.flush()
        session.add(SourceRevision(id=source['id'], document_id='cache_second', asset_id='source_pdf',
            snapshot_hash=sha, storage_key=key))
        session.add(Edition(id='cache_second_edition', document_id='cache_second', target_locale='zh-Hans',
            current_draft_id='cache_second_draft'))
        session.flush()
        session.add(Draft(id='cache_second_draft', document_id='cache_second', edition_id='cache_second_edition',
            source_revision_id=source['id']))


@pytest.mark.parametrize('change', ['equivalent', 'glossary', 'context', 'atoms', 'model', 'delete'])
def test_new_job_cache_identity_and_deleted_origin(client, database, monkeypatch, tmp_path, change):
    db, cfg = database
    source = seed_editor(db, cfg)['source_revision']
    profile = configure(monkeypatch, tmp_path)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
    provider = FakeProvider()
    first = candidate_job(client, db, cfg, 'draft_fixture', 'doc_fixture', profile, provider, 'cache-first')
    assert len(provider.calls) == first['permits'] == 1 and first['progress']['cache_hits'] == 0
    with db.transaction() as session:
        saved = session.scalar(select(TranslationCache))
        original_key, original_value = saved.key, copy.deepcopy(saved.value)
        assert saved.document_id == 'doc_fixture'
    # A second document/job has distinct task/attempt IDs: a paid checkpoint in
    # the original job cannot account for this cache hit.
    clone_source(db, cfg, source, change)
    if change == 'glossary':
        terms = client.post('/api/v1/glossaries/revisions', json={'scope': 'document',
            'document_id': 'cache_second', 'source_language': 'en', 'target_language': 'zh-Hans',
            'entries': [{'source': 'tokens', 'target': '词元', 'mode': 'must', 'variants': []}]},
            headers={'Idempotency-Key': 'cache-new-terms'})
        assert terms.status_code == 201, terms.text
    elif change == 'model':
        profile = profile | {'model_id': 'different-fixture-model'}
        (tmp_path / 'profile.json').write_text(json.dumps(profile), encoding='utf-8')
    elif change == 'delete':
        deleted = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True},
            headers={'If-Match': '"1"'})
        assert deleted.status_code == 202, deleted.text
        # Keep the stale cache row until lookup to exercise the tombstone guard,
        # while holding the independent cleanup task out of the candidate loop.
        with db.transaction() as session:
            for job in session.scalars(select(Job).where(Job.stage == 'cleanup')):
                job.status = 'paused'
            assert session.get(TranslationCache, original_key) is not None
    second = candidate_job(client, db, cfg, 'cache_second_draft', 'cache_second', profile, provider, 'cache-second')
    assert not (first['tasks'] & second['tasks']) and first['job_id'] != second['job_id']
    hit = change == 'equivalent'
    assert second['progress']['cache_hits'] == int(hit)
    assert second['permits'] == int(not hit) and len(provider.calls) == (1 if hit else 2)
    if hit:
        assert second['results'] == first['results']
        with db.transaction() as session:
            attempts = session.scalars(select(Attempt).where(Attempt.job_id == second['job_id'])).all()
            assert all(a.usage is None and a.request_id is None for a in attempts)
    if change == 'delete':
        with db.transaction() as session:
            for job in session.scalars(select(Job).where(Job.stage == 'cleanup')):
                job.status = 'pending'
        cleanup = claim(db)
        assert cleanup is not None and cleanup.kind == 'cleanup'
        cleanup_document(db, cfg, cleanup)
        with db.transaction() as session:
            assert session.get(TranslationCache, original_key) is None
            assert session.get(Document, 'cache_second').deleted_at is None
    else:
        with db.transaction() as session:
            assert session.get(TranslationCache, original_key).value == original_value
