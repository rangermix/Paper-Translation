"""Evidence-bound source structure fixes; actual PDF tests never call a provider."""
import copy
import json
from pathlib import Path

import pytest

from packages.domain.errors import DomainError
from packages.ir import block_hash,digest,flatten_inline
from packages.source_revisions import apply_native_corrections
from tests.integration.test_source_revisions import fixture_source


def continuation():
    source=fixture_source();by={b['id']:b for b in source['blocks']};first,second=by['p1'],by['p2']
    for b,text,bbox in [(first,'Input types of in',[20,700,260,720]),(second,'put tensors are known.',[320,70,550,95])]:
        b.update(raw_text=text,normalized_text=text,source_inline=[{'type':'text','text':text}],normalization_edits=[])
        b['provenance']=[{**first['provenance'][0],'page':1,'bbox':bbox}]
    first.update(kind='list_item',attributes={'list_ordered':False})
    second['parent_id']=first['parent_id']
    from packages.source_revisions.corrections import _set_order
    order=[bid for bid in source['reading_order'] if bid!='p2'];order.insert(order.index('p1')+1,'p2');_set_order(source,order)
    for b in (first,second):b['source_hash']=block_hash(b,source['protected_atoms'])
    proof={'page':1,'bbox':[20,705,250,717],'quote':'Input types of in\x02'}
    inspection={'sha256':source['sha256'],'pages':[{'page':1,'page_size':[612,792],'text_characters':40,'scan_suspected':False,
        'text_regions':[{'bbox':proof['bbox'],'text':proof['quote']},{'bbox':[320,70,540,79],'text':'put tensors are known.'}]}]}
    op={'kind':'merge_continuation','block_ids':['p1','p2'],'joiner':'','page_image_sha256':'a'*64,'visual_review_confirmed':True}
    return source,inspection,proof,op


def test_native_hyphen_continuation_preserves_list_atoms_and_old_raw():
    source,inspection,proof,op=continuation();before=digest(source)
    result=apply_native_corrections(source,inspection,[op],proof,'Agent reviewed both original columns.',[],page_image_verify=lambda page,sha:True)
    assert digest(source)==before
    merged=next(b for b in result['source']['blocks'] if b['id']=='p1')
    assert merged['kind']=='list_item' and merged['attributes']=={'list_ordered':False}
    assert merged['normalized_text']==flatten_inline(merged['source_inline'],result['source']['protected_atoms'])=='Input types of input tensors are known.'
    assert merged['raw_text']=='Input types of in\nput tensors are known.'
    assert len(merged['provenance'])==2 and 'p2' not in result['source']['reading_order']
    mapping=next(m for m in result['mapping'] if m['old_block_ids']==['p1','p2'])
    assert mapping['kind']=='merged' and not mapping['reusable']
    assert result['restorations'][0]['original_raw_hashes']==[digest('Input types of in'),digest('put tensors are known.')]


@pytest.mark.parametrize('change',[{'block_ids':['p2','p1']},{'block_ids':['p1','fn1']},{'joiner':'new text'},{'visual_review_confirmed':False}])
def test_continuation_rejects_unproven_structure_or_joiner(change):
    source,inspection,proof,op=continuation();op.update(change)
    with pytest.raises(DomainError):apply_native_corrections(source,inspection,[op],proof,'Review.',[],page_image_verify=lambda page,sha:True)


def test_word_fusion_requires_actual_native_terminal_hyphen():
    source,inspection,proof,op=continuation();proof['quote']='Input types of in';inspection['pages'][0]['text_regions'][0]['text']=proof['quote']
    with pytest.raises(DomainError) as caught:apply_native_corrections(source,inspection,[op],proof,'Review.',[],page_image_verify=lambda page,sha:True)
    assert caught.value.code=='SOURCE_CONTINUATION_UNPROVEN'


def test_continuation_rejects_a_foreign_page_and_nonterminal_region():
    for foreign in (True,False):
        source,inspection,proof,op=continuation()
        if foreign:next(b for b in source['blocks'] if b['id']=='p2')['provenance'][0]['page']=2
        else:
            proof['bbox']=[20,600,250,610];inspection['pages'][0]['text_regions'][0]['bbox']=proof['bbox']
        for b in source['blocks']:b['source_hash']=block_hash(b,source['protected_atoms'])
        with pytest.raises(DomainError):apply_native_corrections(source,inspection,[op],proof,'Review.',[],page_image_verify=lambda page,sha:True)


