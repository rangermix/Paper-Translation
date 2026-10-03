"""Bounded model-output semantics, independent of inference and IR storage.

Coordinates belong to the physical outer record. Descendants inherit that region;
HTML debug boxes never establish independent glyph/cell geometry.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

from lxml import html as dom
from markdown_it import MarkdownIt

VERSION = 'full-page-semantic-v2'
MAX_DEPTH, MAX_NODES, MAX_TEXT = 32, 10000, 1_000_000
MARKS = {'b':'strong','strong':'strong','i':'emphasis','em':'emphasis','u':'underline',
         'del':'deletion','s':'deletion','sub':'subscript','sup':'superscript','code':'code'}
UNSAFE = {'script','style','iframe','object','embed','svg','canvas','audio','video'}
BLOCK_TAGS = {'p','div','section','article','h1','h2','h3','h4','h5','h6','ul','ol','li','pre','table','blockquote','figure','figcaption','caption','hr'}


def visible(runs):
    return ''.join(run.get('text', '') for run in runs)


def node(kind, runs=None, children=None, attrs=None, path=''):
    result = {'kind':kind,'runs':runs or [],'children':children or [],'attrs':attrs or {},'path':path}
    result['text'] = visible(result['runs']) if result['runs'] else '\n'.join(n['text'] for n in result['children'])
    return result


def separate_notes(nodes):
    """Separate explicitly printed caption/note subtrees from literal content."""
    body=[];notes=[]
    for child in nodes:
        if child['kind'] in {'caption','footnote'}:
            notes.append(child)
        elif child['children']:
            kept,nested=separate_notes(child['children']);notes.extend(nested)
            if kept or child['runs']:
                body.append(node(child['kind'],child['runs'],kept,child['attrs'],child['path']))
        else:body.append(child)
    return body,notes


def safe_url(url):
    try:
        p = urlsplit(url)
        return (len(url)<=2048 and not any(ord(c)<32 for c in url) and '\\' not in url and p.scheme in {'http','https','mailto'}
                and bool(p.netloc if p.scheme!='mailto' else p.path) and p.username is None and p.password is None)
    except ValueError:
        return False


class HTMLSemantics:
    def __init__(self, value, diagnostics):
        self.diagnostics = diagnostics
        self.literals, self.count = {}, 0
        # LaTeX comparisons are text, not HTML tags. Protect them BEFORE lxml.
        def literal(m):
            key = str(len(self.literals))
            payload, attributes = m[3], m[2]
            if m[1].lower()=='pre':
                inner = re.fullmatch(r'<code(\s[^>]*)?>(.*?)</code\s*>', payload, re.S|re.I)
                if inner:
                    payload = inner[2]
                    attributes = (attributes or '') + (inner[1] or '')
            self.literals[key] = (m[1].lower(), html.unescape(payload), attributes, m.start(), m.end())
            return '<span data-literal="'+key+'"></span>'
        value = re.sub(r'<(math|chem|pre|code)(\s[^>]*)?>(.*?)</\1\s*>', literal, value, flags=re.S|re.I)
        # Unclosed literal regions cannot safely go through an HTML repair
        # parser. Keep the affected physical block as an original-image fallback.
        self.incomplete_literals = set()
        def incomplete(m):
            key = str(len(self.literals))
            self.literals[key] = (m[1].lower(), html.unescape(m[3]), m[2], m.start(), m.end())
            self.incomplete_literals.add(key)
            self.warn('LITERAL_UNCLOSED', '/', 'Literal region is incomplete; its source crop remains authoritative')
            return '<span data-literal="'+key+'"></span>'
        value = re.sub(r'<(math|chem|pre|code)(\s[^>]*)?>(.*?)(?=</(?:p|div|td|li)\s*>|$)', incomplete, value, flags=re.S|re.I)
        parser = dom.HTMLParser(recover=True, no_network=True, huge_tree=False)
        self.tree = dom.fragment_fromstring(value or '<span></span>', create_parent=True, parser=parser)
        if parser.error_log:
            self.warn('HTML_REPAIRED', '/', 'Damaged markup was repaired; exact response remains in page evidence')

    def warn(self, code, path, reason):
        if len(self.diagnostics)<100:
            self.diagnostics.append({'code':code,'output_path':path,'reason':reason[:500]})

    def bounded(self, n, depth):
        self.count += 1
        if depth>MAX_DEPTH or self.count>MAX_NODES:
            self.warn('SEMANTIC_LIMIT', n.getroottree().getpath(n), 'Nesting or node limit; remaining content retained as evidence')
            return False
        return True

    def path(self, n):
        literal=self.literals.get(n.get('data-literal'))
        if literal:return f'/payload/chars/{literal[3]}:{literal[4]}'
        return n.getroottree().getpath(n)[:512]

    def inline(self, n, marks=(), depth=0):
        if not self.bounded(n, depth): return []
        tag, path = str(n.tag).lower(), self.path(n)
        if tag in UNSAFE:
            self.warn('UNSAFE_MARKUP_OMITTED', path, tag); return []
        key = n.get('data-literal')
        if key in self.literals:
            kind, text, attributes, _, _ = self.literals[key]
            if kind=='chem':
                self.warn('DERIVED_CHEMICAL_ANNOTATION', path, 'Reactive SMILES is derived notation, retained as an annotation')
                return []
            run = {'type':'math' if kind=='math' else 'code','text':text,'path':path}
            if marks: run['marks']=list(marks)
            return [run]
        if tag=='br': return [{'type':'text','text':'\n','path':path}]
        if tag=='img':
            self.warn('MODEL_MEDIA_ANNOTATION', path, 'Image alt/src is annotation, never fetched or used as printed text'); return []
        if tag=='input':
            control = n.get('type','text').lower()
            if control not in {'checkbox','radio','text'}:
                self.warn('UNSUPPORTED_CONTROL', path, control); return []
            checked = n.get('checked') is not None
            run = {'type':'control','text':('☑' if checked else '☐') if control in {'checkbox','radio'} else n.get('value',''),
                   'control_type':control,'state':('checked' if checked else 'unchecked') if control in {'checkbox','radio'} else 'value','path':path}
            if marks: run['marks']=list(marks)
            return [run]
        if tag=='select':
            options=n.xpath('./option')[:100]; selected=[o for o in options if o.get('selected') is not None]
            text='; '.join(o.text_content() for o in selected)
            return [{'type':'control','text':text,'control_type':'select','state':'selected' if selected else 'unselected','path':path,
                'options':[{'label':o.text_content(),'value':o.get('value',o.text_content()),'selected':o.get('selected') is not None} for o in options]}]
        active = tuple(dict.fromkeys((*marks, *((MARKS[tag],) if tag in MARKS else ()))))
        result=[]
        def add(text):
            if text:
                result.append({'type':'text','text':re.sub(r'[\t\r\n ]+', ' ', text),'path':path, **({'marks':list(active)} if active else {})})
        add(n.text)
        for child in n:
            result.extend(self.inline(child, active, depth+1)); add(child.tail)
        if tag=='a':
            href=n.get('href','')
            for run in result:
                if run['type']!='text': continue
                if href.startswith('#') and re.fullmatch(r'#[A-Za-z0-9._:-]{1,160}',href):
                    run.update(type='xref', target_key=href[1:])
                elif safe_url(href): run.update(type='link',href=href)
                elif href: self.warn('UNSAFE_OR_UNSUPPORTED_LINK', path, href)
        return result

    def trim(self, runs):
        if runs and runs[0]['type']=='text': runs[0]['text']=runs[0]['text'].lstrip()
        if runs and runs[-1]['type']=='text': runs[-1]['text']=runs[-1]['text'].rstrip()
        return [r for r in runs if r.get('text') or r['type']=='control']

    def attrs(self, n):
        attrs={}
        if n.get('id') and len(n.get('id'))<=160: attrs['semantic_id']=n.get('id')
        annotations=[]
        for index,child in enumerate(n.iter()):
            if index>=MAX_NODES:
                self.warn('SEMANTIC_LIMIT',self.path(n),'Annotation scan capacity');break
            if len(annotations)>=100: break
            key=child.get('data-literal'); literal=self.literals.get(key)
            if literal and literal[0]=='chem': annotations.append({'kind':'derived_chemical','value':literal[1][:16000],'output_path':self.path(child)})
            if child.tag=='img' and child.get('alt'): annotations.append({'kind':'visual_description','value':child.get('alt')[:16000],'output_path':self.path(child)})
            if child is not n and child.get('data-bbox'): annotations.append({'kind':'nested_debug_bbox','value':child.get('data-bbox')[:16000],'output_path':self.path(child)})
        if annotations: attrs['annotations']=annotations
        return attrs

    def blocks(self, n, depth=0, default='paragraph'):
        if not self.bounded(n,depth):return []
        tag, path = str(n.tag).lower(), self.path(n)
        if tag=='div' and n.get('data-label'):
            return [html_semantics(self,n,n.get('data-label'),depth)]
        attrs=self.attrs(n)
        key=n.get('data-literal'); literal=self.literals.get(key)
        if literal and literal[0] in {'pre','code'}:
            language=re.search(r'(?:language-|lang-)([A-Za-z0-9_+.-]{1,40})', literal[2] or '')
            if language: attrs['code_language']=language[1]
            return [node('code',[{'type':'code','text':literal[1],'path':path}],attrs=attrs,path=path)]
        if literal and literal[0]=='math' and re.search(r'\bdisplay(?:\s*=|\s|$)',literal[2] or ''):
            return [node('math',[{'type':'math','text':literal[1],'path':path}],attrs=attrs,path=path)]
        if tag in UNSAFE: self.inline(n,depth=depth); return []
        if tag=='hr':return [node('group',attrs=attrs|{'group_type':'layout','separator':'horizontal'},path=path)]
        if tag=='table': return [self.table(n,depth)]
        if tag in {'ul','ol'}:
            attrs.update(group_type='list',list_ordered=tag=='ol')
            if tag=='ol':
                if re.fullmatch(r'-?\d{1,6}', n.get('start','')): attrs['list_start']=int(n.get('start'))
                attrs['list_reversed']=n.get('reversed') is not None
                attrs['list_marker']=n.get('type','1')[:32]
            children=[]; index=attrs.get('list_start',len(n) if attrs.get('list_reversed') else 1)
            for child in n:
                if child.tag!='li': self.warn('LIST_CHILD_UNSUPPORTED', self.path(child), str(child.tag)); continue
                content=self.blocks(child, depth+1, 'list_item')
                leaf=content[0] if len(content)==1 else node('list_item',children=content,attrs={'children_block_ids':[]},path=self.path(child))
                leaf['kind']='list_item';leaf['attrs'].update(list_ordered=tag=='ol')
                if tag=='ol':
                    value=child.get('value','');index=int(value) if re.fullmatch(r'-?\d{1,6}',value) else index
                    leaf['attrs']['list_index']=index;index+=-1 if attrs.get('list_reversed') else 1
                children.append(leaf)
            return [node('group',children=children,attrs=attrs,path=path)]
        if tag in {'figure','blockquote'}:
            children=self.contents(n,depth+1)
            return [node('group',children=children,attrs=attrs|{'group_type':'complex'},path=path)]
        if re.fullmatch('h[1-6]',tag): attrs['level']=int(tag[1]); default='heading'
        elif tag in {'figcaption','caption'}: default='caption'
        if tag=='li' and any(c.tag in BLOCK_TAGS for c in n):
            children=self.contents(n,depth+1)
            return [node('list_item',children=children,attrs=attrs,path=path)]
        if any(c.tag in BLOCK_TAGS or c.get('data-literal') in self.literals and self.literals[c.get('data-literal')][0]=='pre' for c in n):
            children=self.contents(n,depth+1,default)
            return children if tag in {'div','section','article'} else [node('group',children=children,attrs=attrs|{'group_type':'layout'},path=path)]
        runs=self.trim(self.inline(n,depth=depth))
        return [node(default,runs,attrs=attrs,path=path)] if runs else []

    def contents(self, n, depth=0, default='paragraph'):
        if not self.bounded(n,depth):return []
        result=[]; runs=[]
        def flush():
            nonlocal runs
            values=self.trim(runs)
            if values: result.append(node(default,values,attrs=self.attrs(n),path=self.path(n)))
            runs=[]
        if n.text: runs.append({'type':'text','text':re.sub(r'[\t\r\n ]+',' ',n.text),'path':self.path(n)})
        for child in n:
            if self.count>=MAX_NODES:
                self.warn('SEMANTIC_LIMIT',self.path(n),'Node capacity; remaining response stays in evidence');break
            literal=self.literals.get(child.get('data-literal'))
            isblock=child.tag in BLOCK_TAGS or literal and (literal[0]=='pre' or literal[0]=='math' and re.search(r'\bdisplay',literal[2] or ''))
            if isblock: flush();result.extend(self.blocks(child,depth+1,default))
            else: runs.extend(self.inline(child,depth=depth+1))
            if child.tail: runs.append({'type':'text','text':re.sub(r'[\t\r\n ]+',' ',child.tail),'path':self.path(n)})
        flush(); return result

    def table(self, table, depth=0):
        path=self.path(table); rows=table.xpath('./tr|./thead/tr|./tbody/tr|./tfoot/tr')
        if not rows or len(rows)>1000: raise ValueError('table row limit')
        occupied={};cells=[];columns=0;groups=[]
        for r,row in enumerate(rows):
            group={'thead':'head','tbody':'body','tfoot':'foot'}.get(row.getparent().tag,'body')
            if not groups or groups[-1]['kind']!=group: groups.append({'kind':group,'start_row':r,'end_row':r+1})
            else: groups[-1]['end_row']=r+1
            c=0
            for cell in row:
                if cell.tag not in {'td','th'}: continue
                while (r,c) in occupied:c+=1
                spans=[]
                for key in ['rowspan','colspan']:
                    value=cell.get(key,'1')
                    if not re.fullmatch(r'[0-9]{1,4}',value): raise ValueError('invalid table span')
                    spans.append(int(value))
                rs,cs=spans
                if rs==0:
                    end=next((at for at in range(r+1,len(rows)) if rows[at].getparent() is not row.getparent()),len(rows))
                    rs=end-r
                if not 1<=rs<=1000 or not 1<=cs<=1000 or r+rs>len(rows) or (r+rs)*(c+cs)>10000: raise ValueError('table span capacity')
                slots={(y,x) for y in range(r,r+rs) for x in range(c,c+cs)}
                if any(s in occupied for s in slots):raise ValueError('table overlap')
                children=self.contents(cell,depth+1)
                leaf=children[0] if len(children)==1 and children[0]['kind']=='paragraph' else node('group',children=children,attrs={'group_type':'cell'},path=self.path(cell))
                attrs={'role':'header' if cell.tag=='th' else 'data'}
                if cell.get('scope') in {'row','col','rowgroup','colgroup'}:attrs['scope']=cell.get('scope')
                entry={'text':leaf['text'],'row_span':rs,'col_span':cs,'start_row_offset_idx':r,'end_row_offset_idx':r+rs,
                       'start_col_offset_idx':c,'end_col_offset_idx':c+cs,'_semantic':leaf,'_cell_attributes':attrs,
                       '_headers':cell.get('headers','').split()[:100], '_id':cell.get('id','')[:160]}
                cells.append(entry)
                for s in slots: occupied[s]=entry
                c+=cs;columns=max(columns,c)
        if len(occupied)!=len(rows)*columns:raise ValueError('table grid gap')
        result=node('table',attrs=self.attrs(table)|{'row_groups':groups},path=path)
        column_groups=[];column=0
        for group in table.xpath('./colgroup'):
            spans=[c.get('span','1') for c in group if c.tag=='col'] or [group.get('span','1')]
            if not all(re.fullmatch(r'[0-9]{1,4}',v) and 1<=int(v)<=1000 for v in spans):
                self.warn('COLUMN_GROUP_UNSUPPORTED',self.path(group),'Invalid column group span');continue
            end=column+sum(map(int,spans))
            if end>columns:self.warn('COLUMN_GROUP_UNSUPPORTED',self.path(group),'Column group exceeds grid');continue
            column_groups.append({'start_column':column,'end_column':end});column=end
        if column_groups:result['attrs']['column_groups']=column_groups
        result['data']={'num_rows':len(rows),'num_cols':columns,'table_cells':cells}
        result['text']='\n'.join(c['text'] for c in cells)
        captions=table.xpath('./caption')
        result['children']=[node('caption',self.trim(self.inline(c)),attrs={'caption_type':'table'},path=self.path(c)) for c in captions]
        return result


def html_semantics(parser, outer, role, depth=0):
    role=role.lower()
    if len(role)>100:
        parser.warn('MODEL_ROLE_LIMIT',parser.path(outer),'Role exceeds display capacity; its full value remains in the response')
        role=role[:100]
    if any(c.get('data-literal') in parser.incomplete_literals for c in outer.iter()):
        return node('figure',attrs={'model_role':role,'annotations':[{'kind':'incomplete_literal','value':'Incomplete math/code region; see exact response and original crop','output_path':parser.path(outer)}]},path=parser.path(outer))
    children=parser.contents(outer,depth)
    attrs=parser.attrs(outer)|{'model_role':role}
    # Wrappers around printed captions/notes do not change their relationship.
    # Remove these subtrees from the literal body so they cannot be duplicated
    # inside a formula or mislabeled as a generated visual description.
    if role in {'image','picture','figure','diagram','chemical-block'}:
        body,captions=separate_notes(children)
        text=' '.join(n['text'] for n in body)
        if text: attrs.setdefault('annotations',[]).append({'kind':'derived_visual' if role!='chemical-block' else 'derived_chemical','value':text[:16000],'output_path':parser.path(outer)})
        # Explicit nested captions remain source, while descriptive text is auxiliary.
        return node('figure',children=captions,attrs=attrs,path=parser.path(outer))
    if role in {'equation','equation-block','formula'}:
        body,notes=separate_notes(children)
        text='\n'.join(c['text'] for c in body)
        return node('math',[{'type':'math','text':text,'path':parser.path(outer)}],children=notes,attrs=attrs,path=parser.path(outer))
    if role in {'code','code-block','algorithm'}:
        body,notes=separate_notes(children)
        if len(body)==1 and body[0]['kind']=='code':
            body[0]['attrs'].update(attrs);body[0]['children'].extend(notes);return body[0]
        def code_text(n,depth):
            if not parser.bounded(n,depth):return ''
            label=n.get('data-label','').lower()
            if n is not outer and (n.tag in {'caption','figcaption'} or 'caption' in label or 'footnote' in label):return ''
            literal=parser.literals.get(n.get('data-literal'))
            if literal:return literal[1]
            parts=[n.text or '']
            for child in n:parts.extend([code_text(child,depth+1),child.tail or ''])
            return ''.join(parts)
        return node('code',[{'type':'code','text':code_text(outer,depth),'path':parser.path(outer)}],children=notes,attrs=attrs,path=parser.path(outer))
    if role=='table' and len(children)==1 and children[0]['kind']=='table':children[0]['attrs'].update(attrs);return children[0]
    if role in {'title','section-header','sectionheader'} and len(children)==1:
        children[0]['kind']='heading';children[0]['attrs'].setdefault('level',1 if role=='title' else 2)
    if 'caption' in role:
        def caption(c):
            if c['children']:
                for nested in c['children']:caption(nested)
            elif c['kind']!='group':c['kind']='caption';c['attrs']['caption_type']=role.split('_')[0] if '_' in role and role.split('_')[0] in {'figure','table','formula','code','image'} else 'unspecified'
        for c in children:caption(c)
    if 'footnote' in role:
        def footnote(c):
            if c['children']:
                for nested in c['children']:footnote(nested)
            # A horizontal rule is an empty layout group, not empty prose.
            elif c['kind']!='group':c['kind']='footnote';c['attrs']['note_scope']=role.split('_')[0] if '_' in role and role.split('_')[0] in {'page','figure','table','formula','image'} else 'unspecified'
        for c in children:footnote(c)
    if role in {'bibliography','reference','ref_text'}:
        def reference(c):
            if c['children']:
                for nested in c['children']:reference(nested)
            elif c['kind']!='group':c['kind']='reference'
        for c in children:reference(c)
    if len(children)==1:
        children[0]['attrs'].update(attrs);return children[0]
    group={'list-group':'list','form':'form','table-of-contents':'toc','complex-block':'complex'}.get(role,'layout')
    return node('group',children=children,attrs=attrs|{'group_type':group},path=parser.path(outer))


def markdown_semantics(value, diagnostics, path='/text'):
    tokens=MarkdownIt('commonmark',{'html':False}).parse(value)
    if len(tokens)>MAX_NODES:raise ValueError('markdown node capacity')
    inline_nodes=0
    def warn(code,reason):
        if len(diagnostics)<100:diagnostics.append({'code':code,'output_path':path,'reason':reason[:500]})
    def inline(token):
        nonlocal inline_nodes
        result=[];marks=[];link=None
        for t in token.children or []:
            inline_nodes+=1
            if inline_nodes>MAX_NODES:raise ValueError('markdown inline capacity')
            if t.type in {'strong_open','em_open'}:marks.append('strong' if t.type=='strong_open' else 'emphasis')
            elif t.type in {'strong_close','em_close'}:
                if marks:marks.pop()
            elif t.type=='link_open':link=t.attrGet('href')
            elif t.type=='link_close':link=None
            elif t.type in {'text','code_inline','softbreak','hardbreak'}:
                text=t.content if t.type not in {'softbreak','hardbreak'} else '\n'
                run={'type':'code' if t.type=='code_inline' else 'text','text':text,'path':path}
                if marks:run['marks']=list(marks)
                if link and run['type']=='text':
                    if safe_url(link):run.update(type='link',href=link)
                    elif link.startswith('#') and re.fullmatch(r'#[A-Za-z0-9._:-]{1,160}',link):run.update(type='xref',target_key=link[1:])
                    else:warn('UNSAFE_OR_UNSUPPORTED_LINK',link)
                result.append(run)
            elif t.type=='image':warn('MODEL_MEDIA_ANNOTATION',t.content)
        return result
    stack=[node('group',attrs={'group_type':'layout'},path=path)]; current=None
    for t in tokens:
        if len(stack)>MAX_DEPTH:raise ValueError('markdown depth capacity')
        if t.type in {'bullet_list_open','ordered_list_open'}:
            attrs={'group_type':'list','list_ordered':t.type=='ordered_list_open','list_marker':t.markup[:32]}
            if t.type=='ordered_list_open':attrs['list_start']=int(t.attrGet('start') or 1)
            n=node('group',attrs=attrs,path=path);stack[-1]['children'].append(n);stack.append(n)
        elif t.type in {'list_item_open','blockquote_open'}:
            n=node('list_item' if t.type=='list_item_open' else 'group',attrs={'list_ordered':stack[-1]['attrs'].get('list_ordered',False)} if t.type=='list_item_open' else {'group_type':'complex'},path=path)
            if t.type=='list_item_open' and n['attrs']['list_ordered']:n['attrs']['list_index']=stack[-1]['attrs'].get('list_start',1)+len(stack[-1]['children'])
            stack[-1]['children'].append(n);stack.append(n)
        elif t.type in {'bullet_list_close','ordered_list_close','list_item_close','blockquote_close'}:stack.pop()
        elif t.type in {'paragraph_open','heading_open'}:
            current=node('heading' if t.type=='heading_open' else 'paragraph',attrs={'level':int(t.tag[1])} if t.type=='heading_open' else {},path=path)
            stack[-1]['children'].append(current)
        elif t.type=='inline' and current is not None:current['runs']=inline(t);current['text']=visible(current['runs'])
        elif t.type in {'fence','code_block'}:stack[-1]['children'].append(node('code',[{'type':'code','text':t.content,'path':path}],attrs={'code_language':t.info.split()[0][:40]} if t.info.strip() else {},path=path))
        elif t.type=='hr':stack[-1]['children'].append(node('group',attrs={'group_type':'layout','separator':'horizontal'},path=path))
        elif t.type not in {'paragraph_close','heading_close'}:warn('MARKDOWN_CONSTRUCT_UNSUPPORTED',t.type)
    def refresh(n):
        for c in n['children']:refresh(c)
        if n['children']:n['text']='\n'.join(c['text'] for c in n['children'])
    refresh(stack[0]);children=stack[0]['children']
    return children[0] if len(children)==1 else stack[0]
