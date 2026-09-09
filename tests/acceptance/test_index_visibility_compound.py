"""Actual index transaction overlap with publication and withdrawal."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import pytest
from sqlalchemy import event, text
from packages.jobs.queue import claim
from tests.support import seed_editor
from tests.integration.test_publication_lifecycle import seal_and_publish
from workers.main import execute
import packages.search as search

pytestmark=pytest.mark.postgres

@pytest.mark.parametrize('action',['publish','unpublish'])
def test_index_overlaps_pointer_change_without_stale_search_or_wrong_bookmark(client,database,monkeypatch,action):
    db,cfg=database;seed_editor(db,cfg)
    first,_=seal_and_publish(client,db,cfg,1,1,'index-base')
    index_lease=claim(db);assert index_lease.kind=='index'
    assert client.put('/api/v1/reading-position',json={'document_id':'doc_fixture','locale':'zh-Hans','artifact_id':first,'block_id':'item','offset':3},
        headers={'If-Match':'"0"','Idempotency-Key':'old-position'}).status_code==200
    publish_lease=None
    if action=='publish':
        changed=client.patch('/api/v1/drafts/draft_fixture/segments/item',json={'base_segment_version':1,'reason':'New current text',
            'target_inline':[{'type':'text','text':'并发发布后的新版本。'}]},headers={'If-Match':'"1"','Idempotency-Key':'new-text'})
        assert changed.status_code==200
        qa=client.post('/api/v1/drafts/draft_fixture/validate',json={},headers={'If-Match':'"2"','Idempotency-Key':'qa-new'}).json();assert qa['valid']
        sealed=client.post('/api/v1/drafts/draft_fixture/seal',json={'qa_id':qa['id'],'qa_fingerprint':qa['fingerprint'],'generation':2},
            headers={'If-Match':'"2"','Idempotency-Key':'seal-new'}).json()
        queued=client.post('/api/v1/editions/edition_fixture/publish',json={'translation_revision_id':sealed['id'],'expected_generation':2},
            headers={'If-Match':'"2"','Idempotency-Key':'publish-new'})
        assert queued.status_code==202,queued.text
        publish_lease=claim(db);assert publish_lease.kind=='publish'
    entered,release=threading.Event(),threading.Event();pids={}
    original=search.read_snapshot
    def paused(*args,**kwargs):
        if threading.current_thread().name=='index-current-review':
            entered.set();assert release.wait(12)
        return original(*args,**kwargs)
    monkeypatch.setattr(search,'read_snapshot',paused)
    def observe(conn,cursor,statement,parameters,context,many):
        if statement=='SELECT pg_advisory_xact_lock(798205425)':
            role='index-current-review' if threading.current_thread().name=='index-current-review' else 'pointer-current-review'
            pids[role]=conn.connection.driver_connection.info.backend_pid
    event.listen(db.engine,'before_cursor_execute',observe)
    def index():
        threading.current_thread().name='index-current-review';search.update_index(db,cfg,index_lease)
    def change():
        threading.current_thread().name='pointer-current-review'
        if action=='publish':execute(db,cfg,publish_lease)
        else:
            r=client.post('/api/v1/editions/edition_fixture/unpublish',json={'expected_generation':2},headers={'If-Match':'"2"','Idempotency-Key':'withdraw'})
            assert r.status_code==200,r.text
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_index=pool.submit(index);assert entered.wait(10)
            pending_change=pool.submit(change)
            try:
                deadline=time.monotonic()+6;blocked=False
                while time.monotonic()<deadline:
                    if len(pids)==2:
                        with db.engine.connect() as observer:
                            blocked=pids['index-current-review'] in observer.scalar(text('SELECT pg_blocking_pids(:pid)'),{'pid':pids['pointer-current-review']})
                        if blocked:break
                    time.sleep(.02)
                assert blocked,'Actual pointer transaction did not overlap and wait for index transaction'
            finally:release.set()
            pending_index.result(timeout=15);pending_change.result(timeout=15)
    finally:
        release.set();event.remove(db.engine,'before_cursor_execute',observe)
    assert client.get('/api/v1/search',params={'q':'Keep the original'}).json()['items']==[]
    if action=='publish':
        current=client.get('/api/v1/documents/doc_fixture').json()['editions'][0]['current_artifact_id'];assert current!=first
        position=client.get('/api/v1/reading-position',params={'document_id':'doc_fixture','locale':'zh-Hans','artifact_id':current}).json()
        assert position['migration_required'] and position['block_id'] is None and position['previous_position']['artifact_id']==first
        execute(db,cfg,claim(db))
        found=client.get('/api/v1/search',params={'q':'并发发布','side':'target'}).json()['items']
        assert found and all(x['artifact_id']==current for x in found)
    else:
        assert client.get('/read/doc_fixture/zh-Hans').status_code==404
    assert client.get('/artifacts/'+first+'/index.html').status_code==200
