"""Internal authored IR only; real process recovery, never translation-quality evidence."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import copy
import json
import shutil
import time
from pathlib import Path
import sys
sys.path.insert(0,'/harness')

from sqlalchemy import select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Artifact,Attempt,Document,Draft,Edition,Job,Permit,Publication,QA,SegmentVersion,Settings,SourceAsset,SourceRevision,Task,TranslationRevision
from packages.editorial.drafts import context_hash
from packages.ir import block_hash,digest,validate_source
from packages.publisher import verify_artifact
from packages.storage import file_hash,write_snapshot
from smoke_library import request

OUT=Path('/evidence');IDS=['resume-'+chr(65+i) for i in range(10)]
PRICE={'revision':'resume30-fixture','currency':'USD','input_micro_per_million':1000000,'cached_input_micro_per_million':1000000,
       'output_micro_per_million':1000000,'output_includes_reasoning':True,'input_bound_rule':'utf8-byte-ceiling-v1'}
PROFILE={'configured':True,'provider':'openai','model_id':'explicit-fake-resume30','profile_revision':'resume30-fixture',
         'prompt_version':'translate-v1','privacy_revision':'fixture-only','enabled_pairs':[['en','zh-Hans']],
         'max_input_tokens':16384,'max_output_tokens':4096,'max_unit_characters':2000,'price':PRICE}


def records(session):
    return {row.block_id:{'id':row.id,'sequence':row.sequence,'target_hash':digest(row.target_inline),'source_hash':row.source_hash}
        for row in session.scalars(select(SegmentVersion).where(SegmentVersion.draft_id=='draft_resume',SegmentVersion.block_id.in_(IDS)))}


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['prepare','barrier','final']);op=p.parse_args().operation
    cfg=Config.load();db=Database(cfg)
    if op=='prepare':
        ir=json.loads((ROOT/'tests/fixtures/sample-document.json').read_text(encoding='utf8'));source=copy.deepcopy(ir['source_revision'])
        source['id']='source_resume';title=source['blocks'][0];example=source['blocks'][1];blocks=[title]
        for index,bid in enumerate(IDS):
            b=copy.deepcopy(example);value='Controlled paragraph '+chr(65+index)+' keeps its exact saved result after the worker restarts.'
            b.update(id=bid,order=index+1,kind='paragraph',parent_id=title['id'],owner_id=None,language='en',translatable=True,
                raw_text=value,normalized_text=value,normalization_edits=[],source_inline=[{'type':'text','text':value}],warnings=[],attributes={})
            b['source_hash']=block_hash(b,source['protected_atoms']);blocks.append(b)
        source['blocks']=blocks;source['reading_order']=[b['id'] for b in blocks]
        for asset in source['assets']:
            target=cfg.data/asset['storage_key'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'tests'/asset['storage_key'],target)
        validate_source(source,asset_root=cfg.data);key='documents/doc_resume/sources/source_resume.json';sha=write_snapshot(cfg.data,key,source)
        original=next(a for a in source['assets'] if a['id']==source['original_asset_id'])
        with db.transaction() as session:
            assert not list(session.scalars(select(Document))), 'This scenario requires a genuinely fresh database.'
            settings=session.get(Settings,'singleton');settings.dispatch_disabled=False;settings.instance_budget_micro=1000000
            session.add(SourceAsset(id=original['id'],sha256=source['sha256'],byte_size=original['byte_size'],page_count=1,storage_key=original['storage_key']));session.flush()
            session.add(Document(id='doc_resume',title='Explicit FakeProvider process-resume fixture',source_asset_id=original['id'],current_source_id=source['id'],source_language='en'));session.flush()
            session.add(SourceRevision(id=source['id'],document_id='doc_resume',asset_id=original['id'],snapshot_hash=sha,storage_key=key));session.flush()
            session.add(Edition(id='edition_resume',document_id='doc_resume',target_locale='zh-Hans',current_draft_id='draft_resume'));session.flush()
            session.add(Draft(id='draft_resume',document_id='doc_resume',edition_id='edition_resume',source_revision_id=source['id'],profile=PROFILE));session.flush()
            translated_title=next(r for r in ir['translation_revision']['results'] if r['block_id']==title['id'])
            session.add(SegmentVersion(id='title_saved',draft_id='draft_resume',block_id=title['id'],sequence=1,target_inline=translated_title['target_inline'],
                origin='manual_ui',reason='Authored internal title fixture; no semantic accuracy claim',context_hash=context_hash(source,title['id']),source_hash=title['source_hash']))
            payload={'draft_id':'draft_resume','source_revision_id':source['id'],'source_hash':sha,'profile':PROFILE,'locale':'zh-Hans',
                'external_processing_confirmed':True,'publish_policy':'auto_publish','glossary_revision':'empty-v1','glossary':[],'block_ids':IDS}
            session.add(Job(id='resume_job',document_id='doc_resume',stage='translating',payload=payload,budget_micro=1000000));session.flush()
            session.add(Task(id='resume_planner',job_id='resume_job',kind='translate'))
        state={'ids':IDS,'source_key':key,'source_hash':sha,'source_pdf_sha256':source['sha256'],
            'asset_hashes':{a['storage_key']:file_hash(cfg.data/a['storage_key']) for a in source['assets']},
            'source_kind':'authored internal IR fixture; not parsed source gold','provider_kind':'explicit injected FakeProvider; no paid or external request'}
        (OUT/'state.json').write_text(json.dumps(state,indent=2));print(json.dumps({'operation':op,'queued_blocks':10}));return
    state=json.loads((OUT/'state.json').read_text());counter=json.loads((OUT/'fake-calls.json').read_text())
    if op=='final':
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            with db.transaction() as session:
                job=session.get(Job,'resume_job')
                if job.status=='succeeded':break
                assert job.status not in ('failed','waiting_budget','waiting_config','outcome_unknown'),(job.status,job.error)
            time.sleep(.3)
        else:raise AssertionError('Worker did not finish natural lease recovery/publication')
        counter=json.loads((OUT/'fake-calls.json').read_text())
    with db.transaction() as session:
        saved=records(session);job=session.get(Job,'resume_job');permits=list(session.scalars(select(Permit)))
        assert file_hash(cfg.data/state['source_key'])==state['source_hash']
        assert all(file_hash(cfg.data/key)==sha for key,sha in state['asset_hashes'].items())
        if op=='barrier':
            assert len(saved)==3 and job.progress['verified_blocks']==3 and job.progress['total_blocks']==10,(saved,job.progress)
            assert len(permits)==3 and all(p.state=='settled' for p in permits)
            assert sum(counter['by_block'].values())==3 and set(counter['by_block'])==set(saved)
            assert not list(session.scalars(select(Publication))) and not list(session.scalars(select(Artifact)))
            report={'progress_fraction':'3/10','verified_blocks':3,'total_blocks':10,'saved_segments':saved,'fake_calls':counter,
                'source_and_assets_unchanged':True,'publication_count':0,'inflight_paid_permits':0,'simulated_settled_permits':3}
            (OUT/'barrier-verified.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));return
        before=json.loads((OUT/'barrier-verified.json').read_text())
        assert len(saved)==10 and all(saved[k]==v for k,v in before['saved_segments'].items())
        assert counter['by_block']=={bid:1 for bid in IDS},counter
        assert not any(c['block_id'] in before['saved_segments'] for c in counter['events'] if c['phase']=='after-restart')
        assert len(permits)==10 and all(p.state=='settled' and p.actual_micro==150 for p in permits)
        assert job.progress['verified_blocks']==10 and job.progress['verified_units']==10 and job.progress['requests']==10
        publications=list(session.scalars(select(Publication)));artifacts=list(session.scalars(select(Artifact)));revisions=list(session.scalars(select(TranslationRevision)))
        assert len(publications)==len(artifacts)==len(revisions)==1
        edition=session.get(Edition,'edition_resume');artifact=artifacts[0];revision=revisions[0]
        assert edition.current_artifact_id==artifact.id==publications[0].artifact_id and edition.generation==2
        assert artifact.translation_revision_id==revision.id and artifact.state=='verified'
        manifest=verify_artifact(cfg.data/artifact.storage_key);assert digest(manifest)==artifact.manifest_hash
        html=(cfg.data/artifact.storage_key/'index.html').read_text(encoding='utf8')
        assert all(html.count('id="b-'+bid+'"')==1 for bid in IDS)
        assert len(list(session.scalars(select(Task).where(Task.kind=='publish'))))==1
        qa=session.get(QA,session.get(Draft,'draft_resume').qa_id);assert qa.valid is True
        task_rows=[{'id':task.id,'kind':task.kind,'block_id':task.payload.get('unit',{}).get('owner_block_id'),
            'status':task.status,'fence':task.fence,'attempts':task.attempts} for task in session.scalars(select(Task).where(Task.job_id=='resume_job'))]
        assert all(row['status']=='succeeded' for row in task_rows)
        report={'status':'passed','verified_blocks':10,'total_blocks':10,'saved_segments':saved,'fake_calls':counter,
            'initial_three_targets_and_source_hashes_unchanged':True,'initial_three_never_called_after_restart':True,
            'source_and_assets_unchanged':True,'one_result_per_block':True,'simulated_settled_permits':10,'live_provider_requests':0,
            'real_publication_count':1,'real_artifact_count':1,'real_translation_revision_count':1,'artifact_id':artifact.id,
            'qa_id':qa.id,'qa_valid':qa.valid,'qa_fingerprint':qa.fingerprint,'tasks':task_rows,'artifact_manifest_sha256':artifact.manifest_hash,
            'artifact_html_sha256':file_hash(cfg.data/artifact.storage_key/'index.html'),
            'scope':'Actual30percent completion/SIGKILL/restart/QA/seal/publication using explicit FakeProvider; no paid usage, parser gold or translation-quality claim'}
    page,_=request('http://127.0.0.1:8080','GET','/artifacts/'+report['artifact_id']+'/index.html');assert digest(page)==report['artifact_html_sha256']
    (OUT/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':main()
