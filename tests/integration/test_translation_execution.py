import copy
import json
from pathlib import Path
import shutil
from datetime import timedelta
import pytest
from sqlalchemy import select,func

from packages.domain.models import (SourceAsset,SourceRevision,Document,Edition,Draft,Job,Task,Settings,SegmentVersion,Permit,Candidate,ReviewRecord,new_id,now)
from packages.ir import digest,block_hash
from packages.storage import write_snapshot
from packages.jobs.queue import claim,recover_expired
from packages.translation.execution import execute_translation
from packages.providers.fake import FakeProvider
from packages.providers.contract import ProviderFailure

pytestmark=pytest.mark.postgres
ROOT=Path(__file__).resolve().parents[2]
PROFILE={'configured':True,'provider':'openai','model_id':'fixture-model','profile_revision':'test-v1','prompt_version':'translate-v1','privacy_revision':'test-v1','enabled_pairs':[['en','zh-Hans']],'max_input_tokens':16384,'max_output_tokens':4096,'max_unit_characters':2000,'price':{'revision':'test-v1','currency':'USD','input_micro_per_million':1000000,'cached_input_micro_per_million':1000000,'output_micro_per_million':1000000,'output_includes_reasoning':True,'input_bound_rule':'utf8-byte-ceiling-v1'}}


def setup_library(db,cfg,hundred=False):
    source=json.loads((ROOT/'fixtures/sample-document-v3.json').read_text('utf-8'))['source_revision']
    if hundred:
        title=source['blocks'][0];base=source['blocks'][1]
        blocks=[title]
        for i in range(100):
            block=copy.deepcopy(base);block.update(id='para'+str(i),order=i+1);blocks.append(block)
        source['blocks']=blocks;source['reading_order']=[b['id'] for b in blocks]
    for asset in source['assets']:
        target=cfg.data/asset['storage_key'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/asset['storage_key'],target)
    key='source.json';sha=write_snapshot(cfg.data,key,source)
    with db.transaction() as session:
        settings=session.get(Settings,'singleton');settings.instance_budget_micro=10_000_000;settings.dispatch_disabled=False
        asset=SourceAsset(id=source['original_asset_id'],sha256=source['sha256'],byte_size=source['assets'][0]['byte_size'],page_count=1,storage_key=source['assets'][0]['storage_key']);session.add(asset);session.flush()
        doc=Document(id='doc',title='Fixture',source_asset_id=asset.id,current_source_id=source['id'],source_language='en');session.add(doc);session.flush()
        rev=SourceRevision(id=source['id'],document_id=doc.id,asset_id=asset.id,snapshot_hash=sha,storage_key=key);session.add(rev);session.flush()
        edition=Edition(id='edition',document_id=doc.id,target_locale='zh-Hans');session.add(edition);session.flush()
        draft=Draft(id='draft',document_id=doc.id,edition_id=edition.id,source_revision_id=rev.id,profile=PROFILE);session.add(draft);session.flush()
        payload={'draft_id':draft.id,'source_revision_id':rev.id,'source_hash':sha,'profile':PROFILE,'locale':'zh-Hans','external_processing_confirmed':True,'publish_policy':'manual_approval','glossary_revision':'empty-v1','glossary':[]}
        job=Job(id='job',document_id=doc.id,stage='translating',payload=payload,budget_micro=10_000_000);session.add(job);session.flush()
        session.add(Task(id='planner',job_id=job.id,kind='translate'))
    return source


def test_durable_fake_translation_checkpoints(database):
    db,cfg=database;source=setup_library(db,cfg);provider=FakeProvider()
    execute_translation(db,cfg,claim(db),provider)
    count=0
    while lease:=claim(db):execute_translation(db,cfg,lease,provider);count+=1
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(SegmentVersion))==sum(b['translatable'] for b in source['blocks'])
        assert session.get(Job,'job').status in ('succeeded','completed_with_warnings')
        assert all(p.state=='settled' for p in session.scalars(select(Permit)))
    assert count>0 and len(provider.calls)>0


def test_commit_unit_refreshes_draft_after_concurrent_snapshot_change(database,monkeypatch):
    import packages.translation.execution as execution
    db,cfg=database;setup_library(db,cfg)
    execute_translation(db,cfg,claim(db),FakeProvider())
    lease=claim(db)
    with db.transaction() as session:unit=copy.deepcopy(session.get(Task,lease.task_id).payload['unit'])
    original_snapshot=execution.snapshot
    def concurrent_snapshot(session,config,current_lease):
        result=original_snapshot(session,config,current_lease)
        # The request has loaded Draft in its identity map. A different
        # transaction commits an editorial generation before its row lock.
        assert result[2].generation==1
        with db.transaction() as writer:writer.get(Draft,'draft').generation=7
        return result
    monkeypatch.setattr(execution,'snapshot',concurrent_snapshot)
    execution.commit_unit(db,cfg,lease,unit,unit['source_inline'],'unused-cached-key',PROFILE,cache_hit=True)
    with db.transaction() as session:
        assert session.get(Draft,'draft').generation==8
        assert session.scalar(select(func.count()).select_from(SegmentVersion))==1


