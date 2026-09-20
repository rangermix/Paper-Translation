"""Conservative reconciliation of layout inference with native PDF evidence.

The model supplies order and structure. Native geometry may enlarge a known
graphic; native text may restore punctuation only with identical letter/digit
order. Every change is retained in the inspection ledger.
"""
from copy import deepcopy
from difflib import SequenceMatcher
import re
import unicodedata

CAPTION_LABEL=r'(Figure|Table)\s+(?:[A-Z]\.)?\d+(?:\s*\(continued\))?\s*[:.]'


def box(prov,pages):
    b=prov['bbox'];l,t,r,d=(b[k] for k in ('l','t','r','b'))
    if str(b.get('coord_origin','TOPLEFT')).upper().endswith('BOTTOMLEFT'):
        h=pages[prov['page_no']-1]['page_size'][1];t,d=h-t,h-d
    return [min(l,r),min(t,d),max(l,r),max(t,d)]


def set_box(prov,b):
    prov['bbox']=dict(zip(('l','t','r','b'),b),coord_origin='TOPLEFT')


def area(b):return max(0,b[2]-b[0])*max(0,b[3]-b[1])


def overlap(a,b):
    return area([max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])])/max(1,area(a))


def union(boxes):
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]


def recover_native_text(layout,native,*,proven_accents=False):
    def core(text):
        if proven_accents:text=''.join(c for c in unicodedata.normalize('NFD',text).replace('ı','i') if not unicodedata.combining(c))
        return ''.join(c for c in unicodedata.normalize('NFKC',text) if c.isalnum())
    # Even a single changed/missing letter or digit requires source review.
    if not core(layout) or core(layout)!=core(native):return None
    original_native=native
    native=''.join(c for c in native if not c.isspace() and c not in '\x02\xad')
    positions=[i for i,c in enumerate(layout) if not c.isspace()]
    compact=''.join(layout[i] for i in positions);result=list(layout);insertions={}
    # Keep Docling's word/line joining. Only carry the native punctuation edits
    # over, otherwise discretionary line hyphens turn "attention" into "at tention".
    for tag,a,b,c,d in SequenceMatcher(None,compact,native,autojunk=False).get_opcodes():
        if tag=='equal':continue
        if a<b:
            for index in positions[a:b]:result[index]=''
            result[positions[a]]=native[c:d]
        elif c<d:
            position=positions[a-1]+1 if a else 0
            insertions[position]=insertions.get(position,'')+native[c:d]
    result=''.join(insertions.get(i,'')+c for i,c in enumerate(result))+insertions.get(len(result),'')
    # TeX's long arrow is encoded as adjoining minus + right-arrow glyphs.
    # Join only that exact composite present in the native text, never infer
    # an operator from plain hyphens or transform its mathematical meaning.
    if native.count('−→')==len(re.findall(r'−\s*→',result)):
        result=re.sub(r'−\s+→','−→',result)
    # A decimal may be spuriously separated by the layout model. Restore only
    # a complete decimal that is contiguous in the original native region.
    def decimal(match):
        compact=match[1]+'.'+match[2]
        return compact if re.search(r'(?<![\w.])'+re.escape(compact)+r'(?![\w.])',original_native) else match[0]
    result=re.sub(r'(?<![\w.])(\d+)\s*\.\s*(\d+)(?![\w.])',decimal,result)
    if proven_accents:
        for word in re.findall(r'[^\W\d_]+',original_native):
            if any(unicodedata.combining(c) for c in unicodedata.normalize('NFD',word)):
                pattern=r'(?<!\w)'+r'\s*'.join(re.escape(c) for c in word)+r'(?!\w)'
                result=re.sub(pattern,lambda _:word,result)
    return result


def annotation_url_span(text,start,uri):
    """Match a visible URL to its annotation with only wrapping/hyphen loss."""
    i,j=start,0
    while j<len(uri):
        while i<len(text) and text[i].isspace():i+=1
        if i>=len(text):return None
        if text[i]==uri[j]:i+=1;j+=1
        elif uri[j] in '-_':j+=1
        elif text[i]=='-':i+=1
        else:return None
    if i<len(text) and (text[i].isalnum() or text[i] in '/_?=&%#-'):return None
    return i


