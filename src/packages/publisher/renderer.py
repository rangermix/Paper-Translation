"""Deterministic, offline publication. Pointer commits belong to the database layer."""
from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from packages.ir import canonical_bytes, digest, safe_path, strict_loads, validate_ir
from packages.translation.languages import language_name

from packages.paths import ROOT
CSS_HASH = '51dacbcd96a21214ed83a62cad870a6281eb20db1aa260f3a7d782c58fdd18a8'
RENDERER_VERSION = 'reader-python-9.0.0'
EXTENSIONS = {'image/png':'.png', 'image/jpeg':'.jpg', 'image/webp':'.webp', 'application/pdf':'.pdf'}


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
    def reference_link(content, targets):
        return (f'<a class="reference-link" href="#b-{esc(targets[0])}" '
            f'data-reference-targets="{esc(" ".join(targets))}">{content}</a>')

    if references:
        pieces = []
        for segment, targets in references.segments(nodes, atoms):
            content = inline(segment, atoms, typeset=typeset, note_links=note_links)
            pieces.append(reference_link(content, targets) if targets else content)
        return ''.join(pieces)

    out = []
    for node in nodes:
        kind = node['type']
        if kind == 'text':
            text = esc(node['text'])
            for mark in node.get('marks', []):
                tag = {'strong':'strong','emphasis':'em','code':'code'}[mark]
                text = f'<{tag}>{text}</{tag}>'
            out.append(text)
        elif kind == 'protected_ref':
            atom = atoms[node['ref']]
            content = math_markup(atom['value']) if typeset and atom['kind'] == 'math' and atom['value'].strip().startswith(('$','\\(','\\[')) else esc(atom['value'])
            out.append(f'<span class="protected" data-kind="{esc(atom["kind"])}">{content}</span>')
        elif kind == 'link':
            out.append(f'<a href="{esc(node["href"])}" rel="noreferrer noopener">{esc(node["text"])}</a>')
        elif kind == 'xref':
            target = node['target_block_id']
            if note_links and target in note_links:
                marker = ' data-footnote-marker' if re.fullmatch(r'[0-9]{1,3}|[*†‡§¶]', node['label']) else ''
                out.append(f'<a class="footnote-link" href="#{esc(note_links[target])}" role="doc-noteref"{marker}>{esc(node["label"])}</a>')
            else:
                out.append(f'<a href="#b-{esc(target)}">{esc(node["label"])}</a>')
    return ''.join(out)


def render_toc(source, blocks, *, original_labels=False):
    tree, stack = [], []
    for bid in source['reading_order']:
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
    return '<nav class="toc-sections" aria-label="原文章节">' + rendered + '</nav>' if original_labels else rendered


