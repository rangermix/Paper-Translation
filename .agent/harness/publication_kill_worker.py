"""One-off test worker: hold exactly after real durable artifact build."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
from pathlib import Path
import time
from packages.publisher import Publisher
from workers.main import main

original=Publisher.build


def barrier(self,*args,**kwargs):
    manifest=original(self,*args,**kwargs)
    Path('/evidence/publish-kill-barrier.json').write_text(json.dumps({
        'window':'real Publisher.build returned; publication transaction has not started',
        'manifest':manifest,'timestamp':time.time()},indent=2))
    while True:time.sleep(.1)


Publisher.build=barrier
if __name__=='__main__':main()
