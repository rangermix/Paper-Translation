"""Model-specific full-page contracts over the common bounded semantic decoder."""
from __future__ import annotations

import json
import math
import re
from collections import Counter

from packages.ir import strict_loads
from .inspect import PDFError
from .semantic import HTMLSemantics, html_semantics, markdown_semantics, node

LABELS = {
    'text':'text','paragraph':'text','title':'title','sectionheader':'section_header','section-header':'section_header',
    'header':'page_header','footer':'page_footer','pageheader':'page_header','page-header':'page_header',
    'pagefooter':'page_footer','page-footer':'page_footer','caption':'caption','figure_caption':'caption',
    'table_caption':'caption','formula_caption':'caption','code_caption':'caption','image_caption':'caption',
    'footnote':'footnote','page_footnote':'footnote','figure_footnote':'footnote','table_footnote':'footnote','image_footnote':'footnote',
    'table':'table','equation':'formula','equation-block':'formula','formula':'formula','code':'code','code-block':'code','algorithm':'code',
    'image':'picture','picture':'picture','figure':'picture','diagram':'picture','chemical-block':'picture',
    'bibliography':'reference','ref_text':'reference','reference':'reference','page_number':'page_footer',
    'list-group':'text','form':'text','table-of-contents':'text','complex-block':'text',
}


def strip_fences(value):
    if not isinstance(value,str) or len(value)>1_000_000:raise PDFError('PARSER_OUTPUT_INVALID')
    value=value.strip()
    if value.startswith('```'):
        value=re.sub(r'^```[^\n]*\n','',value);value=re.sub(r'\n```\s*$','',value)
    return value


def bbox(value,page,scale=1000):
    if isinstance(value,str):value=[float(x) for x in value.replace(',',' ').split()]
    if (not isinstance(value,(list,tuple)) or len(value)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in value)
        or not 0<=value[0]<value[2]<=scale or not 0<=value[1]<value[3]<=scale):raise PDFError('PARSER_OUTPUT_INVALID')
    width,height=page['page_size']
    return [value[0]/scale*width,value[1]/scale*height,value[2]/scale*width,value[3]/scale*height]


def item(label,text,bounds,page,index,data=None):
    value={'self_ref':f'vlm-{page["page"]}-{index}','label':label,'text':text,'orig':text,
           'prov':[{'page_no':page['page'],'bbox':dict(zip(('l','t','r','b'),bounds),coord_origin='TOPLEFT')}]}
    if data is not None:value['data']=data
    return value


def diagnostic(diagnostics,code,path,reason):
    if len(diagnostics)<100:diagnostics.append({'code':code,'output_path':path,'reason':str(reason)[:500]})


def repetition_diagnostic(items,diagnostics):
    # A warning preserves legitimate repeated text too; it never removes source
    # or blocks translation/publication. Bound fragment scanning independently.
    regions=Counter(i['text'] for i in items if len(i['text'])>=20)
    repeated=any(count>=8 for count in regions.values())
    for item in items:
        if repeated:break
        if item['label'] in {'formula','code','table','picture'}:continue
        fragments=Counter(part.strip() for part in re.split(r'[\n.!?]+',item['text'])[:10000] if len(part.strip())>=20)
        repeated=any(count>=8 for count in fragments.values())
    if repeated:diagnostic(diagnostics,'REPETITIVE_OUTPUT','/','Repeated output may indicate an inference loop; source remains available with original-page evidence')


def physical(semantic,role,bounds,page,index):
    if semantic['kind'] in {'math','code'} and not semantic['text'].strip():
        semantic=node('figure',children=semantic['children'],attrs=semantic['attrs']|{'annotations':semantic['attrs'].get('annotations',[])+[
            {'kind':'empty_literal','value':'Empty math/code output; original region retained','output_path':semantic['path']}]},path=semantic['path'])
    label='picture' if semantic['kind']=='figure' else LABELS.get(role,'text')
    value=item(label, '' if semantic['kind']=='figure' else semantic['text'],bounds,page,index,semantic.get('data'))
    value['_semantic']=semantic
    value['_model_provenance']=[dict(p,bbox=dict(p['bbox'])) for p in value['prov']]
    semantic['attrs']['output_id']=value['self_ref']
    if semantic['kind']=='heading':value['level']=semantic['attrs'].get('level',2);value['_explicit_level']=True
    value.setdefault('captions',[])
    return value


