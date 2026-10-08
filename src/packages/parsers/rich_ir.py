"""Lower recovered physical records into versioned semantic source blocks."""
from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher

from .semantic import node, visible


def limit_semantic_items(items, inspection):
    """Reserve capacity for native recovery and retain oversized regions as images.

    Limits apply to emitted semantic leaves/atoms, rather than their temporary
    parent projections. Exact responses stay in independently bounded evidence.
    """
    from .inline import tokens
    kept=[];used=[0,0,0]
    def cost(tree):
        result=[1,0,0]
        for run in tree['runs']:
            result[1]+=len(run['text'])
            result[2]+=1 if run['type'] in {'math','code','control'} else 1+2*sum(1 for _ in tokens(run['text']))
        for child in tree['children']:
            result=[a+b for a,b in zip(result,cost(child))]
        for cell in (tree.get('data') or {}).get('table_cells',[]):
            extra=cost(cell['_semantic'])
            if cell['_semantic']['kind'] not in {'paragraph','table_cell','group'}:extra[0]+=1
            result=[a+b for a,b in zip(result,extra)]
        return result
    for item in items:
        if len(kept)>=8000:
            inspection.setdefault('warnings',[]).append({'code':'SEMANTIC_CAPACITY','reason':'Remaining physical regions are retained in the original PDF and exact page responses'})
            break
        tree=item.get('_semantic')
        budget=cost(tree) if tree else [1,len(item.get('orig',item.get('text','')) or ''),0]
        if any(a+b>limit for a,b,limit in zip(used,budget,[8000,750000,100000])):
            item=deepcopy(item)
            item['_semantic']=node('figure',attrs={'model_role':(tree or {}).get('attrs',{}).get('model_role','unknown'),
                'output_id':item.get('self_ref',''), 'annotations':[{'kind':'decoder_limit','value':'Semantic capacity exceeded; original page region and exact response are retained','output_path':(tree or {}).get('path','/native')}]},path=(tree or {}).get('path','/native'))
            item.update(label='picture',orig='',text='');item.pop('data',None)
            item['_semantic_limited']=True
            budget=[1,0,0]
            inspection.setdefault('warnings',[]).append({'code':'SEMANTIC_CAPACITY','reference':item.get('self_ref'),'reason':'This region is retained as original imagery without an invented partial structure'})
        used=[a+b for a,b in zip(used,budget)]
        kept.append(item)
    return kept


def merge_semantics(first, second, separator=' '):
    """Carry source runs across deterministic physical-region joins."""
    a,b=first.get('_semantic'),second.get('_semantic')
    if not a and not b:return
    def fallback(item):return node('paragraph',[{'type':'text','text':item.get('orig',item.get('text','')),'path':'/native'}],path='/native')
    a,b=deepcopy(a or fallback(first)),deepcopy(b or fallback(second))
    if second.get('_model_provenance'):
        first.setdefault('_model_provenance',[]).extend(deepcopy(second['_model_provenance']))
    same_prose = a['kind']==b['kind'] and a['kind'] in {'paragraph','reference'}
    list_continuation = a['kind']=='list_item' and b['kind']=='paragraph'
    if (same_prose or list_continuation) and not a['children'] and not b['children']:
        a['runs'] += ([{'type':'text','text':separator,'path':a['path']}] if separator else []) + b['runs']
        a['text']=visible(a['runs']);first['_semantic']=a
    else:first['_semantic']=node('group',children=[a,b],attrs={'group_type':'layout'},path=a['path'])


def reconcile_runs(runs, updated):
    """Keep marks on uniquely attributable repaired spans; never rewrite atoms."""
    before=visible(runs)
    if before==updated:return deepcopy(runs),False
    if len(before)>8192 or len(updated)>8192:return deepcopy(runs),True
    ranges=[];pos=0
    for run in runs:ranges.append((pos,pos+len(run['text']),run));pos+=len(run['text'])
    output=[]
    for kind,i,j,x,y in SequenceMatcher(a=before,b=updated,autojunk=False).get_opcodes():
        owners=[r for start,end,r in ranges if start<j and end>i]
        if kind=='equal':
            for start,end,r in ranges:
                l,h=max(i,start),min(j,end)
                if l<h:output.append(deepcopy(r)|{'text':before[l:h]})
        elif kind=='delete':
            if any(r['type'] in {'math','code','control'} for r in owners):return deepcopy(runs),True
        else:
            if not owners:
                owners=[r for start,end,r in ranges if start<=i<=end]
            signatures={str({k:v for k,v in r.items() if k not in {'text','path'}}) for r in owners}
            if len(signatures)>1 or any(r['type'] in {'math','code','control'} for r in owners):return deepcopy(runs),True
            output.append((deepcopy(owners[0]) if owners else {'type':'text','path':'/native'})|{'text':updated[x:y]})
    return output,False


