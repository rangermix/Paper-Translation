"""Additional literal scenarios, current production with real PostgreSQL and explicit Fake only."""
import copy
import pytest
from sqlalchemy import select, func
from tests.support import seed_editor
from tests.integration.test_edition_translation import configure, prepared
from tests.integration.test_publication_lifecycle import seal_and_publish, drain
from packages.domain.models import Candidate, Document, Draft, Edition, Job, Permit, ReviewRecord, SegmentVersion, Settings, SourceRevision, TranslationMemory
from packages.ir import block_hash, digest, validate_source
from packages.storage import file_hash, write_snapshot
from packages.editorial.drafts import context_hash
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from packages.privacy import cleanup_document

pytestmark=pytest.mark.postgres

def getdraft(client):
    return client.get('/api/v1/drafts/draft_fixture')

def review(client,bid):
    d=getdraft(client); segment=next(x for x in d.json()['segments'] if x['block_id']==bid)
    r=client.post(f'/api/v1/drafts/draft_fixture/segments/{bid}/confirm-review',json={
      'source_hash':segment['source_hash'],'base_segment_version':segment['version'],'context_hash':segment['context_hash'],
      'glossary_revision':segment['glossary_revision'],'reason':'Authored local fixture review marker, not model or PDF gold'},
      headers={'If-Match':d.headers['etag'],'Idempotency-Key':'review-'+bid})
    assert r.status_code==200,r.text
    return r

def setup_candidate(client,database,monkeypatch,tmp_path,selected,reviewed=()):
    db,cfg=database; seed_editor(db,cfg); profile=configure(monkeypatch,tmp_path)
    with db.transaction() as s:
        settings=s.get(Settings,'singleton'); settings.dispatch_disabled=False; settings.instance_budget_micro=10_000_000
    for bid in reviewed:review(client,bid)
    d=getdraft(client)
    terms=client.get('/api/v1/glossaries/effective',params={'document_id':'doc_fixture','source_language':'en','target_language':'zh-Hans'}).json()
    c=client.post('/api/v1/drafts/draft_fixture/candidates',json={'block_ids':selected,
       'profile_revision':profile['profile_revision'],'profile_hash':digest(profile),'glossary_revision':terms['revision'],
       'budget_micro':1_000_000,'external_processing_confirmed':True},
       headers={'If-Match':d.headers['etag'],'Idempotency-Key':'candidate-create'})
    assert c.status_code==202,c.text
    return c.json(),d.json()

