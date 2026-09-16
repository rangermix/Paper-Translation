"""Verify the two real seeded pages and export through the real API and worker."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

from smoke_library import request


BASE='http://127.0.0.1:8080'


def main():
    output=ROOT/'.agent/tmp/evidence/legacy-review'
    output.mkdir(parents=True,exist_ok=True)
    run=subprocess.run(['docker','compose','-f','deployment/compose.production.yaml','run','--rm','--no-deps','maintenance','python','-m','packages.maintenance','seed-legacy'],cwd=ROOT,capture_output=True,text=True,timeout=90)
    assert run.returncode==0,run.stderr
    seeded=json.loads(run.stdout)
    assert seeded['created']==0 and all(row['status']=='already_seeded' for row in seeded['documents'])
    release=json.loads((ROOT/'reference/legacy-manifest.json').read_text())
    results=[]
    for case in release['documents']:
        identifier=case['id']
        artifact=identifier+'-artifact-v1'
        document,_=request(BASE,'GET','/api/v1/documents/'+identifier)
        original,_=request(BASE,'GET','/api/v1/documents/'+identifier+'/original')
        assert original==(ROOT/case['source_path']).read_bytes()
        html,_=request(BASE,'GET','/read/'+identifier+'/zh-Hans')
        reference=(ROOT/case['html_path']).read_bytes()
        patch=release['navigation_patch']
        assert html==reference.replace(patch['from'].encode(),patch['to'].encode(),1)
        css,_=request(BASE,'GET',f'/artifacts/{artifact}/reader.css')
        assert hashlib.sha256(css).hexdigest()==release['reader_css_sha256']
        exports=[]
        for format in ('single_html','bundle'):
            created,_=request(BASE,'POST',f'/api/v1/artifacts/{artifact}/exports',{'format':format,'include_source':False},{'Idempotency-Key':uuid.uuid4().hex},202)
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                current,_=request(BASE,'GET','/api/v1/exports/'+created['id'])
                if current['status']=='succeeded':break
                if current['status']=='failed':raise AssertionError(current)
                time.sleep(.2)
            assert current['status']=='succeeded',current
            content,_=request(BASE,'GET',current['download_url'])
            assert hashlib.sha256(content).hexdigest()==current['sha256']
            path=output/(identifier+('.html' if format=='single_html' else '.zip'))
            path.write_bytes(content)
            if format=='single_html':
                text=content.decode('utf-8')
                assert 'data:application/pdf' not in text
                assert case['source_output'] not in text
            exports.append({'id':created['id'],'format':format,'sha256':current['sha256'],'path':path.relative_to(ROOT).as_posix()})
        results.append({'document_id':identifier,'source_sha256':hashlib.sha256(original).hexdigest(),
                        'html_navigation_only_patch':True,'css_sha256':release['reader_css_sha256'], 'exports':exports})
    (output/'http-results.json').write_text(json.dumps({'status':'passed','second_seed':seeded,'documents':results},indent=2))
    print(json.dumps({'status':'passed','documents':len(results),'real_worker_exports':4,'seed_idempotent':True}))


if __name__=='__main__':main()