def reconcile_tree(tree, updated):
    tree=deepcopy(tree)
    if tree['text']==updated:return tree,False
    if not tree['children']:
        tree['runs'],ambiguous=reconcile_runs(tree['runs'],updated);tree['text']=visible(tree['runs']);return tree,ambiguous
    # Match one whole semantic leaf at a time; multi-leaf changes require an
    # explicit ambiguity warning, rather than stale marks or invented boundaries.
    old=tree['text']
    if len(old)>8192 or len(updated)>8192:return tree,True
    offset=0;changes=SequenceMatcher(a=old,b=updated,autojunk=False).get_opcodes()
    for child in tree['children']:
        start,end=offset,offset+len(child['text']);offset=end+1
        applicable=[op for op in changes if op[0]!='equal' and (op[1]<end and op[2]>start or op[1]==op[2] and start<=op[1]<end)]
        if any(i<start or j>end for _,i,j,_,_ in applicable):return tree,True
        revised=child['text']
        for _,i,j,x,y in reversed(applicable):revised=revised[:i-start]+updated[x:y]+revised[j-start:]
        new,ambiguous=reconcile_tree(child,revised)
        if ambiguous:return tree,True
        child.clear();child.update(new)
    tree['text']='\n'.join(c['text'] for c in tree['children'])
    if tree['text']!=updated:return tree,True
    return tree,False


def reconcile_saved_inline(nodes, atoms, updated):
    from packages.ir import flatten_inline
    runs=[]
    for n in nodes:
        kind='code' if n['type']=='protected_ref' else n['type']
        runs.append({'type':kind,'text':flatten_inline([n],atoms),'_ir':deepcopy(n)})
    restored,ambiguous=reconcile_runs(runs,updated)
    if ambiguous:return deepcopy(nodes),True
    result=[]
    for run in restored:
        n=deepcopy(run.get('_ir',{'type':'text','text':run['text']}))
        if n['type']=='xref':n['label']=run['text']
        elif n['type']!='protected_ref':n['text']=run['text']
        result.append(n)
    return result,False


def slice_semantics(tree,start,end):
    """Slice only proven code-point intervals; protected runs remain indivisible."""
    if not 0<=start<=end<=len(tree['text']):return None
    result=deepcopy(tree)
    if tree['children']:
        result['children']=[];offset=0
        for child in tree['children']:
            length=len(child['text']);a,b=max(start-offset,0),min(end-offset,length)
            if a<b:
                part=slice_semantics(child,a,b)
                if part is None:return None
                result['children'].append(part)
            offset+=length+1
        result['text']='\n'.join(c['text'] for c in result['children'])
    elif tree.get('data'):return None
    else:
        result['runs']=[];offset=0
        for run in tree['runs']:
            length=len(run['text']);a,b=max(start-offset,0),min(end-offset,length)
            if a<b:
                if run['type'] in {'math','code','control'} and (a!=0 or b!=length):return None
                result['runs'].append(deepcopy(run)|{'text':run['text'][a:b]})
            offset+=length
        result['text']=visible(result['runs'])
    return result if result['text']==tree['text'][start:end] else None


