"""Wrap the real worker with a durable explicitly simulated transport and30% barrier."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import os
from pathlib import Path
import threading
import time

from sqlalchemy import select
from packages.domain.models import SegmentVersion
from packages.ir import canonical_bytes
from packages.providers.fake import FakeProvider
import packages.translation.execution as execution
from workers.main import main

OUT=Path('/evidence');lock=threading.Lock();gate=threading.Event()


def durable(name,value):
    temporary=OUT/(name+'.tmp')
    with temporary.open('w') as file:json.dump(value,file,indent=2);file.flush();os.fsync(file.fileno())
    temporary.replace(OUT/name)


def stopped():
    if not (OUT/'restart-authorized.json').exists():
        while gate.is_set():time.sleep(.1)


class CountingFake(FakeProvider):
    def translate(self,units,profile,glossary):
        stopped()
        with lock:
            path=OUT/'fake-calls.json';counter=json.loads(path.read_text()) if path.exists() else {'by_block':{},'events':[]}
            for unit in units:
                bid=unit['owner_block_id'];counter['by_block'][bid]=counter['by_block'].get(bid,0)+1
                counter['events'].append({'block_id':bid,'unit_id':unit['unit_id'],'phase':'after-restart' if (OUT/'restart-authorized.json').exists() else 'before-kill'})
            durable('fake-calls.json',counter)
            response=super().translate(units,profile,glossary)
            response['request_id']='explicit-fake-resume-'+str(len(counter['events']))
            response['output_text']=canonical_bytes({'results':[{'unit_id':u['unit_id'],'target_inline':[{'type':'text','text':'受控段落 '+u['owner_block_id']+'。此文本仅用于离线进程恢复测试。'}]} for u in units]}).decode()
            return response


provider=CountingFake();original_execute=execution.execute_translation;original_commit=execution.commit_unit


def execute(*args,**kwargs):
    stopped();return original_execute(*args,provider=provider,**kwargs)


def commit(db,*args,**kwargs):
    result=original_commit(db,*args,**kwargs)
    if not (OUT/'restart-authorized.json').exists():
        with db.transaction() as session:
            completed=list(session.scalars(select(SegmentVersion).where(SegmentVersion.draft_id=='draft_resume',SegmentVersion.block_id.like('resume-%'))))
        if len(completed)==3:
            gate.set()
            with lock:durable('kill-barrier.json',{'completed_blocks':3,'at':time.time(),'provider_kind':'explicit FakeProvider; no external calls'})
            stopped()
    return result


execution.execute_translation=execute;execution.commit_unit=commit
if __name__=='__main__':main()
