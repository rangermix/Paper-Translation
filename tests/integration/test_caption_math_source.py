import copy
import json
from pathlib import Path
import pytest

from packages.domain.errors import DomainError
from packages.ir import block_hash,digest,validate_ir
from packages.source_revisions import apply_native_corrections
from packages.publisher import Publisher

ROOT=Path(__file__).resolve().parents[2]


def scenario():
    ir=json.loads((ROOT/'fixtures/sample-document-v3.json').read_text(encoding='utf8'));source=ir['source_revision']
    block=next(b for b in source['blocks'] if b['id']=='figcap')
    text='Caption before d model after the source expression.'
    block.update(raw_text=text,normalized_text=text,normalization_edits=[],source_inline=[{'type':'text','text':text}])
    block['provenance'][0]['bbox']=[20,20,350,80];block['source_hash']=block_hash(block,source['protected_atoms'])
    proof={'page':block['provenance'][0]['page'],'bbox':[100,30,106,45],'quote':'d'}
    inspection={'sha256':source['sha256'],'pages':[{'page':proof['page'],'page_size':[612,792],'text_characters':1,'scan_suspected':False,'text_regions':[{'bbox':proof['bbox'],'text':'d'}]}]}
    op={'kind':'annotate_math_crop','block_id':'figcap','start':15,'end':22,'page':proof['page'],'bbox':[98,28,150,50],'page_image_sha256':'c'*64,'visual_review_confirmed':True}
    existing=next(a for a in source['assets'] if a['media_type']=='image/png')
    return ir,inspection,proof,op,lambda page,bbox,sha:{**existing,'id':'caption-math-asset'}


def test_caption_math_xref_preserves_owner_and_renders_independent_root_once(tmp_path):
    ir,inspection,proof,op,crop=scenario();source=ir['source_revision'];before=digest(source)
    changed=apply_native_corrections(source,inspection,[op],proof,'Agent sees the original lower model subscript.',[],crop_asset=crop)
    assert digest(source)==before
    ir['source_revision']=changed['source'];by={b['id']:b for b in changed['source']['blocks']};caption=by['figcap']
    assert caption['owner_id']=='fig' and caption['raw_text']==next(b for b in source['blocks'] if b['id']=='figcap')['raw_text']
    ref=next(n for n in caption['source_inline'] if n['type']=='xref');math=by[ref['target_block_id']]
    assert ref['label']=='d model' and math['kind']=='math' and math['owner_id'] is None
    assert changed['source']['reading_order'].index(math['id'])==changed['source']['reading_order'].index('fig')+1
    from packages.editorial.drafts import render_input
    translation=copy.deepcopy(ir['translation_revision']);example=translation['results'][1]
    translation.update(title='DRAFT',results=[{**copy.deepcopy(example),'block_id':b['id'],'source_hash':b['source_hash'],'status':'unresolved','target_inline':[],
        'review_state':'not_reviewed','review_record':None} for b in changed['source']['blocks']])
    translation['results'][0]['target_inline']=[{'type':'text','text':'DRAFT'}]
    rendered=render_input('doc-caption-proof',changed['source'],translation,mode='draft');validate_ir(rendered,asset_root=ROOT)
    Publisher().build(rendered,ROOT,tmp_path/'artifact')
    html=(tmp_path/'artifact/index.html').read_text(encoding='utf8')
    assert html.count('id="b-'+math['id']+'"')==1 and f'href="#b-{math["id"]}"' in html
    assert html.index('id="b-fig"')<html.index('id="b-figcap"')<html.index('id="b-'+math['id']+'"')
    assert (tmp_path/'artifact/reader.css').read_bytes()==(ROOT/'reference/reader-v1.css').read_bytes()


@pytest.mark.parametrize('change',[{'bbox':[0,0,612,792]},{'start':0,'end':50},{'visual_review_confirmed':False}])
def test_caption_math_rejects_broad_or_unreviewed_retention(change):
    ir,inspection,proof,op,crop=scenario();op.update(change)
    with pytest.raises(DomainError):apply_native_corrections(ir['source_revision'],inspection,[op],proof,'Review.',[],crop_asset=crop)


