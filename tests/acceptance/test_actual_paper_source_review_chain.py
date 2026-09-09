"""Apply agent-authored original-page plans through real API/PG, with no model calls.

These tests preserve failed inference and review evidence. Successful API/coverage
checks are not a substitute for independent review of the resulting source.
"""
import copy
import json
import math
import shutil
import time
from pathlib import Path

import pytest
from PIL import Image

from packages.domain.models import Document,SourceAsset,SourceDraft
from packages.ir import digest,validate_source
from packages.storage import atomic_write,file_hash

ROOT=Path(__file__).resolve().parents[2]


def read(path):return json.loads(path.read_text(encoding='utf8'))


def requests_for(name,corpus,result):
    footnotes=read(corpus/'independent-footnote-plans.json')
    assert footnotes['parser_result_sha256']==file_hash(corpus/'result.json')
    assert footnotes['source_original_sha256']==result['source_revision']['sha256']
    requests=[{'request':r} for r in footnotes['requests']]
    if name=='efficient':
        requests.append({'request':read(ROOT/'.agent/tmp/evidence/math-api-1788655324392852800/request.json')})
        plan=read(corpus/'independent-math-corrections.json')
        assert plan['source_sha']==result['source_revision']['sha256']
        assert plan['source_revision_hash']==digest(result['source_revision'])
    else:
        requests.append({'request':read(ROOT/'.agent/tmp/evidence/footnote-api-1788656159716127700/request.json')})
        continuation=read(corpus/'independent-continuation-plan.json')
        assert continuation['parser_result_sha256']==file_hash(corpus/'result.json')
        requests.append({'request':{k:continuation[k] for k in ['reason','evidence','operations']}})
        plan=read(corpus/'independent-decimal-crop-plans.json')
        assert plan['parser_result_sha256']==file_hash(corpus/'result.json')
        normalization=read(corpus/'independent-normalize-span-requests.json')
        assert normalization['parser_result_sha256']==file_hash(corpus/'result.json')
        requests.extend({'request':{k:r[k] for k in ['reason','evidence','operations']},'exact_original_span':r['exact_old_substring']} for r in normalization['requests'])
    for finding in sorted(plan['operations'],key=lambda f:(f['block_id'],-len(f['prefix']))):
        op={k:finding[k] for k in ['block_id','page','bbox','prefix','suffix','page_image_sha256']}
        op.update(kind='split_with_math_crop',visual_review_confirmed=True)
        requests.append({'request':{'reason':finding.get('reason',finding.get('review_reason')),'evidence':finding['evidence'],'operations':[op]},
            'exact_original_middle':finding['math_substring']})
    return requests


