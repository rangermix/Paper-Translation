"""Internal fixture for process-level money/checkpoint faults; no external API."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import json
from pathlib import Path
import runpy
import time

from sqlalchemy import delete, select
from packages.billing.ledger import budget_totals
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Attempt, Draft, Job, Permit, SegmentVersion, Settings, SourceRevision, Task, TranslationCache

STATE=Path('/evidence/state.json')
PRICE={'revision':'fault-v1','currency':'USD','input_micro_per_million':1000000,'cached_input_micro_per_million':1000000,
       'output_micro_per_million':1000000,'output_includes_reasoning':True,'input_bound_rule':'utf8-byte-ceiling-v1'}
PROFILE={'configured':True,'provider':'openai','model_id':'explicit-fake-process-fault','profile_revision':'fault-v1',
    'prompt_version':'translate-v1','privacy_revision':'fault-v1','enabled_pairs':[['en','zh-Hans']],
    'max_input_tokens':16384,'max_output_tokens':4096,'max_unit_characters':2000,'price':PRICE}


def fake_calls():
    file=Path('/evidence/fake-provider-counter.json')
    return json.loads(file.read_text())['calls'] if file.exists() else 0


def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['prepare','queue','barrier','recovered']);op=parser.parse_args().operation
    cfg=Config.load();db=Database(cfg)
    if op=='prepare':
        runpy.run_path('/tests/support.py')['seed_editor'](db,cfg)
        with db.transaction() as session:
            session.execute(delete(SegmentVersion).where(SegmentVersion.draft_id=='draft_fixture',SegmentVersion.block_id=='item'))
            session.get(Draft,'draft_fixture').profile=PROFILE
            settings=session.get(Settings,'singleton');settings.dispatch_disabled=False;settings.instance_budget_micro=1000000
        STATE.write_text(json.dumps({'explicit_test_double':True,'live_provider_calls':0}))
    elif op=='queue':
        with db.transaction() as session:
            source=session.get(SourceRevision,'src_fixture')
            payload={'draft_id':'draft_fixture','source_revision_id':source.id,'source_hash':source.snapshot_hash,
                'profile':PROFILE,'locale':'zh-Hans','external_processing_confirmed':True,'publish_policy':'manual_approval',
                'glossary_revision':'empty-v1','glossary':[],'block_ids':['item']}
            session.add(Job(id='fault_job',document_id='doc_fixture',stage='translating',payload=payload,budget_micro=1000000));session.flush()
            session.add(Task(id='fault_planner',job_id='fault_job',kind='translate'))
    else:
        window=json.loads(Path('/evidence/translation-kill-barrier.json').read_text())['window']
        checkpoint=window=='after-checkpoint'
        if op=='recovered':
            deadline=time.monotonic()+130
            while time.monotonic()<deadline:
                with db.transaction() as session:
                    job=session.get(Job,'fault_job')
                    if job.status in (('ready','needs_review') if checkpoint else ('outcome_unknown',)):break
                    assert job.status not in ('failed','waiting_config','waiting_budget'),(job.status,job.error)
                time.sleep(.25)
            else:raise AssertionError('Natural lease recovery did not reach expected state')
        with db.transaction() as session:
            task=session.scalar(select(Task).where(Task.job_id=='fault_job',Task.id!='fault_planner'))
            attempts=list(session.scalars(select(Attempt).where(Attempt.task_id==task.id).order_by(Attempt.fence)))
            permits=list(session.scalars(select(Permit)));assert len(permits)==1
            permit=permits[0]
            segments=list(session.scalars(select(SegmentVersion).where(SegmentVersion.draft_id=='draft_fixture',SegmentVersion.block_id=='item')))
            if op=='barrier':
                assert task.status=='leased' and task.fence==1 and task.attempts==1 and not segments
                assert permit.state==('settled' if checkpoint else 'reserved')
                assert attempts[0].state==('settled' if checkpoint else 'dispatching')
                if checkpoint:assert any(e.get('kind')=='validated_unit' for e in attempts[0].evidence)
            elif checkpoint:
                assert task.status=='succeeded' and task.fence==2 and task.attempts==2 and len(attempts)==2
                assert len(segments)==1 and segments[0].sequence==1
                assert segments[0].provenance_json['attempt_id']==attempts[0].id
                assert permit.state=='settled' and permit.actual_micro==150
                assert len(list(session.scalars(select(TranslationCache))))==1
            else:
                assert task.status=='outcome_unknown' and task.fence==1 and task.attempts==1 and len(attempts)==1
                assert permit.state=='unknown' and permit.actual_micro is None and not segments
                assert attempts[0].state=='outcome_unknown' and attempts[0].usage is None
            assert fake_calls()==(0 if window=='before-provider' else 1)
            result={'window':window,'status':'passed','scope':'actual SIGKILL/worker/PostgreSQL with explicit FakeProvider only',
                'provider_response_kind':'simulated, never actual supplier usage','live_provider_calls':0,
                'fake_provider_calls':fake_calls(),'attempts':task.attempts,'fence':task.fence,
                'permit_state':permit.state,'budget_totals':budget_totals(session),'segment_versions':len(segments),
                'natural_lease_expiry':True,'no_automatic_second_dispatch':True}
        if op=='recovered':Path('/evidence/result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'operation':op,'status':'passed'}))


if __name__=='__main__':main()
