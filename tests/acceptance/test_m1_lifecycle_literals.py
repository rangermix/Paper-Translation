"""Actual PostgreSQL/API/file lifecycle with deterministic in-flight Fake wire."""
import copy
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy import func, select

from packages.domain.models import Attempt, Document, Draft, Edition, Job, Permit, Publication, SegmentVersion, Settings, SourceDraft, Task, TranslationCache
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.storage import file_hash
from packages.translation.execution import execute_translation
from tests.integration.test_edition_translation import configure
from tests.integration.test_publication_lifecycle import drain, seal_and_publish
from tests.support import seed_editor
import workers.main as worker

pytestmark = pytest.mark.postgres


def published_then_translate(client, database, monkeypatch, tmp_path, offline=False):
    db, cfg = database
    ir = seed_editor(db, cfg)
    artifact, path = seal_and_publish(client, db, cfg, 1, 1, 'literal-original')
    old_hash = file_hash(path)
    drain(db, cfg)
    export = None
    if offline:
        queued = client.post(f'/api/v1/artifacts/{artifact}/exports', json={'format': 'single_html', 'include_source': True},
            headers={'Idempotency-Key': 'literal-offline-copy'})
        assert queued.status_code == 202, queued.text
        worker.execute(db, cfg, claim(db))
        url = '/api/v1/exports/' + queued.json()['export_id'] + '/download'
        downloaded = client.get(url)
        assert downloaded.status_code == 200
        local = tmp_path / 'already-downloaded.html'
        local.write_bytes(downloaded.content)
        export = url, local, file_hash(local)
    profile = configure(monkeypatch, tmp_path)
    source = ir['source_revision']
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
        session.add(SourceDraft(id='literal_next_source', document_id='doc_fixture', asset_id='source_pdf',
            source=copy.deepcopy(source), coverage={'can_translate': True, 'unresolved': []},
            evidence={'kind': 'controlled_internal_source_fixture'}))
    confirmed = client.post('/api/v1/imports/literal_next_source/confirm', json={'source_hash': digest(source),
        'preflight_generation': 1, 'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile),
        'locale': 'zh-Hans', 'budget_micro': 10_000_000, 'external_processing_confirmed': True,
        'publish_policy': 'auto_publish'}, headers={'If-Match': '"1"', 'Idempotency-Key': 'literal-translate'})
    assert confirmed.status_code == 202, confirmed.text
    execute_translation(db, cfg, claim(db), FakeProvider())
    return artifact, path, old_hash, confirmed.json(), export


def cancel(client, job_id):
    fetched = client.get('/api/v1/jobs/' + job_id)
    return client.post('/api/v1/jobs/' + job_id + '/cancel', json={},
        headers={'If-Match': fetched.headers['etag'], 'Idempotency-Key': 'literal-cancel'})


