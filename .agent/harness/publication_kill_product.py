"""Fresh private Compose fixture control; all publication runs through real HTTP."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import time
import uuid

from sqlalchemy import select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Artifact, Attempt, Edition, Job, Permit, Publication, Task
from smoke_library import request

BASE='http://127.0.0.1:8080'
STATE=Path('/evidence/state.json')


def command(path,body,generation=1):
    return request(BASE,'POST',path,body,{'If-Match':f'"{generation}"','Idempotency-Key':uuid.uuid4().hex},(200,201,202))[0]


def wait_job(db,identifier,seconds=130):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        with db.transaction() as session:
            job=session.get(Job,identifier)
            if job.status=='succeeded':return
            assert job.status not in ('failed','outcome_unknown'),(job.status,job.error)
        time.sleep(.25)
    raise AssertionError('Real worker did not recover before deadline')


def main():
    args=argparse.ArgumentParser();args.add_argument('operation',choices=['prepare','queue','barrier','recovered']);op=args.parse_args().operation
    cfg=Config.load();db=Database(cfg)
    if op=='prepare':
        runpy.run_path('/tests/support.py')['seed_editor'](db,cfg)
        qa=command('/api/v1/drafts/draft_fixture/validate',{});assert qa['valid']
        revision=command('/api/v1/drafts/draft_fixture/seal',{'qa_id':qa['id'],'qa_fingerprint':qa['fingerprint'],'generation':1})
        job=command('/api/v1/editions/edition_fixture/publish',{'translation_revision_id':revision['id'],'expected_generation':1})
        wait_job(db,job['id'])
        with db.transaction() as session:
            edition=session.get(Edition,'edition_fixture')
            assert edition.generation==2
            artifact=session.get(Artifact,edition.current_artifact_id)
            content,_=request(BASE,'GET','/read/doc_fixture/zh-Hans')
            state={'revision_id':revision['id'],'first_artifact':artifact.id,'first_generation':2,
                   'first_html_sha256':hashlib.sha256(content).hexdigest()}
        STATE.write_text(json.dumps(state,indent=2))
    else:
        state=json.loads(STATE.read_text())
        if op=='queue':
            job=command('/api/v1/editions/edition_fixture/publish',{'translation_revision_id':state['revision_id'],'expected_generation':2},2)
            with db.transaction() as session:
                task=session.scalar(select(Task).where(Task.job_id==job['id']))
                state.update(second_job=job['id'],second_task=task.id,second_artifact=task.payload['artifact_id'])
            STATE.write_text(json.dumps(state,indent=2))
        elif op=='barrier':
            assert Path('/evidence/publish-kill-barrier.json').is_file()
            with db.transaction() as session:
                edition=session.get(Edition,'edition_fixture');task=session.get(Task,state['second_task'])
                assert edition.current_artifact_id==state['first_artifact'] and edition.generation==2
                assert session.get(Artifact,state['second_artifact']) is None
                assert task.status=='leased' and task.attempts==1 and task.fence==1
                assert (cfg.data/f'documents/doc_fixture/artifacts/{state["second_artifact"]}/manifest.json').is_file()
            old,_=request(BASE,'GET','/read/doc_fixture/zh-Hans');assert hashlib.sha256(old).hexdigest()==state['first_html_sha256']
            request(BASE,'GET',f'/artifacts/{state["second_artifact"]}/index.html',expected=404)
        else:
            wait_job(db,state['second_job'])
            with db.transaction() as session:
                edition=session.get(Edition,'edition_fixture');task=session.get(Task,state['second_task'])
                assert edition.current_artifact_id==state['second_artifact'] and edition.generation==3
                assert task.status=='succeeded' and task.attempts==2 and task.fence==2
                events=list(session.scalars(select(Publication).where(Publication.edition_id=='edition_fixture').order_by(Publication.generation)))
                assert [(e.generation,e.artifact_id) for e in events]==[(2,state['first_artifact']),(3,state['second_artifact'])]
                attempts=list(session.scalars(select(Attempt).where(Attempt.task_id==task.id).order_by(Attempt.fence)))
                assert len(attempts)==2 and attempts[-1].state=='succeeded'
                assert not list(session.scalars(select(Permit)))
                assert len(list(session.scalars(select(Artifact))))==2
            old,_=request(BASE,'GET',f'/artifacts/{state["first_artifact"]}/index.html')
            current,_=request(BASE,'GET','/read/doc_fixture/zh-Hans')
            assert hashlib.sha256(old).hexdigest()==state['first_html_sha256']
            assert current==old # Same sealed snapshot republished, byte-identical deterministic HTML.
            result={**state,'status':'passed','window':'after complete artifact files, before database artifact/pointer commit',
                    'process_signal':'SIGKILL','attempts':2,'final_fence':2,'publication_events':2,'provider_calls':0,
                    'old_html_unchanged':True,'unpublished_files_http_404':True,'natural_lease_expiry':True}
            Path('/evidence/result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'operation':op,'status':'passed'}))


if __name__=='__main__':main()