@pytest.mark.postgres
@pytest.mark.parametrize('name,folder',[('efficient','source-review-v2-efficient'),('pathways','source-review-v3-pathways')])
def test_complete_agent_review_plan_api_chain(name,folder,client,database):
    corpus=ROOT/'.agent/tmp/evidence'/folder
    if not (corpus/'independent-footnote-plans.json').is_file():pytest.skip('Requires version-bound real parser output and independent original-page plans.')
    assert read(corpus/'execution.json')['execution']=='real_docling_layout_and_table_model_inference'
    result=read(corpus/'result.json');requests=requests_for(name,corpus,result)
    db,cfg=database;source=copy.deepcopy(result['source_revision']);prefix=f'documents/doc_review_{name}/parser/1';keys={}
    for asset in source['assets']:
        relative=asset['storage_key'];asset['storage_key']=prefix+'/'+relative
        atomic_write(cfg.data,asset['storage_key'],(corpus/relative).read_bytes())
    for page in result['inspection']['pages']:
        keys[str(page['page'])]=prefix+'/'+page['page_image'];atomic_write(cfg.data,keys[str(page['page'])],(corpus/page['page_image']).read_bytes())
    before=digest(source);original_files={str(p.relative_to(cfg.data)):file_hash(p) for p in cfg.data.rglob('*') if p.is_file()}
    document_id=f'doc_review_{name}';initial_id=f'draft_review_{name}'
    with db.transaction() as session:
        original=next(a for a in source['assets'] if a['id']==source['original_asset_id'])
        session.add(SourceAsset(id=source['original_asset_id'],sha256=source['sha256'],byte_size=original['byte_size'],page_count=len(result['inspection']['pages']),storage_key=original['storage_key']));session.flush()
        session.add(Document(id=document_id,title='Actual original '+name+' correction chain',source_asset_id=source['original_asset_id']));session.flush()
        session.add(SourceDraft(id=initial_id,document_id=document_id,asset_id=source['original_asset_id'],source=source,coverage=result['coverage'],evidence={'inspection':result['inspection'],'page_images':keys}))
    changed={'id':initial_id,'generation':1,'source':source};audit=[];saved_sources={initial_id:before};pixel_checks=[]
    for index,item in enumerate(requests):
        payload=copy.deepcopy(item['request']);operation=payload['operations'][0];old_source=copy.deepcopy(changed['source'])
        if 'exact_original_middle' in item:
            block=next(b for b in old_source['blocks'] if b['id']==operation['block_id']);at=len(operation['prefix']);middle=item['exact_original_middle']
            assert block['raw_text'][:at]==operation['prefix'] and block['raw_text'][at:at+len(middle)]==middle
            operation['suffix']=block['raw_text'][at+len(middle):]
        if 'exact_original_span' in item:
            block=next(b for b in old_source['blocks'] if b['id']==operation['block_id'])
            assert block['normalized_text'][operation['start']:operation['end']]==item['exact_original_span']
        url=f'/api/v1/imports/{changed["id"]}/corrections';headers={'If-Match':f'"{changed["generation"]}"','Idempotency-Key':f'review-{name}-{index}'}
        reply=client.post(url,json=payload,headers=headers)
        assert reply.status_code==201,(index,payload,reply.text)
        assert client.post(url,json=payload,headers=headers).json()==reply.json()
        assert client.post(url,json=payload,headers={**headers,'Idempotency-Key':f'review-stale-{name}-{index}'}).status_code==412
        changed=reply.json();validate_source(changed['source'],asset_root=cfg.data);saved_sources[changed['id']]=digest(changed['source'])
        old_by={b['id']:b for b in old_source['blocks']};new_by={b['id']:b for b in changed['source']['blocks']}
        if operation['kind'] in {'annotate_footnote','normalize_native_span'}:
            assert {b:old_by[b]['raw_text'] for b in old_by}=={b:new_by[b]['raw_text'] for b in new_by}
        elif operation['kind']=='split_with_math_crop':
            mapping=next(m for m in changed['evidence']['mapping'] if m['old_block_ids']==[operation['block_id']])
            assert ''.join(new_by[b]['raw_text'] for b in mapping['new_block_ids'])==old_by[operation['block_id']]['raw_text']
            restoration=changed['evidence']['native_restorations'][-1];asset=restoration['asset'];page=next(p for p in result['inspection']['pages'] if p['page']==operation['page'])
            with Image.open(cfg.data/keys[str(operation['page'])]) as original_image,Image.open(cfg.data/asset['storage_key']) as crop:
                sx=original_image.width/page['page_size'][0];sy=original_image.height/page['page_size'][1];box=operation['bbox']
                pixels=(math.floor(box[0]*sx),math.floor(box[1]*sy),math.ceil(box[2]*sx),math.ceil(box[3]*sy));expected=original_image.crop(pixels)
                assert crop.size==expected.size and crop.tobytes()==expected.tobytes()
            assert file_hash(cfg.data/asset['storage_key'])==asset['sha256']
            pixel_checks.append({'block_id':restoration['formula_block_id'],'asset':asset,'page':operation['page'],'bbox':box,'page_image_sha256':operation['page_image_sha256'],'exact_original_pixels':True})
        else:
            first,second=operation['block_ids'];assert new_by[first]['raw_text']==old_by[first]['raw_text']+'\n'+old_by[second]['raw_text']
            assert new_by[first]['kind']==old_by[first]['kind'] and second not in new_by
        audit.append({'request':payload,'response_id':changed['id'],'source_hash':digest(changed['source']),'mapping':changed['evidence']['mapping'],'native_restorations':changed['evidence']['native_restorations']})
    assert all(file_hash(cfg.data/key)==sha for key,sha in original_files.items())
    with db.transaction() as session:
        assert all(digest(session.get(SourceDraft,key).source)==sha for key,sha in saved_sources.items())
    out=ROOT/'.agent/tmp/evidence'/('reviewed-source-'+name+'-'+str(time.time_ns()));out.mkdir()
    (out/'source-before.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'response.json').write_text(json.dumps(changed,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'operations.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8');shutil.copytree(cfg.data,out/'data')
    report={'directory':str(out.relative_to(ROOT)),'actual_parser_corpus':str(corpus.relative_to(ROOT)),'parser_result_sha256':file_hash(corpus/'result.json'),
        'source_before':before,'source_after':digest(changed['source']),'api_201_count':len(audit),'all_prior_source_snapshots_immutable':True,
        'all_original_files_unchanged':True,'idempotency_and_stale_etag_for_every_operation':True,'can_translate':changed['coverage']['can_translate'],
        'exact_pixel_checks':pixel_checks,'independent_final_source_review':'pending; API and coverage success do not certify complete source gold'}
    (out/'verification.json').write_text(json.dumps(report,indent=2));(ROOT/f'.agent/tmp/reports/core-evidence/latest-reviewed-source-{name}.json').write_text(json.dumps(report,indent=2))
