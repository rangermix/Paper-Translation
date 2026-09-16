#!/usr/bin/env python3
"""Repository contract checks. Never marks application gates complete or calls a provider."""
from __future__ import annotations
import copy,hashlib,json,re,os
from datetime import datetime,timezone
from uuid import uuid4
from pathlib import Path
from urllib.parse import unquote
import jsonschema,yaml
from bs4 import BeautifulSoup
from validate_ir import semantic
R=Path(__file__).resolve().parents[1]
checks=[]

def package_files(suffix=None):
 """Check distributable sources, not dependencies or archived agent runs."""
 excluded={'.git','.agent','.venv','venv','node_modules','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','dist','test-results','playwright-report'}
 for directory, dirs, names in os.walk(R):
  dirs[:]=[name for name in dirs if name not in excluded]
  for name in names:
   path=Path(directory)/name
   if suffix is None or path.suffix==suffix:yield path

def agent_reference(path):
 try:return path.resolve().relative_to(R).parts[0]=='.agent'
 except (ValueError,IndexError):return False
def load(p):return json.loads((R/p).read_text('utf-8'))
def must(ok,msg):
 if not ok:raise ValueError(msg)
def check(name,fn):
 try:fn();checks.append({'name':name,'result':'pass'})
 except Exception as e:checks.append({'name':name,'result':'fail','detail':str(e)})
def rejects(fn):
 try:fn()
 except (ValueError,jsonschema.ValidationError):return
 raise AssertionError('Invalid input was not rejected')