def test_m2_at02b_same_edit_replays_stale_and_foreign_block_rejected(client,database):
    db,cfg=database;ir=seed_editor(db,cfg)
    # The rejected ID really exists in another source/draft; a never-created
    # ID alone would exercise only not-found, not the ownership boundary.
    foreign=copy.deepcopy(ir['source_revision']);foreign['id']='foreign-source'
    block=next(b for b in foreign['blocks'] if b['id']=='p2')
    block['id']='foreign-other-draft-block';block['source_hash']=block_hash(block,foreign['protected_atoms'])
    foreign['reading_order']=[block['id'] if bid=='p2' else bid for bid in foreign['reading_order']]
    validate_source(foreign,asset_root=cfg.data)
    key='documents/foreign-document/source.json';snapshot=write_snapshot(cfg.data,key,foreign)
    with db.transaction() as s:
        s.add(Document(id='foreign-document',title='Foreign scoped fixture',source_asset_id='source_pdf',current_source_id=foreign['id']))
        s.flush()
        s.add(SourceRevision(id=foreign['id'],document_id='foreign-document',asset_id='source_pdf',snapshot_hash=snapshot,storage_key=key))
        s.add(Edition(id='foreign-edition',document_id='foreign-document',target_locale='zh-Hans',current_draft_id='foreign-draft'))
        s.flush()
        s.add(Draft(id='foreign-draft',document_id='foreign-document',edition_id='foreign-edition',source_revision_id=foreign['id']))
        s.flush()
        s.add(SegmentVersion(id='foreign-segment',draft_id='foreign-draft',block_id=block['id'],sequence=1,
            target_inline=[{'type':'text','text':'另一个草稿的专属译文。'}],origin='manual_ui',source_hash=block['source_hash'],context_hash=context_hash(foreign,block['id'])))
    foreign_before=client.get('/api/v1/drafts/foreign-draft')
    assert foreign_before.status_code==200 and any(b['block_id']==block['id'] for b in foreign_before.json()['segments'])
    body={'target_inline':[{'type':'text','text':'保留原件！'}],'base_segment_version':1,'reason':'One controlled edit'}
    headers={'If-Match':'"1"','Idempotency-Key':'literal-edit'}
    first=client.patch('/api/v1/drafts/draft_fixture/segments/item',json=body,headers=headers)
    assert first.status_code==200,first.text
    assert client.patch('/api/v1/drafts/draft_fixture/segments/item',json=body,headers=headers).json()==first.json()
    assert client.patch('/api/v1/drafts/draft_fixture/segments/item',json=body,headers={**headers,'Idempotency-Key':'stale-other'}).status_code==412
    missing=client.patch('/api/v1/drafts/draft_fixture/segments/foreign-other-draft-block',json=body,
        headers={'If-Match':first.headers['etag'],'Idempotency-Key':'foreign-block'})
    assert missing.status_code==404,missing.text
    assert getdraft(client).json()==first.json()
    assert client.get('/api/v1/drafts/foreign-draft').json()==foreign_before.json()
    with db.transaction() as s:
        assert s.scalar(select(func.count()).select_from(SegmentVersion).where(SegmentVersion.block_id=='item'))==2

def test_m2_at03a_confirmation_freezes_effective_override_and_impact(client,database,monkeypatch,tmp_path):
    body=prepared(client,database,monkeypatch,tmp_path);db,cfg=database
    def term(scope,target,key):
        r=client.post('/api/v1/glossaries/revisions',json={'scope':scope,'document_id':'doc_fixture' if scope=='document' else None,
         'source_language':'en','target_language':'zh-Hans','entries':[{'source':'tokens','target':target,'mode':'preferred','variants':[]}]},headers={'Idempotency-Key':key})
        assert r.status_code==201,r.text
        return r.json()
    global_row=term('global','全库词元','global');local=term('document','本篇词元','local')
    impact=client.post('/api/v1/glossaries/'+local['id']+'/impact',json={'document_id':'doc_fixture'},headers={'Idempotency-Key':'impact'})
    assert impact.status_code==200 and [x['block_id'] for x in impact.json()['items']]==['p1']
    terms=client.get('/api/v1/glossaries/effective',params={'document_id':'doc_fixture','source_language':'en','target_language':'zh-Hans'}).json()
    assert terms['entries'][0]['target']=='本篇词元'
    started=client.post('/api/v1/editions/new_edition/translate',json=body,headers={'If-Match':'"1"','Idempotency-Key':'confirm'})
    assert started.status_code==202,started.text
    with db.transaction() as s:
        payload=copy.deepcopy(s.get(Job,started.json()['job_id']).payload)
        d=s.get(Draft,started.json()['draft_id'])
        assert d.glossary_revision==terms['revision'] and d.profile['glossary_entries']==terms['entries']
        assert payload['glossary']==terms['entries'] and payload['glossary_revision']==terms['revision']
    term('document','随后新词元','local-after')
    with db.transaction() as s:
        assert s.get(Job,started.json()['job_id']).payload==payload
        assert s.get(Draft,started.json()['draft_id']).glossary_revision==terms['revision']
        assert s.scalar(select(func.count()).select_from(Permit))==0