def test_paid_timeout_stops_claim_and_preserves_reservation(database):
    db,cfg=database;setup_library(db,cfg);provider=FakeProvider([ProviderFailure('OUTCOME_UNKNOWN','unknown')])
    execute_translation(db,cfg,claim(db),provider)
    execute_translation(db,cfg,claim(db),provider)
    assert claim(db) is None and len(provider.calls)==1
    with db.transaction() as session:
        assert session.get(Job,'job').status=='outcome_unknown'
        assert session.scalar(select(Permit)).state=='unknown'


def test_two_candidates_preserve_hundred_current_segments(database):
    db,cfg=database;source=setup_library(db,cfg,hundred=True)
    with db.transaction() as session:
        job=session.get(Job,'job');job.payload=job.payload|{'block_ids':['para1','para2'],'candidate_id':'candidate'}
        session.get(Task,'planner').kind='candidate'
        for block in source['blocks']:
            session.add(SegmentVersion(id=new_id('seg'),draft_id='draft',block_id=block['id'],sequence=1,target_inline=block['source_inline'],origin='manual_ui',context_hash='a'*64,source_hash=block['source_hash'],reason='Previously reviewed'))
        session.add(Candidate(id='candidate',draft_id='draft',job_id='job',base={'segments':{'para1':1,'para2':1}}))
        session.flush()
        from packages.editorial.drafts import segment_fingerprint
        draft=session.get(Draft,'draft')
        for segment in session.scalars(select(SegmentVersion)):
            session.add(ReviewRecord(id=new_id('review'),draft_id=draft.id,block_id=segment.block_id,segment_version=segment.sequence,fingerprint=segment_fingerprint(draft,segment),origin='manual_ui',reason='Controlled test review record'))
        session.flush();before={s.id:digest(s.target_inline) for s in session.scalars(select(SegmentVersion))};reviews={r.id:r.fingerprint for r in session.scalars(select(ReviewRecord))}
    provider=FakeProvider()
    while lease:=claim(db):execute_translation(db,cfg,lease,provider)
    with db.transaction() as session:
        after={s.id:digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
        assert before==after
        assert reviews=={r.id:r.fingerprint for r in session.scalars(select(ReviewRecord))}
        candidate=session.get(Candidate,'candidate');assert set(candidate.results)=={'para1','para2'} and candidate.status=='ready'


def test_optional_semantic_review_never_changes_target(database):
    db,cfg=database;source=setup_library(db,cfg)
    with db.transaction() as session:
        job=session.get(Job,'job');job.payload=job.payload|{'profile':PROFILE|{'semantic_review_enabled':True}}
        session.get(Task,'planner').kind='semantic_review'
        for block in source['blocks']:
            if block['translatable']:session.add(SegmentVersion(id=new_id('seg'),draft_id='draft',block_id=block['id'],sequence=1,target_inline=block['source_inline'],origin='manual_ui',context_hash='a'*64,source_hash=block['source_hash'],reason='Existing translation fixture'))
        session.flush();before={s.id:digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
    provider=FakeProvider()
    while lease:=claim(db):execute_translation(db,cfg,lease,provider)
    with db.transaction() as session:
        assert before=={s.id:digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
        assert session.get(Job,'job').progress['review_completed'] is True
        assert session.get(Job,'job').progress['accuracy_certified'] is False


def test_pause_return_resume_reuses_paid_validated_checkpoint(database):
    db,cfg=database;setup_library(db,cfg)
    execute_translation(db,cfg,claim(db),FakeProvider())
    lease=claim(db)
    def pause_during_call(units):
        with db.transaction() as session:
            job=session.get(Job,'job');job.status='paused';job.control_epoch+=1
        return {'results':[{'unit_id':u['unit_id'],'target_inline':u['source_inline']} for u in units]}
    provider=FakeProvider([pause_during_call])
    execute_translation(db,cfg,lease,provider)
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(SegmentVersion))==0
        assert session.scalar(select(Permit)).state=='settled'
        session.get(Task,lease.task_id).lease_expires=now()-timedelta(seconds=1)
    recover_expired(db)
    with db.transaction() as session:session.get(Job,'job').status='pending'
    resumed=claim(db)
    assert resumed.task_id==lease.task_id and resumed.fence>lease.fence
    execute_translation(db,cfg,resumed,provider)
    assert len(provider.calls)==1
    with db.transaction() as session:assert session.scalar(select(func.count()).select_from(SegmentVersion))==1