@pytest.mark.postgres
def test_actual_pathways_crosscolumn_bullet_api_preserves_pdf_and_source_snapshots(client,database):
    import shutil,time
    from packages.domain.models import SourceAsset,SourceDraft,Document
    from packages.storage import atomic_write,file_hash
    from packages.ir import validate_source
    root=Path(__file__).resolve().parents[2];corpus=root/'.agent/tmp/evidence/source-review-v3-pathways'
    if not (corpus/'result.json').is_file():pytest.skip('Requires actual version-bound Pathways inference.')
    assert json.loads((corpus/'execution.json').read_text())['execution']=='real_docling_layout_and_table_model_inference'
    result=json.loads((corpus/'result.json').read_text(encoding='utf8'));source=copy.deepcopy(result['source_revision'])
    db,cfg=database;keys={};prefix='documents/doc_cont_actual/parser/1'
    for asset in source['assets']:
        relative=asset['storage_key'];asset['storage_key']=prefix+'/'+relative
        atomic_write(cfg.data,asset['storage_key'],(corpus/relative).read_bytes())
    for page in result['inspection']['pages']:
        keys[str(page['page'])]=prefix+'/'+page['page_image'];atomic_write(cfg.data,keys[str(page['page'])],(corpus/page['page_image']).read_bytes())
    before=digest(source);original_files={str(p.relative_to(cfg.data)):file_hash(p) for p in cfg.data.rglob('*') if p.is_file()}
    with db.transaction() as session:
        asset=source['assets'][0];session.add(SourceAsset(id=source['original_asset_id'],sha256=source['sha256'],byte_size=asset['byte_size'],page_count=20,storage_key=asset['storage_key']));session.flush()
        session.add(Document(id='doc_cont_actual',title='Actual original cross-column continuation',source_asset_id=source['original_asset_id']));session.flush()
        session.add(SourceDraft(id='draft_cont_actual',document_id='doc_cont_actual',asset_id=source['original_asset_id'],source=source,coverage=result['coverage'],evidence={'inspection':result['inspection'],'page_images':keys}))
    native=client.get('/api/v1/imports/draft_cont_actual/native-regions').json();page=next(p for p in native['pages'] if p['page']==18)
    proof=next(r for r in page['text_regions'] if r['text']=='Input and output types, and the shapes of any in\x02')
    first=next(b for b in source['blocks'] if b['raw_text']=='• Input and output types, and the shapes of any in')
    second=next(b for b in source['blocks'] if b['raw_text']=='put/output tensors, are known before the input data have been computed.')
    payload={'reason':'Agent actually viewed original Pathways page 18: the bottom left bullet ends in a printed in- and continues at top right with put/output, before the next independent bullet. Restore the single list item without changing any other text.',
        'evidence':{'page':18,'bbox':proof['bbox'],'quote':proof['text']},'operations':[{'kind':'merge_continuation','block_ids':[first['id'],second['id']],
        'joiner':'','page_image_sha256':page['page_image_sha256'],'visual_review_confirmed':True}]}
    bad=copy.deepcopy(payload);bad['operations'][0]['page_image_sha256']='0'*64
    failure=client.post('/api/v1/imports/draft_cont_actual/corrections',json=bad,headers={'If-Match':'"1"','Idempotency-Key':'continuation-bad-image'})
    assert failure.status_code==409 and failure.json()['error']['code']=='SOURCE_PAGE_IMAGE_STALE'
    headers={'If-Match':'"1"','Idempotency-Key':'continuation-actual'}
    response=client.post('/api/v1/imports/draft_cont_actual/corrections',json=payload,headers=headers)
    assert response.status_code==201,response.text
    replay=client.post('/api/v1/imports/draft_cont_actual/corrections',json=payload,headers=headers)
    assert replay.json()==response.json()
    stale=client.post('/api/v1/imports/draft_cont_actual/corrections',json=payload,headers={**headers,'Idempotency-Key':'continuation-stale'})
    assert stale.status_code==412
    changed=response.json();after=changed['source'];validate_source(after,asset_root=cfg.data)
    merged=next(b for b in after['blocks'] if b['id']==first['id'])
    assert merged['kind']=='list_item' and merged['attributes']==first['attributes'] and merged['parent_id']==first['parent_id']
    assert merged['normalized_text']=='• Input and output types, and the shapes of any input/output tensors, are known before the input data have been computed.'
    assert merged['raw_text']==first['raw_text']+'\n'+second['raw_text']
    assert len(merged['provenance'])==2 and second['id'] not in after['reading_order']
    assert {b['id']:b['raw_text'] for b in source['blocks'] if b['id'] not in [first['id'],second['id']]}=={b['id']:b['raw_text'] for b in after['blocks'] if b['id']!=first['id']}
    with db.transaction() as session:assert digest(session.get(SourceDraft,'draft_cont_actual').source)==before
    assert all(file_hash(cfg.data/key)==sha for key,sha in original_files.items())
    out=root/'.agent/tmp/evidence'/('continuation-api-'+str(time.time_ns()));out.mkdir()
    (out/'source-before.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'response.json').write_text(json.dumps(changed,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8');shutil.copytree(cfg.data,out/'data')
    report={'directory':str(out.relative_to(root)),'actual_parser_corpus':str(corpus.relative_to(root)),'source_before':before,'source_after':digest(after),
        'api_status':201,'idempotent_replay':True,'stale_image_rejected':True,'stale_etag_rejected':True,'old_source_and_original_files_unchanged':True,
        'unselected_raw_unchanged':True,'block_ids':[first['id'],second['id']],'page_image_sha256':page['page_image_sha256']}
    (out/'verification.json').write_text(json.dumps(report,indent=2));(root/'.agent/tmp/reports/core-evidence/latest-continuation-correction.json').write_text(json.dumps(report,indent=2))