def html_items(raw,page,diagnostics=None):
    diagnostics=diagnostics if diagnostics is not None else []
    value=strip_fences(raw);parser=HTMLSemantics(value,diagnostics)
    outer=parser.tree.xpath('.//div[@data-bbox][@data-label]')
    outer=[n for n in outer if not any(p.get('data-bbox') and p.get('data-label') for p in n.iterancestors())]
    if len(outer)>1000:diagnostic(diagnostics,'LAYOUT_CAPACITY','/','Only the first 1000 physical regions are decoded; the full response remains in evidence')
    result=[];blank=False
    for index,n in enumerate(outer[:1000]):
        role=n.get('data-label').lower();path=parser.path(n)
        if len(role)>100:diagnostic(diagnostics,'MODEL_ROLE_LIMIT',path,'Role exceeds display capacity; its full value remains in the response');role=role[:100]
        if role in {'blank-page','blankpage'}:blank=True;continue
        try:
            bounds=bbox(n.get('data-bbox'),page)
            if role not in LABELS:diagnostic(diagnostics,'UNKNOWN_MODEL_ROLE',path,role)
            try:semantic=html_semantics(parser,n,role)
            except ValueError as exc:
                if role!='table':raise
                diagnostic(diagnostics,'TABLE_STRUCTURE_UNSUPPORTED',path,exc)
                semantic=node('table',attrs={'model_role':role,'annotations':[{'kind':'unsupported_table','value':n.text_content()[:16000],'output_path':path}]},path=path)
            if semantic['kind'] in {'math','code'} and not semantic['text'].strip():diagnostic(diagnostics,'EMPTY_LITERAL',path,'Empty math/code output; original region retained')
            result.append(physical(semantic,role,bounds,page,index))
        except (ValueError,TypeError,KeyError,PDFError) as exc:
            diagnostic(diagnostics,'LAYOUT_ELEMENT_INVALID',path,exc)
    if not result and value and not blank:raise PDFError('PARSER_OUTPUT_INVALID')
    repetition_diagnostic(result,diagnostics)
    return result


def complete_json_prefix(value,diagnostics):
    """Salvage only complete independent objects from a truncated layout array."""
    start=value.find('[')
    if start<0:raise PDFError('PARSER_OUTPUT_INVALID')
    # Recognize the documented top-level array/envelopes; never flatten nested pages.
    if value[:start].strip() and not re.fullmatch(r'\{\s*"(?:layout|elements|blocks|layout_elements)"\s*:\s*',value[:start]):raise PDFError('PARSER_OUTPUT_INVALID')
    pos=start+1;entries=[];decoder=json.JSONDecoder()
    while len(entries)<1000:
        while pos<len(value) and value[pos].isspace():pos+=1
        if pos>=len(value) or value[pos]==']':break
        try:_,end=decoder.raw_decode(value,pos)
        except ValueError:break
        try:entries.append(strict_loads(value[pos:end]))
        except ValueError as exc:
            diagnostic(diagnostics,'LAYOUT_ELEMENT_INVALID',f'/{len(entries)}',exc)
            entries.append(None)
        pos=end
        while pos<len(value) and value[pos].isspace():pos+=1
        if pos>=len(value) or value[pos]!=',':break
        pos+=1
    if not entries:raise PDFError('PARSER_OUTPUT_INVALID')
    diagnostic(diagnostics,'JSON_INCOMPLETE','/','Only independently complete layout objects were recovered; page is incomplete')
    return entries