def carry_reference_semantics(item,replacement,start=None,end=None):
    """Associate native bibliography evidence with unique emitted semantic spans."""
    tree=item.get('_semantic')
    if not tree:return
    text=replacement['orig']
    candidates=[]
    if start is not None:
        reconciled,ambiguous=reconcile_tree(tree,item['orig'])
        candidate=None if ambiguous else slice_semantics(reconciled,start,end)
        if candidate:candidates.append(candidate)
    else:
        trees=[c['_semantic'] for c in (tree.get('data') or {}).get('table_cells',[])] or [tree]
        target=''.join(c for c in text if c.isalnum())
        for cell in trees:
            positions=[i for i,c in enumerate(cell['text']) if c.isalnum()]
            core=''.join(cell['text'][i] for i in positions)
            at=core.find(target) if target else -1
            if at>=0 and core.find(target,at+1)<0:
                candidate=slice_semantics(cell,positions[at],positions[at+len(target)-1]+1)
                if candidate:candidates.append(candidate)
    if len(candidates)==1:
        candidate,ambiguous=reconcile_tree(candidates[0],text)
        if not ambiguous:
            def reference(n):
                if n['children']:
                    for child in n['children']:reference(child)
                else:n['kind']='reference'
            reference(candidate)
            replacement['_semantic']=candidate
        else:replacement['_semantic_recovery_ambiguous']=True
    else:replacement['_semantic_recovery_ambiguous']=True
    if replacement.get('_semantic_recovery_ambiguous'):
        replacement['_semantic']=node('reference',[{'type':'text','text':text,'path':'/native'}],attrs={'annotations':[{'kind':'ambiguous_recovery','value':'Native reference cannot be uniquely aligned with model formatting; exact response remains available','output_path':tree['path']}]},path='/native')
    replacement['_model_provenance']=deepcopy(item.get('_model_provenance',[]))
    replacement['_semantic_version']='4.0'


def carry_retained_spans(item,original_text,spans):
    tree=item.get('_semantic')
    if not tree:return
    reconciled,ambiguous=reconcile_tree(tree,original_text)
    fragments=[] if ambiguous else [slice_semantics(reconciled,a,b) for a,b in spans]
    if not fragments or any(part is None for part in fragments):
        item['_semantic']=node('paragraph',[{'type':'text','text':item['orig'],'path':'/native'}],path='/native')
        item['_semantic_recovery_ambiguous']=True
    else:
        first={'_semantic':fragments[0]}
        for part in fragments[1:]:merge_semantics(first,{'_semantic':part})
        item['_semantic']=first['_semantic']


def resolve_scoped_relations(source):
    """Use a unique typed role and local page geometry; leave ambiguity explicit."""
    blocks=source['blocks']
    for block in blocks:
        if block['owner_id'] is not None or len(block['provenance'])!=1:continue
        key='caption_type' if block['kind']=='caption' else 'note_scope' if block['kind']=='footnote' else None
        scope=block['attributes'].get(key) if key else None
        expected={'image':'figure','figure':'figure','table':'table','formula':'math','code':'code'}.get(scope)
        if not expected:continue
        loc=block['provenance'][0];x0,y0,x1,y1=loc['bbox'];candidates=[]
        for owner in blocks:
            if owner['kind']!=expected or len(owner['provenance'])!=1:continue
            region=owner['provenance'][0];a,b,c,d=region['bbox']
            horizontal=max(0,min(x1,c)-max(x0,a))/max(1,min(x1-x0,c-a))
            distance=b-y1 if key=='caption_type' and scope=='table' and y1<=b else y0-d
            if region['page']==loc['page'] and horizontal>=.75 and -.5<=distance<=60:candidates.append(owner)
        if len(candidates)==1:
            owner=candidates[0];block['owner_id']=owner['id'];source['reading_order'].remove(block['id'])
            owner['attributes'].setdefault('caption_block_ids' if key=='caption_type' else 'note_block_ids',[]).append(block['id'])
        else:block['warnings'].append('说明/注释具有明确类型，但没有唯一同页区域关联；保留独立内容，未猜测归属。')


