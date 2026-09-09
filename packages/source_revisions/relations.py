"""Explicit, evidence-bound source relationships; no model-authored source."""
import copy
import re

from packages.domain.errors import require
from packages.ir import digest,flatten_inline
from packages.parsers.pdf_docling import overlap
from .corrections import _split_inline,_set_order


def annotate_footnote(source,operation,evidence,reason,page_image_verify):
    expected={'kind','block_id','start','end','target_block_id','page_image_sha256','visual_review_confirmed'}
    require(set(operation)==expected and operation['visual_review_confirmed'] is True,'SOURCE_VISUAL_REVIEW_REQUIRED',status=422)
    require(callable(page_image_verify),'SOURCE_PAGE_IMAGE_REQUIRED',status=422)
    require(isinstance(operation['block_id'],str) and isinstance(operation['target_block_id'],str),'SOURCE_FOOTNOTE_TARGET_INVALID',status=422)
    by={b['id']:b for b in source['blocks']};block=by.get(operation['block_id']);target=by.get(operation['target_block_id'])
    require(block and block['kind'] in {'heading','paragraph','list_item','caption','table_cell'} and target and target['kind']=='footnote','SOURCE_FOOTNOTE_TARGET_INVALID',status=422)
    start,end=operation['start'],operation['end'];text=block['normalized_text']
    require(type(start) is int and type(end) is int and 0<=start<end<=len(text),'SOURCE_OFFSET_INVALID',status=422)
    marker=text[start:end]
    require(re.fullmatch(r'(?:[0-9]{1,3}|[*†‡])',marker) is not None and evidence['quote'].strip()==marker,'SOURCE_FOOTNOTE_MARKER_MISMATCH',status=422)
    require(re.match(r'^\s*'+re.escape(marker)+r'(?:\s|[.)])',target['normalized_text']) is not None,'SOURCE_FOOTNOTE_MARKER_MISMATCH',status=422)
    page=evidence['page']
    require(any(p['page']==page and overlap(evidence['bbox'],p['bbox'])>=.6 for p in block['provenance'])
        and any(p['page']==page for p in target['provenance']),'SOURCE_NATIVE_EVIDENCE_MISMATCH',status=422)
    require(isinstance(operation['page_image_sha256'],str) and re.fullmatch('[a-f0-9]{64}',operation['page_image_sha256']),'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
    require(page_image_verify(page,operation['page_image_sha256']),'SOURCE_PAGE_IMAGE_STALE')
    left,tail=_split_inline(block['source_inline'],start,source['protected_atoms'])
    middle,right=_split_inline(tail,end-start,source['protected_atoms'])
    require(flatten_inline(middle,source['protected_atoms'])==marker and all(n['type']=='text' or
        n['type']=='protected_ref' and source['protected_atoms'][n['ref']]['kind']=='number' for n in middle),'SOURCE_FOOTNOTE_MARKER_MISMATCH',status=422)
    original_raw=block['raw_text'];original_normalized=block['normalized_text']
    block['source_inline']=left+[{'type':'xref','target_block_id':target['id'],'label':marker}]+right
    require(flatten_inline(block['source_inline'],source['protected_atoms'])==original_normalized,'SOURCE_UNPROVEN_TEXT')
    return {'action':'annotate_footnote','block_id':block['id'],'target_block_id':target['id'],'start':start,'end':end,
        'marker':marker,'original_raw_hash':digest(original_raw),'original_normalized_hash':digest(original_normalized),
        'original_pdf_sha256':source['sha256'],'page_image_sha256':operation['page_image_sha256'],
        'native_marker_evidence':copy.deepcopy(evidence),'target_provenance':copy.deepcopy(target['provenance']),
        'visual_review_confirmed':True,'reason':reason}


def merge_continuation(source,operation,evidence,reason,page_image_verify):
    expected={'kind','block_ids','joiner','page_image_sha256','visual_review_confirmed'}
    require(set(operation)==expected and operation['visual_review_confirmed'] is True,'SOURCE_VISUAL_REVIEW_REQUIRED',status=422)
    require(callable(page_image_verify),'SOURCE_PAGE_IMAGE_REQUIRED',status=422)
    ids=operation['block_ids'];by={b['id']:b for b in source['blocks']};order=source['reading_order']
    require(isinstance(ids,list) and len(ids)==2 and all(isinstance(i,str) and i in order for i in ids) and ids[0]!=ids[1],
        'SOURCE_MERGE_INVALID',status=422)
    first,second=(by[i] for i in ids)
    require(order[order.index(ids[0]):order.index(ids[0])+2]==ids,'SOURCE_MERGE_NOT_ADJACENT',status=422)
    require(first['kind'] in {'paragraph','list_item'} and second['kind']=='paragraph'
        and first['owner_id'] is None and second['owner_id'] is None and first['parent_id']==second['parent_id']
        and first['language']==second['language'] and first['translatable']==second['translatable'],
        'SOURCE_MERGE_UNSUPPORTED',status=422)
    page=evidence['page'];loc=first['provenance'][-1]
    require(all(p['page']==page for b in (first,second) for p in b['provenance'])
        and overlap(evidence['bbox'],loc['bbox'])>=.6 and abs(evidence['bbox'][3]-loc['bbox'][3])<=3,
        'SOURCE_NATIVE_EVIDENCE_MISMATCH',status=422)
    joiner=operation['joiner']
    require(isinstance(joiner,str) and joiner in {'',' '},'SOURCE_CONTINUATION_UNPROVEN',status=422)
    left=copy.deepcopy(first['source_inline']);right=copy.deepcopy(second['source_inline'])
    if joiner=='':
        terminal=re.search(r'([A-Za-z]+)[\-\u00ad\x02]\s*$',evidence['quote'])
        ending=re.search(r'([A-Za-z]+)(-?)$',first['normalized_text'])
        require(terminal and ending and terminal[1]==ending[1] and re.match(r'[a-z]',second['normalized_text']),
            'SOURCE_CONTINUATION_UNPROVEN','Joining a split word requires the original native terminal hyphen and matching word fragments.',status=422)
        if ending[2]:
            left,removed=_split_inline(left,len(first['normalized_text'])-1,source['protected_atoms'])
            require(all(n['type']=='text' for n in removed),'SOURCE_PROTECTED_EDIT',status=422)
    require(isinstance(operation['page_image_sha256'],str) and re.fullmatch('[a-f0-9]{64}',operation['page_image_sha256']),
        'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
    require(page_image_verify(page,operation['page_image_sha256']),'SOURCE_PAGE_IMAGE_STALE')
    original=[copy.deepcopy(b) for b in (first,second)]
    first['raw_text']=first['raw_text']+'\n'+second['raw_text']
    first['source_inline']=left+([{'type':'text','text':joiner}] if joiner else [])+right
    first['normalized_text']=flatten_inline(first['source_inline'],source['protected_atoms'])
    first['normalization_edits']=[{'raw_start':0,'raw_end':len(first['raw_text']),'replacement':first['normalized_text'],
        'rule_id':'native-pdf-continuation-v1','reviewed':False,'evidence':reason}]
    first['provenance']=list({digest(p):p for b in original for p in b['provenance']}.values())
    first['warnings']=list(dict.fromkeys(first['warnings']+second['warnings']))
    source['blocks']=[b for b in source['blocks'] if b['id']!=second['id']]
    def retarget(nodes):
        for node in nodes:
            if node.get('target_block_id')==second['id']:node['target_block_id']=first['id']
            if 'children' in node:retarget(node['children'])
    for block in source['blocks']:retarget(block['source_inline'])
    _set_order(source,[i for i in order if i!=second['id']])
    return {'kind':'merged','old_block_ids':ids,'new_block_ids':[first['id']]}, {
        'action':'merge_continuation','block_ids':ids,'result_block_id':first['id'],'joiner':joiner,
        'original_raw_hashes':[digest(b['raw_text']) for b in original],
        'original_blocks':original,'original_pdf_sha256':source['sha256'],
        'page_image_sha256':operation['page_image_sha256'],'native_terminal_evidence':copy.deepcopy(evidence),
        'visual_review_confirmed':True,'reason':reason}


def merge_native_continuation(source,inspection,operation,evidence,reason,page_image_verify):
    """Rejoin one original word across a floating graphic, preserving every root."""
    from .native import verified_native_region
    expected={'kind','block_ids','rule','continuation_evidence','page_image_sha256s','visual_review_confirmed'}
    require(set(operation)==expected and operation['visual_review_confirmed'] is True,'SOURCE_VISUAL_REVIEW_REQUIRED',status=422)
    require(callable(page_image_verify),'SOURCE_PAGE_IMAGE_REQUIRED',status=422)
    ids=operation['block_ids'];by={b['id']:b for b in source['blocks']};order=source['reading_order']
    require(isinstance(ids,list) and len(ids)==2 and all(isinstance(i,str) and i in order for i in ids) and ids[0]!=ids[1],
        'SOURCE_MERGE_INVALID',status=422)
    first,second=(by[i] for i in ids);a,b=(order.index(i) for i in ids)
    require(a<b and all(by[i]['kind'] in {'figure','table','math'} for i in order[a+1:b]),'SOURCE_MERGE_INTERRUPTED_BY_TEXT',status=422)
    require(first['kind'] in {'paragraph','list_item'} and second['kind']=='paragraph' and first['owner_id'] is None and second['owner_id'] is None
        and first['parent_id']==second['parent_id'] and first['language']==second['language'] and first['translatable']==second['translatable'],
        'SOURCE_MERGE_UNSUPPORTED',status=422)
    rule=operation['rule'];require(isinstance(rule,str) and rule in {'remove_line_wrap','retain_line_hyphen'},'SOURCE_NORMALIZATION_RULE_INVALID',status=422)
    proofs=[evidence,operation['continuation_evidence']];regions=[];locs=[first['provenance'][-1],second['provenance'][0]]
    for proof,loc in zip(proofs,locs):
        _,region=verified_native_region(inspection,proof);regions.append(region)
        require(len(region.get('native_indices',[]))==len(region['text']) and bool(region['native_indices']),'SOURCE_NATIVE_ORDER_REQUIRED',status=422)
        require(proof['page']==loc['page'] and overlap(proof['bbox'],loc['bbox'])>=.6,'SOURCE_NATIVE_EVIDENCE_MISMATCH',status=422)
    require(abs(proofs[0]['bbox'][3]-locs[0]['bbox'][3])<=3 and abs(proofs[1]['bbox'][1]-locs[1]['bbox'][1])<=3,
        'SOURCE_NATIVE_ORDER_REQUIRED',status=422)
    page_delta=proofs[1]['page']-proofs[0]['page']
    require(page_delta in {0,1},'SOURCE_NATIVE_ORDER_REQUIRED',status=422)
    if page_delta==0:
        require(max(regions[0]['native_indices'])<min(regions[1]['native_indices']) and
            (proofs[1]['bbox'][1]>=proofs[0]['bbox'][3] or proofs[1]['bbox'][0]>=proofs[0]['bbox'][2]),'SOURCE_NATIVE_ORDER_REQUIRED',status=422)
    terminal=re.search(r'([A-Za-z]+(?:-[A-Za-z]+)*)[-\u00ad\x02]\s*$',proofs[0]['quote'])
    initial=re.match(r'\s*([A-Za-z]+)',proofs[1]['quote'])
    ending=re.search(r'([A-Za-z]+(?:-[A-Za-z]+)*)(-?)$',first['normalized_text'])
    beginning=re.match(r'([A-Za-z]+)',second['normalized_text'])
    require(terminal and initial and ending and beginning and terminal[1]==ending[1] and initial[1]==beginning[1]
        and beginning[1][0].islower(),'SOURCE_CONTINUATION_UNPROVEN',status=422)
    # Only the terminal/initial glyph occurrence is eligible. No free-form replacement or whitespace trimming.
    hashes=operation['page_image_sha256s'];pages={str(p['page']) for p in proofs}
    require(isinstance(hashes,dict) and set(hashes)==pages,'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
    for page,sha in hashes.items():
        require(isinstance(sha,str) and re.fullmatch('[a-f0-9]{64}',sha),'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
        require(page_image_verify(int(page),sha),'SOURCE_PAGE_IMAGE_STALE')
    left=copy.deepcopy(first['source_inline']);right=copy.deepcopy(second['source_inline'])
    left_prefix,left_word=_split_inline(left,len(first['normalized_text'])-len(ending[0]),source['protected_atoms'])
    right_word,right_suffix=_split_inline(right,len(beginning[0]),source['protected_atoms'])
    require(all(n['type']=='text' for n in left_word+right_word),'SOURCE_PROTECTED_EDIT',status=422)
    joined=terminal[1]+('-' if rule=='retain_line_hyphen' else '')+initial[1]
    original=[copy.deepcopy(first),copy.deepcopy(second)];intervening=list(order[a+1:b])
    first['raw_text']=first['raw_text']+'\n'+second['raw_text']
    first['source_inline']=left_prefix+[{'type':'text','text':joined}]+right_suffix
    first['normalized_text']=flatten_inline(first['source_inline'],source['protected_atoms'])
    first['normalization_edits']=[{'raw_start':0,'raw_end':len(first['raw_text']),'replacement':first['normalized_text'],
        'rule_id':'native-float-continuation-'+rule+'-v1','reviewed':False,'evidence':reason}]
    first['provenance']=list({digest(p):p for block in original for p in block['provenance']}.values())
    first['warnings']=list(dict.fromkeys(first['warnings']+second['warnings']))
    source['blocks']=[block for block in source['blocks'] if block['id']!=second['id']]
    def retarget(nodes):
        for node in nodes:
            if node.get('target_block_id')==second['id']:node['target_block_id']=first['id']
            if 'children' in node:retarget(node['children'])
    for block in source['blocks']:retarget(block['source_inline'])
    _set_order(source,[i for i in order if i!=second['id']])
    return {'kind':'merged','old_block_ids':ids,'new_block_ids':[first['id']]},{
        'action':'merge_native_continuation','block_ids':ids,'result_block_id':first['id'],'rule':rule,'joined_word':joined,
        'original_blocks':original,'original_raw_hashes':[digest(block['raw_text']) for block in original],
        'original_pdf_sha256':source['sha256'],'page_image_sha256s':copy.deepcopy(hashes),'native_evidence':copy.deepcopy(proofs),
        'native_regions':copy.deepcopy(regions),'intervening_root_ids':intervening,'original_reading_order':list(order),
        'visual_review_confirmed':True,'reason':reason}
