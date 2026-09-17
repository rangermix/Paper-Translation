import copy
import json
from pathlib import Path

import pytest

from packages.domain.errors import DomainError
from packages.ir import block_hash,digest,validate_source
from packages.source_revisions import apply_native_corrections

ROOT=Path(__file__).resolve().parents[2]


def scenario():
    source=json.loads((ROOT/'tests/fixtures/sample-document.json').read_text(encoding='utf8'))['source_revision']
    block=next(b for b in source['blocks'] if b['id']=='p1')
    text='Before formula N = sqrt A/B after formula.'
    block.update(raw_text=text,normalized_text=text,source_inline=[{'type':'text','text':text}],normalization_edits=[])
    block['provenance'][0]['bbox']=[20,20,250,120]
    block['source_hash']=block_hash(block,source['protected_atoms'])
    loc=block['provenance'][0]
    evidence={'page':loc['page'],'bbox':[100,50,110,65],'quote':'q'}
    inspection={'sha256':source['sha256'],'pages':[{'page':loc['page'],'page_size':loc['page_size'],
        'text_characters':1,'text_regions':[{'bbox':evidence['bbox'],'text':'q'}],'scan_suspected':False}]}
    operation={'kind':'split_with_math_crop','block_id':'p1','page':loc['page'],'bbox':[90,45,150,75],
        'prefix':'Before formula ','suffix':' after formula.','page_image_sha256':'c'*64,'visual_review_confirmed':True}
    image=next(a for a in source['assets'] if a['media_type']=='image/png')
    def crop(page,bbox,sha):
        assert (page,bbox,sha)==(operation['page'],operation['bbox'],'c'*64)
        return {**image,'id':'math-crop-asset','storage_key':'generated/formula.png'}
    return source,inspection,evidence,operation,crop


def test_math_split_preserves_prose_and_exact_middle_with_new_asset():
    source,inspection,evidence,operation,crop=scenario();before=digest(source)
    result=apply_native_corrections(source,inspection,[operation],evidence,'Agent compared the fraction on the original page.',[],crop_asset=crop)
    assert digest(source)==before
    mapping=next(m for m in result['mapping'] if m['old_block_ids']==['p1'])
    by={b['id']:b for b in result['source']['blocks']};parts=[by[bid] for bid in mapping['new_block_ids']]
    assert [p['kind'] for p in parts]==['paragraph','math','paragraph']
    assert ''.join(p['normalized_text'] for p in parts)=='Before formula N = sqrt A/B after formula.'
    assert parts[1]['attributes']=={'representation':'image','asset_id':'math-crop-asset'}
    assert all(p['parent_id']==parts[0]['parent_id'] for p in parts)
    assert result['coverage']['can_translate']
    assert result['restorations'][0]['page_image_sha256']=='c'*64
    validate_source(result['source'])


@pytest.mark.parametrize('change',[{'prefix':'Invented prose'}, {'bbox':[1,1,500,500]},
    {'bbox':[20,20,250,120]}, {'visual_review_confirmed':False}, {'prefix':'','suffix':''}])
def test_math_split_rejects_unproven_text_geometry_or_whole_paragraph(change):
    source,inspection,evidence,operation,crop=scenario();operation.update(change)
    with pytest.raises(DomainError):
        apply_native_corrections(source,inspection,[operation],evidence,'Agent review.',[],crop_asset=crop)


def test_math_split_allows_native_glyph_edge_margin_but_not_unrelated_overreach():
    source,inspection,evidence,operation,crop=scenario()
    source['blocks'][1]['provenance'][0]['bbox']=[20,20,250,64.5]
    # A native descender extends beyond the layout model's approximate box.
    operation['bbox']=[90,45,150,65.5]
    result=apply_native_corrections(source,inspection,[operation],evidence,'Original glyph descender checked.',[],crop_asset=crop)
    assert result['restorations'][0]['layout_edge_margin_points']==1.0
    operation['bbox'][3]=68
    with pytest.raises(DomainError):
        apply_native_corrections(source,inspection,[operation],evidence,'Review.',[],crop_asset=crop)