@pytest.mark.parametrize('source_field',['source_inline','normalized_text'])
def test_m2_at11b_target_editor_cannot_mutate_source(client,database,source_field):
    db,cfg=database;ir=seed_editor(db,cfg)
    with db.transaction() as s:
        source_path=cfg.data/s.get(SourceRevision,'src_fixture').storage_key
    before=getdraft(client).json();source_hash=file_hash(source_path)
    original=next(a for a in ir['source_revision']['assets'] if a['id']==ir['source_revision']['original_asset_id'])
    pdf_hash=file_hash(cfg.data/original['storage_key'])
    body={'target_inline':[{'type':'text','text':'合法目标字段仍不能夹带源文写入。'}],
          'base_segment_version':1,'reason':'Attempt to add a claim absent from the author source',
          source_field:([{'type':'text','text':'The author did not write this.'}] if source_field=='source_inline' else 'The author did not write this.')}
    result=client.patch('/api/v1/drafts/draft_fixture/segments/item',json=body,
        headers={'If-Match':'"1"','Idempotency-Key':'target-cannot-write-source'})
    assert result.status_code==422,result.text
    assert getdraft(client).json()==before and file_hash(source_path)==source_hash
    assert file_hash(cfg.data/original['storage_key'])==pdf_hash
    with db.transaction() as s:
        assert s.scalar(select(func.count()).select_from(SourceRevision))==1

def test_m2_at05b_batch_accept_rejects_unacknowledged_locked_block_atomically(client,database,monkeypatch,tmp_path):
    db,cfg=database;c,before=setup_candidate(client,database,monkeypatch,tmp_path,['item','p1'],reviewed=['item'])
    provider=FakeProvider()
    while lease:=claim(db):execute_translation(db,cfg,lease,provider)
    assert provider.calls
    with db.transaction() as s:
        row=s.get(Candidate,c['id']); assert row.status=='ready'; generation=row.generation
    accepted=client.post('/api/v1/candidates/'+c['id']+'/accept',json={'block_ids':['item','p1']},
        headers={'If-Match':f'"{generation}"','Idempotency-Key':'batch-locked'})
    assert accepted.status_code==409,accepted.text
    assert accepted.json()['error']['code']=='REVIEWED_BLOCKS_LOCKED'
    assert accepted.json()['error']['details']['blocks']==['item']
    assert getdraft(client).json()['segments']==before['segments']

def test_m2_at06a_one_character_invalidates_only_its_review_keeps_history(client,database):
    db,cfg=database;seed_editor(db,cfg);review(client,'item');before=review(client,'p1')
    old=next(x for x in before.json()['segments'] if x['block_id']=='item')
    nodes=copy.deepcopy(old['target_inline']); nodes[-1]['text']+='！'
    changed=client.patch('/api/v1/drafts/draft_fixture/segments/item',json={'target_inline':nodes,'base_segment_version':old['version'],'reason':'Add exactly one punctuation character'},
        headers={'If-Match':before.headers['etag'],'Idempotency-Key':'one-character'})
    assert changed.status_code==200,changed.text
    rows={x['block_id']:x for x in changed.json()['segments']}
    assert rows['item']['review_status']=='not_reviewed' and rows['p1']['review_status']=='human_reviewed'
    assert [x for x in changed.json()['segments'] if x['block_id']!='item']==[x for x in before.json()['segments'] if x['block_id']!='item']
    with db.transaction() as s:
        assert s.scalar(select(func.count()).select_from(ReviewRecord))==2

