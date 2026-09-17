"""Actual offline Docling on a PDF-only cross-page resource fixture; no authored IR."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse,json,os,sys,uuid
from pathlib import Path
sys.path.insert(0,str(ROOT))
from harness.live_provider_run import run_recorded_command
from packages.ir import digest,validate_source


def verify(output):
    expected=json.loads((ROOT/'tests/fixtures/cross-page-resources/expected-visible.json').read_text())
    result=json.loads((output/'actual/result.json').read_text(encoding='utf8'));source=result['source_revision']
    validate_source(source,asset_root=output/'actual');by={b['id']:b for b in source['blocks']}
    assert source['sha256']==expected['pdf_sha256']==digest((ROOT/'tests/fixtures/cross-page-resources/cross-page-resources.pdf').read_bytes())
    rows=[];captions=[]
    for bid in source['reading_order']:
        block=by[bid]
        if block['kind']!='table':continue
        attrs=block['attributes'];assert attrs['representation']=='structured' and (attrs['rows'],attrs['columns'])==(6,4)
        matrix=[['']*4 for _ in range(6)]
        for cell in attrs['cells']:
            assert cell['row_span']==cell['column_span']==1
            child=by[cell['content_block_id']];matrix[cell['row']][cell['column']]=child['normalized_text']
            assert child['owner_id']==bid and all(p['page']==block['provenance'][0]['page'] and p['asset_id']=='original-pdf' for p in child['provenance'])
        assert matrix[0]==['Row','Samples','Latency (ms)','Status']
        rows.extend({'page':block['provenance'][0]['page'],'values':r} for r in matrix[1:])
        assert len(attrs['caption_block_ids'])==1
        caption=by[attrs['caption_block_ids'][0]];assert caption['owner_id']==bid
        captions.append({'table_id':bid,'page':block['provenance'][0]['page'],'caption_id':caption['id'],'text':caption['normalized_text']})
    assert rows==expected['table_rows']
    issue=next(i for i in result['coverage']['unresolved'] if i['reason']=='Original image overlaps separate incomplete layout graphics')
    # This legacy parser field describes coverage, not application readiness.
    assert not result['coverage']['can_translate'] and len(result['coverage']['unresolved'])==1
    assert all(any('分组与图注' in w for w in by[bid]['warnings']) for bid in issue['block_ids'])
    assets={a['storage_key']:digest((output/'actual'/a['storage_key']).read_bytes()) for a in source['assets']}
    assert all(assets[a['storage_key']]==a['sha256'] for a in source['assets'])
    footnotes=[b for b in source['blocks'] if b['kind']=='footnote'];assert len(footnotes)==1
    assert footnotes[0]['provenance'][0]['page']==1 and footnotes[0]['normalized_text']=='1 Values are synthetic; they test extraction, not scientific claims.'
    return {'status':'passed_with_source_warnings','table_rows_complete_and_ordered':True,'table_rows':rows,
        'captions':captions,'assets_sha256':assets,'source_sha256':digest(source),'result_sha256':digest((output/'actual/result.json').read_bytes()),
        'unresolved':result['coverage']['unresolved'],'diagnostic_can_translate':result['coverage']['can_translate'],'footnote':footnotes[0],
        'scope':'Real PDF/Docling; complete original assets and table rows retained with figure-grouping warnings. Parser coverage is diagnostic; this probe does not exercise workflow readiness or certify figure grouping or footnote references.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--current-source-overlay',action='store_true',
        help='Explicitly mount the current two parser source modules read-only, recording hashes; omit for immutable image validation.')
    args=parser.parse_args();output=ROOT/'.agent/tmp/evidence/cross-page-table-runs'/uuid.uuid4().hex[:8];(output/'actual').mkdir(parents=True)
    commands=[];env=dict(os.environ)
    def command(argv):return run_recorded_command(argv,env=env,commands=commands,evidence_path=output/'commands.json',timeout=180)
    image=command(['docker','image','inspect','--format','{{.Id}}',os.environ['ACCEPTANCE_PARSER_IMAGE']]).strip()
    argv=['docker','run','--rm','--network','none','--read-only','--user','10001:10001','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--memory','4g','--cpus','2','--pids-limit','128','--tmpfs','/tmp:rw,nosuid,size=512m,mode=1777']
    mounts=[(ROOT/'tests/fixtures/cross-page-resources','/source',True),(ROOT/'.agent/harness','/harness',True),(output/'actual','/result',False)]
    overlays={}
    if args.current_source_overlay:
        for relative in ['src/packages/parsers/pdf_docling.py','src/packages/parsers/fidelity.py']:
            mounts.append((ROOT/relative,'/app/'+relative,True));overlays[relative]=digest((ROOT/relative).read_bytes())
    for host,target,readonly in mounts:argv+=['--mount',f'type=bind,source={host},target={target}'+(',readonly' if readonly else '')]
    argv += [image,'python','/harness/parser_corpus.py','--pdf','/source/cross-page-resources.pdf','--output','/result']
    report={'parser_image':image,'readonly_source_overlays':overlays,'network_mode':'none','provider_requests':0,
        'harness_sha256':digest(Path(__file__).read_bytes())}
    try:
        command(argv);report.update(verify(output));report['execution']=json.loads((output/'actual/execution.json').read_text())
    except BaseException as error:
        report.update(status='failed',exception_type=type(error).__name__,message=str(error));raise
    finally:(output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'status':report['status'],'evidence':str(output.relative_to(ROOT))}))


if __name__=='__main__':main()
