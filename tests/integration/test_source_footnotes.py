import copy
import json
from pathlib import Path
import pytest

from packages.domain.errors import DomainError
from packages.ir import block_hash,digest,flatten_inline
from packages.source_revisions import apply_native_corrections
from tests.integration.test_source_revisions import fixture_source


def source_note():
    source=fixture_source();body=next(b for b in source['blocks'] if b['id']=='p1');note=next(b for b in source['blocks'] if b['id']=='fn1')
    source['protected_atoms']['native-note-marker']={'kind':'number','value':'1'}
    body.update(raw_text='A source marker 1 here.',normalized_text='A source marker 1 here.',normalization_edits=[],
        source_inline=[{'type':'text','text':'A source marker '},{'type':'protected_ref','ref':'native-note-marker'},{'type':'text','text':' here.'}])
    body['provenance'][0]['bbox']=[20,20,250,50]
    note.update(raw_text='1 The original footnote.',normalized_text='1 The original footnote.',normalization_edits=[],source_inline=[{'type':'text','text':'1 The original footnote.'}])
    note['provenance'][0]['page']=body['provenance'][0]['page']
    for b in (body,note):b['source_hash']=block_hash(b,source['protected_atoms'])
    proof={'page':body['provenance'][0]['page'],'bbox':[110,21,114,26],'quote':'1'}
    inspection={'sha256':source['sha256'],'pages':[{'page':proof['page'],'page_size':[612,792],'text_characters':1,'scan_suspected':False,'text_regions':[{'bbox':proof['bbox'],'text':'1'}]}]}
    op={'kind':'annotate_footnote','block_id':'p1','start':16,'end':17,'target_block_id':'fn1','page_image_sha256':'a'*64,'visual_review_confirmed':True}
    return source,inspection,proof,op


def test_link_footnote_preserves_raw_atoms_and_traces_both_original_regions():
    source,inspection,proof,op=source_note();before=digest(source)
    result=apply_native_corrections(source,inspection,[op],proof,'Agent viewed original superscript and same-page footnote.',[],page_image_verify=lambda page,sha:True)
    assert digest(source)==before
    b=next(b for b in result['source']['blocks'] if b['id']=='p1')
    assert b['source_inline'][1]=={'type':'xref','target_block_id':'fn1','label':'1'}
    assert b['raw_text']==b['normalized_text']==flatten_inline(b['source_inline'],result['source']['protected_atoms'])=='A source marker 1 here.'
    assert result['restorations'][0]['target_provenance']
    assert result['restorations'][0]['page_image_sha256']=='a'*64


@pytest.mark.parametrize('change',[{'target_block_id':'p2'},{'target_block_id':[]},{'start':0,'end':1},{'end':18},{'visual_review_confirmed':False}])
def test_footnote_annotation_rejects_unproven_target_offsets_and_review(change):
    source,inspection,proof,op=source_note();op.update(change)
    with pytest.raises(DomainError):apply_native_corrections(source,inspection,[op],proof,'Review.',[],page_image_verify=lambda page,sha:True)


def test_footnote_annotation_cannot_use_a_footnote_on_another_page():
    source,inspection,proof,op=source_note();note=next(b for b in source['blocks'] if b['id']=='fn1');note['provenance'][0]['page']+=1;note['source_hash']=block_hash(note,source['protected_atoms'])
    with pytest.raises(DomainError):apply_native_corrections(source,inspection,[op],proof,'Review.',[],page_image_verify=lambda page,sha:True)


