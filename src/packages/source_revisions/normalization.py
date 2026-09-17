"""Small explicit mechanical spans, derived solely from stored native evidence."""
import copy
import re
import unicodedata

from packages.domain.errors import require
from packages.ir import digest,flatten_inline
from packages.parsers.pdf_docling import overlap
from .corrections import _split_inline


def _core(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text) if c.isalnum())


def _bind_occurrence(block,inspection,regions,proofs,first_offset,last_offset,start,end):
    """Repeated text needs the same native glyph occurrence, not only its value."""
    chars=[];seen=set()
    for loc in block['provenance']:
        native=[r for page in inspection['pages'] if page['page']==loc['page'] for r in page['text_regions'] if overlap(r['bbox'],loc['bbox'])>=.6]
        if any(len(r.get('native_indices',[]))!=len(r['text']) for r in native):continue
        values={index:c for r in native for index,c in zip(r['native_indices'],r['text'])}
        for index in sorted(values):
            key=(loc['page'],index)
            if key not in seen:chars.append((key,values[index]));seen.add(key)
    positions={};native_text=''
    for key,c in chars:
        positions[key]=(len(native_text),len(native_text)+len(_core(c)));native_text+=_core(c)
    source_text=_core(block['normalized_text']);selected=_core(block['normalized_text'][start:end])
    require(bool(selected),'SOURCE_NORMALIZATION_UNPROVEN',status=422)
    source_interval=(len(_core(block['normalized_text'][:start])),len(_core(block['normalized_text'][:end])))
    first=(proofs[0]['page'],regions[0]['native_indices'][first_offset]);last=(proofs[-1]['page'],regions[-1]['native_indices'][last_offset-1])
    # A source paragraph split around an image retains its original larger PDF locator.
    # Its complete meaningful sequence must have one exact occurrence inside that native parent.
    source_offsets=[m.start() for m in re.finditer('(?='+re.escape(source_text)+')',native_text)]
    if len(source_offsets)==1 and first in positions and last in positions:
        native_interval=(positions[first][0],positions[last][1])
        offset=source_offsets[0]
        require(native_interval==(source_interval[0]+offset,source_interval[1]+offset),'SOURCE_NATIVE_OCCURRENCE_MISMATCH',status=422)
        return {'basis':'aligned_original_native_glyph_indices','source_core_interval':list(source_interval),'native_core_interval':list(native_interval),
            'complete_source_native_core_offset':offset}
    def occurrences(text):
        return sum(1 for _ in re.finditer('(?='+re.escape(selected)+')',text))
    require(occurrences(source_text)==1 and occurrences(native_text)<=1,'SOURCE_NATIVE_OCCURRENCE_MISMATCH',
        'Repeated source text requires a complete original native glyph alignment to the selected occurrence.',status=422)
    return {'basis':'unique_source_literal_and_native_region','source_core_interval':list(source_interval)}


