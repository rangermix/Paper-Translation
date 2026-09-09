"""Run inside the app image of the fresh, internally networked Compose instance."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid
from smoke_library import request,upload,etag

BASE='http://127.0.0.1:8080'
OUTPUT=Path('/evidence/offline-library.json')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--export-legacy',action='store_true')
    args=parser.parse_args()
    original=Path('/app/fixtures/sample.pdf').read_bytes()
    if args.export_legacy:
        evidence=json.loads(OUTPUT.read_text())
        evidence['legacy']=[]
        for identifier in ('legacy-efficient','legacy-pathways'):
            page,_=request(BASE,'GET','/read/'+identifier+'/zh-Hans')
            exports=[]
            for format in ('single_html','bundle'):
                created,_=request(BASE,'POST','/api/v1/artifacts/'+identifier+'-artifact-v1/exports',{'format':format,'include_source':False},{'Idempotency-Key':uuid.uuid4().hex},202)
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    result,_=request(BASE,'GET','/api/v1/exports/'+created['id'])
                    if result['status']=='succeeded':break
                    time.sleep(.2)
                assert result['status']=='succeeded',result
                data,_=request(BASE,'GET',result['download_url'])
                assert hashlib.sha256(data).hexdigest()==result['sha256']
                exports.append({'id':created['id'],'format':format,'sha256':result['sha256']})
            evidence['legacy'].append({'id':identifier,'html_sha256':hashlib.sha256(page).hexdigest(),'exports':exports})
        OUTPUT.write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'status':'passed','offline_legacy_exports':4}))
        return
    if args.verify:
        before=json.loads(OUTPUT.read_text())
        current,_=request(BASE,'GET','/api/v1/documents/'+before['document_id'])
        content,_=request(BASE,'GET','/api/v1/documents/'+before['document_id']+'/original')
        assert current['title']=='Offline acceptance' and current['starred'] and current['tags']==['offline']
        assert content==original
        for case in before['legacy']:
            page,_=request(BASE,'GET','/read/'+case['id']+'/zh-Hans')
            assert hashlib.sha256(page).hexdigest()==case['html_sha256']
            for export in case['exports']:
                data,_=request(BASE,'GET','/api/v1/exports/'+export['id']+'/download')
                assert hashlib.sha256(data).hexdigest()==export['sha256']
        print(json.dumps({'status':'passed','scope':'restored fresh volume original/metadata/legacy current pointers'}))
        return
    caps,_=request(BASE,'GET','/api/v1/capabilities')
    assert caps['provider_configured'] is False
    verified=upload(BASE,original,'offline-acceptance.pdf')
    assert verified['status']=='verified'
    document,h=request(BASE,'POST','/api/v1/imports',{'source':{'kind':'pdf_upload','upload_id':verified['id']},'source_language':'en','target_language':'zh-Hans'},{'Idempotency-Key':uuid.uuid4().hex},201)
    updated,_=request(BASE,'PATCH','/api/v1/documents/'+document['id'],{'title':'Offline acceptance','tags':['offline'],'starred':True},{'If-Match':etag(h)})
    assert updated['status']=='source_only'
    content,_=request(BASE,'GET','/api/v1/documents/'+document['id']+'/original')
    assert content==original
    evidence={'status':'passed','document_id':document['id'],'original_sha256':hashlib.sha256(content).hexdigest(),
              'scope':'real app/worker/parser/PostgreSQL on fresh volumes and internal networks, no host Python or Node required'}
    OUTPUT.write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence))


if __name__=='__main__':main()