def bibliography_columns(item,page):
    """Recover a falsely tabulated bibliography only with hanging-column proof."""
    data=item.get('data',{});cells=data.get('table_cells',[])
    if data.get('num_cols')!=2 or len(cells)<4 or item.get('captions') or any(c.get('column_header') or c.get('row_header') for c in cells):return None
    if sum(bool(re.search(r'\b(?:19|20)\d{2}\b',c.get('text',''))) for c in cells)<len(cells)/2:return None
    b=[item['prov'][0]['bbox'][key] for key in ('l','t','r','b')]
    middle=(b[0]+b[2])/2
    regions=[r for r in page.get('text_regions',[]) if overlap(r['bbox'],b)>=.8 and r['text'].strip()]
    if not regions or any(r['bbox'][0]<middle<r['bbox'][2] for r in regions):return None
    groups=[]
    for column in ([r for r in regions if r['bbox'][2]<middle],[r for r in regions if r['bbox'][0]>middle]):
        if len(column)<3:return None
        lines=[]
        for r in sorted(column,key=lambda r:(r['bbox'][1],r['bbox'][0])):
            target=next((line for line in reversed(lines) if
                min(union([q['bbox'] for q in line])[3],r['bbox'][3])-max(union([q['bbox'] for q in line])[1],r['bbox'][1])
                    >=.5*min(union([q['bbox'] for q in line])[3]-union([q['bbox'] for q in line])[1],r['bbox'][3]-r['bbox'][1])),None)
            if target is None:lines.append([r])
            else:target.append(r)
        for line in lines:line.sort(key=lambda r:r['bbox'][0])
        left=min(line[0]['bbox'][0] for line in lines)
        starts=[i for i,line in enumerate(lines) if line[0]['bbox'][0]<=left+1.5]
        if len(starts)<2 or not any(line[0]['bbox'][0]>left+2 for line in lines):return None
        current=[]
        for i,line in enumerate(lines):
            if current and i in starts:groups.append(current);current=[]
            current.extend(line)
        if current:groups.append(current)
    output=[]
    for index,group in enumerate(groups):
        raw='\n'.join(r['text'].strip() for r in group)
        text=re.sub(r'\x02\s*','',raw)
        prov={'page_no':page['page'],'charspan':[0,len(text)]};set_box(prov,union([r['bbox'] for r in group]))
        output.append({'self_ref':item['self_ref']+f'/native-reference-{index}','label':'reference','orig':text,'text':text,
            'prov':[prov],'native_reference_regions':deepcopy(group)})
    return output


