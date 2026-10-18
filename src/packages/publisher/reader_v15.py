"""Reader v15: target-language UI, with v12 content and v13/v14 reading features.

Authored UI is translated at construction. Document strings, original evidence,
protected atoms and font license texts are never traversed or rewritten.
"""
from __future__ import annotations

from copy import deepcopy
import html
import re
from urllib.parse import quote

from packages.ir import flatten_inline, validate_ir
from .reader_locales import (resolve_reader_locale, translate, reader_language_name,
                             reader_messages_json, translate_diagnostic)

from packages.paths import ROOT
RENDERER_VERSION = 'reader-python-15.0.0'


def esc(value):
    return html.escape(str(value), quote=True)


def math_markup(value, *, display=False):
    tex = value.strip()
    for left, right in [('$$','$$'), ('\\[','\\]'), ('\\(','\\)'), ('$','$')]:
        if tex.startswith(left) and tex.endswith(right):
            tex = tex[len(left):-len(right)].strip()
            break
    cls = 'math-display' if display else 'math-inline'
    return f'<span class="{cls}" data-tex="{esc(tex)}" data-display="{str(display).lower()}">{esc(value)}</span>'


def inline(nodes, atoms, *, typeset=False, references=None, note_links=None):
    if references:
        pieces=[]
        def segments():
            run=[]
            for node in nodes:
                if node['type']=='xref' and node['target_block_id'] in references.ids:
                    yield from references.segments(run,atoms)
                    run=[]
                    label={'type':'text','text':node['label']}
                    if node.get('marks'):label['marks']=node['marks']
                    yield [label],[node['target_block_id']]
                else:run.append(node)
            yield from references.segments(run,atoms)
        for segment,targets in segments():
            content=inline(segment,atoms,typeset=typeset,note_links=note_links)
            if targets:content=f'<a class="reference-link" href="#b-{esc(targets[0])}" data-reference-targets="{esc(" ".join(targets))}">{content}</a>'
            pieces.append(content)
        return ''.join(pieces)
    out=[]
    for node in nodes:
        kind=node['type']
        if kind=='text':content=esc(node['text'])
        elif kind=='protected_ref':
            atom=atoms[node['ref']]
            content=math_markup(atom['value']) if atom['kind']=='math' else esc(atom['value'])
            if atom.get('options'):
                content+='<span class="static-options">'+''.join('<span'+(' aria-current="true"' if o['selected'] else '')+'>'+esc(o['label'])+'</span>' for o in atom['options'])+'</span>'
            content=f'<span class="protected" data-kind="{esc(atom["kind"])}">{content}</span>'
        elif kind=='link':content=f'<a href="{esc(node["href"])}" rel="noreferrer noopener">{esc(node["text"])}</a>'
        else:
            note=' class="footnote-link" role="doc-noteref" data-footnote-target="'+esc(node['target_block_id'])+'"' if note_links and node['target_block_id'] in note_links else ''
            if note and 'superscript' not in node.get('marks',[]) and re.fullmatch(r'[0-9]{1,3}|[*∗†‡§¶]',node['label']):note+=' data-footnote-marker'
            content=f'<a href="#b-{esc(node["target_block_id"])}"{note}>{esc(node["label"])}</a>'
        for mark in node.get('marks',[]):
            tag={'strong':'strong','emphasis':'em','code':'code','underline':'u','deletion':'del','subscript':'sub','superscript':'sup'}[mark]
            content=f'<{tag}>{content}</{tag}>'
        out.append(content)
    return ''.join(out)


def render_toc(source, blocks, *, original_labels=False, locale="en"):
    t = lambda key, **values: translate(locale, key, **values)
    tree, stack = [], []
    for bid in [b['id'] for b in sorted(blocks.values(),key=lambda b:b['order'])]:
        block = blocks[bid]
        if block['kind'] != 'heading' or bid == source['title_block_id']:
            continue
        node = {'id': bid, 'level': block['attributes']['level'], 'label': block['normalized_text'], 'children': []}
        while stack and stack[-1]['level'] >= node['level']:
            stack.pop()
        (stack[-1]['children'] if stack else tree).append(node)
        stack.append(node)
    def render(nodes):
        if not nodes:
            return ''
        tag = 'ul' if original_labels else 'ol'
        return f'<{tag}>' + ''.join('<li><a href="#b-' + esc(node['id']) + '">' + esc(node['label']) + '</a>'
            + render(node['children']) + '</li>' for node in nodes) + f'</{tag}>'
    rendered = render(tree)
    return f'<nav class="toc-sections" aria-label="{esc(t('双语章节'))}">' + rendered + '</nav>' if original_labels else rendered


