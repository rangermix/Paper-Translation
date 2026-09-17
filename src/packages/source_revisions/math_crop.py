"""Explicit visual source correction using a hash-bound original page raster."""
import copy
import io
import math
import re

from packages.domain.errors import require
from packages.ir import digest,flatten_inline
from packages.parsers.pdf_docling import _source_nodes,overlap
from packages.storage import atomic_write,file_hash,safe_path
from .corrections import _set_order,_split_inline


def split_with_math_crop(source,operation,evidence,reason,crop_asset):
    expected={'kind','block_id','page','bbox','prefix','suffix','page_image_sha256','visual_review_confirmed'}
    require(set(operation)==expected and operation['visual_review_confirmed'] is True,'SOURCE_VISUAL_REVIEW_REQUIRED',status=422)
    require(callable(crop_asset),'SOURCE_PAGE_IMAGE_REQUIRED',status=422)
    block=next((b for b in source['blocks'] if b['id']==operation['block_id']),None)
    require(block and block['kind']=='paragraph' and block['owner_id'] is None,'SOURCE_MATH_SPLIT_UNSUPPORTED',status=422)
    require(block['raw_text']==block['normalized_text'],'SOURCE_SPLIT_MAPPING_REQUIRED',status=422)
    prefix,suffix=operation['prefix'],operation['suffix'];text=block['raw_text']
    require(isinstance(prefix,str) and isinstance(suffix,str) and (prefix.strip() or suffix.strip())
        and text.startswith(prefix) and text.endswith(suffix) and len(prefix)+len(suffix)<len(text),'SOURCE_UNPROVEN_TEXT',status=422)
    start,end=len(prefix),len(text)-len(suffix)
    middle=text[start:end]
    require(middle.strip() and len(middle)<=len(text)/2,'SOURCE_MATH_CROP_TOO_BROAD',status=422)
    bbox=operation['bbox'];number=operation['page']
    require(type(number) is int and isinstance(bbox,list) and len(bbox)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in bbox),'SOURCE_CROP_INVALID',status=422)
    require(bbox[0]<bbox[2] and bbox[1]<bbox[3],'SOURCE_CROP_INVALID',status=422)
    def edge_margin(loc):
        b=loc['bbox']
        return max(0,b[0]-bbox[0],b[1]-bbox[1],bbox[2]-b[2],bbox[3]-b[3])
    # Layout boxes can clip a native radical/descender by a fraction of a point.
    # Permit only a tiny, visually reviewed padding next to the native proof;
    # the image remains hash-bound and broad/foreign crops are still rejected.
    def supported_edge(loc):
        b=loc['bbox'];proof=evidence['bbox']
        return all(not extends or abs(crop_edge-proof_edge)<=1 for extends,crop_edge,proof_edge in [
            (bbox[0]<b[0],bbox[0],proof[0]),(bbox[1]<b[1],bbox[1],proof[1]),
            (bbox[2]>b[2],bbox[2],proof[2]),(bbox[3]>b[3],bbox[3],proof[3])])
    loc=next((loc for loc in block['provenance'] if loc['page']==number and
        (overlap(bbox,loc['bbox'])>=.999 or edge_margin(loc)<=2 and supported_edge(loc))),None)
    require(loc is not None,'SOURCE_CROP_OUTSIDE_BLOCK',status=422)
    area=lambda b:(b[2]-b[0])*(b[3]-b[1])
    require(area(bbox)<=.5*area(loc['bbox']) and area(bbox)<=.1*loc['page_size'][0]*loc['page_size'][1],'SOURCE_MATH_CROP_TOO_BROAD',status=422)
    require(evidence['page']==number and overlap(evidence['bbox'],bbox)>=.9,'SOURCE_NATIVE_EVIDENCE_MISMATCH',status=422)
    require(isinstance(operation['page_image_sha256'],str) and re.fullmatch('[a-f0-9]{64}',operation['page_image_sha256']),'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
    left,tail=_split_inline(block['source_inline'],start,source['protected_atoms'])
    _,right=_split_inline(tail,end-start,source['protected_atoms'])
    asset=crop_asset(number,bbox,operation['page_image_sha256'])
    require(asset['id'] not in {a['id'] for a in source['assets']},'SOURCE_ASSET_CONFLICT')
    source['assets'].append(asset)
    token=digest({'source_id':source['id'],'operation':operation})[:24]
    parts=[]
    if prefix:
        before=copy.deepcopy(block);before.update(raw_text=prefix,normalized_text=prefix,source_inline=left,normalization_edits=[]);parts.append(before)
    formula=copy.deepcopy(block);formula.update(id='math-'+token if parts else block['id'],kind='math',translatable=False,
        raw_text=middle,normalized_text=middle,normalization_edits=[],attributes={'representation':'image','asset_id':asset['id']},
        provenance=[{**loc,'bbox':bbox}],warnings=['依据原PDF页图审校保留公式；分数与上下标以图像为准。'])
    formula['source_inline']=_source_nodes(middle,formula['id'],source['protected_atoms'],'math');parts.append(formula)
    if suffix:
        after=copy.deepcopy(block);after.update(id='paragraph-'+token,raw_text=suffix,normalized_text=suffix,source_inline=right,normalization_edits=[]);parts.append(after)
    old_id=block['id'];order=list(source['reading_order']);index=order.index(old_id)
    order[index:index+1]=[part['id'] for part in parts]
    source['blocks']=[b for b in source['blocks'] if b['id']!=old_id]+parts
    _set_order(source,order)
    return {'kind':'split','old_block_ids':[old_id],'new_block_ids':[p['id'] for p in parts]}, {
        'action':'split_with_math_crop','block_id':old_id,'formula_block_id':formula['id'],'page':number,'bbox':bbox,
        'page_image_sha256':operation['page_image_sha256'],'original_middle_text':middle,'reason':reason,
        'layout_edge_margin_points':edge_margin(loc),'original_layout_bbox':list(loc['bbox']),
        'visual_review_confirmed':True,'original_pdf_sha256':source['sha256'],'asset':copy.deepcopy(asset)}


def verify_page_image(data_root,draft,number,expected_sha):
    require(isinstance(expected_sha,str) and re.fullmatch('[a-f0-9]{64}',expected_sha),'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
    page=next((p for p in draft.evidence.get('inspection',{}).get('pages',[]) if p['page']==number),None)
    key=draft.evidence.get('page_images',{}).get(str(number))
    require(page and key,'SOURCE_PAGE_IMAGE_REQUIRED')
    path=safe_path(data_root,key,must_exist=True)
    require(file_hash(path)==expected_sha,'SOURCE_PAGE_IMAGE_STALE')
    return page,path


def annotate_math_crop(source,operation,evidence,reason,crop_asset,inspection):
    """Keep owned prose intact and reference an independently rendered root math."""
    expected={'kind','block_id','start','end','page','bbox','page_image_sha256','visual_review_confirmed'}
    require(set(operation)==expected and operation['visual_review_confirmed'] is True,'SOURCE_VISUAL_REVIEW_REQUIRED',status=422)
    require(callable(crop_asset),'SOURCE_PAGE_IMAGE_REQUIRED',status=422)
    block=next((b for b in source['blocks'] if b['id']==operation['block_id']),None)
    require(block and block['kind'] in {'paragraph','caption','table_cell','list_item','heading','footnote'},'SOURCE_MATH_ANNOTATION_UNSUPPORTED',status=422)
    start,end=operation['start'],operation['end'];text=block['normalized_text']
    require(type(start) is int and type(end) is int and 0<=start<end<=len(text),'SOURCE_OFFSET_INVALID',status=422)
    middle=text[start:end]
    require(middle.strip() and len(middle)<=len(text)/2,'SOURCE_MATH_CROP_TOO_BROAD',status=422)
    bbox,number=operation['bbox'],operation['page']
    require(type(number) is int and isinstance(bbox,list) and len(bbox)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in bbox)
        and bbox[0]<bbox[2] and bbox[1]<bbox[3],'SOURCE_CROP_INVALID',status=422)
    edge_evidence=[]
    def supported(loc):
        if loc['page']!=number:return False
        if overlap(bbox,loc['bbox'])>=.999:return True
        box=loc['bbox'];margin=max(0,box[0]-bbox[0],box[1]-bbox[1],bbox[2]-box[2],bbox[3]-box[3])
        if margin>2:return False
        regions=[r for page in inspection['pages'] if page['page']==number for r in page['text_regions']
            if overlap(r['bbox'],bbox)>=.9 and overlap(r['bbox'],box)>=.6]
        proofs=[]
        for axis,extends in enumerate([bbox[0]<box[0],bbox[1]<box[1],bbox[2]>box[2],bbox[3]>box[3]]):
            if not extends:continue
            candidates=[r for r in regions if abs(r['bbox'][axis]-bbox[axis])<=1]
            if not candidates:return False
            proofs.extend(candidates)
        edge_evidence.extend(copy.deepcopy(proofs));return True
    loc=next((loc for loc in block['provenance'] if supported(loc)),None)
    require(loc is not None,'SOURCE_CROP_OUTSIDE_BLOCK',status=422)
    area=lambda box:(box[2]-box[0])*(box[3]-box[1])
    require(area(bbox)<=.5*area(loc['bbox']) and area(bbox)<=.1*loc['page_size'][0]*loc['page_size'][1],'SOURCE_MATH_CROP_TOO_BROAD',status=422)
    require(evidence['page']==number and overlap(evidence['bbox'],bbox)>=.9,'SOURCE_NATIVE_EVIDENCE_MISMATCH',status=422)
    require(isinstance(operation['page_image_sha256'],str) and re.fullmatch('[a-f0-9]{64}',operation['page_image_sha256']),'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
    left,tail=_split_inline(block['source_inline'],start,source['protected_atoms']);selected,right=_split_inline(tail,end-start,source['protected_atoms'])
    require(all(node['type']=='text' or node['type']=='protected_ref' and source['protected_atoms'][node['ref']]['kind'] in {'number','math'} for node in selected),
        'SOURCE_PROTECTED_EDIT',status=422)
    asset=crop_asset(number,bbox,operation['page_image_sha256'])
    require(asset['id'] not in {a['id'] for a in source['assets']},'SOURCE_ASSET_CONFLICT')
    source['assets'].append(asset)
    bid='math-annotation-'+digest({'source_id':source['id'],'operation':operation})[:24]
    require(all(b['id']!=bid for b in source['blocks']),'SOURCE_ID_CONFLICT')
    block['source_inline']=left+[{'type':'xref','target_block_id':bid,'label':middle}]+right
    require(flatten_inline(block['source_inline'],source['protected_atoms'])==text,'SOURCE_UNPROVEN_TEXT')
    formula={'id':bid,'kind':'math','order':len(source['blocks']),'parent_id':block['parent_id'] or source['title_block_id'],
        'owner_id':None,'language':block['language'],'translatable':False,'raw_text':middle,'normalized_text':middle,'normalization_edits':[],
        'source_inline':_source_nodes(middle,bid,source['protected_atoms'],'math'),'provenance':[{**loc,'bbox':bbox}],
        'warnings':['依据原PDF页图审校保留公式；正文链接指向此原式，分数与上下标以图像为准。'],
        'attributes':{'representation':'image','asset_id':asset['id']}}
    source['blocks'].append(formula)
    owner=block['owner_id'] or block['id']
    related=[b for b in source['blocks'] if b['id']==owner or b['owner_id']==owner]
    referenced=[node['target_block_id'] for b in related for node in b['source_inline'] if node['type']=='xref' and node['target_block_id'].startswith('math-annotation-')]
    referenced=list(dict.fromkeys(referenced));order=[i for i in source['reading_order'] if i not in referenced];at=order.index(owner)+1
    order[at:at]=referenced;_set_order(source,order)
    return {'kind':'split','old_block_ids':[block['id']],'new_block_ids':[block['id'],bid]}, {
        'action':'annotate_math_crop','block_id':block['id'],'formula_block_id':bid,'start':start,'end':end,
        'original_span':middle,'original_raw_hash':digest(block['raw_text']),'original_pdf_sha256':source['sha256'],
        'page':number,'bbox':bbox,'page_image_sha256':operation['page_image_sha256'],'native_evidence':copy.deepcopy(evidence),
        'layout_edge_margin_points':max(0,loc['bbox'][0]-bbox[0],loc['bbox'][1]-bbox[1],bbox[2]-loc['bbox'][2],bbox[3]-loc['bbox'][3]),
        'native_edge_evidence':edge_evidence,'original_layout_bbox':list(loc['bbox']),
        'owner_id_preserved':block['owner_id'],'visual_review_confirmed':True,'reason':reason,'asset':copy.deepcopy(asset)}


def page_crop_factory(data_root,document_id,draft):
    """No PDF decoder here: read the immutable parser-provided PNG only."""
    def crop(number,bbox,expected_sha):
        from PIL import Image
        page,path=verify_page_image(data_root,draft,number,expected_sha)
        with Image.open(path) as image:
            require(image.format=='PNG' and image.width*image.height<=40_000_000,'SOURCE_PAGE_IMAGE_INVALID')
            width,height=page['page_size'];sx,sy=image.width/width,image.height/height
            require(abs(sx-sy)<.02,'SOURCE_PAGE_IMAGE_INVALID')
            pixels=(math.floor(bbox[0]*sx),math.floor(bbox[1]*sy),math.ceil(bbox[2]*sx),math.ceil(bbox[3]*sy))
            require(0<=pixels[0]<pixels[2]<=image.width and 0<=pixels[1]<pixels[3]<=image.height,'SOURCE_CROP_INVALID')
            output=io.BytesIO();image.crop(pixels).save(output,format='PNG');payload=output.getvalue()
        token=digest({'draft_id':draft.id,'page':number,'bbox':bbox,'page_sha':expected_sha})[:24]
        storage_key=f'documents/{document_id}/source-corrections/{token}/math.png'
        atomic_write(data_root,storage_key,payload)
        return {'id':'math-asset-'+token,'media_type':'image/png','sha256':digest(payload),'storage_key':storage_key,'byte_size':len(payload)}
    return crop
