"""Kill a real bounded worker process after files but before atomic pointer commit."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import argparse
import os
from pathlib import Path
import subprocess
import time
import uuid




def main():
    parser=argparse.ArgumentParser();parser.add_argument('--window',choices=['publication','before-provider','after-response','after-checkpoint'],default='publication');args=parser.parse_args()
    publication=args.window=='publication'
    suffix=uuid.uuid4().hex[:8];project='bilingual-kill-'+suffix;worker=project+'-barrier'
    evidence=ROOT/('.agent/tmp/evidence/publication-process-kill' if publication else '.agent/tmp/evidence/translation-process-kill')/suffix;evidence.mkdir(parents=True)
    override=evidence/'compose.yaml'
    mount=lambda host,target:f'{host.as_posix()}:{target}'
    override.write_text(json.dumps({'services':{
        'app':{'volumes':[mount(ROOT/'.agent/harness','/harness:ro'),mount(ROOT/'tests/support.py','/tests/support.py:ro'),mount(evidence,'/evidence')]},
        'worker':{'environment':{'FAULT_WINDOW':args.window},'volumes':[mount(ROOT/'.agent/harness','/harness:ro'),mount(evidence,'/evidence')]}}}))
    env={**os.environ,'APP_IMAGE':os.environ.get('ACCEPTANCE_APP_IMAGE','bilingual-personal-pdf-app:acceptance-candidate'),
         'PARSER_IMAGE':os.environ.get('ACCEPTANCE_PARSER_IMAGE','bilingual-personal-pdf-parser:acceptance-candidate'),
         'DATABASE_IMAGE':os.environ.get('ACCEPTANCE_DATABASE_IMAGE','bilingual-personal-pdf-db:acceptance-candidate'),
         'PORT':str(18089+['publication','before-provider','after-response','after-checkpoint'].index(args.window))}
    commands=[]
    def run(argv):
        result=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
        commands.append({'argv':argv,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        (evidence/'commands.json').write_text(json.dumps(commands,indent=2))
        assert result.returncode==0,result.stderr[-3000:]+result.stdout[-1000:]
        return result.stdout
    def compose(*args):return run(['docker','compose','-f','deployment/compose.production.yaml','-f','deployment/compose.acceptance-offline.yaml','-f',str(override),'-p',project,*args])
    script='publication_kill' if publication else 'translation_kill'
    def product(action):return compose('exec','-T','app','python','/harness/'+script+'_product.py',action)
    try:
        compose('up','-d','--wait','--no-build','--pull','never')
        product('prepare')
        start=time.monotonic();compose('stop','worker');stop_seconds=round(time.monotonic()-start,3)
        assert stop_seconds<10,stop_seconds
        product('queue')
        compose('run','--detach','--no-deps','--name',worker,'worker','python','/harness/'+script+'_worker.py')
        deadline=time.monotonic()+45
        marker='publish-kill-barrier.json' if publication else 'translation-kill-barrier.json'
        while not (evidence/marker).exists() and time.monotonic()<deadline:time.sleep(.2)
        assert (evidence/marker).exists(),'real worker did not reach fault barrier'
        product('barrier')
        run(['docker','kill','--signal','KILL',worker])
        killed=json.loads(run(['docker','inspect',worker]))[0]
        assert killed['State']['ExitCode']==137
        compose('start','worker')
        product('recovered')
        result=json.loads((evidence/'result.json').read_text());result.update(project=project,killed_container=worker,
            actual_exit_code=137,idle_worker_sigterm_seconds=stop_seconds,all_external_networks_disabled=True)
        (evidence/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        try:run(['docker','rm','--force',worker])
        except Exception:pass
        compose('down','--remove-orphans') # Keep exact named volumes as evidence; never --volumes.


if __name__=='__main__':main()
