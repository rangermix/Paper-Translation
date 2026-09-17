"""Trusted full-structure render and the ordinary public PDF-only boundary."""
import hashlib
import json
from pathlib import Path
import pytest
from packages.ir import IRValidationError, validate_ir
from packages.publisher import Publisher

ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.postgres
def test_m0_at04a_full_internal_structure_renders_but_public_ir_is_not_an_entry(client,tmp_path):
    ir=json.loads((ROOT/'tests/fixtures/complex-reader/document-ir.json').read_text('utf-8'))
    assert {'heading','paragraph','table','table_cell','caption','figure','math','code','footnote','reference'} <= {b['kind'] for b in ir['source_revision']['blocks']}
    validate_ir(ir,ROOT / 'tests')
    output=tmp_path/'trusted-artifact'
    Publisher().build(ir,ROOT / 'tests',output)
    html=(output/'index.html').read_text('utf-8')
    assert all(html.count('id="b-'+b['id']+'"')==1 for b in ir['source_revision']['blocks'])
    refused=client.post('/api/v1/imports',json={'source':ir},headers={'Idempotency-Key':'public-ir-forbidden'})
    assert refused.status_code==422,refused.text
    assert client.post('/api/v1/imports/ir',json=ir).status_code==404
    assert client.get('/api/v1/documents').json()['items']==[]

@pytest.mark.parametrize('damage',['missing-prose','unknown-result','retained-prose'])
def test_m0_at06b_invalid_prose_alignment_is_rejected_before_any_artifact(tmp_path,damage):
    ir=json.loads((ROOT/'tests/fixtures/sample-document.json').read_text('utf-8'))
    rows=ir['translation_revision']['results']
    row=next(r for r in rows if r['block_id']=='p1')
    if damage=='missing-prose':rows.remove(row)
    elif damage=='unknown-result':row['block_id']='unknown-block-not-in-source'
    else:row.update(status='retained',target_inline=[],reason='original_figure')
    with pytest.raises(IRValidationError):validate_ir(ir,ROOT / 'tests')
    output=tmp_path/'rejected-artifact'
    with pytest.raises(IRValidationError):Publisher().build(ir,ROOT / 'tests',output)
    assert not (output/'index.html').exists()

@pytest.mark.postgres
@pytest.mark.parametrize('content',[b'<html><script>fake PDF</script></html>',b'PK\x03\x04fake ZIP file content'])
def test_m0_at01b_disguised_pdf_upload_never_becomes_importable(client,content):
    created=client.post('/api/v1/uploads',json={'filename':'disguised.pdf','media_type':'application/pdf','byte_size':len(content)},headers={'Idempotency-Key':'disguised-create'})
    assert created.status_code==201,created.text
    route='/api/v1/uploads/'+created.json()['id']
    put=client.put(route+'/chunks/0',content=content,headers={'If-Match':created.headers['etag'],'Content-Type':'application/octet-stream',
        'Content-Range':f'bytes 0-{len(content)-1}/{len(content)}','X-Chunk-SHA256':hashlib.sha256(content).hexdigest()})
    assert put.status_code in (415,422),put.text
    denied=client.post('/api/v1/imports',json={'source':{'kind':'pdf_upload','upload_id':created.json()['id']}},headers={'Idempotency-Key':'disguised-import'})
    assert denied.status_code==409,denied.text
    assert client.get('/api/v1/documents').json()['items']==[]