def apply_semantics(source, items, item_blocks, make, crop, evidence=None):
    from .source_adapter import _source_nodes
    source['schema_version']='4.0'
    if evidence is not None:source['parser']['evidence']=evidence
    atoms=source['protected_atoms'];blocks=source['blocks'];crossrefs=[]
    def inlines(runs,bid):
        result=[]
        for index,run in enumerate(runs):
            attrs={}
            if run.get('marks'):attrs['marks']=run['marks']
            if run.get('path'):attrs['output_path']=run['path'][:512]
            if run['type'] in {'math','code','control'}:
                ref=bid+'-s'+str(index)
                atoms[ref]={'kind':run['type'],'value':run['text']}
                if run['type']=='control':atoms[ref].update(state=run['state'],control_type=run['control_type'])
                if run.get('options'):atoms[ref]['options']=deepcopy(run['options'])
                result.append({'type':'protected_ref','ref':ref}|attrs)
            elif run['type']=='link':result.append({'type':'link','text':run['text'],'href':run['href']}|attrs)
            elif run['type']=='xref':
                result.append({'type':'text','text':run['text']}|attrs)
                crossrefs.append((result[-1],run['target_key'],bid))
            else:
                for inline in _source_nodes(run['text'],bid+'-r'+str(index),atoms,'paragraph'):
                    result.append(inline|attrs)
        return result
    def fill(block,semantic, inherited=False,region_id=None,model_provenance=None):
        old_kind=block['kind'];old_attrs=block['attributes'];kind=semantic['kind']
        attrs=deepcopy(semantic['attrs'])
        if len(attrs.get('annotations',[]))>100:
            attrs['annotations']=attrs['annotations'][:100]
            block['warnings'].append('辅助注释超过显示容量；完整内容保留在响应证据中。')
        region_id=region_id or attrs.get('output_id') or block['id']
        attrs.setdefault('output_id',region_id)
        for field in ['asset_id','comparison_asset_id','comparison_scope','recognition','equation_number']:
            if field in old_attrs:attrs.setdefault(field,old_attrs[field])
        block['kind']=kind;block['attributes']=attrs
        block['raw_text']=block['normalized_text']=visible(semantic['runs']);block['normalization_edits']=[]
        block['source_inline']=inlines(semantic['runs'],block['id'])
        block['translatable']=kind in {'heading','paragraph','list_item','caption','table_cell','footnote'} and bool(block['normalized_text'].strip())
        for loc in block['provenance']:
            from .fidelity import box
            emitted=any(p['page_no']==loc['page'] and box(p,source_pages)==loc['bbox'] for p in model_provenance or [])
            loc.update(geometry='inherited' if inherited else 'emitted' if emitted else 'native',output_path=semantic['path'][:512],region_id=region_id)
        if kind=='heading':attrs.setdefault('level',2)
        if kind=='list_item':attrs.setdefault('list_ordered',False)
        if kind in {'math','code'}:
            attrs['representation']='latex' if kind=='math' else 'plain'
            if not attrs.get('asset_id') and len(block['provenance'])==1:attrs['asset_id']=crop(block['provenance'],block['id'])
            block['warnings'].append('模型识别的公式或代码保留原 PDF 区域供核对。')
        if kind in {'figure','table'}:attrs.setdefault('caption_block_ids',[])
        if kind=='figure':
            block['raw_text']=block['normalized_text']='';block['source_inline']=[]
            if not attrs.get('asset_id'):attrs['asset_id']=crop(block['provenance'],block['id'])
        if kind=='table':
            data=semantic.get('data'); old_cells=old_attrs.get('cells',[]) if old_kind=='table' else []
            if data:
                attrs.update(representation='structured',rows=data['num_rows'],columns=data['num_cols'],cells=[])
                headers={}; pending=[]
                for index,cell in enumerate(data['table_cells']):
                    existing=next((b for b in blocks if index<len(old_cells) and b['id']==old_cells[index]['content_block_id']),None)
                    child=existing or make('table_cell',cell['text'],deepcopy(block['provenance']),owner=block['id'])
                    child_tree=deepcopy(cell['_semantic'])
                    child_tree,ambiguous=reconcile_tree(child_tree,child['normalized_text'] if existing else cell['text'])
                    if ambiguous:child['warnings'].append('单元格 PDF 修复无法明确关联语义范围；保留识别语义及独立 PDF 证据。')
                    if child_tree['kind']=='group':child_tree['attrs']['group_type']='cell'
                    # The grid cell is the owner of any compound content.
                    if child_tree['children'] or child_tree['kind'] not in {'paragraph','table_cell'}:
                        tree=node('table_cell',children=child_tree['children'] if child_tree['kind']=='group' else [child_tree],path=child_tree['path'])
                    else:tree=deepcopy(child_tree);tree['kind']='table_cell'
                    fill(child,tree,True,region_id,model_provenance)
                    entry={k:cell[k] for k in ['row_span','col_span']}
                    entry.update(row=cell['start_row_offset_idx'],column=cell['start_col_offset_idx'],column_span=entry.pop('col_span'),content_block_id=child['id'])
                    entry.update(cell['_cell_attributes']);attrs['cells'].append(entry)
                    if cell['_id']:headers.setdefault(cell['_id'],[]).append(child['id'])
                    pending.append((entry,cell['_headers']))
                for entry,keys in pending:
                    resolved=[headers[k][0] for k in keys if len(headers.get(k,[]))==1 and any(c['content_block_id']==headers[k][0] and c.get('role')=='header' for c in attrs['cells'])]
                    if resolved:entry['header_block_ids']=list(dict.fromkeys(resolved))
                    if len(resolved)!=len(keys):block['warnings'].append('表格 headers 引用未完整匹配；未猜测标题关联。')
            else:attrs.update(representation='image',asset_id=attrs.get('asset_id') or crop(block['provenance'],block['id']));block['warnings'].append('表格结构未恢复；原图和响应证据完整保留。')
            block['raw_text']=block['normalized_text']='';block['source_inline']=[];block['translatable']=False
        if kind=='group':attrs.setdefault('group_type','layout');attrs['children_block_ids']=[]
        if semantic['children']:
            if kind in {'list_item','table_cell'}:attrs['children_block_ids']=[]
            for tree in semantic['children']:
                child=make(tree['kind'],'',deepcopy(block['provenance']),owner=block['id'])
                fill(child,tree,True,region_id,model_provenance)
                if child['kind']=='caption' and kind in {'figure','table','math','code'}:attrs.setdefault('caption_block_ids',[]).append(child['id'])
                elif child['kind']=='footnote' and kind in {'figure','table','math'}:attrs.setdefault('note_block_ids',[]).append(child['id'])
                else:attrs.setdefault('children_block_ids',[]).append(child['id'])
        if kind in {'group','list_item','table_cell'} and semantic['children']:
            block['raw_text']=block['normalized_text']='';block['source_inline']=[];block['translatable']=False
        if old_attrs.get('caption_block_ids'):
            attrs.setdefault('caption_block_ids',[]).extend(cid for cid in old_attrs['caption_block_ids'] if cid not in attrs.get('caption_block_ids',[]))
        if attrs.get('asset_id'):
            attrs['asset_scope']='page' if attrs['asset_id'].startswith('page-image-') else 'region'
            if attrs['asset_scope']=='page':block['warnings'].append('区域裁图达到数量限制；保留整页原图及原 PDF 区域定位。')
    # All physical locators carry their original PDF page dimensions.
    page_sizes={loc['page']:loc['page_size'] for b in blocks for loc in b['provenance']}
    source_pages=[{'page_size':page_sizes.get(page,[1,1])} for page in range(1,max(page_sizes,default=0)+1)]
    for item in items:
        tree=item.get('_semantic');block=item_blocks.get(item.get('self_ref'))
        if not tree or not block or item.get('_nb_navigation_title'):continue
        if tree['kind']=='paragraph' and not tree['children'] and block['kind'] in {'reference','caption','list_item'}:
            tree=deepcopy(tree);tree['kind']=block['kind']
            for key in ['list_ordered','list_index']:
                if key in block['attributes']:tree['attrs'][key]=block['attributes'][key]
        # A native caption may turn a printed code listing into an original figure.
        if block['kind']=='figure' and tree['kind']=='code':
            tree=node('figure',attrs=deepcopy(tree['attrs'])|{'annotations':[{'kind':'code_transcription','value':tree['text'][:16000],'output_path':tree['path']}]},path=tree['path'])
        tree,ambiguous=reconcile_tree(tree,block['normalized_text']) if tree['kind'] not in {'figure','table'} else (deepcopy(tree),False)
        if ambiguous:block['warnings'].append('PDF 修复无法明确关联语义范围；保留模型语义和独立 PDF 修复证据。')
        fill(block,tree,region_id=item.get('self_ref'),model_provenance=item.get('_model_provenance'))
    keys={}
    for b in blocks:
        if b['attributes'].get('semantic_id'):keys.setdefault(b['attributes']['semantic_id'],[]).append(b['id'])
    by={key:ids[0] for key,ids in keys.items() if len(ids)==1}
    for inline,key,bid in crossrefs:
        if key in by:
            label=inline.pop('text');inline.update(type='xref',label=label,target_block_id=by[key])
        else:
            next(b for b in blocks if b['id']==bid)['warnings'].append('模型内部链接没有明确目标，保留可见标签；未猜测交叉引用。')
    # Native/recovered blocks have no emitted model geometry.
    for block in blocks:
        for loc in block['provenance']:loc.setdefault('geometry','native')
    resolve_scoped_relations(source)
    return source
