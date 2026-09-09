"""Execute independently viewed original word-boundary plans, through actual PG/API."""
import copy
import json
import shutil
import time
from pathlib import Path

import pytest

from packages.domain.models import Document,SourceAsset,SourceDraft
from packages.ir import digest,validate_source
from packages.storage import file_hash

ROOT=Path(__file__).resolve().parents[2]
def read(path):return json.loads(path.read_text(encoding='utf8'))


@pytest.mark.postgres
def test_actual_efficient_35_native_spans_and_two_float_seams(client,database):
    base=ROOT/'.agent/tmp/evidence/math-annotation-api-all-1788658908884891000';corpus=ROOT/'.agent/tmp/evidence/source-review-v2-efficient'
    if not (corpus/'independent-cross-figure-requests.json').is_file():pytest.skip('Requires independent original-page/native plans and actual inferred source.')
    prior=read(base/'response.json');source=copy.deepcopy(prior['source'])
    normalization=read(corpus/'independent-normalize-span-requests.json');seams=read(corpus/'independent-cross-figure-requests.json')
    assert len(normalization['requests'])==35 and len(seams['requests'])==2
    for plan in [normalization,seams]:
        assert plan['source_hash']==digest(source) and plan['source_response_sha256']==file_hash(base/'response.json')
    assert seams['original_pdf_sha256']==source['sha256']
    db,cfg=database;shutil.copytree(base/'data',cfg.data,dirs_exist_ok=True)
    original_files={str(p.relative_to(cfg.data)):file_hash(p) for p in cfg.data.rglob('*') if p.is_file()}
    initial='draft_efficient_native_final';document='doc_review_efficient';snapshots={initial:digest(source)}
    with db.transaction() as session:
        asset=next(a for a in source['assets'] if a['id']==source['original_asset_id'])
        session.add(SourceAsset(id=asset['id'],sha256=source['sha256'],byte_size=asset['byte_size'],page_count=18,storage_key=asset['storage_key']));session.flush()
        session.add(Document(id=document,title='Original Efficient native boundary review',source_asset_id=asset['id']));session.flush()
        session.add(SourceDraft(id=initial,document_id=document,asset_id=asset['id'],source=source,coverage=prior['coverage'],evidence=prior['evidence']))
    current={'id':initial,'generation':1,'source':source};audit=[]
    for index,item in enumerate(normalization['requests']+seams['requests']):
        old=copy.deepcopy(current['source']);by={b['id']:b for b in old['blocks']};op=item['operations'][0]
        if op['kind']=='normalize_native_span':
            assert by[op['block_id']]['normalized_text'][op['start']:op['end']]==item['expected_current_span']
        else:
            first,second=op['block_ids'];assert by[first]['normalized_text']==item['expected_first_normalized'] and by[second]['normalized_text']==item['expected_second_normalized']
            assert old['reading_order'][old['reading_order'].index(first)+1:old['reading_order'].index(second)]==item['intervening_roots_must_be_preserved']
        payload={k:copy.deepcopy(item[k]) for k in ['reason','evidence','operations']}
        url=f'/api/v1/imports/{current["id"]}/corrections';headers={'If-Match':f'"{current["generation"]}"','Idempotency-Key':f'efficient-native-final-{index}'}
        if index==0:
            bad=copy.deepcopy(payload);hashes=bad['operations'][0]['page_image_sha256s'];hashes[next(iter(hashes))]='0'*64
            denied=client.post(url,json=bad,headers={**headers,'Idempotency-Key':'efficient-native-bad-page'})
            assert denied.status_code==409 and denied.json()['error']['code']=='SOURCE_PAGE_IMAGE_STALE'
        result=client.post(url,json=payload,headers=headers);assert result.status_code==201,(index,payload,result.text)
        assert client.post(url,json=payload,headers=headers).json()==result.json()
        assert client.post(url,json=payload,headers={**headers,'Idempotency-Key':f'efficient-native-stale-{index}'}).status_code==412
        current=result.json();validate_source(current['source'],asset_root=cfg.data);snapshots[current['id']]=digest(current['source'])
        after={b['id']:b for b in current['source']['blocks']};restoration=current['evidence']['native_restorations'][-1]
        if op['kind']=='normalize_native_span':
            assert restoration['replacement']==item['reviewed_result']
            assert {bid:b['raw_text'] for bid,b in by.items()}=={bid:b['raw_text'] for bid,b in after.items()}
            assert current['source']['reading_order']==old['reading_order']
        else:
            first,second=op['block_ids'];assert restoration['joined_word']==item['expected_joined_word']
            assert after[first]['raw_text']==by[first]['raw_text']+'\n'+by[second]['raw_text']
            assert after[first]['provenance']==by[first]['provenance']+by[second]['provenance']
            assert current['source']['reading_order']==[bid for bid in old['reading_order'] if bid!=second]
            assert {bid:b['raw_text'] for bid,b in by.items() if bid not in op['block_ids']}=={bid:b['raw_text'] for bid,b in after.items() if bid!=first}
        for bid,b in by.items():
            if b['kind'] in {'figure','table','math','caption','table_cell'}:
                ignored={'order','source_hash'}
                if op['kind']=='normalize_native_span' and op['block_id']==bid:
                    # The independently reviewed plan also restores two caption name hyphens.
                    ignored|={'normalized_text','normalization_edits','source_inline'}
                assert {k:v for k,v in b.items() if k not in ignored}=={k:v for k,v in after[bid].items() if k not in ignored}
        audit.append({'request':payload,'source_hash':digest(current['source']),'response_id':current['id'],'native_restoration':restoration})
        if (index+1)%10==0:print(f'Actual native API: {index+1}/37 complete.',flush=True)
    assert all(file_hash(cfg.data/key)==sha for key,sha in original_files.items())
    with db.transaction() as session:assert all(digest(session.get(SourceDraft,key).source)==sha for key,sha in snapshots.items())
    out=ROOT/'.agent/tmp/evidence'/('efficient-native-final-'+str(time.time_ns()));out.mkdir()
    for name,value in [('source-before',source),('response',current),('operations',audit)]:
        (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    shutil.copytree(cfg.data,out/'data')
    report={'directory':str(out.relative_to(ROOT)),'base_directory':str(base.relative_to(ROOT)),'source_before':digest(source),'source_after':digest(current['source']),
        'actual_parser_result_sha256':file_hash(corpus/'result.json'),'api_201_count':37,'every_operation_idempotent_and_stale_etag_rejected':True,
        'stale_page_hash_rejected':True,'all_prior_snapshots_and_original_files_unchanged':True,'all_graphics_math_and_caption_owners_unchanged':True,
        'caption_raw_unchanged_except_explicit_normalized_spans':True,
        'raw_unchanged_except_two_audited_original_block_concatenations':True,'original_pdf_sha256':source['sha256'],
        'independent_final_source_review':'pending; actual API success is not independent source gold or translated content'}
    (out/'verification.json').write_text(json.dumps(report,indent=2));(ROOT/'.agent/tmp/reports/core-evidence/latest-efficient-native-final.json').write_text(json.dumps(report,indent=2))
