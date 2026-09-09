"""Explicit test double with durable counters; real worker/leases/ledger are used."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import os
from pathlib import Path
import time

from packages.providers.fake import FakeProvider
import packages.translation.execution as execution
from workers.main import main

WINDOW=os.environ['FAULT_WINDOW']


def durable(name,value):
    with (Path('/evidence')/name).open('w') as file:
        json.dump(value,file,indent=2);file.flush();os.fsync(file.fileno())


def barrier():
    durable('translation-kill-barrier.json',{'window':WINDOW,'at':time.time(),
        'provider_kind':'explicit FakeProvider, never real Provider evidence'})
    while True:time.sleep(.1)


class CountingFake(FakeProvider):
    def translate(self,*args,**kwargs):
        if WINDOW=='before-provider':barrier()
        response=super().translate(*args,**kwargs)
        durable('fake-provider-counter.json',{'calls':len(self.calls),'usage_kind':'simulated, not supplier billing'})
        return response


provider=CountingFake()
execute_original=execution.execute_translation


def execute(*args,**kwargs):
    return execute_original(*args,provider=provider,**kwargs)


execution.execute_translation=execute
if WINDOW=='after-response':
    settle_original=execution.settle
    def settle(*args,**kwargs):
        barrier()
        return settle_original(*args,**kwargs)
    execution.settle=settle
elif WINDOW=='after-checkpoint':
    commit_original=execution.commit_unit
    def commit(*args,**kwargs):
        barrier()
        return commit_original(*args,**kwargs)
    execution.commit_unit=commit


if __name__=='__main__':main()
