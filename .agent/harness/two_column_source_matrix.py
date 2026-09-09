"""Real production-spool parsing of the bounded double-column source gold PDF."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid


sys.path.insert(0,str(ROOT))


def verify_source(source,coverage,expected):
    from packages.ir import validate_source
    validate_source(source)
    by={b['id']:b for b in source['blocks']};items=expected['items'];matched=[]
    def compact(s):return ' '.join(s.split())
    for item in items:
        if item['key']=='continuation_b':continue
        text=expected['continuation']['text'] if item['key']=='continuation_a' else item['text']
        choices=[b for b in source['blocks'] if compact(b['normalized_text'])==compact(text)]
        if item['kind']=='list_item':
            choices=[b for b in source['blocks'] if compact(b['normalized_text']).removeprefix('- ')==compact(text).removeprefix('- ')]
        assert len(choices)==1,(item['key'],[b['normalized_text'] for b in source['blocks']])
        block=choices[0];assert block['kind']==item['kind'],(item['key'],block['kind'])
        pages={p['page'] for p in block['provenance']}
        assert pages==({1,2} if item['key']=='continuation_a' else {item['page']}),(item['key'],pages)
        assert all(p['asset_id']==source['original_asset_id'] for p in block['provenance'])
        matched.append({'key':item['key'],'block_id':block['id'],'kind':block['kind'],'pages':sorted(pages)})
    actual=[bid for bid in source['reading_order']]
    assert actual==[m['block_id'] for m in matched],(actual,matched)
    assert coverage['can_translate'] and not coverage['unresolved'],coverage['unresolved']
    return matched


def inside():
    from packages.ir import digest,validate_source
    from packages.parsers.models import parser_version
    from packages.parsers.spool import write_request,verify_result
    from workers.parser.main import run_once,ModelHealth
    root=Path('/result');fixture=Path('/fixtures/two-column-source');pdf=fixture/'two-column-source.pdf'
    expected=json.loads((fixture/'expected-visible.json').read_text());assert digest(pdf.read_bytes())==expected['pdf_sha256']
    inputs,outputs=root/'inputs',root/'outputs';outputs.mkdir()
    request={'task_id':'two-column','fence':1,'source_sha256':expected['pdf_sha256'],'max_pages':2,
        'deadline':(datetime.now(timezone.utc)+timedelta(seconds=150)).isoformat(),'parser_version':parser_version(),
        'operation':'parse','asset_id':'original-pdf','profile':{'language':'en'}}
    write_request(inputs,request,pdf);health=ModelHealth(outputs,os.environ['DOCLING_ARTIFACTS_PATH']);health.heartbeat()
    started=time.monotonic();assert run_once(inputs,outputs,health.heartbeat)
    actual=outputs/'two-column/1';result=verify_result(actual,request)
    summary={'seconds':time.monotonic()-started,'request':request,'spool_result':result,
        'scope':'Real production spawn/process_request in a 4GiB container, bound to the recorded image and optional source overlays; no source correction and no Provider.'}
    try:
        assert result['status']=='succeeded',result
        payload=json.loads((actual/'payload.json').read_text());source=payload['source_revision']
        validate_source(source,asset_root=actual)
        summary['matched']=verify_source(source,payload['coverage'],expected)
        summary.update(status='passed',source_sha256=digest(source),coverage=payload['coverage'],
            assets={a['storage_key']:digest((actual/a['storage_key']).read_bytes()) for a in source['assets']})
    finally:(root/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'status':summary['status'],'seconds':summary['seconds']}))


def outside(overlay):
    from harness.live_provider_run import run_recorded_command
    from packages.ir import digest
    output=ROOT/'.agent/tmp/evidence/two-column-source-runs'/uuid.uuid4().hex[:8];output.mkdir(parents=True)
    commands=[]
    def command(argv):return run_recorded_command(argv,env=dict(os.environ),commands=commands,evidence_path=output/'commands.json',timeout=210)
    image=command(['docker','image','inspect','--format','{{.Id}}',os.environ['ACCEPTANCE_PARSER_IMAGE']]).strip()
    argv=['docker','run','--rm','--network','none','--read-only','--user','10001:10001','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '--memory','4g','--cpus','2','--pids-limit','128','--tmpfs','/tmp:rw,nosuid,size=512m,mode=1777']
    mounts=[(ROOT/'fixtures','/fixtures',True),(ROOT/'.agent/harness','/harness',True),(output,'/result',False)];overlays={}
    if overlay:
        for relative in ['packages/parsers/pdf_docling.py','workers/parser/main.py']:
            mounts.append((ROOT/relative,'/app/'+relative,True));overlays[relative]=digest((ROOT/relative).read_bytes())
    for host,target,readonly in mounts:argv+=['--mount',f'type=bind,source={host},target={target}'+(',readonly' if readonly else '')]
    argv += [image,'python','/harness/two_column_source_matrix.py','--inside']
    report={'parser_image':image,'source_overlays':overlays,'network':'none','provider_requests':0,
        'harness_sha256':digest(Path(__file__).read_bytes()),'status':'not_completed'}
    try:command(argv);report['status']='passed'
    finally:(output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({'status':report['status'],'evidence':str(output.relative_to(ROOT))}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--inside',action='store_true');parser.add_argument('--current-source-overlay',action='store_true');args=parser.parse_args()
    inside() if args.inside else outside(args.current_source_overlay)