def render_html(ir, asset_paths, *, include_source=False):
    validate_ir(ir)
    source, tr = ir['source_revision'], ir['translation_revision']
    locale = resolve_reader_locale(tr['target_language'])
    t = lambda key, **values: translate(locale, key, **values)
    diagnostic = lambda value: translate_diagnostic(locale, value)
    blocks = {b['id']:b for b in source['blocks']}
    results = {r['block_id']:r for r in tr['results']}
    atoms = source['protected_atoms']
    sidenotes = True
    named_fonts = sidenotes or ir['render']['template_id'] == 'reader-v7'
    font_selection = named_fonts or ir['render']['template_id'] == 'reader-v6'
    margins = font_selection or ir['render']['template_id'] == 'reader-v5'
    enhanced = margins or ir['render']['template_id'] == 'reader-v4'
    modern = enhanced or ir['render']['template_id'] == 'reader-v3'
    from packages.ir.retention import original_only_blocks
    retained = original_only_blocks(source) if enhanced else {}
    # A typed note remains a note even when its physical page position follows
    # the References heading; bibliography-range heuristics are not note links.
    retained = {bid:reason for bid,reason in retained.items()
        if not (blocks[bid]['kind']=='footnote' and reason=='original_reference')}
    from packages.publisher.semantic_notes import FootnoteIndex
    note_index = FootnoteIndex(source, retained)
    references, footnotes, note_links, children = None, {}, {}, {}
    if sidenotes:
        from packages.publisher.references import ReferenceIndex
        references = ReferenceIndex(source['blocks'], retained)
        note_serial = 0
        for block in sorted(blocks.values(), key=lambda block: block['order']):
            if block['owner_id']:
                children.setdefault(block['owner_id'], []).append(block['id'])
            if block['kind'] in {'reference', 'code', 'math'} or retained.get(block['id']) == 'original_reference':
                continue
            for node in note_index.nodes(block['source_inline'],block['id']):
                if node['type'] == 'xref' and blocks[node['target_block_id']]['kind'] == 'footnote':
                    target = node['target_block_id']
                    origins = footnotes.setdefault(target, {})
                    if block['id'] not in origins:
                        note_serial += 1
                        anchor = 'b-' + target if not origins else f'note-{note_serial}'
                        origins[block['id']] = (anchor, node['label'])
                        note_links.setdefault(block['id'], {})[target] = anchor

    def rich(nodes, bid=None):
        return inline(note_index.nodes(nodes,bid), atoms, typeset=enhanced,
            references=references if bid not in retained else None,
            note_links=note_links.get(bid))
    def original_image(block, asset_id, *, alternative=None, figure=False):
        path = asset_paths.get(asset_id) or asset_paths.get(alternative)
        if path:
            cls = ' class="figure-image"' if enhanced and figure else ''
            return f'<img{cls} loading="lazy" src="{esc(path)}" alt="{esc(t('原 PDF 图像'))}" style="max-width:100%;height:auto">'
        original = asset_paths.get(source['original_asset_id'])
        if original:
            return f'<a data-original-reference href="{esc(original)}" data-missing-source-label="{esc(t('对照图暂不可用；本次导出未包含原 PDF。'))}">{esc(t('对照图暂不可用，打开原 PDF 查看'))}</a>'
        return f'<p class="note">{esc(t('对照图暂不可用；本次导出未包含原 PDF。'))}</p>'
    def comparison(block):
        attributes = block['attributes']
        asset_id = attributes.get('comparison_asset_id')
        if enhanced and block['kind'] == 'table' and not asset_id:
            asset_id = attributes.get('asset_id')
        if not asset_id:
            return ''
        page = block['provenance'][0]['page'] if block['provenance'] else None
        scope = t('显示整页') if attributes.get('comparison_scope') == 'page' else t('显示对应区域')
        return f'<details class="original-comparison"><summary>{esc(t("查看原文 · 第 {page} 页 · {scope}", page=page or "—", scope=scope))}</summary>{original_image(block,asset_id,alternative=attributes.get("asset_id"))}</details>'
    def pair(block):
        if block['kind'] == 'table_cell' and not block['normalized_text'].strip(): return ''
        result = results[block['id']]
        src = rich(block['source_inline'], block['id'])
        if enhanced and block['kind'] == 'table_cell':
            reason = retained.get(block['id']) or (result['reason'] if result['status'] == 'retained' else '')
            if reason:
                return f'<div class="cell-original" data-original-only="{esc(reason)}">{src}</div>'
            target = (rich(result['target_inline'], block['id']) if result['status'] == 'translated'
                else f'<span lang="{esc(locale)}">{esc(t("此格暂无译文，保留原文："))}</span>'
                + f'<span lang="{esc(block["language"])}">{src}</span>')
            return f'<div class="cell-source" data-language="source" lang="{esc(block["language"])}">{src}</div><div class="cell-target" data-language="target" lang="{esc(tr["target_language"])}">{target}</div>'
        reason = retained.get(block['id']) or (result['reason'] if result['status'] == 'retained' else '')
        if reason:
            return f'<div class="para en original-only" data-original-only="{esc(reason)}" lang="{esc(block["language"])}" style="grid-column:1 / -1"><span class="label">{esc(t('原文'))}</span>{src}</div>'
        content = f'<div class="para en" data-language="source" lang="{esc(block["language"])}"><span class="label">{esc(t('原文'))}</span>{src}</div>'
        if result['status'] == 'translated':
            content += f'<div class="para zh" data-language="target" lang="{esc(tr["target_language"])}"><span class="label">{esc(t('译文'))}</span>{rich(result["target_inline"], block["id"])}</div>'
        elif result['status'] == 'unresolved':
            content += f'<div class="para zh" data-language="target"><strong>{esc(t('DRAFT — 此块译文未完成'))}</strong></div>'
        elif result['status'] == 'fallback':
            content += f'<div class="para zh source-fallback" data-language="target"><strong>{esc(t('此段尚无译文，以下保留原文'))}</strong>' + (f'<div lang="{esc(block["language"])}">{src}</div>' if src else '<div>' + esc(t('此处保留原页图像，请查看原文对照。')) + '</div>') + '</div>'
        return content
    def warnings(block, *, include_comparison=True):
        if block['kind'] == 'table_cell' and not block['normalized_text'].strip():
            return ''  # The table-level original supplies comparison for empty cells.
        notes = block['warnings'] + results[block['id']]['warnings']
        annotations=block['attributes'].get('annotations',[])
        auxiliary=''.join('<details class="parser-annotation"><summary>'+esc(t('模型辅助信息 · {kind}', kind=a['kind']))+'</summary><pre>'+esc(a['value'])+'</pre></details>' for a in annotations)
        if enhanced and (block['kind'] == 'table' or margins and block['kind'] == 'figure'):
            notes = list(dict.fromkeys(notes + [note for child in blocks.values() if child['owner_id'] == block['id']
                for note in child['warnings'] + results[child['id']]['warnings']]))
        rendered = ''.join(f'<p class="note">{esc(diagnostic(note))}</p>' for note in notes)
        if modern and notes:
            rendered = f'<details class="block-notes"><summary>{esc(t("内容提示（{count} 项）", count=len(notes)))}</summary>{rendered}</details>'
        return rendered + auxiliary + (comparison(block) if include_comparison else '')
    def margin_notes(content):
        label = t('脚注、参考文献与内容提示') if sidenotes else t('内容提示与原文对照')
        return f'<aside class="reader-notes" aria-label="{esc(label)}">' + content + '</aside>' if content else ''
    def block_footnotes(bid):
        content = []
        for target, anchor in note_links.get(bid, {}).items():
            label = footnotes[target][bid][1]
            # The canonical entry is in the collected footnotes; side cards have
            # distinct anchors and never duplicate a source block identity.
            anchor='b-'+target+'-at-'+bid
            attrs = ''
            content.append(f'<section class="footnote-card" id="{esc(anchor)}" data-note-target="{esc(target)}"{attrs} role="doc-footnote" tabindex="-1">'
                f'<div class="sidenote-heading">{esc(t("脚注 · {label}", label=label))} <a href="#b-{esc(bid)}" aria-label="{esc(t('返回引用位置'))}">↩</a></div>'
                + pair(blocks[target]) + warnings(blocks[target])
                + f'<a class="reference-source" href="#b-{esc(target)}">{esc(t('在脚注列表中查看'))}</a></section>')
        return ''.join(content)
    def frame(block, content, *, tag='section', css='pair', notes=None):
        attrs = f'id="b-{esc(block["id"])}" data-block-id="{esc(block["id"])}" data-kind="{block["kind"]}"'
        if block['kind']=='footnote':attrs+=' role="doc-footnote" tabindex="-1"'
        notes = warnings(block) if notes is None else notes
        if sidenotes:
            # Figure/table captions and leaf cells are rendered inside this
            # frame. Other children render their own rows and note anchors.
            embedded = list(block['attributes'].get('caption_block_ids',[])) if block['kind'] in {'figure','table'} else []
            if block['kind']=='table':
                embedded += [cell['content_block_id'] for cell in block['attributes'].get('cells',[])
                    if not blocks[cell['content_block_id']]['attributes'].get('children_block_ids')]
            notes = block_footnotes(block['id']) + ''.join(block_footnotes(cid) for cid in embedded) + notes
        if margins:
            return f'<div class="reader-block"><{tag} class="{css}" {attrs}>{content}</{tag}>' + margin_notes(notes) + '</div>'
        return f'<{tag} class="{css}" {attrs}>{content}{notes}</{tag}>'
    def render(bid, *, in_list=False):
        block = blocks[bid]; kind = block['kind']; a = block['attributes']
        attrs = f'id="b-{esc(bid)}" data-block-id="{esc(bid)}" data-kind="{kind}"'
        if bid==source['title_block_id']:return ''
        if kind=='footnote' or bid in metadata:return ''
        if kind=='reference' or retained.get(bid)=='original_reference' and kind!='table_cell':
            return f'<div class="reference-entry" {attrs} data-original-only="original_reference">'+rich(block['source_inline'],bid)+warnings(block)+'</div>'
        if kind=='group':
            if a.get('separator')=='horizontal':return f'<hr {attrs}>'
            children_ids=a.get('children_block_ids',[])
            if a['group_type']=='list':
                tag='ol' if a.get('list_ordered') else 'ul'
                settings=(f' start="{a.get("list_start",1)}"' + (' reversed' if a.get('list_reversed') else '')) if tag=='ol' else ''
                if tag=='ol' and a.get('list_marker') in {'1','a','A','i','I'}:settings+=f' type="{a["list_marker"]}"'
                if tag=='ol' and a.get('list_marker')==')':settings+=' class="semantic-list-custom"'
                return f'<section class="semantic-group" {attrs}><{tag}{settings}>'+''.join(render(cid,in_list=True) for cid in children_ids)+f'</{tag}>'+warnings(block)+'</section>'
            return f'<section class="semantic-group" {attrs}>'+''.join(render(cid) for cid in children_ids)+warnings(block)+'</section>'
        if kind=='list_item' and in_list:
            value=f' value="{a["list_index"]}"' if a.get('list_ordered') and 'list_index' in a else ''
            owner=blocks.get(block['owner_id'])
            if owner and owner['attributes'].get('list_marker')==')':value+=f' data-marker="{esc(str(a.get("list_index",1))+")")}"'
            # A list item's child paragraphs carry its content. The container
            # owns the marker and anchor, but has no bilingual paragraph itself.
            own = pair(block) if block['source_inline'] else ''
            notes = margin_notes(block_footnotes(bid)+warnings(block))
            row = '<div class="reader-block">'+('<div class="pair">'+own+'</div>' if own else '')+notes+'</div>' if own or notes else ''
            return f'<li {attrs}{value}>'+row+''.join(render(cid) for cid in a.get('children_block_ids',[]))+'</li>'
        if kind=='table_cell':
            return ''.join(render(cid) for cid in a.get('children_block_ids',[])) if a.get('children_block_ids') else pair(block)
        if kind=='code' and a.get('representation')=='plain':
            language=f' class="language-{esc(a["code_language"])}"' if a.get('code_language') else ''
            return frame(block,'<pre><code'+language+'>'+esc(block['normalized_text'])+'</code></pre>'+''.join(render(cid) for cid in a.get('caption_block_ids',[])))
        if kind == 'heading':
            level = max(2,min(6,a['level']))
            result = results[bid]
            if result['status'] == 'retained':
                return frame(block, f'<h{level}><span class="en-title" data-original-only="{esc(result["reason"])}" lang="{esc(block["language"])}">{inline(block["source_inline"],atoms)}</span></h{level}>', css='section-heading')
            target = (rich(result['target_inline'], bid) if sidenotes else inline(result['target_inline'],atoms)) if result['status'] == 'translated' else ''
            if result['status'] == 'fallback':
                target = inline(block['source_inline'],atoms) + f'<small class="fallback-label">{esc(t('（原文，暂无译文）'))}</small>'
            return frame(block, f'<h{level}><span class="en-title" data-language="source" lang="{esc(block["language"])}">{rich(block["source_inline"], bid) if sidenotes else inline(block["source_inline"],atoms)}</span><span class="zh-title" data-language="target" lang="{esc(tr["target_language"])}">{target}</span></h{level}>', css='section-heading')
        if kind in {'figure','table'}:
            captions = ''.join(f'<div class="pair" id="b-{esc(cid)}" data-block-id="{esc(cid)}" data-kind="caption">{pair(blocks[cid])}{"" if margins else warnings(blocks[cid],include_comparison=not enhanced)}</div>' for cid in a.get('caption_block_ids',[]))
            if kind == 'figure' or a['representation'] == 'image':
                inner = original_image(block, a['asset_id'], alternative=a.get('comparison_asset_id'),figure=True)
            else:
                starts = {(c['row'],c['column']):c for c in a['cells']}
                rows = []
                for row in range(a['rows']):
                    cells = []
                    for col in range(a['columns']):
                        if (row,col) not in starts:
                            continue
                        cell = starts[(row,col)]; cid = cell['content_block_id']
                        notes = '' if enhanced else warnings(blocks[cid])
                        tag='th' if cell.get('role')=='header' else 'td'
                        scope=f' scope="{esc(cell["scope"])}"' if cell.get('scope') else ''
                        headers=' headers="'+esc(' '.join('b-'+hid for hid in cell.get('header_block_ids',[])))+'"' if cell.get('header_block_ids') else ''
                        cells.append(f'<{tag} id="b-{esc(cid)}" data-block-id="{esc(cid)}" data-kind="table_cell" rowspan="{cell["row_span"]}" colspan="{cell["column_span"]}"{scope}{headers}>{render(cid)}{notes}</{tag}>')
                    rows.append('<tr>'+''.join(cells)+'</tr>')
                groups=a.get('row_groups') or [{'kind':'body','start_row':0,'end_row':len(rows)}]
                sections=[]
                for group in groups:
                    tag={'head':'thead','body':'tbody','foot':'tfoot'}[group['kind']]
                    sections.append('<'+tag+'>'+''.join(rows[group['start_row']:group['end_row']])+'</'+tag+'>')
                columns=''.join(f'<colgroup span="{g["end_column"]-g["start_column"]}"></colgroup>' for g in a.get('column_groups',[]))
                inner='<div class="table-wrap"><table>'+columns+''.join(sections)+'</table></div>'
                if enhanced:
                    inner = f'<p class="table-key">{esc(t('原文在上 · 译文在下 · 数值保留原文'))}</p>' + inner
                if a.get('asset_id') and not enhanced:
                    inner += f'<details><summary>{esc(t('查看原 PDF 表格'))}</summary>' + original_image(block, a['asset_id'], alternative=a.get('comparison_asset_id')) + '</details>'
            notes=''.join(render(cid) for cid in a.get('note_block_ids',[]))
            return frame(block, f'{inner}<figcaption>{captions}</figcaption>'+notes, tag='figure')
        if kind in {'code','math'}:
            auxiliary = ''
            if enhanced and kind == 'math' and a.get('representation') == 'latex':
                number = f'<span class="equation-number">{esc(a["equation_number"])}</span>' if a.get('equation_number') else ''
                return frame(block, f'<div class="equation-row">{math_markup(block["normalized_text"],display=True)}{number}</div>'+''.join(render(cid) for cid in a.get('caption_block_ids',[])+a.get('note_block_ids',[])))
            if modern and (a.get('asset_id') or a.get('comparison_asset_id')):
                inner = original_image(block,a.get('asset_id'),alternative=a.get('comparison_asset_id'))
                if block['normalized_text']:
                    recognized = f'<details><summary>{esc(t('识别文字（仅供辅助对照）'))}</summary><pre><code>{esc(block["normalized_text"])}</code></pre></details>'
                    if margins:
                        auxiliary = recognized
                    else:
                        inner += recognized
            elif a.get('representation') == 'image':
                inner = original_image(block, a['asset_id'])
            else:
                inner = f'<pre style="overflow-x:auto"><code>{esc(block["normalized_text"])}</code></pre>'
            if not modern and a.get('recognition') and a.get('asset_id'):
                inner += f'<details><summary>{esc(t('查看原PDF裁图'))}</summary>' + original_image(block, a['asset_id']) + '</details>'
            note = f'<p class="meta">{esc(t('本地识别的 LaTeX 表示。'))}</p>' if kind == 'math' and a.get('recognition') else f'<p class="meta">{esc(t('保留原式，未推测或重写数学表示。'))}</p>' if kind == 'math' else ''
            return frame(block, f'<div class="para en">{inner}{note}</div>', notes=warnings(block) + auxiliary if margins else None)
        backlinks = ''
        if kind == 'footnote':
            origins = [b['id'] for b in blocks.values() if any(n['type']=='xref' and n['target_block_id']==bid for n in b['source_inline'])]
            backlinks = ''.join(f'<a href="#b-{esc(origin)}" aria-label="{esc(t('返回引用位置'))}">↩</a>' for origin in origins)
        if kind == 'list_item':
            tag = 'ol' if a['list_ordered'] else 'ul'
            start = f' start="{max(1,a.get("list_index",1))}"' if tag == 'ol' else ''
            return f'<{tag}{start}><li class="pair" {attrs}>{pair(block)}{warnings(block)}</li></{tag}>'
        return frame(block, pair(block) + backlinks)
    title = source['title_block_id']
    labels = deepcopy(blocks)
    for block_id, block in labels.items():
        result = results.get(block_id, {})
        if block['kind'] == 'heading' and result.get('status') == 'translated':
            target = flatten_inline(result.get('target_inline', []), source['protected_atoms']).strip()
            original_label = block['normalized_text'].strip()
            if target and target != original_label:
                block['normalized_text'] = target + ' / ' + original_label
    toc = render_toc(source, labels, original_labels=margins, locale=locale)
    metadata = []
    if margins:
        ordered = [b['id'] for b in sorted(blocks.values(),key=lambda b:b['order'])]
        for bid in ordered[ordered.index(title) + 1:] if title in ordered else []:
            if blocks[bid]['kind'] in {'group','footnote'}:continue
            reason = retained.get(bid) or (results[bid]['reason'] if results[bid]['status'] == 'retained' else '')
            if reason not in {'original_author_list', 'original_affiliation', 'original_contact', 'original_identifier'}:
                break
            metadata.append(bid)
    title_metadata = '<div class="title-metadata">' + ''.join(
        f'<div id="b-{esc(bid)}" data-block-id="{esc(bid)}" data-kind="{blocks[bid]["kind"]}" data-original-only="{esc(retained.get(bid) or results[bid]["reason"])}" lang="{esc(blocks[bid]["language"])}">{rich(blocks[bid]["source_inline"], bid)}</div>'
        for bid in metadata) + '</div>' if metadata else ''
    if enhanced:
        sections, bibliography, list_items = [], [], []
        def list_entry(bid):
            block = blocks[bid]
            marker = r'^\s*(?:(?:\d+|[A-Za-z])[.)]|\(\d+\))\s+' if block['attributes']['list_ordered'] else r'^\s*[-*•·▪]\s+'
            cls = ' class="list-literal-marker"' if re.match(marker, block['normalized_text']) else ''
            if sidenotes:
                return (f'<li{cls} id="b-{esc(bid)}" data-block-id="{esc(bid)}" data-kind="list_item">'
                    f'<div class="reader-block"><div class="pair">{pair(block)}</div>'
                    + margin_notes(block_footnotes(bid) + warnings(block)) + '</div></li>')
            return f'<li{cls} id="b-{esc(bid)}" data-block-id="{esc(bid)}" data-kind="list_item">{pair(block)}</li>'
        def flush_list():
            if not list_items:
                return
            first = blocks[list_items[0]]
            tag = 'ol' if first['attributes']['list_ordered'] else 'ul'
            start = f' start="{max(1, first["attributes"].get("list_index", 1))}"' if tag == 'ol' else ''
            items = ''.join(list_entry(bid) for bid in list_items)
            notes = ''.join(dict.fromkeys(warnings(blocks[bid]) for bid in list_items))
            if sidenotes:
                sections.append(f'<section class="reader-list sidenote-list"><{tag}{start}>{items}</{tag}></section>')
            else:
                sections.append(f'<div class="reader-block"><section class="pair reader-list"><{tag}{start}>{items}</{tag}></section>' + margin_notes(notes) + '</div>')
            list_items.clear()
        def flush_references():
            if not bibliography:
                return
            entries = ''.join(f'<div class="reference-entry" id="b-{esc(bid)}" data-block-id="{esc(bid)}" data-kind="reference" data-original-only="original_reference">{rich(blocks[bid]["source_inline"], bid)}</div>' for bid in bibliography)
            comparisons = {}
            for bid in bibliography:
                block = blocks[bid]
                aid = block['attributes'].get('comparison_asset_id')
                if aid:
                    comparisons.setdefault(aid, block)
            proof = ''.join(original_image(block, aid) for aid,block in comparisons.items())
            details = f'<details class="original-comparison"><summary>{esc(t('查看参考文献原页'))}</summary>' + proof + '</details>' if proof else ''
            content = f'<section class="bibliography" aria-label="{esc(t('参考文献'))}">' + entries + ('' if margins else details) + '</section>'
            sections.append('<div class="reader-block">' + content + margin_notes(details) + '</div>' if margins else content)
            bibliography.clear()
        for bid in source['reading_order']:
            if bid == title or bid in metadata:
                continue
            if retained.get(bid) == 'original_reference':
                flush_list()
                bibliography.append(bid)
            else:
                flush_references()
                block = blocks[bid]
                if margins and block['kind'] == 'list_item':
                    previous = blocks[list_items[-1]] if list_items else None
                    if previous and (previous['parent_id'] != block['parent_id']
                            or previous['attributes']['list_ordered'] != block['attributes']['list_ordered']
                            or block['attributes'].get('list_ordered') and 'list_index' in block['attributes']
                            and block['attributes']['list_index'] != previous['attributes'].get('list_index', 1) + 1):
                        flush_list()
                    list_items.append(bid)
                else:
                    flush_list()
                    sections.append(render(bid))
        flush_references()
        flush_list()
        body = ''.join(sections)
    else:
        body = ''.join(render(bid) for bid in source['reading_order'] if bid != title)
    collected_notes = []
    for block in sorted(blocks.values(),key=lambda block:block['order']):
        if block['kind'] != 'footnote':continue
        bid=block['id']
        backlinks=''.join(f'<a href="#b-{esc(origin)}" aria-label="{esc(t('返回引用位置'))}">↩</a>' for origin in footnotes.get(bid,{}))
        collected_notes.append(f'<section class="footnote-entry" id="b-{esc(bid)}" data-block-id="{esc(bid)}" data-kind="footnote" role="doc-footnote" tabindex="-1">'
            + '<div class="reader-block"><div class="pair">'+pair(block)+'</div>'
            + margin_notes(warnings(block))+'</div>'+backlinks+'</section>')
    if collected_notes:
        body += f'<section class="footnotes" aria-label="{esc(t('脚注'))}" role="doc-endnotes"><h2>{esc(t('脚注'))}</h2>'+''.join(collected_notes)+'</section>'
    original = f'<a href="{esc(asset_paths[source["original_asset_id"]])}" download>{esc(t('原文 PDF'))}</a>' if include_source else ''
    draft = sum(r['status'] in {'unresolved','fallback'} for r in results.values())
    draft_notice = f'<p class="note" role="status">{esc(t("DRAFT — 未完成草稿，缺失 {count} 块译文", count=draft))}</p>' if ir['render']['mode']=='draft' else ''
    display_title = t('DRAFT — 标题译文未完成') if ir['render']['mode'] == 'draft' and results[title]['status'] == 'unresolved' else tr['title']
    display_title = display_title or t('原文 PDF')
    title_markup, source_title_markup = esc(display_title), esc(ir['document']['title'])
    if sidenotes:
        source_title_markup = rich(blocks[title]['source_inline'], title)
        if results[title]['status'] == 'translated':
            title_markup = rich(results[title]['target_inline'], title)
    panel = ''
    if modern:
        findings = []
        for block in source['blocks']:
            notes = block['warnings'] + results[block['id']]['warnings']
            if not notes: continue
            page = block['provenance'][0]['page'] if block['provenance'] else None
            level = 'important' if results[block['id']]['status'] == 'fallback' or any(re.search(r'NUMBER|MISSING|PROTECTED|TABLE|缺|数字', n) for n in notes) else 'general'
            category = 'numeric' if any(re.search(r'NUMBER|数字', n) for n in notes) else block['kind']
            findings.append((block['id'], page, level, category, notes))
        category_names = {'numeric':t('数字'), 'heading':t('标题'), 'paragraph':t('段落'), 'table':t('表格'), 'table_cell':t('表格单元格'), 'code':t('代码'), 'math':t('公式'), 'figure':t('图片'), 'caption':t('图注'), 'list_item':t('列表'), 'footnote':t('脚注'), 'reference':t('参考文献'), 'group':t('分组')}
        options = lambda values: ''.join(f'<option value="{esc(v)}">{esc(category_names.get(v, v))}</option>' for v in sorted(set(values)))
        items = ''.join(f'<li data-issue data-severity="{level}" data-page="{page or ""}" data-category="{category}"><a href="#b-{esc(bid)}">{esc(t("第 {page} 页 · 重要提示" if level == "important" else "第 {page} 页 · 一般提示", page=page or "—"))}</a><details><summary>{esc(t("查看说明（{count} 项）", count=len(notes)))}</summary>'+''.join(f'<p>{esc(diagnostic(n))}</p>' for n in notes)+'</details></li>' for bid,page,level,category,notes in findings)
        panel = f'<section class="issue-panel" aria-label="{esc(t('内容提示'))}"><h2>{esc(t('内容提示'))}</h2><p>{esc(t('提示不影响阅读、发布或导出。暂无译文的段落已明确标注并保留原文。'))}</p>'
        if findings:
            panel += f'<div class="issue-filters"><label>{esc(t('重要性'))}<select data-issue-filter="severity"><option value="">{esc(t('全部'))}</option><option value="important">{esc(t('重要'))}</option><option value="general">{esc(t('一般'))}</option></select></label><label>{esc(t('页码'))}<select data-issue-filter="page"><option value="">{esc(t('全部页'))}</option>'+options(str(x[1]) for x in findings if x[1])+f'</select></label><label>{esc(t('类型'))}<select data-issue-filter="category"><option value="">{esc(t('全部类型'))}</option>'+options(x[3] for x in findings)+'</select></label></div><ul>'+items+f'</ul><p data-issue-empty hidden>{esc(t('此筛选下没有提示。'))}</p>'
        else: panel += f'<p>{esc(t('未发现需要提示的内容差异。'))}</p>'
        panel += '</section>'
    title_notes = ''
    if margins:
        overview = '<details class="reader-guide"><summary>' + esc(t('内容提示 · {count} 块', count=len(findings)) if findings else t('内容提示')) + '</summary>' + panel + '</details>'
        title_notes = margin_notes(block_footnotes(title) + ''.join(block_footnotes(bid) for bid in metadata)
            + overview + warnings(blocks[title]) + ''.join(warnings(blocks[bid]) for bid in metadata))
    font_controls = (f'<div class="font-controls" role="group" aria-label="{esc(t('字体与字号'))}">'
        f'<label class="font-picker">{esc(t('字体'))}<select data-font-select title="{esc(t('MiSans 已内置；其他选项使用本机字体。'))}">'
        f'<option value="default">{esc(t('默认（MiSans）'))}</option><option value="serif">{esc(t('衬线'))}</option>'
        f'<option value="sans">{esc(t('无衬线'))}</option><option value="monospace">{esc(t('等宽'))}</option>'
        f'<option value="fz-song">{esc(t('方正宋体'))}</option><option value="fz-hei">{esc(t('方正黑体'))}</option>'
        f'<option value="source-han-serif">{esc(t('思源宋体'))}</option><option value="source-han-sans">{esc(t('思源黑体'))}</option>'
        f'<option value="misans">MiSans</option><option value="harmonyos-sans">{esc(t('鸿蒙黑体'))}</option>'
        '<option value="noto-sans-sc">Noto Sans Simplified Chinese</option></select></label>'
        f'<button data-action="smaller" aria-label="{esc(t('减小字号'))}">A−</button>'
        f'<button data-action="larger" aria-label="{esc(t('增大字号'))}">A＋</button></div>')
    code_fonts = (f'<label class="font-picker code-font-picker">{esc(t('代码字体'))}'
        f'<select data-code-font-select title="{esc(t('JetBrains Mono 已内置；其他选项使用本机字体。'))}">'
        f'<option value="default">{esc(t('JetBrains Mono（默认）'))}</option>'
        '<option value="fira-code">Fira Code</option><option value="cascadia-code">Cascadia Code</option>'
        '<option value="source-code-pro">Source Code Pro</option><option value="ibm-plex-mono">IBM Plex Mono</option>'
        '<option value="consolas">Consolas</option><option value="menlo">Menlo</option>'
        f'<option value="monospace">{esc(t('系统等宽'))}</option></select></label>')
    spacing_options = ''.join('<option value="' + value + '"' + (' selected' if value == '1.72' else '')
        + '>' + esc(t('{value} 倍（默认）' if value == '1.72' else '{value} 倍', value=value)) + '</option>'
        for value in ('1.4', '1.72', '2', '2.4'))
    preferences = (code_fonts + f'<label class="spacing-picker">{esc(t('行距'))}<select data-line-height-select>'
        + spacing_options + f'</select></label><label class="theme-picker">{esc(t('主题'))}<select data-theme-select>'
        f'<option value="system">{esc(t('跟随系统'))}</option><option value="light">{esc(t('浅色'))}</option>'
        f'<option value="dark">{esc(t('深色'))}</option></select></label>')
    licenses = ''.join('<details><summary>' + esc(t('{font} 字体许可', font=label)) + '</summary><pre>'
        + esc((ROOT / 'res/vendor/reader-fonts' / filename).read_text('utf-8')) + '</pre></details>'
        for label, filename in [('MiSans', 'MiSans-LICENSE.txt'), ('JetBrains Mono', 'JetBrainsMono-OFL.txt')])
    font_notice = f'<footer class="reader-font-notice">{esc(t('本页使用 MiSans 与 JetBrains Mono 字体。'))}' + licenses + '</footer>'
    destination = '/#/documents/' + quote(ir['document']['id'], safe='')
    navigation = (f'<nav class="reader-return" data-online-reader aria-label="{esc(t('返回文库'))}">'
                  '<a data-return-document href="' + esc(destination) + f'">{esc(t('返回文档'))}</a>'
                  f'<a data-return-search hidden>{esc(t('返回搜索结果'))}</a></nav>')
    locale_data = '<script type="application/json" id="reader-i18n-data">' + reader_messages_json(locale) + '</script>'
    return ('<!doctype html>\n<html lang="'+esc(locale)+'"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' data:; font-src \'self\' data:; style-src \'self\' \'unsafe-inline\'; script-src \'self\'; connect-src \'none\'; base-uri \'none\'; form-action \'none\'; object-src \'none\'">'
            '<title>'+esc(display_title)+'</title><link rel="stylesheet" href="reader.css">'+('<script src="math.js" defer></script>' if enhanced else '')+'<script src="reader.js" defer></script></head><body style="overflow-wrap:anywhere">'
            + navigation + f'<nav class="toolbar" aria-label="{esc(t('阅读设置'))}"><button data-action="both" data-view aria-pressed="true">{esc(t('双语'))}</button><button data-action="source" data-view aria-pressed="false">{esc(t('原文'))}</button><button data-action="target" data-view aria-pressed="false">{esc(t('译文'))}</button>'+font_controls+preferences+original+'</nav>'+('<div class="reader-header">' if margins else '')+
            '<header class="hero" id="b-'+esc(title)+'" data-block-id="'+esc(title)+'" data-kind="heading"><div class="kicker">'+esc(t('对照文库 · {source} / {target}', source=reader_language_name(source['language'], locale), target=reader_language_name(tr['target_language'], locale)))+'</div>'
            '<h1 data-language="target" lang="'+esc(tr['target_language'])+'">'+title_markup+'</h1><p class="original-title" data-language="source" lang="'+esc(source['language'])+'">'+source_title_markup+'</p>'+title_metadata+'<p class="note">'+esc(diagnostic(ir['document']['notice']))+'</p>'+draft_notice+('' if margins else warnings(blocks[title]))+'</header>'+(title_notes+'</div>' if margins else '')+
            f'<p id="reader-storage-notice" class="note" hidden>{esc(t('浏览器存储不可用；正文仍可完整阅读。'))}</p><div class="layout"><aside class="toc" aria-label="{esc(t('文章目录'))}"><h2>{esc(t('目录'))}</h2>'+toc+('' if margins else panel)+'</aside><article>'+body+'</article></div>'+font_notice+locale_data+'</body></html>\n').encode('utf-8')