def test_native_descender_supports_only_tiny_math_annotation_crop_edge():
    ir,inspection,proof,op,crop=scenario();proof['bbox']=[100,67,106,78]
    inspection['pages'][0]['text_regions']=[{'bbox':proof['bbox'],'text':'d'}, {'bbox':[108,76,145,80.2],'text':'model'}]
    op['bbox']=[98,65,150,80.4]
    changed=apply_native_corrections(ir['source_revision'],inspection,[op],proof,'Agent saw the descender beyond the layout box.',[],crop_asset=crop)
    assert changed['restorations'][0]['layout_edge_margin_points']==pytest.approx(.4)
    assert changed['restorations'][0]['native_edge_evidence']
    op['bbox'][3]=82.5
    with pytest.raises(DomainError):apply_native_corrections(ir['source_revision'],inspection,[op],proof,'Review.',[],crop_asset=crop)


@pytest.mark.postgres
def test_actual_efficient_math_annotation_plan_api_and_reader(client,database):
    import os,time,shutil,math
    from PIL import Image
    from packages.domain.models import SourceAsset,SourceDraft,Document
    from packages.storage import file_hash
    from packages.publisher import export_single_html,export_bundle
    from packages.editorial.drafts import render_input
    base=ROOT/'.agent/tmp/evidence/reviewed-source-efficient-1788656992188257600'
    if not (base/'remaining-math-reviewed-plans.json').is_file():pytest.skip('Requires independently reviewed real original-page mathematical source plan.')
    plan=json.loads((base/'remaining-math-reviewed-plans.json').read_text(encoding='utf8'));prior=json.loads((base/'response.json').read_text(encoding='utf8'))
    source=copy.deepcopy(prior['source']);assert digest(source)==plan['source_hash']
    scope=os.environ.get('MATH_ANNOTATION_SCOPE','caption');assert scope in {'caption','all'}
    candidates=[r for r in plan['candidates'] if scope=='all' or r['kind']=='caption'];assert len(candidates)==(86 if scope=='all' else 2)
    db,cfg=database;shutil.copytree(base/'data',cfg.data,dirs_exist_ok=True);original_files={str(p.relative_to(cfg.data)):file_hash(p) for p in cfg.data.rglob('*') if p.is_file()}
    original_hash=digest(source);initial='draft_math_annotation';document='doc_review_efficient'
    with db.transaction() as session:
        original=next(a for a in source['assets'] if a['id']==source['original_asset_id'])
        session.add(SourceAsset(id=original['id'],sha256=source['sha256'],byte_size=original['byte_size'],page_count=18,storage_key=original['storage_key']));session.flush()
        session.add(Document(id=document,title='Original mathematical source review',source_asset_id=original['id']));session.flush()
        session.add(SourceDraft(id=initial,document_id=document,asset_id=original['id'],source=source,coverage=prior['coverage'],evidence=prior['evidence']))
    current={'id':initial,'generation':1,'source':source};audit=[];snapshots={initial:original_hash}
    for index,finding in enumerate(candidates):
        block=next(b for b in current['source']['blocks'] if b['id']==finding['block_id'])
        assert finding['visual_review_confirmed'] is True and block['normalized_text'][finding['start']:finding['end']]==finding['math_substring']
        operation={k:finding[k] for k in ['block_id','start','end','page','bbox','page_image_sha256','visual_review_confirmed']};operation['kind']='annotate_math_crop'
        payload={'reason':finding['review_reason'],'evidence':finding['evidence'],'operations':[operation]}
        url=f'/api/v1/imports/{current["id"]}/corrections';headers={'If-Match':f'"{current["generation"]}"','Idempotency-Key':f'math-annotation-{index}'}
        reply=client.post(url,json=payload,headers=headers);assert reply.status_code==201,(index,operation,reply.text)
        assert client.post(url,json=payload,headers=headers).json()==reply.json()
        assert client.post(url,json=payload,headers={**headers,'Idempotency-Key':f'math-annotation-stale-{index}'}).status_code==412
        current=reply.json();snapshots[current['id']]=digest(current['source']);restoration=current['evidence']['native_restorations'][-1];asset=restoration['asset']
        page=next(p for p in prior['evidence']['inspection']['pages'] if p['page']==operation['page']);page_key=prior['evidence']['page_images'][str(operation['page'])]
        assert file_hash(cfg.data/page_key)==operation['page_image_sha256'] and file_hash(cfg.data/asset['storage_key'])==asset['sha256']
        with Image.open(cfg.data/page_key) as original_image,Image.open(cfg.data/asset['storage_key']) as crop:
            sx=original_image.width/page['page_size'][0];sy=original_image.height/page['page_size'][1];box=operation['bbox']
            expected=original_image.crop((math.floor(box[0]*sx),math.floor(box[1]*sy),math.ceil(box[2]*sx),math.ceil(box[3]*sy)))
            assert crop.size==expected.size and crop.tobytes()==expected.tobytes()
        audit.append({'request':payload,'response_id':current['id'],'source_hash':digest(current['source']),'restoration':restoration,'exact_original_pixels':True})
        if (index+1)%10==0:print(f'Actual math annotation API: {index+1}/{len(candidates)} complete.',flush=True)
    by={b['id']:b for b in current['source']['blocks']}
    assert all(by[b['id']]['raw_text']==b['raw_text'] and by[b['id']]['owner_id']==b['owner_id'] for b in source['blocks'])
    assert all(file_hash(cfg.data/key)==sha for key,sha in original_files.items())
    with db.transaction() as session:assert all(digest(session.get(SourceDraft,key).source)==sha for key,sha in snapshots.items())
    template=json.loads((ROOT/'fixtures/sample-document-v3.json').read_text(encoding='utf8'));translation=copy.deepcopy(template['translation_revision']);example=translation['results'][1]
    translation.update(source_revision_id=current['source']['id'],title='DRAFT',results=[{**copy.deepcopy(example),'block_id':b['id'],'source_hash':b['source_hash'],
        'status':'unresolved','target_inline':[],'review_state':'not_reviewed','review_record':None} for b in current['source']['blocks']])
    translation['results'][0]['target_inline']=[{'type':'text','text':'DRAFT'}]
    ir=render_input(document,current['source'],translation,mode='draft');validate_ir(ir,asset_root=cfg.data)
    out=ROOT/'.agent/tmp/evidence'/('math-annotation-api-'+scope+'-'+str(time.time_ns()));out.mkdir()
    Publisher().build(ir,cfg.data,out/'artifact');export_single_html(out/'artifact',out/'single.html');export_bundle(out/'artifact',out/'bundle.zip')
    html=(out/'artifact/index.html').read_text(encoding='utf8')
    for item in audit:
        bid=item['restoration']['formula_block_id'];assert html.count(f'id="b-{bid}"')==1 and f'href="#b-{bid}"' in html
    (out/'source-before.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'response.json').write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf8');(out/'operations.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'reader-ir.json').write_text(json.dumps(ir,ensure_ascii=False,indent=2),encoding='utf8');shutil.copytree(cfg.data,out/'data')
    report={'directory':str(out.relative_to(ROOT)),'source_before':original_hash,'source_after':digest(current['source']),'scope':scope,'api_201_count':len(audit),
        'every_prior_snapshot_and_original_file_unchanged':True,'every_base_raw_and_owner_unchanged':True,'every_crop_exact_original_pixels':True,
        'every_operation_idempotent_and_stale_etag_rejected':True,'each_math_independent_root_rendered_once_and_reachable':True,
        'reader_v1_css_unchanged':file_hash(out/'artifact/reader.css')==file_hash(ROOT/'reference/reader-v1.css'),
        'reader_mode':'DRAFT; source review only, no translated target generated','independent_browser_review':'pending'}
    (out/'verification.json').write_text(json.dumps(report,indent=2));(ROOT/f'.agent/tmp/reports/core-evidence/latest-math-annotation-{scope}.json').write_text(json.dumps(report,indent=2))