def reconcile_items(original,pages):
    items=deepcopy(original);audit=[]
    for item in items:
        for prov in item.get('prov',[]):set_box(prov,box(prov,pages))
        item['captions']=[{'$ref':r.get('$ref',r.get('cref'))} for r in item.get('captions',[]) if isinstance(r,dict) and (r.get('$ref') or r.get('cref'))]
    # A reference cannot skip a whole page and consume a later author's entry.
    # Exact model charspans split the text without inventing or dropping prose;
    # later fragments return to their original page/column position.
    split_items=[];deferred=[];bibliography=False
    for item in items:
        if item.get('label') in {'section_header','title'}:
            bibliography=(item.get('orig',item.get('text','')) or '').strip().casefold() in {'references','bibliography','参考文献'}
        prov=item.get('prov',[]);text=item.get('orig',item.get('text','')) or ''
        if bibliography and any(b['page_no']-a['page_no']>1 for a,b in zip(prov,prov[1:])):
            spans=[p.get('charspan') for p in prov]
            if all(s and len(s)==2 and 0<=s[0]<=s[1]<=len(text) for s in spans) and spans[0][0]==0 and spans[-1][1]==len(text) and all(a[1]<=b[0] and not text[a[1]:b[0]].strip() for a,b in zip(spans,spans[1:])):
                fragments=[]
                for index,p in enumerate(prov):
                    clone=deepcopy(item);part=text[p['charspan'][0]:p['charspan'][1]]
                    clone.update(orig=part,text=part,label='reference',self_ref=item['self_ref']+f'/part-{index}',prov=[deepcopy(p)])
                    clone['prov'][0]['charspan']=[0,len(part)];fragments.append(clone)
                split_items.append(fragments[0]);deferred.extend(fragments[1:])
                audit.append({'action':'discontinuous_reference_split','reference':item['self_ref'],'original_text':text,'original_provenance':deepcopy(prov),'fragments':[f['self_ref'] for f in fragments]});continue
        split_items.append(item)
    def reading_position(item):
        p=item['prov'][0];b=box(p,pages);width=pages[p['page_no']-1]['page_size'][0]
        return p['page_no'],int(b[0]>=width/2),b[1]
    for fragment in deferred:
        at=next((i for i,item in enumerate(split_items) if item.get('prov') and item.get('label') not in {'page_header','page_footer'} and reading_position(item)>reading_position(fragment)),len(split_items))
        split_items.insert(at,fragment)
    items=split_items
    repaired=[];bibliography=False
    for item in items:
        if item.get('label') in {'section_header','title'}:
            bibliography=(item.get('orig',item.get('text','')) or '').strip().casefold() in {'references','bibliography','参考文献'}
        replacements=None
        if bibliography and item.get('label')=='table' and len(item.get('prov',[]))==1:
            replacements=bibliography_columns(item,pages[item['prov'][0]['page_no']-1])
        if replacements:
            repaired.extend(replacements)
            audit.append({'action':'native_bibliography_columns','reference':item.get('self_ref'),
                'page':item['prov'][0]['page_no'],'basis':'reference_section_two_separate_hanging_columns_with_years',
                'entries':[{'reference':r['self_ref'],'regions':r['native_reference_regions']} for r in replacements]})
        else:repaired.append(item)
    items=repaired
    # A code listing explicitly labelled as a numbered figure is an original
    # figure. Its pixels preserve indentation, line breaks and syntax colours.
    for item in items:
        if item.get('label')!='code' or len(item.get('prov',[]))!=1:continue
        p=item['prov'][0];b=box(p,pages)
        for caption in items:
            if caption.get('label') not in {'caption','text','paragraph'} or len(caption.get('prov',[]))!=1 or not re.match(r'Figure\s+(?:[A-Z]\.)?\d+\s*[:.]',caption.get('orig',caption.get('text','')) or ''):continue
            cp=caption['prov'][0];cb=box(cp,pages)
            if p['page_no']==cp['page_no'] and 0<=cb[1]-b[3]<=35 and min(cb[2],b[2])-max(cb[0],b[0])>=.8*min(cb[2]-cb[0],b[2]-b[0]):
                item['label']='picture';caption['label']='caption';item['captions'].append({'$ref':caption['self_ref']})
                audit.append({'action':'code_figure_original_raster','reference':item.get('self_ref'),'caption_reference':caption['self_ref']});break
    graphics=[i for i in items if i.get('label') in {'picture','table'} and len(i.get('prov',[]))==1]
    # A substantial native form overlapping this inferred graphic is stronger
    # crop evidence than the layout box. Never turn a full page into a fallback.
    for item in graphics:
        p=item['prov'][0];b=box(p,pages);page=pages[p['page_no']-1]
        candidates=[r['bbox'] for r in page.get('graphic_regions',[])+page.get('image_regions',[])
            if overlap(b,r['bbox'])>=.8 and area(r['bbox'])<=2.5*area(b) and area(r['bbox'])<.65*area([0,0,*page['page_size']])]
        if candidates:
            revised=union([b,min(candidates,key=area)]);set_box(p,revised)
            audit.append({'action':'native_graphic_bounds','reference':item.get('self_ref'),'before':b,'after':revised,'page':p['page_no']})
    # Keep only the caption beginning at its explicit Figure/Table label. A
    # preceding chart axis is retained by the native graphic, not translated.
    for item in items:
        text=item.get('orig',item.get('text','')) or '';match=re.search(r'\b'+CAPTION_LABEL,text)
        if not match or item.get('label') not in {'caption','text','paragraph'}:continue
        if match.start() and item.get('label')!='caption':continue
        item['label']='caption'
        if match.start() and len(item.get('prov',[]))==1:
            p=item['prov'][0];b=box(p,pages);regions=pages[p['page_no']-1].get('text_regions',[])
            anchors=[r for r in regions if re.match(r'\s*'+re.escape(match.group()),r['text']) and overlap(r['bbox'],b)>.6]
            if anchors:
                start=min(r['bbox'][1] for r in anchors);b[1]=start;set_box(p,b)
                audit.append({'action':'caption_prefix_retained_in_graphic','reference':item.get('self_ref'),'text':text[:match.start()]})
                text=text[match.start():];item['orig']=item['text']=text;p['charspan']=[0,len(text)]
    # Ensure expanded graphics cannot obscure a separate, explicit caption.
    for graphic in graphics:
        gp=graphic['prov'][0];gb=box(gp,pages)
        for caption in items:
            if caption.get('label')!='caption' or len(caption.get('prov',[]))!=1:continue
            cp=caption['prov'][0];cb=box(cp,pages)
            if cp['page_no']==gp['page_no'] and gb[1]<cb[1]<gb[3] and cb[1]>gb[1]+.7*(gb[3]-gb[1]) and min(gb[2],cb[2])>max(gb[0],cb[0]):
                gb[3]=cb[1]-.1;set_box(gp,gb)
    retained=[]
    for item in items:
        if item in graphics or item.get('label') in {'caption','page_header','page_footer'}:
            retained.append(item);continue
        text=item.get('orig',item.get('text','')) or '';keep=[];parts=[];removed=False
        for p in item.get('prov',[]):
            b=box(p,pages)
            owner=next((g for g in graphics if g['label']=='picture' and g['prov'][0]['page_no']==p['page_no'] and overlap(b,box(g['prov'][0],pages))>=.65),None)
            if owner:
                removed=True;audit.append({'action':'retain_text_in_graphic','reference':item.get('self_ref'),'graphic_reference':owner.get('self_ref'),'page':p['page_no'],'bbox':b,'charspan':p.get('charspan')})
            else:
                keep.append(p);span=p.get('charspan',[0,len(text)]);parts.append(text[span[0]:span[1]])
        if removed:
            if not keep:continue
            # Exact charspans, not string guessing, separate cross-page merges.
            if any(not p.get('charspan') for p in item.get('prov',[])):retained.append(item);continue
            item['prov']=keep;item['orig']=item['text']=' '.join(parts);offset=0
            for p,part in zip(keep,parts):p['charspan']=[offset,offset+len(part)];offset+=len(part)+1
        retained.append(item)
    items=retained
    # Explicit labels plus same-page geometry permit an unambiguous caption
    # association, including multiple panels sharing one spanning caption.
    removed_refs=set()
    for caption in [i for i in items if i.get('label')=='caption' and len(i.get('prov',[]))==1]:
        cp=caption['prov'][0];cb=box(cp,pages);text=caption.get('orig',caption.get('text',''))
        prefix=re.match(CAPTION_LABEL,text)
        if not prefix:continue
        label='picture' if prefix[1]=='Figure' else 'table';ref=caption.get('self_ref')
        candidates=[]
        for g in graphics:
            if g.get('self_ref') in removed_refs or g['label']!=label or g['prov'][0]['page_no']!=cp['page_no']:continue
            gb=box(g['prov'][0],pages);horizontal=max(0,min(cb[2],gb[2])-max(cb[0],gb[0]))/max(1,min(cb[2]-cb[0],gb[2]-gb[0]))
            # Table captions conventionally precede their grid, including an
            # explicit continued caption on the next page. Page identity and
            # horizontal alignment remain mandatory; never cross a page here.
            distance=gb[1]-cb[3] if label=='table' and cb[3]<=gb[1] else cb[1]-gb[3]
            if horizontal>.75 and -.5<=distance<=60:candidates.append((distance,g))
        if not candidates:continue
        nearest=min(d for d,g in candidates);group=[g for d,g in candidates if d<=nearest+8]
        owner=group[0]
        if len(group)>1:
            boxes=[box(g['prov'][0],pages) for g in group]
            if max(b[1] for b in boxes)>min(b[3] for b in boxes):continue
            set_box(owner['prov'][0],union(boxes))
            for g in group[1:]:removed_refs.add(g.get('self_ref'))
            audit.append({'action':'shared_caption_panels','references':[g.get('self_ref') for g in group],'caption_reference':ref})
        for g in graphics:g['captions']=[r for r in g.get('captions',[]) if r['$ref']!=ref]
        owner['captions'].append({'$ref':ref})
        audit.append({'action':'caption_association','graphic_reference':owner.get('self_ref'),'caption_reference':ref,'basis':'explicit_label_and_native_geometry'})
    items=[i for i in items if i.get('self_ref') not in removed_refs]
    # Reconciliation is local to each locator and preserves native region order.
    for item in items:
        if item.get('label') in {'picture','table','formula'}:continue
        from .glyphs import region_text
        chunks=[];proven_accents=False
        for p in item.get('prov',[]):
            b=box(p,pages);regions=pages[p['page_no']-1].get('text_regions',[])
            chunks.append(region_text([r for r in regions if overlap(r['bbox'],b)>=.8]))
            proven_accents|=any(a.get('action')=='native_latin_accent_composition' and overlap(a['base']['bbox'],b)>=.8
                               for a in pages[p['page_no']-1].get('glyph_reconciliations',[]))
        before=item.get('orig',item.get('text','')) or '';native=' '.join(chunks)
        fixed=recover_native_text(before,native,proven_accents=proven_accents)
        if fixed and fixed!=before:
            item['orig']=item['text']=fixed
            audit.append({'action':'native_punctuation_restored','reference':item.get('self_ref'),'before':before,'after':fixed})
        # Annotation destinations are evidence only when the visible URL has
        # identical letters/digits. This restores line-end hyphens in URLs;
        # an unrelated/malicious hyperlink destination cannot rewrite prose.
        current=item.get('orig',item.get('text','')) or ''
        for p in item.get('prov',[]):
            b=box(p,pages)
            for link in pages[p['page_no']-1].get('links',[]):
                if overlap(link['bbox'],b)<.6:continue
                for match in list(re.finditer(r'https?\s*:\s*/\s*/',current)):
                    end=annotation_url_span(current,match.start(),link['uri'])
                    if end is not None and current[match.start():end]!=link['uri']:
                        visible=current[match.start():end]
                        updated=current[:match.start()]+link['uri']+current[end:]
                        audit.append({'action':'native_url_annotation_restored','reference':item.get('self_ref'),'before':visible,'after':link['uri'],'page':p['page_no']})
                        current=updated
        item['orig']=item['text']=current
        if item.get('label')=='section_header':
            number=re.match(r'^((?:[A-Z]\.)?\d+(?:\.\d+)*|[A-Z])(?:\.?\s)',item.get('orig',''))
            if number:item['level']=min(6,2+number[1].count('.'))
    joined=[];bibliography=False
    for item in items:
        if item.get('label') in {'section_header','title'}:
            bibliography=(item.get('orig','') or '').strip().casefold() in {'references','bibliography','参考文献'}
        merged=False
        if bibliography and joined and item.get('label') in {'text','reference'} and item.get('prov'):
            previous=joined[-1]
            if previous.get('label') in {'text','reference'} and previous.get('prov') and item['prov'][0]['page_no']==previous['prov'][-1]['page_no']+1:
                before=previous.get('orig','');tail=item.get('orig','');combined=before+tail
                for p in previous['prov']:
                    b=box(p,pages)
                    for link in pages[p['page_no']-1].get('links',[]):
                        if overlap(link['bbox'],b)<.6:continue
                        for match in re.finditer(r'https?\s*:\s*/\s*/',before):
                            end=annotation_url_span(combined,match.start(),link['uri'])
                            if end is not None and end>len(before):
                                fixed=combined[:match.start()]+link['uri']+combined[end:]
                                previous['orig']=previous['text']=fixed;previous['prov']+=deepcopy(item['prov'])
                                audit.append({'action':'native_url_reference_continuation','reference':previous.get('self_ref'),'continued_reference':item.get('self_ref'),'before':[before,tail],'after':fixed,'annotation_uri':link['uri']})
                                merged=True;break
                        if merged:break
                    if merged:break
        if not merged:joined.append(item)
    return joined,audit
