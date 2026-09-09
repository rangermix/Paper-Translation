"""M2-AT12B: one real persisted review/cache chain per changed-source axis.

SourceDraft inputs are explicitly authored identity fixtures, not parser gold.
Only the response transport is Fake; confirmation, draft creation, task planning,
cache lookup, ledger and result commits are production API/PostgreSQL behavior.
"""
import copy

import pytest
from sqlalchemy import select

from packages.domain.models import Candidate, Document, Draft, ReviewRecord, SourceDraft, SourceRevision, Task, TranslationCache
from packages.ir import block_hash, digest, validate_source
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.storage import file_hash, read_snapshot
from packages.translation.execution import execute_translation
from tests.acceptance.test_m2_literal_compound import review, setup_candidate

pytestmark=pytest.mark.postgres


@pytest.mark.parametrize('change',['section-context','protected-atom-semantics'])
def test_changed_source_context_or_atoms_do_not_inherit_real_review_or_persistent_cache(client,database,monkeypatch,tmp_path,change):
    db,cfg=database
    created,_=setup_candidate(client,database,monkeypatch,tmp_path,['p1'])
    first_provider=FakeProvider()
    while lease:=claim(db):execute_translation(db,cfg,lease,first_provider)
    assert len(first_provider.calls)==1
    with db.transaction() as s:
        candidate=s.get(Candidate,created['id']);candidate_generation=candidate.generation
        cached=s.scalars(select(TranslationCache)).all()
        assert len(cached)==1
        cache_key,cache_value=cached[0].key,copy.deepcopy(cached[0].value)
    accepted=client.post('/api/v1/candidates/'+created['id']+'/accept',json={'block_ids':['p1']},
        headers={'If-Match':f'"{candidate_generation}"','Idempotency-Key':'inheritance-explicit-accept'})
    assert accepted.status_code==200,accepted.text
    reviewed=review(client,'p1').json()
    old_segment=next(b for b in reviewed['segments'] if b['block_id']=='p1')
    assert old_segment['review_status']=='human_reviewed'
    with db.transaction() as s:
        old_revision=s.get(SourceRevision,'src_fixture');source=read_snapshot(cfg.data,old_revision)
        old_source_file=cfg.data/old_revision.storage_key;old_source_hash=file_hash(old_source_file)
        old_reviews={r.id:{k:getattr(r,k) for k in ['draft_id','block_id','segment_version','fingerprint','origin','reason']}for r in s.scalars(select(ReviewRecord))}
        assert len(old_reviews)==1
    revised=copy.deepcopy(source);revised['id']='authored-changed-source'
    paragraph=next(b for b in revised['blocks'] if b['id']=='p1')
    if change=='section-context':
        heading=revised['blocks'][0]
        heading.update(raw_text='Different experimental section',normalized_text='Different experimental section',
            normalization_edits=[],source_inline=[{'type':'text','text':'Different experimental section'}])
        heading['source_hash']=block_hash(heading,revised['protected_atoms'])
    else:
        # Same printed64 and identical paragraph text, different resolved atom
        # semantics. A raw-text-only cache or review transfer would be unsafe.
        revised['protected_atoms']['n64']['kind']='math'
        paragraph['source_hash']=block_hash(paragraph,revised['protected_atoms'])
    assert paragraph['normalized_text']==next(b for b in source['blocks'] if b['id']=='p1')['normalized_text']
    validate_source(revised,asset_root=cfg.data)
    with db.transaction() as s:
        doc=s.get(Document,'doc_fixture')
        s.add(SourceDraft(id='changed-source-preflight',document_id=doc.id,asset_id=doc.source_asset_id,
            base_revision_id='src_fixture',source=revised,coverage={'can_translate':True,'unresolved':[]},
            evidence={'document_generation':doc.generation,'origin':'controlled_internal_fixture',
                'reason':'Identity inheritance test; not a claim that this IR was extracted from the source PDF'}))
    # The normal confirmation path computes the mapping and creates the new
    # editable draft; the test never copies or clears review/cache rows itself.
    from packages.domain.config import provider_profile
    profile=provider_profile()
    confirmed=client.post('/api/v1/imports/changed-source-preflight/confirm',json={
        'source_hash':digest(revised),'preflight_generation':1,'profile_revision':profile['profile_revision'],
        'profile_hash':digest(profile),'locale':'zh-Hans','budget_micro':1_000_000,
        'external_processing_confirmed':True,'publish_policy':'manual_approval'},
        headers={'If-Match':'"1"','Idempotency-Key':'confirm-changed-source'})
    assert confirmed.status_code==202,confirmed.text
    result=confirmed.json();new_id=result['draft_id']
    assert new_id!='draft_fixture'
    before=client.get('/api/v1/drafts/'+new_id).json()
    new_segment=next(b for b in before['segments'] if b['block_id']=='p1')
    assert new_segment['review_status']=='not_reviewed' and new_segment['target_inline']==[]
    with db.transaction() as s:
        new=s.get(Draft,new_id);revision=s.get(SourceRevision,new.source_revision_id)
        assert revision.parent_id=='src_fixture'
        mapping=next(r for r in revision.metadata_json['mapping'] if r['old_block_ids']==['p1'])
        assert not mapping['reusable']
        assert not s.scalars(select(ReviewRecord).where(ReviewRecord.draft_id==new_id)).all()
        assert s.get(TranslationCache,cache_key).value==cache_value
    second_provider=FakeProvider()
    while lease:=claim(db):
        assert lease.kind=='translate' and lease.job_id==result['job_id']
        execute_translation(db,cfg,lease,second_provider)
    with db.transaction() as s:
        p1_tasks=s.scalars(select(Task).where(Task.job_id==result['job_id'])).all()
        p1_tasks=[t for t in p1_tasks if t.payload.get('unit',{}).get('owner_block_id')=='p1']
        assert len(p1_tasks)==1 and p1_tasks[0].status=='succeeded'
        assert p1_tasks[0].result['cache_hit'] is False
        assert s.get(TranslationCache,cache_key).value==cache_value
        assert {r.id:{k:getattr(r,k) for k in ['draft_id','block_id','segment_version','fingerprint','origin','reason']}for r in s.scalars(select(ReviewRecord))}==old_reviews
    assert any(u['owner_block_id']=='p1' for request in second_provider.calls for u in request)
    after=client.get('/api/v1/drafts/'+new_id).json()
    assert next(b for b in after['segments'] if b['block_id']=='p1')['review_status']!='human_reviewed'
    assert next(b for b in client.get('/api/v1/drafts/draft_fixture').json()['segments'] if b['block_id']=='p1')==old_segment
    assert file_hash(old_source_file)==old_source_hash