def render_html(ir, asset_paths, *, include_source=False):
    validate_ir(ir)
    source, tr = ir['source_revision'], ir['translation_revision']
    blocks = {b['id']:b for b in source['blocks']}
    results = {r['block_id']:r for r in tr['results']}
    atoms = source['protected_atoms']
    sidenotes = ir['render']['template_id'] in {'reader-v8', 'reader-v9'}
    named_fonts = sidenotes or ir['render']['template_id'] == 'reader-v7'
    font_selection = named_fonts or ir['render']['template_id'] == 'reader-v6'
    margins = font_selection or ir['render']['template_id'] == 'reader-v5'
    enhanced = margins or ir['render']['template_id'] == 'reader-v4'
    modern = enhanced or ir['render']['template_id'] == 'reader-v3'
    from packages.ir.retention import original_only_blocks
    retained = original_only_blocks(source) if enhanced else {}
    references, markers, footnotes, note_links, children = None, None, {}, {}, {}
    if sidenotes:
        from packages.publisher.references import ReferenceIndex
        from packages.publisher.footnotes import FootnoteIndex
        references = ReferenceIndex(source['blocks'], retained)
        markers = FootnoteIndex(source['blocks'], retained)
        note_serial = 0
        for block in sorted(blocks.values(), key=lambda block: block['order']):
            if block['owner_id']:
                children.setdefault(block['owner_id'], []).append(block['id'])
            if block['kind'] in {'footnote', 'reference', 'code', 'math'} or retained.get(block['id']) == 'original_reference':
                continue
            for node in markers.annotate(block['source_inline'], block['id']):
                if node['type'] == 'xref' and blocks[node['target_block_id']]['kind'] == 'footnote':
                    target = node['target_block_id']
                    origins = footnotes.setdefault(target, {})
                    if block['id'] not in origins:
                        note_serial += 1
                        anchor = 'b-' + target if not origins else f'note-{note_serial}'
                        origins[block['id']] = (anchor, node['label'])
                        note_links.setdefault(block['id'], {})[target] = anchor

    def rich(nodes, bid=None):
        return inline(markers.annotate(nodes, bid) if markers else nodes, atoms, typeset=enhanced,
            references=references if bid not in retained else None,
            note_links=note_links.get(bid))
    def original_image(block, asset_id, *, alternative=None, figure=False):
        path = asset_paths.get(asset_id) or asset_paths.get(alternative)
        if path:
            cls = ' class="figure-image"' if enhanced and figure else ''
            return f'<img{cls} loading="lazy" src="{esc(path)}" alt="原 PDF 图像" style="max-width:100%;height:auto">'
        original = asset_paths.get(source['original_asset_id'])
        if original:
            return f'<a data-original-reference href="{esc(original)}">对照图暂不可用，打开原 PDF 查看</a>'
        return '<p class="note">对照图暂不可用；本次导出未包含原 PDF。</p>'
    def comparison(block):
        attributes = block['attributes']
        asset_id = attributes.get('comparison_asset_id')
        if enhanced and block['kind'] == 'table' and not asset_id:
            asset_id = attributes.get('asset_id')
        if not asset_id:
            return ''
        page = block['provenance'][0]['page'] if block['provenance'] else None
        scope = '显示整页' if attributes.get('comparison_scope') == 'page' else '显示对应区域'
        return f'<details class="original-comparison"><summary>查看原文 · 第 {page or "—"} 页 · {scope}</summary>{original_image(block,asset_id,alternative=attributes.get("asset_id"))}</details>'
    def pair(block):
        if block['kind'] == 'table_cell' and not block['normalized_text'].strip(): return ''
        result = results[block['id']]
        src = rich(block['source_inline'], block['id'])
        if enhanced and block['kind'] == 'table_cell':
            reason = retained.get(block['id']) or (result['reason'] if result['status'] == 'retained' else '')
            if reason:
                return f'<div class="cell-original" data-original-only="{esc(reason)}">{src}</div>'
            target = rich(result['target_inline'], block['id']) if result['status'] == 'translated' else '此格暂无译文，保留原文：' + src
            return f'<div class="cell-source" data-language="source">{src}</div><div class="cell-target" data-language="target">{target}</div>'
        if result['status'] == 'retained':
            return f'<div class="para en original-only" data-original-only="{esc(result["reason"])}" lang="{esc(block["language"])}" style="grid-column:1 / -1"><span class="label">原文</span>{src}</div>'
        content = f'<div class="para en" data-language="source" lang="{esc(block["language"])}"><span class="label">原文</span>{src}</div>'
        if result['status'] == 'translated':
            content += f'<div class="para zh" data-language="target" lang="{esc(tr["target_language"])}"><span class="label">译文</span>{rich(result["target_inline"], block["id"])}</div>'
        elif result['status'] == 'unresolved':
            content += '<div class="para zh" data-language="target"><strong>DRAFT — 此块译文未完成</strong></div>'
        elif result['status'] == 'fallback':
            content += '<div class="para zh source-fallback" data-language="target"><strong>此段尚无译文，以下保留原文</strong><div>' + (src or '此处保留原页图像，请查看原文对照。') + '</div></div>'
        return content
    def warnings(block, *, include_comparison=True):
        if block['kind'] == 'table_cell' and not block['normalized_text'].strip():
            return ''  # The table-level original supplies comparison for empty cells.
        notes = block['warnings'] + results[block['id']]['warnings']
        if enhanced and (block['kind'] == 'table' or margins and block['kind'] == 'figure'):
            notes = list(dict.fromkeys(notes + [note for child in blocks.values() if child['owner_id'] == block['id']
                for note in child['warnings'] + results[child['id']]['warnings']]))
        rendered = ''.join(f'<p class="note">{esc(note)}</p>' for note in notes)
        if modern and notes:
            rendered = f'<details class="block-notes"><summary>{len(notes)} 项内容提示</summary>{rendered}</details>'
        return rendered + (comparison(block) if include_comparison else '')
    def margin_notes(content):
        label = '脚注、参考文献与内容提示' if sidenotes else '内容提示与原文对照'
        return f'<aside class="reader-notes" aria-label="{label}">' + content + '</aside>' if content else ''
    def block_footnotes(bid):
        content = []
        for target, anchor in note_links.get(bid, {}).items():
            label = footnotes[target][bid][1]
            attrs = f' data-block-id="{esc(target)}" data-kind="footnote"' if anchor == 'b-' + target else ''
            content.append(f'<section class="footnote-card" id="{esc(anchor)}" data-note-target="{esc(target)}"{attrs} role="doc-footnote" tabindex="-1">'
                f'<div class="sidenote-heading">脚注 · {esc(label)} <a href="#b-{esc(bid)}" aria-label="返回引用位置">↩</a></div>'
                + pair(blocks[target]) + warnings(blocks[target]) + '</section>')
        return ''.join(content)
    def frame(block, content, *, tag='section', css='pair', notes=None):
        attrs = f'id="b-{esc(block["id"])}" data-block-id="{esc(block["id"])}" data-kind="{block["kind"]}"'
        notes = warnings(block) if notes is None else notes
        if sidenotes:
            notes = block_footnotes(block['id']) + ''.join(block_footnotes(cid) for cid in children.get(block['id'], [])) + notes
        if margins:
            return f'<div class="reader-block"><{tag} class="{css}" {attrs}>{content}</{tag}>' + margin_notes(notes) + '</div>'
        return f'<{tag} class="{css}" {attrs}>{content}{notes}</{tag}>'
    def render(bid):
        block = blocks[bid]; kind = block['kind']; a = block['attributes']
        attrs = f'id="b-{esc(bid)}" data-block-id="{esc(bid)}" data-kind="{kind}"'
        if kind == 'heading':
            level = max(2,min(6,a['level']))
            result = results[bid]
            if result['status'] == 'retained':
                return frame(block, f'<h{level}><span class="en-title" data-original-only="{esc(result["reason"])}" lang="{esc(block["language"])}">{inline(block["source_inline"],atoms)}</span></h{level}>', css='section-heading')
            target = (rich(result['target_inline'], bid) if sidenotes else inline(result['target_inline'],atoms)) if result['status'] == 'translated' else ''
            if result['status'] == 'fallback':
                target = inline(block['source_inline'],atoms) + '<small class="fallback-label">（原文，暂无译文）</small>'
            return frame(block, f'<h{level}><span class="en-title" data-language="source">{rich(block["source_inline"], bid) if sidenotes else inline(block["source_inline"],atoms)}</span><span class="zh-title" data-language="target">{target}</span></h{level}>', css='section-heading')
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
                        cells.append(f'<td id="b-{esc(cid)}" data-block-id="{esc(cid)}" data-kind="table_cell" rowspan="{cell["row_span"]}" colspan="{cell["column_span"]}">{pair(blocks[cid])}{notes}</td>')
                    rows.append('<tr>'+''.join(cells)+'</tr>')
                inner = '<div class="table-wrap" style="overflow-x:auto;max-width:100%"><table><tbody>'+''.join(rows)+'</tbody></table></div>'
                if enhanced:
                    inner = '<p class="table-key">原文在上 · 译文在下 · 数值保留原文</p>' + inner
                if a.get('asset_id') and not enhanced:
                    inner += '<details><summary>查看原 PDF 表格</summary>' + original_image(block, a['asset_id'], alternative=a.get('comparison_asset_id')) + '</details>'
            return frame(block, f'{inner}<figcaption>{captions}</figcaption>', tag='figure')
        if kind in {'code','math'}:
            auxiliary = ''
            if enhanced and kind == 'math' and a.get('representation') == 'latex':
                number = f'<span class="equation-number">{esc(a["equation_number"])}</span>' if a.get('equation_number') else ''
                return frame(block, f'<div class="equation-row">{math_markup(block["normalized_text"],display=True)}{number}</div>')
            if modern and (a.get('asset_id') or a.get('comparison_asset_id')):
                inner = original_image(block,a.get('asset_id'),alternative=a.get('comparison_asset_id'))
                if block['normalized_text']:
                    recognized = f'<details><summary>识别文字（仅供辅助对照）</summary><pre><code>{esc(block["normalized_text"])}</code></pre></details>'
                    if margins:
                        auxiliary = recognized
                    else:
                        inner += recognized
            elif a.get('representation') == 'image':
                inner = original_image(block, a['asset_id'])
            else:
                inner = f'<pre style="overflow-x:auto"><code>{esc(block["normalized_text"])}</code></pre>'
            if not modern and a.get('recognition') and a.get('asset_id'):
                inner += '<details><summary>查看原PDF裁图</summary>' + original_image(block, a['asset_id']) + '</details>'
            note = '<p class="meta">本地识别的 LaTeX 表示。</p>' if kind == 'math' and a.get('recognition') else '<p class="meta">保留原式，未推测或重写数学表示。</p>' if kind == 'math' else ''
            return frame(block, f'<div class="para en">{inner}{note}</div>', notes=warnings(block) + auxiliary if margins else None)
        backlinks = ''
        if kind == 'footnote':
            origins = [b['id'] for b in blocks.values() if any(n['type']=='xref' and n['target_block_id']==bid for n in b['source_inline'])]
            backlinks = ''.join(f'<a href="#b-{esc(origin)}" aria-label="返回引用位置">↩</a>' for origin in origins)
        if kind == 'list_item':
            tag = 'ol' if a['list_ordered'] else 'ul'
            start = f' start="{max(1,a.get("list_index",1))}"' if tag == 'ol' else ''
            return f'<{tag}{start}><li class="pair" {attrs}>{pair(block)}{warnings(block)}</li></{tag}>'
        return frame(block, pair(block) + backlinks)
    title = source['title_block_id']
    toc = render_toc(source, blocks, original_labels=margins)
    metadata = []
    if margins:
        for bid in source['reading_order'][source['reading_order'].index(title) + 1:]:
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
            details = '<details class="original-comparison"><summary>查看参考文献原页</summary>' + proof + '</details>' if proof else ''
            content = '<section class="bibliography" aria-label="参考文献">' + entries + ('' if margins else details) + '</section>'
            sections.append('<div class="reader-block">' + content + margin_notes(details) + '</div>' if margins else content)
            bibliography.clear()
        for bid in source['reading_order']:
            if bid == title or bid in metadata or sidenotes and bid in footnotes:
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
    original = f'<a href="{esc(asset_paths[source["original_asset_id"]])}" download>原始 PDF</a>' if include_source else ''
    draft = sum(r['status'] in {'unresolved','fallback'} for r in results.values())
    draft_notice = f'<p class="note" role="status">DRAFT — 未完成草稿，缺失 {draft} 块译文</p>' if ir['render']['mode']=='draft' else ''
    display_title = 'DRAFT — 标题译文未完成' if ir['render']['mode'] == 'draft' and results[title]['status'] == 'unresolved' else tr['title']
    display_title = display_title or '原 PDF'
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
        category_names = {'numeric':'数字', 'heading':'标题', 'paragraph':'段落', 'table':'表格', 'table_cell':'表格单元格', 'code':'代码', 'math':'公式', 'figure':'图片', 'caption':'图注', 'list_item':'列表', 'footnote':'脚注', 'reference':'参考文献'}
        options = lambda values: ''.join(f'<option value="{esc(v)}">{esc(category_names.get(v, v))}</option>' for v in sorted(set(values)))
        items = ''.join(f'<li data-issue data-severity="{level}" data-page="{page or ""}" data-category="{category}"><a href="#b-{esc(bid)}">第 {page or "—"} 页 · {"重要" if level == "important" else "一般"}提示</a><details><summary>查看说明（{len(notes)} 项）</summary>'+''.join(f'<p>{esc(n)}</p>' for n in notes)+'</details></li>' for bid,page,level,category,notes in findings)
        panel = '<section class="issue-panel" aria-label="内容提示"><h2>内容提示</h2><p>提示不影响阅读、发布或导出。暂无译文的段落已明确标注并保留原文。</p>'
        if findings:
            panel += '<div class="issue-filters"><label>重要性<select data-issue-filter="severity"><option value="">全部</option><option value="important">重要</option><option value="general">一般</option></select></label><label>页码<select data-issue-filter="page"><option value="">全部页</option>'+options(str(x[1]) for x in findings if x[1])+'</select></label><label>类型<select data-issue-filter="category"><option value="">全部类型</option>'+options(x[3] for x in findings)+'</select></label></div><ul>'+items+'</ul><p data-issue-empty hidden>此筛选下没有提示。</p>'
        else: panel += '<p>未发现需要提示的内容差异。</p>'
        panel += '</section>'
    title_notes = ''
    if margins:
        overview = '<details class="reader-guide"><summary>内容提示' + (f' · {len(findings)} 块' if findings else '') + '</summary>' + panel + '</details>'
        title_notes = margin_notes(block_footnotes(title) + ''.join(block_footnotes(bid) for bid in metadata)
            + overview + warnings(blocks[title]) + ''.join(warnings(blocks[bid]) for bid in metadata))
    font_controls = '<button data-action="smaller" aria-label="减小字号">A−</button><button data-action="larger" aria-label="增大字号">A＋</button>'
    if font_selection:
        font_options = ''
        font_hint = ''
        if named_fonts:
            font_options = ('<option value="fz-song">方正宋体</option><option value="fz-hei">方正黑体</option>'
                '<option value="source-han-serif">思源宋体</option><option value="source-han-sans">思源黑体</option>'
                '<option value="misans">MiSans</option><option value="harmonyos-sans">鸿蒙黑体</option>'
                '<option value="noto-sans-sc">Noto Sans Simplified Chinese</option>')
            font_hint = ' title="使用本机字体；未安装时使用备用字体。"'
        font_controls = ('<div class="font-controls" role="group" aria-label="字体与字号">'
            '<label class="font-picker">字体<select data-font-select' + font_hint + '>'
            '<option value="default">默认</option><option value="serif">衬线</option>'
            '<option value="sans">无衬线</option><option value="monospace">等宽</option>' + font_options +
            '</select></label>' + font_controls + '</div>')
    return ('<!doctype html>\n<html lang="'+esc(tr['target_language'])+'"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' data:; style-src \'self\' \'unsafe-inline\'; script-src \'self\'; connect-src \'none\'; base-uri \'none\'; form-action \'none\'; object-src \'none\'">'
            '<title>'+esc(display_title)+'</title><link rel="stylesheet" href="reader.css">'+('<script src="math.js" defer></script>' if enhanced else '')+'<script src="reader.js" defer></script></head><body style="overflow-wrap:anywhere">'
            '<nav class="toolbar" aria-label="阅读设置"><button data-action="both" data-view aria-pressed="true">双语</button><button data-action="source" data-view aria-pressed="false">原文</button><button data-action="target" data-view aria-pressed="false">译文</button>'+font_controls+'<button data-action="theme">切换主题</button>'+original+'</nav>'+('<div class="reader-header">' if margins else '')+
            '<header class="hero" id="b-'+esc(title)+'" data-block-id="'+esc(title)+'" data-kind="heading"><div class="kicker">对照文库 · '+esc(language_name(source['language']))+' / '+esc(language_name(tr['target_language']))+'</div>'
            '<h1 data-language="target">'+title_markup+'</h1><p class="original-title" data-language="source">'+source_title_markup+'</p>'+title_metadata+'<p class="note">'+esc(ir['document']['notice'])+'</p>'+draft_notice+('' if margins else warnings(blocks[title]))+'</header>'+(title_notes+'</div>' if margins else '')+
            '<p id="reader-storage-notice" class="note" hidden>浏览器存储不可用；正文仍可完整阅读。</p><div class="layout"><aside class="toc" aria-label="文章目录"><h2>目录</h2>'+toc+('' if margins else panel)+'</aside><article>'+body+'</article></div></body></html>\n').encode('utf-8')