@pytest.mark.parametrize('damage',['missing-target','asset-hash'])
def test_m2_at07b_hard_issue_cannot_be_ignored_or_old_qa_reused(client,database,damage):
    db,cfg=database;seed_editor(db,cfg)
    old=client.post('/api/v1/drafts/draft_fixture/validate',json={},headers={'If-Match':'"1"','Idempotency-Key':'old-qa'}).json()
    assert old['valid']
    draft_id='draft_fixture'
    if damage=='asset-hash':(cfg.data/'fixtures/figure.png').write_bytes(b'changed PNG bytes')
    else:
        # Given a partially generated new draft. The edit API correctly rejects
        # empty targets; construct the missing-generation fixture explicitly.
        draft_id='draft_missing'
        with db.transaction() as s:
            old_draft=s.get(Draft,'draft_fixture')
            s.add(Draft(id=draft_id,document_id=old_draft.document_id,edition_id=old_draft.edition_id,source_revision_id=old_draft.source_revision_id))
            s.flush()
            for row in s.scalars(select(SegmentVersion).where(SegmentVersion.draft_id=='draft_fixture')):
                if row.block_id!='item':
                    s.add(SegmentVersion(id='missing-copy-'+row.block_id,draft_id=draft_id,block_id=row.block_id,sequence=1,
                        target_inline=copy.deepcopy(row.target_inline),source_hash=row.source_hash,context_hash=row.context_hash,
                        origin='manual_ui',reason='Controlled partial-generation fixture'))
            s.get(Edition,'edition_fixture').current_draft_id=draft_id
    url='/api/v1/drafts/'+draft_id
    draft=client.get(url)
    qa=client.post(url+'/validate',json={},headers={'If-Match':draft.headers['etag'],'Idempotency-Key':'new-qa'})
    assert qa.status_code==200 and not qa.json()['valid'],qa.text
    hard=next(x for x in qa.json()['issues'] if x['severity']=='important')
    ignored=client.post(url+'/issues/'+hard['fingerprint']+'/resolve',json={'reason':'Attempt ignore','evidence':{'quote':'Keep the original.','page':1}},headers={'If-Match':draft.headers['etag'],'Idempotency-Key':'ignore-hard'})
    assert ignored.status_code==(409 if damage=='asset-hash' else 200),ignored.text
    draft=client.get(url)
    denied=client.post(url+'/seal',json={'qa_id':old['id'],'qa_fingerprint':old['fingerprint'],'generation':draft.json()['generation']},headers={'If-Match':draft.headers['etag'],'Idempotency-Key':'stale-seal'})
    assert denied.status_code==(409 if damage=='asset-hash' else 201),denied.text

def test_m2_at09b_duplicate_locale_returns_existing_without_other_edition_change(client,database,monkeypatch,tmp_path):
    db,cfg=database;seed_editor(db,cfg);p=configure(monkeypatch,tmp_path,locales=('zh-Hans','en'))
    original=client.get('/api/v1/documents/doc_fixture').json()['editions']
    body={'source_revision_id':'src_fixture','target_locale':'zh-Hans','profile_hash':digest(p)}
    first=client.post('/api/v1/documents/doc_fixture/editions',json=body,headers={'If-Match':'"1"','Idempotency-Key':'duplicate'})
    assert first.status_code==201 and first.json()['id']=='edition_fixture',first.text
    second=client.post('/api/v1/documents/doc_fixture/editions',json=body,headers={'If-Match':'"1"','Idempotency-Key':'duplicate-again'})
    assert second.json()==first.json()
    other=client.post('/api/v1/documents/doc_fixture/editions',json={**body,'target_locale':'en'},headers={'If-Match':'"1"','Idempotency-Key':'other-locale'})
    assert other.status_code==201 and other.json()['id']!='edition_fixture'
    all_rows=client.get('/api/v1/documents/doc_fixture').json()['editions']
    assert next(x for x in all_rows if x['id']=='edition_fixture')==original[0]
    with db.transaction() as s:assert s.scalar(select(func.count()).select_from(Edition))==2

def test_m2_at14a_actual_running_candidate_returns_after_manual_edit(client,database,monkeypatch,tmp_path):
    db,cfg=database;c,before=setup_candidate(client,database,monkeypatch,tmp_path,['item'])
    def arriving(units):
        assert len(units)==1
        d=getdraft(client)
        changed=client.patch('/api/v1/drafts/draft_fixture/segments/item',json={'target_inline':[{'type':'text','text':'必须保留人工修改。'}],'base_segment_version':1,'reason':'Actual user edit while Provider call is pending'},headers={'If-Match':d.headers['etag'],'Idempotency-Key':'during-call'})
        assert changed.status_code==200,changed.text
        return {'results':[{'unit_id':units[0]['unit_id'],'target_inline':copy.deepcopy(units[0]['source_inline'])}]}
    provider=FakeProvider([arriving])
    while lease:=claim(db):execute_translation(db,cfg,lease,provider)
    assert len(provider.calls)==1
    with db.transaction() as s:
        row=s.get(Candidate,c['id']); assert row.status=='ready'; generation=row.generation
    accepted=client.post('/api/v1/candidates/'+c['id']+'/accept',json={},headers={'If-Match':f'"{generation}"','Idempotency-Key':'accept-late'})
    assert accepted.status_code==409 and accepted.json()['error']['code']=='CANDIDATE_CONFLICT',accepted.text
    assert accepted.json()['error']['details']['blocks']==['item']
    assert next(x for x in getdraft(client).json()['segments'] if x['block_id']=='item')['target_inline']==[{'type':'text','text':'必须保留人工修改。'}]