@pytest.mark.postgres
def test_real_docling_math_crop_api_asset_hash_etag_and_immutable_source(client,database):
    """Controlled original-paper evidence; requires the separately run real parser."""
    import shutil
    import time
    import os
    from PIL import Image
    from packages.domain.models import Document,SourceAsset,SourceDraft
    from packages.storage import atomic_write,file_hash
    corpus=Path(os.environ.get('MATH_CORPUS',str(ROOT/'.agent/tmp/evidence/final-efficient')))
    if not (corpus/'result.json').is_file():pytest.skip('Run the real final Efficient parser corpus before this acceptance test.')
    assert json.loads((corpus/'execution.json').read_text())['execution']=='real_docling_layout_and_table_model_inference'
    db,cfg=database;result=json.loads((corpus/'result.json').read_text(encoding='utf8'))
    source=copy.deepcopy(result['source_revision']);prefix='documents/doc_math_api/parser/real/1'
    for asset in source['assets']:
        original_key=asset['storage_key'];asset['storage_key']=prefix+'/'+original_key
        atomic_write(cfg.data,asset['storage_key'],(corpus/original_key).read_bytes())
    image_keys={}
    for page in result['inspection']['pages']:
        image_keys[str(page['page'])]=prefix+'/'+page['page_image']
        atomic_write(cfg.data,image_keys[str(page['page'])],(corpus/page['page_image']).read_bytes())
    original_hash=digest(source)
    original_files={str(p.relative_to(cfg.data)):file_hash(p) for p in cfg.data.rglob('*') if p.is_file()}
    with db.transaction() as session:
        asset=SourceAsset(id=source['original_asset_id'],sha256=source['sha256'],byte_size=source['assets'][0]['byte_size'],page_count=18,storage_key=source['assets'][0]['storage_key'])
        session.add(asset);session.flush()
        session.add(Document(id='doc_math_api',title='Actual original PDF math correction',source_asset_id=asset.id));session.flush()
        session.add(SourceDraft(id='draft_math_api',document_id='doc_math_api',asset_id=asset.id,source=source,coverage=result['coverage'],
            evidence={'inspection':result['inspection'],'page_images':image_keys}))
    native=client.get('/api/v1/imports/draft_math_api/native-regions');assert native.status_code==200
    page=next(p for p in native.json()['pages'] if p['page']==6)
    region=next(r for r in page['text_regions'] if r['text']=='q' and 390<r['bbox'][1]<420)
    block=next(b for b in source['blocks'] if 'choice N = √ BLn chips F' in b['raw_text'])
    expression='N = √ BLn chips F';before,after=block['raw_text'].split(expression)
    operation={'kind':'split_with_math_crop','block_id':block['id'],'page':6,'bbox':[55,397,119,416],
        'prefix':before,'suffix':after,'page_image_sha256':page['page_image_sha256'],'visual_review_confirmed':True}
    body={'reason':'Agent /root/ir_publisher_parser inspected original page 6: N equals the square root of BLn_chips divided by F. Keep the exact original image; preserve all surrounding prose.',
        'evidence':{'page':6,'bbox':region['bbox'],'quote':region['text']},'operations':[operation]}
    bad=copy.deepcopy(body);bad['operations'][0]['page_image_sha256']='0'*64
    rejected=client.post('/api/v1/imports/draft_math_api/corrections',json=bad,headers={'If-Match':'"1"','Idempotency-Key':'math-stale-image'})
    assert rejected.status_code==409 and 'SOURCE_PAGE_IMAGE_STALE' in rejected.text
    headers={'If-Match':'"1"','Idempotency-Key':'math-source-crop'}
    corrected=client.post('/api/v1/imports/draft_math_api/corrections',json=body,headers=headers)
    assert corrected.status_code==201,corrected.text
    again=client.post('/api/v1/imports/draft_math_api/corrections',json=body,headers=headers)
    assert again.status_code==201 and again.json()==corrected.json()
    stale=client.post('/api/v1/imports/draft_math_api/corrections',json=body,headers={'If-Match':'"1"','Idempotency-Key':'math-stale-etag'})
    assert stale.status_code in (409,412)
    changed=corrected.json();new_source=changed['source']
    # Only the reviewed formula is certified here. Complete ordered coverage
    # may expose unrelated deficiencies in the original real parser snapshot.
    assert not any(u.get('page')==6 and u.get('bbox')==region['bbox'] for u in changed['coverage']['unresolved'])
    mapping=next(m for m in changed['evidence']['mapping'] if m['old_block_ids']==[block['id']])
    by={b['id']:b for b in new_source['blocks']};parts=[by[bid] for bid in mapping['new_block_ids']]
    assert ''.join(b['raw_text'] for b in parts)==block['raw_text']
    math=next(b for b in parts if b['kind']=='math');asset=next(a for a in new_source['assets'] if a['id']==math['attributes']['asset_id'])
    assert file_hash(cfg.data/asset['storage_key'])==asset['sha256']
    with Image.open(cfg.data/image_keys['6']) as original,Image.open(cfg.data/asset['storage_key']) as crop:
        expected=original.crop((82,595,179,624))
        assert crop.size==expected.size and crop.tobytes()==expected.tobytes()
    with db.transaction() as session:
        old=session.get(SourceDraft,'draft_math_api')
        assert digest(old.source)==original_hash and old.coverage==result['coverage']
        assert old.evidence['superseded_by']==changed['id']
    assert all(file_hash(cfg.data/key)==sha for key,sha in original_files.items())
    validate_source(new_source,asset_root=cfg.data)
    # An independent agent may provide additional exact original-page findings.
    # Apply those through the same public correction route, right-to-left per
    # paragraph so every existing prefix retains its stable source block id.
    import os
    plan_path=os.environ.get('MATH_REVIEW_PLAN')
    additional=[]
    if plan_path:
        plan=json.loads(Path(plan_path).read_text(encoding='utf8'))
        assert plan['source_sha']==source['sha256']
        if 'source_revision_hash' in plan:assert plan['source_revision_hash']==digest(result['source_revision'])
        for number,finding in enumerate(sorted(plan['operations'],key=lambda f:(f['block_id'],-len(f['prefix'])))):
            current=next(b for b in changed['source']['blocks'] if b['id']==finding['block_id'])
            at=len(finding['prefix']);middle=finding['math_substring']
            assert current['raw_text'][:at]==finding['prefix'] and current['raw_text'][at:at+len(middle)]==middle
            op={key:finding[key] for key in ['block_id','page','bbox','page_image_sha256','visual_review_confirmed']}
            op.update(kind='split_with_math_crop',prefix=current['raw_text'][:at],suffix=current['raw_text'][at+len(middle):])
            payload={'reason':finding['reason'],'evidence':finding['evidence'],'operations':[op]}
            reply=client.post(f'/api/v1/imports/{changed["id"]}/corrections',json=payload,
                headers={'If-Match':f'"{changed["generation"]}"','Idempotency-Key':f'independent-math-{number}'})
            assert reply.status_code==201,reply.text
            additional.append({'request':payload,'response_id':reply.json()['id']})
            changed=reply.json();new_source=changed['source']
        validate_source(new_source,asset_root=cfg.data)
    out=ROOT/'.agent/tmp/evidence'/('math-api-'+str(time.time_ns()));out.mkdir()
    (out/'request.json').write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'response.json').write_text(json.dumps(changed,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'source-before.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf8')
    shutil.copyfile(cfg.data/asset['storage_key'],out/'math.png');shutil.copyfile(cfg.data/image_keys['6'],out/'original-page-6.png')
    shutil.copytree(cfg.data,out/'data')
    (out/'additional-requests.json').write_text(json.dumps(additional,ensure_ascii=False,indent=2),encoding='utf8')
    proof={'directory':str(out.relative_to(ROOT)),'real_parser_execution':str(corpus.relative_to(ROOT)),'api_status':201,
        'original_source_hash':original_hash,'new_source_hash':digest(new_source),'crop_sha256':asset['sha256'],
        'original_page_sha256':page['page_image_sha256'],'etag':corrected.headers['etag'],'idempotent_replay':True,
        'stale_image_rejected':True,'stale_etag_rejected':True,'original_source_and_files_unchanged':True,'can_translate':changed['coverage']['can_translate']}
    proof['additional_agent_reviewed_corrections']=len(additional)
    (out/'verification.json').write_text(json.dumps(proof,indent=2))
    (ROOT/'.agent/tmp/reports/core-evidence/latest-math-correction.json').write_text(json.dumps(proof,indent=2))