class Publisher:
    def build(self, ir, asset_root, output_dir, *, include_source=False, qa_fingerprint=None):
        validate_ir(ir, asset_root)
        from packages.templates.registry import get_template
        from packages.domain.errors import DomainError
        try:
            template = get_template(ir['render']['template_id'])
        except DomainError as exc:
            raise ValueError(exc.code) from exc
        if ir['render']['template_sha256'] != template['css_sha256']:
            raise ValueError('TEMPLATE_HASH_MISMATCH')
        if any(block['kind'] not in template['kinds'] for block in ir['source_revision']['blocks']):
            raise ValueError('TEMPLATE_UNSUPPORTED_KIND')
        css, js = (ROOT/template['css_path']).read_bytes(), (ROOT/template['js_path']).read_bytes()
        if digest(css) != template['css_sha256'] or digest(js) != template['js_sha256']:
            raise ValueError('TEMPLATE_HASH_MISMATCH')
        target = Path(output_dir)
        if target.exists():
            raise FileExistsError('immutable artifact exists')
        target.parent.mkdir(parents=True,exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.build-',dir=target.parent))
        try:
            files = {'reader.css':css, 'reader.js':js}
            types = {'index.html':'text/html','reader.css':'text/css','reader.js':'text/javascript'}
            for extra in template.get('extra_assets', []):
                content = (ROOT / extra['source']).read_bytes()
                if digest(content) != extra['sha256']:
                    raise ValueError('TEMPLATE_HASH_MISMATCH')
                files[extra['path']] = content
                types[extra['path']] = extra['media_type']
            paths = {}
            original = ir['source_revision']['original_asset_id']
            for asset in ir['source_revision']['assets']:
                if asset['id'] == original and not include_source:
                    continue
                if ir['translation_revision'].get('content_policy') == 'nonblocking-v1' and asset['id'] != original and not safe_path(asset_root,asset['storage_key'],must_exist=False).exists():
                    continue
                path = ('original.pdf' if asset['id'] == original else 'assets/'+asset['sha256']+EXTENSIONS[asset['media_type']])
                paths[asset['id']] = path
                files[path] = safe_path(asset_root,asset['storage_key']).read_bytes()
                types[path] = asset['media_type']
            files['index.html'] = render_html(ir,paths,include_source=include_source)
            manifest = {'schema_version':'1.0','document_id':ir['document']['id'], 'source_revision_id':ir['source_revision']['id'], 'translation_revision_id':ir['translation_revision']['id'], 'target_locale':ir['translation_revision']['target_language'], 'template_id':template['id'],'template_sha256':template['css_sha256'],'template_version':template['version'],'template_js_sha256':template['js_sha256'],'renderer_version':template['renderer_version'],'renderer_sha256':template['renderer_sha256'], 'source_snapshot_hash':digest(ir['source_revision']),'translation_snapshot_hash':digest(ir['translation_revision']),'settings_hash':ir['render']['settings_hash'],'mode':ir['render']['mode'],'include_source':include_source,
                        'files':[{'path':path,'media_type':types[path],'byte_size':len(content),'sha256':digest(content)} for path,content in sorted(files.items())]}
            manifest['content_digest'] = digest(manifest['files'])
            manifest['qa_fingerprint'] = qa_fingerprint
            for path,content in files.items():
                file = safe_path(staging,path,must_exist=False); file.parent.mkdir(parents=True,exist_ok=True)
                with file.open('xb') as handle:
                    handle.write(content); handle.flush(); os.fsync(handle.fileno())
            (staging/'manifest.json').write_bytes(canonical_bytes(manifest))
            verify_artifact(staging)
            # Same parent/volume rename only; caller separately commits Edition CAS.
            staging.rename(target)
            return manifest
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def verify_artifact(artifact_dir):
    root = Path(artifact_dir)
    manifest = strict_loads(safe_path(root,'manifest.json').read_bytes())
    names = [entry['path'] for entry in manifest['files']]
    if len(names) != len(set(names)) or 'index.html' not in names:
        raise ValueError('invalid artifact manifest')
    if digest(manifest['files']) != manifest['content_digest']:
        raise ValueError('artifact manifest digest mismatch')
    for entry in manifest['files']:
        path = safe_path(root,entry['path'])
        if path.stat().st_size != entry['byte_size'] or digest(path.read_bytes()) != entry['sha256']:
            raise ValueError('artifact file hash mismatch: '+entry['path'])
    return manifest


def export_files(artifact_dir, include_source):
    root = Path(artifact_dir)
    manifest = verify_artifact(root)
    files = {entry['path']:safe_path(root,entry['path']).read_bytes() for entry in manifest['files']}
    if manifest.get('legacy'):
        files.pop('legacy-original.html',None)
        text=files['index.html'].decode('utf-8').replace(manifest['navigation_patch']['to'],'')
        if not include_source:
            original=manifest['original_pdf_path']
            text=re.sub(r'<a\b[^>]*href="'+re.escape(original)+r'"[^>]*>.*?</a>','',text,flags=re.S)
            files.pop(original,None)
        files['index.html']=text.encode('utf-8')
        manifest['include_source']=include_source
        manifest['files']=[entry for entry in manifest['files'] if entry['path'] in files]
        for entry in manifest['files']:
            entry['byte_size']=len(files[entry['path']]);entry['sha256']=digest(files[entry['path']])
        manifest['content_digest']=digest(manifest['files'])
        files['manifest.json']=canonical_bytes(manifest)
        return manifest,files
    if include_source and not manifest['include_source']:
        raise ValueError('ASSET_MISSING: artifact has no original PDF')
    if not include_source and manifest['include_source']:
        content = files['index.html'].decode('utf-8')
        content = re.sub(r'<a href="original\.pdf" download>原始 PDF</a>', '', content)
        content = re.sub(r'<a data-original-reference href="original\.pdf">.*?</a>', '<span>对照图暂不可用；本次导出未包含原 PDF。</span>', content)
        files['index.html'] = content.encode('utf-8')
        files.pop('original.pdf',None)
        manifest['include_source'] = False
        manifest['files'] = [entry for entry in manifest['files'] if entry['path'] in files]
        for entry in manifest['files']:
            entry['byte_size'] = len(files[entry['path']]); entry['sha256'] = digest(files[entry['path']])
        manifest['content_digest'] = digest(manifest['files'])
    files['manifest.json'] = canonical_bytes(manifest)
    return manifest, files


def export_bundle(artifact_dir, destination, *, include_source=False):
    target = Path(destination)
    manifest, files = export_files(artifact_dir,include_source)
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info,content,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    return target


def export_single_html(artifact_dir, destination, *, include_source=False):
    target = Path(destination)
    manifest, files = export_files(artifact_dir,include_source)
    content = files['index.html'].decode('utf-8')
    if manifest.get('legacy'):
        content=content.replace('<head>','<head><meta http-equiv="Content-Security-Policy" content="'+esc(manifest['content_security_policy'])+'">',1)
    else:
        css = files['reader.css'].decode('utf-8')
        content = content.replace('<link rel="stylesheet" href="reader.css">','<style>'+css+'</style>')
        hashes = []
        for path in re.findall(r'<script src="([A-Za-z0-9._/-]+)" defer></script>', content):
            # HTML parsing normalizes line endings before CSP hashes inline text.
            js = files[path].decode('utf-8').replace('\r\n','\n').replace('\r','\n')
            content = content.replace(f'<script src="{path}" defer></script>','<script defer>'+js+'</script>')
            hashes.append("'sha256-" + base64.b64encode(__import__('hashlib').sha256(js.encode()).digest()).decode() + "'")
        content = content.replace("script-src 'self'", 'script-src ' + ' '.join(hashes))
        if 'math-LICENSE.txt' in files:
            notice = files['math-LICENSE.txt'].decode('utf-8')
            content = content.replace('</body>', '<pre hidden data-vendor-license="KaTeX">' + esc(notice) + '</pre></body>')
    for entry in manifest['files']:
        if entry['media_type'].startswith('image/') or entry['media_type'] == 'application/pdf':
            uri = 'data:'+entry['media_type']+';base64,'+base64.b64encode(files[entry['path']]).decode()
            content = content.replace('"'+entry['path']+'"','"'+uri+'"')
    with target.open('xb') as handle:
        handle.write(content.encode('utf-8'))
    return target
