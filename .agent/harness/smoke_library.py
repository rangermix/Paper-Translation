"""Exercise the real Compose HTTP/worker/parser/PostgreSQL path without a Provider."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid




def request(base, method, path, body=None, headers=None, expected=200):
    headers={'X-Library-Request':'1',**(headers or {})}
    if isinstance(body,dict):
        body=json.dumps(body).encode();headers['Content-Type']='application/json'
    try:
        response=urlopen(Request(base+path,data=body,headers=headers,method=method),timeout=15)
    except HTTPError as error:
        response=error
    raw=response.read();status=response.status
    assert status in (expected if isinstance(expected,tuple) else (expected,)), f'{method} {path}: expected {expected}, received {status}; {raw[:300]!r}'
    result=json.loads(raw) if response.headers.get('Content-Type','').startswith('application/json') else raw
    return result,dict(response.headers.items())


def etag(headers):
    return next(value for key,value in headers.items() if key.lower()=='etag')


def upload(base,data,name):
    uid=uuid.uuid4().hex
    body={'filename':name,'media_type':'application/pdf','byte_size':len(data)}
    created,h=request(base,'POST','/api/v1/uploads',body,{'Idempotency-Key':uid},201)
    same,_=request(base,'POST','/api/v1/uploads',body,{'Idempotency-Key':uid},201)
    assert same==created
    path=f'/api/v1/uploads/{created["id"]}'
    content_hash=hashlib.sha256(data).hexdigest()
    chunk_headers={'If-Match':etag(h),'Content-Range':f'bytes 0-{len(data)-1}/{len(data)}','Content-Type':'application/octet-stream','X-Chunk-SHA256':content_hash}
    chunk,h=request(base,'PUT',path+'/chunks/0',data,chunk_headers)
    same,_=request(base,'PUT',path+'/chunks/0',data,chunk_headers)
    assert same==chunk
    finalized,_=request(base,'POST',path+'/finalize',{'expected_sha256':content_hash,'total_bytes':len(data)}, {'If-Match':etag(h),'Idempotency-Key':uid+'-final'},202)
    repeated,_=request(base,'POST',path+'/finalize',{'expected_sha256':content_hash,'total_bytes':len(data)}, {'If-Match':etag(h),'Idempotency-Key':uid+'-final'},202)
    assert repeated==finalized
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        state,h=request(base,'GET',path)
        if state['status'] in ('verified','failed'):
            return state
        time.sleep(.3)
    raise AssertionError('Isolated inspector did not finish within 45 seconds')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8080')
    parser.add_argument('--verify-existing',action='store_true')
    args=parser.parse_args()
    base=args.base_url.rstrip('/')
    report_path=ROOT/'.agent/tmp/evidence/library-smoke.json'
    data=(ROOT/'fixtures/sample.pdf').read_bytes()
    if args.verify_existing:
        previous=json.loads(report_path.read_text())
        document,h=request(base,'GET','/api/v1/documents/'+previous['document_id'])
        assert document['title']=='Acceptance sample' and document['starred'] and document['tags']==['acceptance']
        original,_=request(base,'GET','/api/v1/documents/'+previous['document_id']+'/original')
        assert original==data
        print(json.dumps({'status':'passed','scope':'existing document survives service replacement','document_id':document['id'],'source_sha256':hashlib.sha256(original).hexdigest()}))
        return
    caps,_=request(base,'GET','/api/v1/capabilities')
    assert caps['source_mime_types']==['application/pdf'] and caps['provider_configured'] is False
    schema,_=request(base,'GET','/openapi.json')
    assert not schema.get('components',{}).get('securitySchemes')
    for route in ('login','users','workspaces','roles','sessions','imports/ir','imports/url','imports/text','imports/bilingual'):
        request(base,'POST','/api/v1/'+route,{},expected=404)
    for source in ({'kind':'url','url':'https://example.invalid/paper.pdf'},{'kind':'text','text':'Not a PDF'},{'kind':'ir','document':{}}):
        request(base,'POST','/api/v1/imports',{'source':source},{'Idempotency-Key':uuid.uuid4().hex},(415,422))
    invalid=upload(base,b'%PDF-1.7\nThis is not a real PDF\n%%EOF','disguised.pdf')
    assert invalid['status']=='failed' and invalid['error']['code']=='PDF_INVALID'
    verified=upload(base,data,'acceptance-sample.pdf')
    assert verified['status']=='verified'
    document,h=request(base,'POST','/api/v1/imports',{'source':{'kind':'pdf_upload','upload_id':verified['id']},'source_language':'en','target_language':'zh-Hans'}, {'Idempotency-Key':uuid.uuid4().hex},201)
    assert document['status']=='source_only'
    path='/api/v1/documents/'+document['id']
    request(base,'PATCH',path,{'title':'should fail'},expected=428)
    changed,new_h=request(base,'PATCH',path,{'title':'Acceptance sample','tags':['acceptance'],'starred':True},{'If-Match':etag(h)})
    request(base,'PATCH',path,{'title':'stale edit'}, {'If-Match':etag(h)},412)
    original,_=request(base,'GET',path+'/original')
    assert original==data
    partial,_=request(base,'GET',path+'/original',headers={'Range':'bytes=0-15'},expected=206)
    assert partial==data[:16]
    request(base,'GET','/api/v1/capabilities',headers={'Host':'attacker.invalid'},expected=400)
    request(base,'PATCH',path,{'starred':False},{'Origin':'https://attacker.invalid','If-Match':etag(new_h)},403)
    state={'status':'passed','scope':'real HTTP + PostgreSQL + isolated native inspector; no Provider calls',
           'document_id':document['id'],'upload_id':verified['id'],'source_sha256':hashlib.sha256(original).hexdigest(),
           'document_generation':changed['generation'],'invalid_pdf_code':invalid['error']['code'],
           'checks':['no identity routes','PDF-only source schema','invalid PDF bytes rejected','idempotent upload/chunk/finalize','source_only import','metadata persists in API','missing/stale ETag refused','byte-identical original','Range support','Host/Origin rejection']}
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(state,ensure_ascii=False))


if __name__=='__main__':main()
