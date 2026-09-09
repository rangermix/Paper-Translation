"""Independent real-PG source replacement races. Authored spool is not parser gold."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import time

import pytest
from sqlalchemy import event, select, text

from packages.billing.ledger import budget_totals
from packages.domain.errors import DomainError
from packages.domain.models import Attempt, Document, Job, Permit, SourceAsset, Task, Upload, now
from packages.ir import canonical_bytes, digest
from packages.jobs.queue import claim
from packages.privacy import cleanup_document
from tests.integration.test_source_replacement import replacement, replace_api
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('changed_binding', ['asset', 'snapshot_hash'])
def test_worker_refuses_obsolete_asset_or_snapshot_before_provider(client, database, changed_binding):
    from apps.api.library import enqueue
    from packages.providers.fake import FakeProvider
    from packages.translation.execution import execute_translation
    from tests.integration.test_translation_execution import PROFILE
    db, cfg = database
    ir = seed_editor(db, cfg)
    if changed_binding == 'asset':
        replacement(db, cfg)
        assert replace_api(client).status_code == 201
    source_hash = digest(ir['source_revision']) if changed_binding == 'asset' else '0'*64
    with db.transaction() as session:
        enqueue(session, 'translate', {'draft_id': 'draft_fixture', 'source_revision_id': 'src_fixture',
            'source_hash': source_hash, 'profile': PROFILE, 'locale': 'zh-Hans', 'external_processing_confirmed': True}, 'doc_fixture')
    provider = FakeProvider()
    with pytest.raises(DomainError) as error:
        execute_translation(db, cfg, claim(db), provider)
    assert error.value.code == 'SOURCE_STALE'
    assert provider.calls == []
    with db.transaction() as session:
        assert list(session.scalars(select(Permit))) == []


def test_candidate_creation_and_accept_reject_replaced_asset(client, database):
    from packages.domain.models import Candidate
    db, cfg = database
    seed_editor(db, cfg)
    replacement(db, cfg)
    with db.transaction() as session:
        session.add(Candidate(id='old_candidate', draft_id='draft_fixture', status='ready', base={}, results={}))
    assert replace_api(client).status_code == 201
    created = client.post('/api/v1/drafts/draft_fixture/candidates', json={'block_ids': ['p1'],
        'profile_revision': 'test-v1', 'profile_hash': '0'*64, 'glossary_revision': 'empty-v1',
        'budget_micro': 1000000, 'external_processing_confirmed': True},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'old-source-candidate'})
    accepted = client.post('/api/v1/candidates/old_candidate/accept', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'old-source-accept'})
    for response in (created, accepted):
        assert response.status_code == 409, response.text
        assert response.json()['error']['code'] == 'SOURCE_STALE'


@pytest.mark.parametrize('first', ['import', 'cleanup'])
def test_last_reference_cleanup_and_import_serialize(client, database, first):
    db, cfg = database
    seed_editor(db, cfg)
    original = (cfg.data / 'fixtures/sample.pdf').read_bytes()
    with db.transaction() as session:
        session.add(Upload(id='receipt_old', filename='old.pdf', byte_size=len(original),
            received_bytes=len(original), status='verified', sha256=digest(original),
            source_asset_id='source_pdf', expires_at=now()+timedelta(hours=1)))
    deleted = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True},
        headers={'If-Match': '"1"'})
    assert deleted.status_code == 202, deleted.text
    lease = claim(db)
    assert lease.kind == 'cleanup'
    acquired, release = threading.Event(), threading.Event()
    pids = []
    guarded = threading.Lock()

    def before(conn, cursor, statement, params, context, many):
        if statement == 'SELECT pg_advisory_xact_lock(798205425)':
            with guarded:
                pids.append(conn.connection.driver_connection.info.backend_pid)

    def after(conn, cursor, statement, params, context, many):
        if statement == 'SELECT pg_advisory_xact_lock(798205425)' and not acquired.is_set():
            acquired.set()
            assert release.wait(10), 'test did not release first actual global lock'

    def import_source():
        return client.post('/api/v1/imports', json={'source': {'kind': 'pdf_upload', 'upload_id': 'receipt_old'},
            'source_language': 'en'}, headers={'Idempotency-Key': 'independent-shared-import'})

    operations = {'import': import_source, 'cleanup': lambda: cleanup_document(db, cfg, lease)}
    event.listen(db.engine, 'before_cursor_execute', before)
    event.listen(db.engine, 'after_cursor_execute', after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(operations[first])
            assert acquired.wait(10)
            second = 'cleanup' if first == 'import' else 'import'
            b = pool.submit(operations[second])
            try:
                deadline = time.monotonic()+8
                blocked = False
                while time.monotonic() < deadline:
                    if len(pids) == 2:
                        with db.engine.connect() as observer:
                            blocked = pids[0] in observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': pids[1]})
                        if blocked:
                            break
                    time.sleep(.02)
                assert blocked, 'second real transaction did not block on the first advisory lock'
            finally:
                release.set()
            results = {first: a.result(timeout=15), second: b.result(timeout=15)}
    finally:
        release.set()
        event.remove(db.engine, 'before_cursor_execute', before)
        event.remove(db.engine, 'after_cursor_execute', after)
    response = results['import']
    with db.transaction() as session:
        if first == 'import':
            assert response.status_code == 201, response.text
            doc = session.get(Document, response.json()['id'])
            assert doc.source_asset_id == 'source_pdf'
            assert session.get(SourceAsset, 'source_pdf')
            assert (cfg.data / 'fixtures/sample.pdf').read_bytes() == original
            assert client.get('/api/v1/documents/'+doc.id+'/original').content == original
        else:
            assert response.status_code == 409, response.text
            assert response.json()['error']['code'] == 'UPLOAD_INCOMPLETE'
            assert session.get(SourceAsset, 'source_pdf') is None
            assert session.get(Upload, 'receipt_old').status == 'deleted'
            assert not (cfg.data / 'fixtures/sample.pdf').exists()


def test_replacement_preserves_unknown_risk_and_forbids_retry(client, database):
    from apps.api.library import enqueue
    db, cfg = database
    seed_editor(db, cfg)
    replacement(db, cfg)
    with db.transaction() as session:
        job = enqueue(session, 'translate', {}, 'doc_fixture')
        job_id = job.id
    lease = claim(db)
    with db.transaction() as session:
        session.get(Job, job_id).status = 'outcome_unknown'
        session.get(Task, lease.task_id).status = 'outcome_unknown'
        attempt = session.get(Attempt, lease.attempt_id)
        attempt.state = 'outcome_unknown'
        session.add(Permit(id='unknown_receipt', attempt_id=lease.attempt_id, job_id=job_id,
            control_epoch=lease.control_epoch, reserved_micro=80000, state='unknown', price_snapshot={'revision': 'synthetic-risk-only'}))
    assert replace_api(client).status_code == 201
    job = client.get('/api/v1/jobs/'+job_id).json()
    assert job['status'] == 'outcome_unknown' and job['unknown_micro'] == 80000
    assert job['progress']['source_superseded'] is True
    before = job['attempts']
    for decision in ['retry_accept_risk', 'resume']:
        path = '/api/v1/attempts/'+lease.attempt_id+'/resolve' if decision == 'retry_accept_risk' else '/api/v1/jobs/'+job_id+'/resume'
        body = {'decision': decision, 'reason': 'Controlled independent risk probe', 'budget_micro': 1000000,
            'duplicate_charge_risk_confirmed': True} if decision == 'retry_accept_risk' else {}
        refused = client.post(path, json=body, headers={'If-Match': '"'+str(job['generation'])+'"', 'Idempotency-Key': decision})
        assert refused.status_code == 409, refused.text
        assert refused.json()['error']['code'] == 'SOURCE_STALE'
    after = client.get('/api/v1/jobs/'+job_id).json()
    assert after['attempts'] == before
    assert claim(db) is None
    with db.transaction() as session:
        assert budget_totals(session) == {'actual_micro': 0, 'reserved_micro': 0, 'unknown_micro': 80000}
        assert session.get(Permit, 'unknown_receipt').actual_micro is None
        assert session.get(Attempt, lease.attempt_id).usage is None


def test_late_usage_settles_after_source_replacement_without_retry_or_content_write(client, database):
    from apps.api.library import enqueue
    from packages.billing.ledger import authorize, mark_unknown, settle
    from packages.domain.models import Settings, SegmentVersion
    from tests.integration.test_budget import PRICE
    db, cfg = database
    seed_editor(db, cfg)
    replacement(db, cfg)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.instance_budget_micro, settings.dispatch_disabled = 1000000, False
        job = enqueue(session, 'translate', {'external_processing_confirmed': True, 'profile': {'price': PRICE}}, 'doc_fixture')
        job.budget_micro = 1000000
        job_id = job.id
        before_segments = {s.id: digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
    lease = claim(db)
    with db.transaction() as session:
        authorize(session, lease, 80, PRICE)
    with db.transaction() as session:
        mark_unknown(session, lease.attempt_id, 'Explicit synthetic timeout; no supplier request')
        session.get(Job, job_id).status = 'outcome_unknown'
        session.get(Task, lease.task_id).status = 'outcome_unknown'
    assert replace_api(client).status_code == 201
    for _ in range(2):
        with db.transaction() as session:
            settle(session, lease.attempt_id, {'input_tokens': 10, 'output_tokens': 20}, 'synthetic-late-evidence')
    assert claim(db) is None
    with db.transaction() as session:
        assert budget_totals(session) == {'actual_micro': 30, 'reserved_micro': 0, 'unknown_micro': 0}
        assert session.get(Job, job_id).status == 'outcome_unknown'
        assert session.get(Job, job_id).progress['source_superseded'] is True
        assert session.get(Document, 'doc_fixture').source_asset_id == 'asset_new'
        assert {s.id: digest(s.target_inline) for s in session.scalars(select(SegmentVersion))} == before_segments


@pytest.mark.parametrize('stage', ['building', 'checking'])
def test_replacement_fences_auto_publish_and_checking_jobs(client, database, stage):
    from apps.api.library import enqueue
    from packages.jobs.queue import assert_current
    db, cfg = database
    seed_editor(db, cfg)
    replacement(db, cfg)
    with db.transaction() as session:
        job = enqueue(session, 'translate', {}, 'doc_fixture')
        job.stage = stage  # execute_translation uses these exact persisted stages.
        job_id = job.id
    lease = claim(db)
    assert replace_api(client).status_code == 201
    with db.transaction() as session:
        job = session.get(Job, job_id)
        assert job.progress.get('source_superseded') is True
        assert job.control_epoch > lease.control_epoch
        with pytest.raises(DomainError) as error:
            assert_current(session, lease)
        assert error.value.code == 'CONTROL_CHANGED'


def test_parse_commit_and_import_do_not_deadlock(client, database, monkeypatch):
    """Stop after the real final lease lock; overlap the actual import transaction."""
    import workers.main as worker
    from apps.api.library import enqueue
    db, cfg = database
    seed_editor(db, cfg)
    replacement(db, cfg)
    with db.transaction() as session:
        enqueue(session, 'parse', {'source_asset_id': 'source_pdf', 'base_revision_id': 'src_fixture'}, 'doc_fixture')
    lease = claim(db)
    output = cfg.parser_outputs / lease.task_id / str(lease.fence)
    output.mkdir(parents=True)
    payload = canonical_bytes({'source_revision': None, 'inspection': {'pages': [], 'page_count': 1},
        'coverage': {'can_translate': False, 'unresolved': [{'reason': 'Controlled authored spool'}]}})
    (output / 'payload.json').write_bytes(payload)
    (output / 'result.json').write_bytes(canonical_bytes({'task_id': lease.task_id, 'fence': lease.fence,
        'source_sha256': digest((cfg.data/'fixtures/sample.pdf').read_bytes()), 'operation': 'parse', 'status': 'succeeded',
        'files': [{'path': 'payload.json', 'byte_size': len(payload), 'sha256': digest(payload)}]}))
    stopped, resume = threading.Event(), threading.Event()
    calls = 0
    worker_pid, import_pid = [], []
    original_assert = worker.assert_current

    def stop_after_final_lease(session, current, *args, **kwargs):
        nonlocal calls
        result = original_assert(session, current, *args, **kwargs)
        calls += 1
        if calls == 2:
            worker_pid.append(session.scalar(text('SELECT pg_backend_pid()')))
            stopped.set()
            assert resume.wait(12)
        return result

    def observe_import(conn, cursor, statement, params, context, many):
        if statement == 'SELECT pg_advisory_xact_lock(798205425)' and threading.current_thread().name != 'source-parser-review':
            import_pid.append(conn.connection.driver_connection.info.backend_pid)

    def run_parse():
        threading.current_thread().name = 'source-parser-review'
        try:
            worker.parse_spool(db, cfg, lease)
            return 'committed'
        except DomainError as error:
            return error.code

    monkeypatch.setattr(worker, 'assert_current', stop_after_final_lease)
    event.listen(db.engine, 'before_cursor_execute', observe_import)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            parsed = pool.submit(run_parse)
            assert stopped.wait(10)
            imported = pool.submit(replace_api, client)
            try:
                deadline = time.monotonic()+8
                blocked = False
                while time.monotonic() < deadline:
                    if import_pid:
                        with db.engine.connect() as observer:
                            blocked = worker_pid[0] in observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': import_pid[0]})
                        if blocked:
                            break
                    time.sleep(.02)
                assert blocked, 'real import did not overlap the locked worker transaction'
            finally:
                resume.set()
            outcome = parsed.result(timeout=15)
            response = imported.result(timeout=15)
            assert outcome in {'committed', 'CONTROL_CHANGED', 'SOURCE_STALE', 'FENCE_EXPIRED'}
            assert response.status_code in (201, 412), response.text
    finally:
        resume.set()
        event.remove(db.engine, 'before_cursor_execute', observe_import)


def test_deleted_document_cannot_regain_late_parser_files(client, database, monkeypatch):
    """Physical deletion must also fence the earlier copy from isolated spool."""
    import workers.main as worker
    from apps.api.library import enqueue
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        enqueue(session, 'parse', {'source_asset_id': 'source_pdf', 'base_revision_id': 'src_fixture'}, 'doc_fixture')
    lease = claim(db)
    output = cfg.parser_outputs / lease.task_id / str(lease.fence)
    output.mkdir(parents=True)
    payload = canonical_bytes({'source_revision': None, 'inspection': {'pages': [], 'page_count': 1},
        'coverage': {'can_translate': False, 'unresolved': [{'reason': 'Controlled late output text'}]}})
    (output/'payload.json').write_bytes(payload)
    (output/'result.json').write_bytes(canonical_bytes({'task_id': lease.task_id, 'fence': lease.fence,
        'source_sha256': digest((cfg.data/'fixtures/sample.pdf').read_bytes()), 'operation': 'parse', 'status': 'succeeded',
        'files': [{'path': 'payload.json', 'byte_size': len(payload), 'sha256': digest(payload)}]}))
    before_copy, continue_copy = threading.Event(), threading.Event()
    atomic = worker.atomic_write
    pids = {'worker': [], 'delete': []}

    def observe(conn, cursor, statement, params, context, many):
        if statement == 'SELECT pg_advisory_xact_lock(798205425)':
            owner = 'worker' if threading.current_thread().name == 'late-parser-review' else 'delete'
            pids[owner].append(conn.connection.driver_connection.info.backend_pid)

    def pause_copy(root, key, data, *args, **kwargs):
        if str(key).startswith('documents/doc_fixture/parser/'):
            before_copy.set()
            assert continue_copy.wait(12)
        return atomic(root, key, data, *args, **kwargs)

    def execute():
        threading.current_thread().name = 'late-parser-review'
        try:
            worker.parse_spool(db, cfg, lease)
            return 'committed'
        except DomainError as error:
            return error.code

    monkeypatch.setattr(worker, 'atomic_write', pause_copy)
    event.listen(db.engine, 'before_cursor_execute', observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            parsed = pool.submit(execute)
            assert before_copy.wait(10)
            deletion = pool.submit(client.request, 'DELETE', '/api/v1/documents/doc_fixture',
                json={'confirm': True}, headers={'If-Match': '"1"'})
            blocked = False
            try:
                deadline = time.monotonic()+8
                while time.monotonic() < deadline and not deletion.done():
                    if pids['worker'] and pids['delete']:
                        with db.engine.connect() as observer:
                            blocked = pids['worker'][-1] in observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': pids['delete'][-1]})
                        if blocked:
                            break
                    time.sleep(.02)
                if not blocked:
                    # Retain the original failing schedule for a regression:
                    # unprotected cleanup completes before the late copy.
                    removed = deletion.result(timeout=10)
                    assert removed.status_code == 202, removed.text
                    cleanup_document(db, cfg, claim(db))
                    assert not (cfg.data/'documents/doc_fixture').exists()
            finally:
                continue_copy.set()
            outcome = parsed.result(timeout=15)
            if blocked:
                removed = deletion.result(timeout=15)
                if removed.status_code == 412:
                    current = client.get('/api/v1/documents/doc_fixture').json()
                    removed = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True},
                        headers={'If-Match': '"'+str(current['generation'])+'"'})
                assert removed.status_code == 202, removed.text
                cleanup_lease = claim(db)
                assert cleanup_lease.kind == 'cleanup'
                cleanup_document(db, cfg, cleanup_lease)
            assert outcome in {'committed', 'CONTROL_CHANGED', 'FENCE_EXPIRED', 'DOCUMENT_DELETED'}
    finally:
        continue_copy.set()
        event.remove(db.engine, 'before_cursor_execute', observe)
    assert not (cfg.data/'documents/doc_fixture').exists(), 'Late parser spool content resurrected deleted document files'