def json_items(raw,page,diagnostics=None):
    diagnostics=diagnostics if diagnostics is not None else []
    value=strip_fences(raw)
    try:data=strict_loads(value)
    except ValueError:data=complete_json_prefix(value,diagnostics)
    root_path=''
    if isinstance(data,dict):
        key=next((k for k in ('layout','elements','blocks','layout_elements') if k in data),None)
        if key is None:raise PDFError('PARSER_OUTPUT_INVALID')
        if set(data)-{key}:diagnostic(diagnostics,'UNINTERPRETED_ENVELOPE_FIELDS','/',','.join(sorted(set(data)-{key})))
        root_path='/'+key
        data=data[key]
    if not isinstance(data,list):raise PDFError('PARSER_OUTPUT_INVALID')
    if len(data)>1000:diagnostic(diagnostics,'LAYOUT_CAPACITY','/','Only the first 1000 physical regions are decoded; the full response remains in evidence')
    result=[]
    for index,entry in enumerate(data[:1000]):
        path=f'{root_path}/{index}'
        try:
            if not isinstance(entry,dict):raise ValueError('Single-page layout entry must be an object')
            role=str(entry.get('category',entry.get('label','text'))).lower()
            if len(role)>100:diagnostic(diagnostics,'MODEL_ROLE_LIMIT',path,'Role exceeds display capacity; its full value remains in the response');role=role[:100]
            text=entry.get('text',entry.get('content',''))
            if not isinstance(text,str):raise ValueError('Layout text must be a string')
            bounds=bbox(entry.get('bbox'),page)
            if role not in LABELS:diagnostic(diagnostics,'UNKNOWN_MODEL_ROLE',path,role)
            label=LABELS.get(role,'text')
            if label=='picture':semantic=node('figure',attrs={'model_role':role,**({'annotations':[{'kind':'derived_visual','value':text[:16000],'output_path':path}]} if text else {})},path=path)
            elif label=='formula':semantic=node('math',[{'type':'math','text':text,'path':path}],attrs={'model_role':role},path=path)
            elif label=='table':
                parser=HTMLSemantics(text,diagnostics);tables=parser.tree.xpath('.//table')
                try:
                    if len(tables)!=1:raise ValueError('Expected one HTML table')
                    semantic=parser.table(tables[0])
                    # Inner paths belong to the decoded JSON text field, not
                    # the entire JSON response. Qualify cells and literal spans
                    # so multiple tables cannot claim the same output locator.
                    pending=[semantic]
                    while pending:
                        current=pending.pop()
                        if isinstance(current,dict):
                            for key,value in current.items():
                                if key in {'path','output_path'} and isinstance(value,str):
                                    current[key]=(path+'/text'+value.removeprefix('/payload') if value.startswith('/payload/') else path+'/text/html'+value)[:512]
                                elif isinstance(value,(dict,list)):pending.append(value)
                        elif isinstance(current,list):pending.extend(current)
                    semantic['path']=path
                except ValueError as exc:
                    diagnostic(diagnostics,'TABLE_STRUCTURE_UNSUPPORTED',path,exc)
                    semantic=node('table',attrs={'annotations':[{'kind':'unsupported_table','value':text[:16000],'output_path':path}]},path=path)
                semantic['attrs']['model_role']=role
            else:
                semantic=markdown_semantics(text,diagnostics,path+'/text');semantic['attrs']['model_role']=role
                if label in {'title','section_header'} and semantic['kind']!='group':
                    semantic['kind']='heading';semantic['attrs'].setdefault('level',1 if label=='title' else 2)
                if label in {'caption','footnote','reference'}:
                    scope=role.split('_')[0]
                    def role_leaf(n):
                        if n['children']:
                            for child in n['children']:role_leaf(child)
                        else:
                            n['kind']=label
                            if label=='caption':n['attrs']['caption_type']=scope if scope in {'figure','table','formula','code','image'} else 'unspecified'
                            elif label=='footnote':n['attrs']['note_scope']=scope if scope in {'page','figure','table','formula','image'} else 'unspecified'
                    role_leaf(semantic)
            extras=set(entry)-{'bbox','category','label','text','content'}
            if extras:diagnostic(diagnostics,'UNINTERPRETED_LAYOUT_FIELDS',path,','.join(sorted(extras)))
            if semantic['kind'] in {'math','code'} and not semantic['text'].strip():diagnostic(diagnostics,'EMPTY_LITERAL',path,'Empty math/code output; original region retained')
            result.append(physical(semantic,role,bounds,page,index))
        except (ValueError,TypeError,KeyError,PDFError) as exc:diagnostic(diagnostics,'LAYOUT_ELEMENT_INVALID',path,exc)
    if data and not result:raise PDFError('PARSER_OUTPUT_INVALID')
    repetition_diagnostic(result,diagnostics)
    return result