def digest(b):return hashlib.sha256(b).hexdigest()
def main():
 req=load('contracts/requirements.json');tasks=load('contracts/implementation-backlog.json');gates=load('contracts/exit-gates.json')
 rs={x['id']:x for x in req};ts={x['id']:x for x in tasks};gs={x['id']:x for x in gates};ats=[a for x in req for a in x['tests']]
 check('65 unique requirements',lambda:must(len(rs)==len(req)==65,'count'))
 check('42 unique implementation work packages',lambda:must(len(ts)==len(tasks)==42,'count'))
 check('130 unique planned acceptance scenarios',lambda:must(len(ats)==len({a['id'] for a in ats})==130 and all(a['status']=='planned' for a in ats),'count/state'))
 check('24 unevaluated gates; work not falsely completed',lambda:must(len(gs)==len(gates)==24 and all(g['status']=='not_evaluated' for g in gates) and all(t['status']=='not_started' for t in tasks),'count/state'))
 def coverage():
  for rid,r in rs.items():
   must(any(rid in t['requirements'] for t in tasks),f'no task {rid}')
   must(any(rid in g['requirements'] for g in gates),f'no gate {rid}')
   must(all(a['requirement_id']==rid for a in r['tests']),f'AT mismatch {rid}')
  for t in tasks:must(set(t['depends_on'])<=ts.keys() and set(t['requirements'])<=rs.keys(),'unknown reference')
  for g in gates:must(set(g['requirements'])<=rs.keys(),'unknown gate reference')
 check('all requirements map to work, tests and gates',coverage)
 def dag():
  done=set();todo=set(ts)
  while todo:
   ready={i for i in todo if set(ts[i]['depends_on'])<=done};must(ready,'cycle');todo-=ready;done|=ready
 check('dependency graph acyclic',dag)
 for fn in ['document-ir-v3.schema.json','translation-response.schema.json','artifact-manifest.schema.json','import-request.schema.json']:
  check('JSON Schema syntax: '+fn,lambda fn=fn:jsonschema.Draft202012Validator.check_schema(load('contracts/'+fn)))
 sample=load('fixtures/sample-document-v3.json');isc=load('contracts/import-request.schema.json')
 check('PDF IR fixture passes syntax and semantic invariants',lambda:semantic(sample))
 check('all declared block kinds covered by fixture',lambda:must({b['kind'] for b in sample['source_revision']['blocks']}==set(load('contracts/document-ir-v3.schema.json')['$defs']['block']['properties']['kind']['enum']),'omitted kind'))
 def assets():
  for a in sample['source_revision']['assets']:
   p=R/a['storage_key'];must(p.is_file() and digest(p.read_bytes())==a['sha256'] and p.stat().st_size==a['byte_size'],'asset mismatch')
  must((R/'fixtures/sample.pdf').read_bytes().startswith(b'%PDF-'),'not PDF')
 check('fixture asset bytes and PDF signature match',assets)
 check('PDF upload request positive',lambda:jsonschema.validate(load('fixtures/import-pdf.json'),isc))
 check('provider output fixture positive',lambda:jsonschema.validate(load('fixtures/provider-output.json'),load('contracts/translation-response.schema.json')))
 for kind in ['url','upload','local_html','bilingual','text','markdown','docx','zip']:
  check('reject source kind '+kind,lambda kind=kind:rejects(lambda:jsonschema.validate({'source':{'kind':kind,'upload_id':'upl_fixture'}},isc)))
 for field,val in [('url','https://example.invalid'),('attachments',[]),('workspace_id','ws_1'),('user_id','u1')]:
  check('reject extra import '+field,lambda field=field,val=val:rejects(lambda:jsonschema.validate({**load('fixtures/import-pdf.json'),field:val},isc)))
 def invalid_mutation(fn):
  v=copy.deepcopy(sample);fn(v);rejects(lambda:semantic(v))
 tests=[
 ('unknown document identity',lambda v:v['document'].update(workspace_id='x')),
 ('nonPDF original asset MIME',lambda v:v['source_revision']['assets'][0].update(media_type='text/html')),
 ('nonPDF provenance',lambda v:v['source_revision']['blocks'][1]['provenance'][0].update(type='local_html')),
 ('invalid PDF bbox',lambda v:v['source_revision']['blocks'][1]['provenance'][0].update(bbox=[-1,0,3,4])),
 ('duplicate block',lambda v:v['source_revision']['blocks'].append(copy.deepcopy(v['source_revision']['blocks'][1]))),
 ('missing translation',lambda v:v['translation_revision']['results'].pop()),
 ('stale source hash',lambda v:v['translation_revision']['results'][1].update(source_hash='f'*64)),
 ('lost protected atom',lambda v:v['translation_revision']['results'][1].update(target_inline=[{'type':'text','text':'wrong'}])),
 ('duplicated protected atom',lambda v:v['translation_revision']['results'][1]['target_inline'].append({'type':'protected_ref','ref':'n64'})),
 ('unsubstantiated human review',lambda v:v['translation_revision']['results'][1].update(review_state='human_reviewed')),
 ('caption duplicated in root order',lambda v:v['source_revision']['reading_order'].append('figcap')),
 ('unsafe asset path',lambda v:v['source_revision']['assets'][0].update(storage_key='../private')),
 ('release with unresolved prose',lambda v:v['translation_revision']['results'][1].update(status='unresolved'))]
 for name,fn in tests:check('reject '+name,lambda fn=fn:invalid_mutation(fn))
 def reviewed_without_identity():
  from validate_ir import canonical
  v=copy.deepcopy(sample);t=v['translation_revision']['results'][1]
  t['review_state']='human_reviewed';t['review_record']={'origin':'manual_ui','reviewed_at':'2026-09-06T00:00:00Z','source_hash':t['source_hash'],'target_hash':digest(canonical(t['target_inline'])),'context_hash':t['context_hash'],'glossary_revision':t['generation']['glossary_revision'],'inherited_from':None}
  semantic(v)
 check('valid human review has no user or actor identity',reviewed_without_identity)
 def no_identity_schema():
  forbidden={'actor_id','user_id','workspace_id','tenant_id','account_id','role_id','reviewer_id'}
  def scan(x):
   if isinstance(x,dict):
    must(not (set(x.get('properties',{})) & forbidden),'identity field in schema')
    for v in x.values():scan(v)
   elif isinstance(x,list):
    for v in x:scan(v)
  for fn in ['document-ir-v3.schema.json','artifact-manifest.schema.json','import-request.schema.json']:scan(load('contracts/'+fn))
 check('public and IR schemas omit identity fields',no_identity_schema)
 check('frozen reader-v1 CSS equals supplied version',lambda:must(digest((R/'reference/reader-v1.css').read_bytes())=='51dacbcd96a21214ed83a62cad870a6281eb20db1aa260f3a7d782c58fdd18a8','style drift'))
 def reference():
  for p,h in load('reference/reference-files.sha256.json').items():must(digest((R/p).read_bytes())==h,'changed reference '+p)
 check('controlled reader resources match manifest',reference)
 check('no font or actual credential files in package',lambda:must(not any(p.suffix.lower() in {'.ttf','.otf','.woff','.woff2','.eot','.pem','.key'} or p.name=='.env' for p in package_files()),'font/secret found'))
 def composed():
  c=yaml.safe_load((R/'compose.yaml').read_text())
  must(c['include']==['deployment/compose.production.yaml'],'root production include')
  must(set(c['services'])=={'verify'} and c['services']['verify']['profiles']==['tools'],'unexpected root services')
  must(c['services']['verify']['network_mode']=='none' and not c['services']['verify'].get('ports'),'verification isolation')
  p=yaml.safe_load((R/'deployment/compose.production.yaml').read_text());s=p['services']
  must(c['name']==p['name'],'production project and volume identity')
  must(set(s)=={'init','db','migrate','app','worker','parser','maintenance'},'target services')
  must('127.0.0.1' in s['app']['ports'][0],'bind')
  must([k for k,v in s.items() if 'ports' in v]==['app'],'unexpected published port')
  must(s['parser']['network_mode']=='none' and not s['parser'].get('secrets'),'parser internet/secrets')
  must('secrets' not in s['app'] and s['worker']['secrets']==['provider_key'],'key boundary')
  must('docker.sock' not in str(s),'Docker socket')
  must('backups:/backups' in s['init']['volumes'],'backup volume not initialized')
 check('Compose target graph, loopback, isolation and single port (static only)',composed)
 check('dependency inventory honestly remains design-only',lambda:must(load('deployment/dependency-inventory.json')['status']=='design_inventory_not_release_lock' and load('deployment/dependency-inventory.json')['runtime_installs_allowed'] is False,'false lock'))
 def scope():
  s=load('contracts/scope.json');must(s['supported_upload_mime_types']==['application/pdf'],'PDF only')
  for k in ['url_import_enabled','automatic_remote_assets','identity_system','login_enabled','teams_enabled','acl_enabled','reverse_proxy_included']:must(s[k] is False,'scope '+k)
 check('scope reflects all five user changes',scope)
 def docs():
  for p in package_files('.md'):
   for h in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)',p.read_text()):
    if h.startswith(('http:','https:','mailto:','#')):continue
    target=p.parent/unquote(h.split('#')[0])
    # Agent material is optional in source exports and excluded from images.
    if agent_reference(target):continue
    must(target.exists(),f'{p.relative_to(R)} -> {h}')
 check('all Markdown links resolve',docs)
 def html():
  release=load('reference/legacy-manifest.json')
  # Seed navigation is patched to the app root at import; reference bytes stay frozen.
  patch=release['navigation_patch']
  parsers={(R/item['html_path']).resolve():BeautifulSoup(
   (R/item['html_path']).read_text().replace(patch['from'],patch['to'],1),'html.parser')
   for item in release['documents']}
  for p,soup in parsers.items():
   for n in soup.select('a[href],img[src],script[src],link[href],iframe[src]'):
    h=n.get('href',n.get('src',''))
    if h=='/' or h.startswith(('http:','https:','mailto:','data:','blob:','javascript:')):continue
    path,_,anchor=h.partition('#');t=(p.parent/unquote(path)).resolve() if path else p
    must(t.exists(),f'{p.relative_to(R)} -> {h}')
    if anchor and not anchor.startswith('/') and t in parsers:
     must(parsers[t].find(id=unquote(anchor)) is not None,f'unknown anchor {p.name} -> {h}')
 check('controlled seed HTML resources and anchors resolve after navigation patch',html)
 report={'purpose':'Repository contract validation only; NOT application acceptance','version':'3.0','checks':checks,'passed':sum(x['result']=='pass' for x in checks),'failed':sum(x['result']=='fail' for x in checks),'counts':{'requirements':len(req),'work_packages':len(tasks),'acceptance_scenarios':len(ats),'gates':len(gates)},'production_acceptance':'not_evaluated_by_this_tool','docker_runtime_validation':'not_evaluated_by_this_tool'}
 try:
  run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
  output=R/'.agent/tmp/validation/runs'/run_id/'package-validation.json'
  output.parent.mkdir(parents=True,exist_ok=True)
  output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 except OSError:pass # read-only verification container; report still printed
 for x in checks:print(x['result'].upper(),x['name'],x.get('detail',''))
 print(f"TOTAL {report['passed']} passed, {report['failed']} failed")
 return int(report['failed']>0)
if __name__=='__main__':raise SystemExit(main())