def test_m2_at17b_memory_and_search_removed_but_shared_original_survives_gc(client,database):
    db,cfg=database;seed_editor(db,cfg);r=review(client,'p1')
    saved=client.post('/api/v1/translation-memory',json={'draft_id':'draft_fixture','block_id':'p1','segment_version':1,'independent':False},headers={'Idempotency-Key':'tm-save'})
    assert saved.status_code==201,saved.text
    artifact,_=seal_and_publish(client,db,cfg,r.json()['generation'],1,'memory-delete');drain(db,cfg)
    assert client.get('/api/v1/search',params={'q':'tokens'}).json()['items']
    with db.transaction() as s:s.add(Document(id='shared_original',title='Another actual reference',source_asset_id='source_pdf'))
    original=(cfg.data/'fixtures/sample.pdf').read_bytes()
    doc=client.get('/api/v1/documents/doc_fixture')
    deleted=client.request('DELETE','/api/v1/documents/doc_fixture',json={'confirm':True},headers={'If-Match':doc.headers['etag']})
    assert deleted.status_code==202
    assert client.get('/api/v1/translation-memory').json()['items']==[]
    assert client.get('/api/v1/search',params={'q':'tokens'}).json()['items']==[]
    assert client.get('/api/v1/translation-memory/'+saved.json()['id']).status_code==410
    cleanup_document(db,cfg,claim(db))
    assert client.get('/api/v1/documents/shared_original/original').content==original
    with db.transaction() as s:assert s.get(TranslationMemory,saved.json()['id']) is None

def test_m2_at20b_candidate_response_after_delete_and_gc_cannot_resurrect(client,database,monkeypatch,tmp_path):
    from packages.domain.models import Attempt
    db,cfg=database;c,before=setup_candidate(client,database,monkeypatch,tmp_path,['item'])
    with db.transaction() as s:s.add(Document(id='shared_candidate_original',title='Shared PDF stays',source_asset_id='source_pdf'))
    original=(cfg.data/'fixtures/sample.pdf').read_bytes()
    def delete_then_return(units):
        doc=client.get('/api/v1/documents/doc_fixture')
        removed=client.request('DELETE','/api/v1/documents/doc_fixture',json={'confirm':True},headers={'If-Match':doc.headers['etag']})
        assert removed.status_code==202,removed.text
        cleanup=claim(db);assert cleanup.kind=='cleanup'
        cleanup_document(db,cfg,cleanup)
        return {'results':[{'unit_id':u['unit_id'],'target_inline':copy.deepcopy(u['source_inline'])} for u in units]}
    provider=FakeProvider([delete_then_return])
    while lease:=claim(db):execute_translation(db,cfg,lease,provider)
    assert len(provider.calls)==1
    with db.transaction() as s:
        assert s.get(Document,'doc_fixture').deleted_at is not None
        assert s.get(Candidate,c['id']) is None
        assert s.scalar(select(func.count()).select_from(SegmentVersion))==0
        assert not any(e.get('kind')=='validated_unit' for a in s.scalars(select(Attempt)) for e in a.evidence)
        permits=list(s.scalars(select(Permit)));assert len(permits)==1 and permits[0].state=='settled'
    assert client.get('/api/v1/documents/doc_fixture').status_code==410
    assert client.get('/api/v1/documents/shared_candidate_original/original').content==original
    assert not (cfg.data/'documents/doc_fixture').exists()