@pytest.mark.postgres
def test_actual_pathways_footnote_api_keeps_original_hash_and_rejects_stale_evidence(client,database):
    import shutil,time
    from packages.domain.models import SourceAsset,SourceDraft,Document
    from packages.storage import atomic_write,file_hash
    from packages.ir import validate_source
    root=Path(__file__).resolve().parents[2];corpus=root/'.agent/tmp/evidence/source-review-v3-pathways'
    if not (corpus/'result.json').is_file():pytest.skip('Requires actual version-bound Pathways inference.')
    assert json.loads((corpus/'execution.json').read_text())['execution']=='real_docling_layout_and_table_model_inference'
    result=json.loads((corpus/'result.json').read_text(encoding='utf8'));source=copy.deepcopy(result['source_revision'])
    db,cfg=database;keys={};prefix='documents/doc_note_actual/parser/1'
    for asset in source['assets']:
        relative=asset['storage_key'];asset['storage_key']=prefix+'/'+relative
        atomic_write(cfg.data,asset['storage_key'],(corpus/relative).read_bytes())
    for page in result['inspection']['pages']:
        keys[str(page['page'])]=prefix+'/'+page['page_image'];atomic_write(cfg.data,keys[str(page['page'])],(corpus/page['page_image']).read_bytes())
    before=digest(source);original_files={str(p.relative_to(cfg.data)):file_hash(p) for p in cfg.data.rglob('*') if p.is_file()}
    with db.transaction() as session:
        asset=source['assets'][0];session.add(SourceAsset(id=source['original_asset_id'],sha256=source['sha256'],byte_size=asset['byte_size'],page_count=20,storage_key=asset['storage_key']));session.flush()
        session.add(Document(id='doc_note_actual',title='Actual original footnote relationship',source_asset_id=source['original_asset_id']));session.flush()
        session.add(SourceDraft(id='draft_note_actual',document_id='doc_note_actual',asset_id=source['original_asset_id'],source=source,coverage=result['coverage'],evidence={'inspection':result['inspection'],'page_images':keys}))
    native=client.get('/api/v1/imports/draft_note_actual/native-regions').json();page=next(p for p in native['pages'] if p['page']==7)
    proof=next(r for r in page['text_regions'] if r['bbox']==[202.881,598.059,204.855,602.773])
    assert proof['text']=='1'
    body=next(b for b in source['blocks'] if 'p3.2xlarge VMs 1 with' in b['raw_text']);start=body['normalized_text'].index('VMs 1')+4
    target=next(b for b in source['blocks'] if b['kind']=='footnote' and b['raw_text'].startswith('1 These VMs'))
    payload={'reason':'Agent actually viewed original Pathways page 7: superscript 1 after p3.2xlarge VMs points to the bottom footnote describing one V100 GPU and eight CPU cores.',
        'evidence':{'page':7,'bbox':proof['bbox'],'quote':proof['text']},'operations':[{'kind':'annotate_footnote','block_id':body['id'],'start':start,'end':start+1,
        'target_block_id':target['id'],'page_image_sha256':page['page_image_sha256'],'visual_review_confirmed':True}]}
    bad=copy.deepcopy(payload);bad['operations'][0]['page_image_sha256']='0'*64
    failure=client.post('/api/v1/imports/draft_note_actual/corrections',json=bad,headers={'If-Match':'"1"','Idempotency-Key':'footnote-bad-image'})
    assert failure.status_code==409 and failure.json()['error']['code']=='SOURCE_PAGE_IMAGE_STALE'
    headers={'If-Match':'"1"','Idempotency-Key':'footnote-actual'}
    response=client.post('/api/v1/imports/draft_note_actual/corrections',json=payload,headers=headers)
    assert response.status_code==201,response.text
    replay=client.post('/api/v1/imports/draft_note_actual/corrections',json=payload,headers=headers)
    assert replay.json()==response.json()
    stale=client.post('/api/v1/imports/draft_note_actual/corrections',json=payload,headers={**headers,'Idempotency-Key':'footnote-stale'})
    assert stale.status_code==412
    changed=response.json();after=changed['source'];validate_source(after,asset_root=cfg.data)
    assert {b['id']:b['raw_text'] for b in source['blocks']}=={b['id']:b['raw_text'] for b in after['blocks']}
    annotated=next(b for b in after['blocks'] if b['id']==body['id'])
    assert {'type':'xref','target_block_id':target['id'],'label':'1'} in annotated['source_inline']
    with db.transaction() as session:assert digest(session.get(SourceDraft,'draft_note_actual').source)==before
    assert all(file_hash(cfg.data/key)==sha for key,sha in original_files.items())
    out=root/'.agent/tmp/evidence'/('footnote-api-'+str(time.time_ns()));out.mkdir()
    (out/'source-before.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'response.json').write_text(json.dumps(changed,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8');shutil.copytree(cfg.data,out/'data')
    report={'directory':str(out.relative_to(root)),'actual_parser_corpus':str(corpus.relative_to(root)),'source_before':before,'source_after':digest(after),
        'api_status':201,'idempotent_replay':True,'stale_image_rejected':True,'stale_etag_rejected':True,'all_raw_and_original_files_unchanged':True,
        'source_block_id':body['id'],'target_block_id':target['id'],'page_image_sha256':page['page_image_sha256']}
    (out/'verification.json').write_text(json.dumps(report,indent=2));(root/'.agent/tmp/reports/core-evidence/latest-footnote-correction.json').write_text(json.dumps(report,indent=2))