@pytest.mark.parametrize('ordering', ['cancel_before_last_return', 'cancel_before_publish_commit', 'publish_before_cancel'])
def test_cancel_and_final_result_or_publication_follow_commit_order(client, database, monkeypatch, tmp_path, ordering):
    db, cfg = database
    old, old_path, old_hash, started, _ = published_then_translate(client, database, monkeypatch, tmp_path)
    # Complete all but the actual final requested unit; the held response has a
    # persisted reserved permit, not merely a mocked job.status transition.
    while True:
        lease = claim(db)
        assert lease and lease.kind == 'translate'
        with db.transaction() as session:
            remaining = session.scalar(select(func.count()).select_from(Task).where(Task.job_id == started['job_id'], Task.status == 'pending'))
        if remaining == 0:
            break
        execute_translation(db, cfg, lease, FakeProvider())
    reached, release = threading.Event(), threading.Event()
    if ordering == 'cancel_before_last_return':
        def last_return(units):
            reached.set()
            assert release.wait(15)
            return {'results': [{'unit_id': u['unit_id'], 'target_inline': u['source_inline']} for u in units]}
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(execute_translation, db, cfg, lease, FakeProvider([last_return]))
            try:
                assert reached.wait(10)
                with db.transaction() as session:
                    assert session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id)).state == 'reserved'
                assert cancel(client, started['job_id']).status_code == 202
            finally:
                release.set()
            pending.result(timeout=15)
    else:
        execute_translation(db, cfg, lease, FakeProvider())
        publication = claim(db)
        assert publication and publication.kind == 'publish'
        if ordering == 'cancel_before_publish_commit':
            original, count = worker.assert_current, 0
            def barrier(session, current, **kwargs):
                nonlocal count
                if current.task_id == publication.task_id:
                    count += 1
                    if count == 2:
                        reached.set()
                        assert release.wait(15)
                return original(session, current, **kwargs)
            monkeypatch.setattr(worker, 'assert_current', barrier)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(worker.execute, db, cfg, publication)
                try:
                    assert reached.wait(10)
                    assert cancel(client, publication.job_id).status_code == 202
                finally:
                    release.set()
                pending.result(timeout=15)
        else:
            worker.execute(db, cfg, publication)
            rejected = cancel(client, started['job_id'])
            assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'JOB_TERMINAL'
    with db.transaction() as session:
        job = session.get(Job, started['job_id'])
        edition = session.get(Edition, 'edition_fixture')
        publications = list(session.scalars(select(Publication)))
        assert session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id)).state == 'settled'
        if ordering == 'publish_before_cancel':
            assert job.status == 'succeeded' and edition.current_artifact_id != old and len(publications) == 2
        else:
            assert job.status == ('succeeded' if ordering == 'cancel_before_publish_commit' else 'cancelled')
            if ordering == 'cancel_before_publish_commit': assert session.get(Job, publication.job_id).status == 'cancelled'
            assert edition.current_artifact_id == old and len(publications) == 1
    assert file_hash(old_path) == old_hash
    assert client.get(f'/artifacts/{old}/index.html').status_code == 200


def test_delete_inflight_document_with_downloaded_export_is_immediate_and_cannot_resurrect(client, database, monkeypatch, tmp_path):
    db, cfg = database
    old, old_path, old_hash, started, export = published_then_translate(client, database, monkeypatch, tmp_path, offline=True)
    url, offline_path, offline_hash = export
    lease = claim(db)
    assert lease and lease.kind == 'translate'
    reached, release = threading.Event(), threading.Event()
    def delayed_return(units):
        reached.set()
        assert release.wait(15)
        return {'results': [{'unit_id': u['unit_id'], 'target_inline': u['source_inline']} for u in units]}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(execute_translation, db, cfg, lease, FakeProvider([delayed_return]))
        try:
            assert reached.wait(10)
            with db.transaction() as session:
                assert session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id)).state == 'reserved'
            document = client.get('/api/v1/documents/doc_fixture')
            removed = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True},
                headers={'If-Match': document.headers['etag']})
            assert removed.status_code == 202, removed.text
            assert 'Downloaded copies cannot be recalled' in removed.json()['notice']
            for path in ['/api/v1/documents/doc_fixture', '/api/v1/documents/doc_fixture/original',
                    '/api/v1/drafts/' + started['draft_id'], f'/artifacts/{old}/index.html', url]:
                assert client.get(path).status_code == 410, path
            assert file_hash(offline_path) == offline_hash
            # Complete physical cleanup before the already-paid response returns.
            cleanup = claim(db)
            assert cleanup and cleanup.kind == 'cleanup'
            worker.execute(db, cfg, cleanup)
            assert not old_path.exists()
        finally:
            release.set()
        pending.result(timeout=15)
    with db.transaction() as session:
        assert session.get(Document, 'doc_fixture').deleted_at is not None
        assert session.get(Draft, started['draft_id']) is None
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
        assert session.scalar(select(func.count()).select_from(TranslationCache)) == 0
        permit = session.scalar(select(Permit).where(Permit.attempt_id == lease.attempt_id))
        assert permit.state == 'settled' and permit.actual_micro > 0
        assert not any(item.get('target_inline') for item in session.get(Attempt, lease.attempt_id).evidence)
    assert not (cfg.data / 'documents/doc_fixture').exists()
    assert file_hash(offline_path) == offline_hash
    # Cleanup erases the export row; its old handle may now be unknown (404).
    assert client.get(url).status_code in (404, 410)
