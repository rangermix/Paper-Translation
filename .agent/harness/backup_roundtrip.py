"""Exercise the real Compose backup/restore CLI against the acceptance document."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
from pathlib import Path
import subprocess
import time

from smoke_library import request, etag


BASE = 'http://127.0.0.1:8080'
COMPOSE = ['docker', 'compose', '-f', 'deployment/compose.production.yaml']


def main():
    calls=[]
    def cli(*args):
        argv=COMPOSE+['run','--rm','--no-deps','maintenance','python','-m','packages.maintenance',*args]
        run=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=180)
        calls.append({'argv':argv,'exit_code':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
        (ROOT/'.agent/tmp/evidence/backup-roundtrip-commands.json').write_text(json.dumps(calls,indent=2))
        assert run.returncode==0,run.stderr
        return json.loads(run.stdout.strip().splitlines()[-1])
    previous=json.loads((ROOT/'.agent/tmp/evidence/library-smoke.json').read_text())
    path='/api/v1/documents/'+previous['document_id']
    before,h=request(BASE,'GET',path)
    original,_=request(BASE,'GET',path+'/original')
    backup=cli('backup')
    identifier=backup['backup_id']
    cli('verify-backup','--backup-id',identifier)
    rejected,_=request(BASE,'PATCH',path,{'title':'Blocked during backup'},{'If-Match':etag(h)},expected=503)
    assert rejected['error']['code']=='MAINTENANCE'
    cli('maintenance-off')
    before,h=request(BASE,'GET',path)
    changed,_=request(BASE,'PATCH',path,{'title':'Temporary restore acceptance mutation'},{'If-Match':etag(h)})
    assert changed['title']!=before['title']
    restored=cli('restore','--backup-id',identifier,'--replace')
    cli('verify')
    after,h=request(BASE,'GET',path)
    restored_original,_=request(BASE,'GET',path+'/original')
    assert after==before,(after,before)
    assert restored_original==original
    rejected,_=request(BASE,'PATCH',path,{'title':'Blocked after restore'},{'If-Match':etag(h)},expected=503)
    assert rejected['error']['code']=='MAINTENANCE'
    cli('maintenance-off')
    summary={'status':'passed','backup_id':identifier,'document_id':before['id'],
        'checked':['real pg_dump/pg_restore','backup hash verification','maintenance rejects writes',
            'intentional metadata mutation rolled back','source bytes restored identically',
            'post-restore consistency verification','restore retains maintenance until explicit maintenance-off'],
        'dispatch_disabled':restored['dispatch_disabled'],'files':backup['files']}
    (ROOT/'.agent/tmp/evidence/backup-roundtrip.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))


if __name__=='__main__':
    main()