def normalize_native_span(source,inspection,operation,evidence,reason,page_image_verify):
    from .native import verified_native_region
    rule=operation.get('rule')
    require(isinstance(rule,str) and rule in {'restore_native_spacing','remove_line_wrap','retain_line_hyphen'},'SOURCE_NORMALIZATION_RULE_INVALID',status=422)
    expected={'kind','block_id','start','end','rule','page_image_sha256s','visual_review_confirmed'}
    if rule!='restore_native_spacing':expected.add('continuation_evidence')
    require(set(operation)==expected and operation['visual_review_confirmed'] is True,'SOURCE_VISUAL_REVIEW_REQUIRED',status=422)
    require(callable(page_image_verify),'SOURCE_PAGE_IMAGE_REQUIRED',status=422)
    block=next((b for b in source['blocks'] if b['id']==operation['block_id']),None)
    require(block and block['kind'] in {'paragraph','list_item','caption','reference','heading','footnote'},'SOURCE_NORMALIZATION_UNSUPPORTED',status=422)
    start,end=operation['start'],operation['end'];text=block['normalized_text']
    require(type(start) is int and type(end) is int and 0<=start<end<=len(text),'SOURCE_OFFSET_INVALID',status=422)
    selected=text[start:end];proofs=[evidence]
    if rule!='restore_native_spacing':proofs.append(operation['continuation_evidence'])
    regions=[];loc_indices=[]
    for proof in proofs:
        _,region=verified_native_region(inspection,proof)
        require(len(region.get('native_indices',[]))==len(region['text']) and bool(region['native_indices']),
            'SOURCE_NATIVE_ORDER_REQUIRED',status=422)
        indices=[i for i,loc in enumerate(block['provenance']) if loc['page']==proof['page'] and overlap(region['bbox'],loc['bbox'])>=.6]
        require(bool(indices),'SOURCE_NATIVE_EVIDENCE_MISMATCH',status=422)
        loc_indices.append(indices[0]);regions.append(region)
    if rule=='restore_native_spacing':
        require(selected.replace(' ','').isalpha(),'SOURCE_NORMALIZATION_UNPROVEN',status=422)
        indices=[i for i,c in enumerate(evidence['quote']) if not c.isspace()]
        compact=''.join(evidence['quote'][i] for i in indices);needle=''.join(selected.split())
        matches=[m.start() for m in re.finditer('(?='+re.escape(needle)+')',compact)]
        require(len(matches)==1,'SOURCE_NORMALIZATION_UNPROVEN',status=422)
        at=matches[0];replacement=' '.join(evidence['quote'][indices[at]:indices[at+len(needle)-1]+1].split())
        require(replacement.replace(' ','')==needle and replacement!=selected,'SOURCE_NORMALIZATION_UNPROVEN',status=422)
        first_offset,last_offset=indices[at],indices[at+len(needle)-1]+1
    else:
        first=re.search(r'([A-Za-z]+(?:-[A-Za-z]+)*)[-\u00ad\x02]\s*$',proofs[0]['quote'])
        second=re.match(r'\s*([A-Za-z]+)',proofs[1]['quote'])
        require(first and second,'SOURCE_NORMALIZATION_UNPROVEN',status=422)
        after=second[1];compact_selected=re.sub(r'\s+','',selected)
        suffix_starts=[0]+[m.end() for m in re.finditer('-',first[1])]
        candidates=[(offset,first[1][offset:]) for offset in suffix_starts
            if compact_selected in {first[1][offset:]+after,first[1][offset:]+'-'+after}]
        require(len(candidates)==1,'SOURCE_NORMALIZATION_UNPROVEN',status=422)
        native_suffix_offset,before=candidates[0]
        i,j=loc_indices;a,b=proofs[0]['bbox'],proofs[1]['bbox']
        if i==j:
            require(proofs[0]['page']==proofs[1]['page'] and 0<=b[1]-a[3]<=30
                and max(regions[0]['native_indices'])<min(regions[1]['native_indices']),'SOURCE_NATIVE_ORDER_REQUIRED',status=422)
        else:
            require(j==i+1 and abs(a[3]-block['provenance'][i]['bbox'][3])<=3
                and abs(b[1]-block['provenance'][j]['bbox'][1])<=3,'SOURCE_NATIVE_ORDER_REQUIRED',status=422)
        replacement=before+('-' if rule=='retain_line_hyphen' else '')+after
        require(replacement!=selected,'SOURCE_NORMALIZATION_UNPROVEN',status=422)
        first_offset,last_offset=first.start(1)+native_suffix_offset,second.end(1)
    occurrence=_bind_occurrence(block,inspection,regions,proofs,first_offset,last_offset,start,end)
    hashes=operation['page_image_sha256s'];pages={str(p['page']) for p in proofs}
    require(isinstance(hashes,dict) and pages<=set(hashes)<={str(loc['page']) for loc in block['provenance']},'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
    for page in hashes:
        sha=hashes[page]
        require(isinstance(sha,str) and re.fullmatch('[a-f0-9]{64}',sha),'SOURCE_PAGE_IMAGE_HASH_REQUIRED',status=422)
        require(page_image_verify(int(page),sha),'SOURCE_PAGE_IMAGE_STALE')
    left,tail=_split_inline(block['source_inline'],start,source['protected_atoms']);middle,right=_split_inline(tail,end-start,source['protected_atoms'])
    require(all(n['type']=='text' for n in middle),'SOURCE_PROTECTED_EDIT',status=422)
    old_raw=block['raw_text'];old_edits=copy.deepcopy(block['normalization_edits'])
    block['source_inline']=left+[{'type':'text','text':replacement}]+right
    block['normalized_text']=text[:start]+replacement+text[end:]
    block['normalization_edits']=[{'raw_start':0,'raw_end':len(old_raw),'replacement':block['normalized_text'],
        'rule_id':'native-span-'+rule+'-v1','reviewed':False,'evidence':reason}]
    require(flatten_inline(block['source_inline'],source['protected_atoms'])==block['normalized_text'],'SOURCE_UNPROVEN_TEXT')
    return {'action':'normalize_native_span','block_id':block['id'],'rule':rule,'start':start,'end':end,
        'original_span':selected,'replacement':replacement,'original_raw_hash':digest(old_raw),'original_normalized_hash':digest(text),
        'prior_normalization_edits':old_edits,'native_evidence':copy.deepcopy(proofs),'native_regions':copy.deepcopy(regions),
        'occurrence_binding':occurrence,
        'page_image_sha256s':copy.deepcopy(hashes),'original_pdf_sha256':source['sha256'],'visual_review_confirmed':True,'reason':reason}
