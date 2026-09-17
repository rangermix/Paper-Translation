"""Actual cold PDF action parse with an internal listener and positive controls.

Uses only an empty Provider key, immutable image IDs, fresh volumes and isolated
networks. Counts successful listener requests; does not claim syscall tracing.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import uuid


sys.path.insert(0, str(ROOT / '.agent/harness'))
from live_provider_run import run_recorded_command
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject

APP = os.environ.get('ACCEPTANCE_APP_IMAGE', 'sha256:cf026d80b2a9a337f9528e78238258508cf24119208e0ce99265dd16661ee52e')
PARSER = os.environ.get('ACCEPTANCE_PARSER_IMAGE', 'sha256:7e2732e340e9c148663918d5d75977f50b66908071c2fbb265fa08af9ede39f6')
DATABASE = os.environ.get('ACCEPTANCE_DATABASE_IMAGE', 'sha256:04a249fe1c97c960a51b8630d0cec6b82a9a8ee87a78933c1e15bccbd669ff2a')

SERVER = r'''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
state={'controls':0,'pdf_requests':[]}
def save(): Path('/probe-evidence/counts.json').write_text(json.dumps(state))
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=='/control':state['controls']+=1
  elif self.path.startswith('/pdf-'):state['pdf_requests'].append(self.path)
  save();data=json.dumps(state).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_POST(self):self.do_GET()
 def log_message(self,*args):pass
save();HTTPServer(('0.0.0.0',8787),Handler).serve_forever()
'''

PRODUCT = r'''
import hashlib,json,time,urllib.request
from pathlib import Path
from sqlalchemy import func,select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Attempt,Permit,SourceDraft,SourceRevision,Task
from smoke_library import request,upload,etag
out=Path('/action-evidence');meta=json.loads((out/'input.json').read_text());data=(out/'action-probe.pdf').read_bytes()
assert hashlib.sha256(data).hexdigest()==meta['sha256']
def probe(path):return json.loads(urllib.request.urlopen('http://probe:8787/'+path,timeout=5).read())
assert probe('control')=={'controls':1,'pdf_requests':[]}
base='http://127.0.0.1:8080';state=upload(base,data,'action-probe.pdf');assert state['status']=='verified',state
doc,headers=request(base,'POST','/api/v1/imports',{'source':{'kind':'pdf_upload','upload_id':state['id']},'source_language':'en'}, {'Idempotency-Key':'probe-import'},201)
original,_=request(base,'GET',doc['original_url']);assert original==data
job,_=request(base,'POST','/api/v1/documents/'+doc['id']+'/parse',{'source_asset_id':doc['source_asset_id']}, {'If-Match':etag(headers),'Idempotency-Key':'probe-parse'},202)
deadline=time.monotonic()+150
while time.monotonic()<deadline:
 current,_=request(base,'GET','/api/v1/jobs/'+job['job_id'])
 if current['status'] in {'needs_review','succeeded','failed'}:break
 time.sleep(.25)
assert current['status'] in {'needs_review','succeeded'} and current['import_id'],current
preflight,_=request(base,'GET','/api/v1/imports/'+current['import_id']+'/preflight')
(out/'preflight.json').write_text(json.dumps(preflight,ensure_ascii=False,indent=2))
assert preflight['can_translate'] and not preflight['unresolved'],preflight['unresolved']
assert [b['normalized_text'] for b in preflight['blocks']]==meta['source_text']
page,_=request(base,'GET',preflight['pages'][0]['page_image_url']);assert page.startswith(b'\x89PNG')
time.sleep(.3);counts=probe('control');assert counts=={'controls':2,'pdf_requests':[]},counts
db=Database(Config.load())
with db.transaction() as s:
 assert s.scalar(select(func.count()).select_from(Permit))==0
 assert s.scalar(select(func.count()).select_from(SourceRevision))==0
 assert s.scalar(select(func.count()).select_from(SourceDraft))==1
 tasks=list(s.scalars(select(Task)));assert sorted(t.kind for t in tasks)==['inspect','parse']
 assert all(t.status=='succeeded' and t.attempts==1 for t in tasks)
 assert s.scalar(select(func.count()).select_from(Attempt))==2
assert not Path('/tmp/action-probe-must-not-run').exists()
result={'status':'passed','document_id':doc['id'],'source_draft_id':preflight['id'],'sha256':meta['sha256'],
 'actual_parse':True,'source_text_exact':True,'original_bytes_exact':True,'preflight_can_translate':True,
 'probe_counts':counts,'provider_permits':0,'external_provider_requests':0,
 'boundary':'No successful PDF-specific listener request under network none; this is not a syscall trace of connect attempts.'}
(out/'product-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
'''


def main():
    import re
    if not all(re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in (APP, PARSER, DATABASE)):
        raise ValueError("Use exact inspected image IDs in ACCEPTANCE_*_IMAGE; mutable tags are not accepted.")
    token = uuid.uuid4().hex[:10]
    project = 'bilingual-action-probe-' + token
    out = ROOT / '.agent/tmp/evidence/action-probe' / token
    out.mkdir(parents=True)
    (out / 'driver.py').write_bytes(Path(__file__).read_bytes())
    (out / 'probe_server.py').write_text(SERVER, encoding='utf-8')
    (out / 'product.py').write_text(PRODUCT, encoding='utf-8')
    with socket.socket() as port:
        port.bind(('127.0.0.1', 18092))
    expected = next(d for d in json.loads((ROOT / 'tests/fixtures/live-provider/manifest.json').read_text('utf-8'))['documents'] if d['id']=='controlled-en')
    source = ROOT / 'tests/fixtures/live-provider/controlled-en.pdf'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=expected['sha256']:
        raise RuntimeError('Controlled source changed')
    writer = PdfWriter(clone_from=PdfReader(source))
    probe_url = 'http://probe:8787/pdf-' + token
    def action(kind, field, target):
        return DictionaryObject({NameObject('/S'):NameObject(kind),NameObject(field):TextStringObject(target)})
    uri = action('/URI', '/URI', probe_url+'/uri')
    uri[NameObject('/Next')] = ArrayObject([action('/SubmitForm','/F',probe_url+'/submit'),
        action('/GoToR','/F',probe_url+'/remote.pdf'),action('/Launch','/F','/tmp/action-probe-must-not-run')])
    uri['/Next'][1][NameObject('/D')] = ArrayObject([FloatObject(0),NameObject('/Fit')])
    writer._root_object[NameObject('/OpenAction')] = uri
    writer.pages[0][NameObject('/AA')] = DictionaryObject({NameObject('/O'):action('/URI','/URI',probe_url+'/page-open')})
    writer.add_annotation(0, DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Link'),
        NameObject('/Rect'):ArrayObject([FloatObject(x) for x in [5,5,15,15]]),NameObject('/A'):action('/URI','/URI',probe_url+'/link')}))
    writer.write(out / 'action-probe.pdf')
    fixture = {'sha256':hashlib.sha256((out/'action-probe.pdf').read_bytes()).hexdigest(),'source_text':expected['source_text'],
        'native_source_sha256':expected['sha256'],'pdf_probe_prefix':probe_url,'actions':['URI','SubmitForm','GoToR','Launch','page AA URI','link URI']}
    (out/'input.json').write_text(json.dumps(fixture,indent=2),encoding='utf-8')
    empty = ROOT/'deployment/provider_key.empty'
    if empty.read_bytes():raise RuntimeError('Only empty Provider key permitted')
    env={**os.environ,'APP_IMAGE':APP,'PARSER_IMAGE':PARSER,'DATABASE_IMAGE':DATABASE,'PORT':'18092','PROVIDER_KEY_FILE':str(empty)}
    override=out/'override.json'
    override.write_text(json.dumps({'services':{'app':{'volumes':[str(ROOT/'.agent/harness')+':/harness:ro',str(out)+':/action-evidence'],'environment':{'PYTHONPATH':'/app/src:/app:/harness'}},
        'probe':{'image':APP,'command':['python','/probe-evidence/probe_server.py'],'user':'10001:10001','read_only':True,
            'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'volumes':[str(out)+':/probe-evidence'],'networks':['backend'],
            'healthcheck':{'test':['CMD','python','-c',"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/counts').read()"],'interval':'2s','timeout':'2s','retries':10}}},
        'networks':{'http':{'internal':True},'provider_egress':{'internal':True}}}),encoding='utf-8')
    commands=[]
    def call(argv,timeout=240):return run_recorded_command(argv,env=env,commands=commands,evidence_path=out/'commands.json',timeout=timeout)
    base=['docker','compose','-f','deployment/compose.production.yaml','-f',str(override),'-p',project]
    def compose(*args):return call(base+list(args))
    result={'status':'running','project':project,'images':{'app':APP,'parser':PARSER,'database':DATABASE},'started_at':datetime.now(timezone.utc).isoformat()}
    try:
        call(['docker','image','inspect',APP,PARSER,DATABASE])
        compose('up','-d','--wait','--no-build','--pull','never')
        networks=json.loads(call(['docker','network','inspect',*[project+'_'+n for n in ['http','backend','provider_egress']]]))
        if not all(n['Internal'] for n in networks):raise RuntimeError('Application networks must be internal')
        parser=json.loads(call(['docker','inspect',compose('ps','-q','parser').strip()]))[0]
        if parser['HostConfig']['NetworkMode']!='none':raise RuntimeError('Parser must have no network')
        env_names=[line.split('=',1)[0] for line in parser['Config']['Env']]
        if any(any(word in name.upper() for word in ['SECRET','TOKEN','PROVIDER_KEY','DATABASE']) for name in env_names):raise RuntimeError('Unexpected parser secret environment')
        if {m['Destination'] for m in parser['Mounts'] if m['Type']!='tmpfs'}!={'/inputs','/outputs'}:raise RuntimeError('Unexpected parser mount')
        compose('exec','-T','parser','python','-m','workers.parser.health')
        compose('exec','-T','app','python','/action-evidence/product.py')
        result.update(status='passed',product=json.loads((out/'product-result.json').read_text()),parser_environment_names=env_names,
            all_networks_internal=True,parser_network_none=True,parser_model_hash_health_passed=True)
    except BaseException as error:
        result.update(status='failed',error_type=type(error).__name__,error=str(error)[-2000:]);raise
    finally:
        try:compose('logs','--no-color','--tail','120','app','worker','parser','probe')
        finally:
            compose('down','--remove-orphans')
            remaining=call(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project]).strip()
            result.update(remaining_containers=remaining.splitlines() if remaining else [],volumes_retained=True,finished_at=datetime.now(timezone.utc).isoformat())
            (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps({'status':result['status'],'evidence':str(out),'remaining':remaining}))
            if remaining:raise RuntimeError('Action probe cleanup incomplete')


if __name__=='__main__':main()
