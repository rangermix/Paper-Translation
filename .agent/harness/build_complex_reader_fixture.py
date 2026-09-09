"""Authored M0 renderer fixture. Never a parser gold or public IR import."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import copy
import json
from pathlib import Path
import sys
import textwrap

from reportlab.pdfgen import canvas


sys.path.insert(0, str(ROOT))
from packages.ir import block_hash, digest, validate_ir

DEST = ROOT / 'fixtures/complex-reader'
TITLE = 'A deliberately long publication title for reviewing offline bilingual reading, merged table cells, exact code, and cross-page source locations'
CODE = 'checkpoint = save_document(source_revision, translation_revision, expected_generation, immutable=True)\nif checkpoint.outcome == "unknown":\n    do_not_dispatch_a_second_request(checkpoint.request_id, preserve_reserved_budget=True)\nelse:\n    publish_after_verifying_every_asset(checkpoint.artifact_directory, expected_hash=checkpoint.sha256)'


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    pdf_path = DEST / 'complex-reader.pdf'
    pdf = canvas.Canvas(str(pdf_path), pagesize=(612, 792), invariant=1)
    pdf.setTitle(TITLE)
    pdf.setAuthor('Local acceptance fixture; explicitly authored')
    base = json.loads((ROOT / 'fixtures/sample-document-v3.json').read_text('utf-8'))
    source, tr = base['source_revision'], base['translation_revision']
    source.update(id='src_complex', title_block_id='title', blocks=[], reading_order=[], protected_atoms={})
    source['parser']['name'] = 'manually-authored-complex-renderer-fixture'
    tr.update(id='tr_complex', source_revision_id='src_complex', title='离线双语阅读复杂结构样例：长标题、合并单元格、原样代码与跨页来源位置', results=[])
    base['document'].update(id='doc_complex', title=TITLE, notice='M0人工编写的两页PDF及对应IR；只验证结构发布与离线阅读，不是解析质量或真实Provider翻译证据。')
    locations = {}

    def loc(page, box):
        return {'type': 'pdf', 'asset_id': 'source_pdf', 'page': page, 'bbox': box,
                'coordinate_system': 'top-left-points', 'page_size': [612, 792]}

    def block(bid, kind, text, target, page, box, *, parent='title', owner=None, attrs=None, provenance=None):
        value = {'id': bid, 'order': len(source['blocks']), 'parent_id': parent, 'owner_id': owner,
            'kind': kind, 'language': 'en', 'translatable': target is not None, 'raw_text': text,
            'normalized_text': text, 'source_hash': '0'*64, 'normalization_edits': [],
            'source_inline': [{'type': 'text', 'text': text}] if text else [],
            'provenance': provenance or [loc(page, box)], 'warnings': [], 'attributes': attrs or {}}
        value['source_hash'] = block_hash(value, source['protected_atoms'])
        source['blocks'].append(value)
        if owner is None:
            source['reading_order'].append(bid)
        result = copy.deepcopy(base_result)
        result.update(block_id=bid, source_hash=value['source_hash'], status='translated' if target is not None else 'retained',
            target_inline=[{'type': 'text', 'text': target}] if target is not None else [],
            reason='' if target is not None else 'authored_original_' + kind)
        result['generation']['kind'] = 'human' if target is not None else 'retained'
        tr['results'].append(result)
        locations[bid] = {'source_text': text, 'target_text': target, 'provenance': value['provenance'], 'attributes': value['attributes']}
        return value

    def draw(text, top, *, font='Helvetica', size=11, x=50, leading=16):
        pdf.setFont(font, size)
        lines = text.split('\n')
        for index, line in enumerate(lines):
            pdf.drawString(x, 792-top-index*leading, line)
        return [x, top-size-2, max(x+pdf.stringWidth(line,font,size) for line in lines), top+(len(lines)-1)*leading+3]

    base_result = json.loads((ROOT / 'fixtures/sample-document-v3.json').read_text('utf-8'))['translation_revision']['results'][0]
    title_lines = '\n'.join(textwrap.wrap(TITLE, 63))
    title_box = draw(title_lines, 54, size=17, leading=23)
    block('title', 'heading', TITLE, tr['title'], 1, title_box, parent=None, attrs={'level': 1})
    heading = 'Section one: explicit structure'
    block('section-one', 'heading', heading, '第一节：明确的结构', 1, draw(heading, 155, size=14), attrs={'level': 2})
    text = 'Every visible cell below belongs to the same authored source table.'
    block('intro', 'paragraph', text, '下方每个可见单元格都属于同一个人工编写的原表。', 1, draw(text, 187), parent='section-one')

    def table(bid, page, top, rows, cols, cells, caption):
        width, height, x = 480/cols, 38, 50
        bounds = [x, top, x+480, top+rows*height]
        descriptors = []
        for name, row, col, rspan, cspan, text, target in cells:
            descriptors.append({'row': row, 'column': col, 'row_span': rspan, 'column_span': cspan, 'content_block_id': name})
        block(bid, 'table', '', None, page, bounds, attrs={'representation':'structured','rows':rows,'columns':cols,
              'caption_block_ids':[bid+'-caption'], 'cells':descriptors})
        for name, row, col, rspan, cspan, text, target in cells:
            bx, by = x+col*width, top+row*height
            pdf.rect(bx, 792-by-rspan*height, cspan*width, rspan*height, fill=0, stroke=1)
            draw(text, by+23, x=bx+9)
            block(name, 'table_cell', text, target, page, [bx,by,bx+cspan*width,by+rspan*height], owner=bid)
        target_caption = '表一：完整的两行两列表格。' if bid == 'regular-table' else '表二：三行三列表格中跨两行与跨两列的单元格。'
        block(bid+'-caption', 'caption', caption, target_caption, page, draw(caption, top+rows*height+23), owner=bid)

    table('regular-table', 1, 220, 2, 2, [
        ('regular-state',0,0,1,1,'State','状态'), ('regular-value',0,1,1,1,'Value','值'),
        ('regular-saved',1,0,1,1,'Saved','已保存'), ('regular-count',1,1,1,1,'64','64')], 'Table one. A complete two by two grid.')
    heading = 'Deep subsection: exact long code'
    block('deep-code', 'heading', heading, '深入小节：原样保留长代码', 1, draw(heading, 365, size=14), parent='section-one', attrs={'level':4})
    block('long-code', 'code', CODE, None, 1, draw(CODE, 397, font='Courier', size=8, leading=18), parent='deep-code', attrs={'code_language':'python'})
    text = 'This paragraph begins on page one and continues on page two.\nThe second source location is part of the same paragraph, not a new block.'
    first = draw(text.split('\n')[0], 650)
    pdf.showPage()
    second = draw(text.split('\n')[1], 58)
    block('cross-page', 'paragraph', text, '本段开始于第一页，并延续到第二页。第二个来源位置仍属于同一段，而不是新块。', 1, first,
          parent='deep-code', provenance=[loc(1, first), loc(2, second)])
    heading = 'Section two: merged cells and retained originals'
    block('section-two', 'heading', heading, '第二节：合并单元格与保留原件', 2, draw(heading, 104, size=14), attrs={'level':2})
    table('merged-table', 2, 137, 3, 3, [
        ('merged-label',0,0,2,1,'State group','状态组'), ('merged-columns',0,1,1,2,'Combined columns','合并列'),
        ('merged-left',1,1,1,1,'Left','左侧'), ('merged-right',1,2,1,1,'Right','右侧'),
        ('merged-a',2,0,1,1,'A','甲'), ('merged-b',2,1,1,1,'B','乙'), ('merged-c',2,2,1,1,'C','丙')],
        'Table two. Row span two and column span two in a three by three grid.')
    text = 'Keep the original figure, code, formula, footnote, and reference.'
    block('list', 'list_item', text, '保留原图、代码、公式、脚注和参考文献。', 2, draw(text, 320), parent='section-two', attrs={'list_ordered':True,'list_index':1})
    pdf.drawImage(str(ROOT/'fixtures/figure.png'),50,792-437,width=360,height=100)
    block('figure', 'figure', '', None, 2, [50,337,410,437], parent='section-two', attrs={'asset_id':'figure_png','caption_block_ids':['figure-caption']})
    text = 'Figure one. Three original colour patches.'
    block('figure-caption','caption',text,'图一：三个原始色块。',2,draw(text,457),parent='section-two',owner='figure')
    block('formula','math','x + 1',None,2,draw('x + 1',492,font='Courier'),parent='section-two',attrs={'representation':'plain'})
    text = 'Read the authored note before treating this as evidence.'
    p = block('note-reference','paragraph',text,'在将其视为证据之前，请阅读人工编写的注释。',2,draw(text,529),parent='section-two')
    p['source_inline'] = [{'type':'text','text':'Read the '},{'type':'xref','target_block_id':'footnote','label':'authored note'},{'type':'text','text':' before treating this as evidence.'}]
    p['source_hash'] = block_hash(p, {})
    tr['results'][-1]['source_hash'] = p['source_hash']
    tr['results'][-1]['target_inline'] = [{'type':'text','text':'在将其视为证据之前，请阅读'},{'type':'xref','target_block_id':'footnote','label':'人工编写的注释'},{'type':'text','text':'。'}]
    text = 'Authored fixture only. No parser accuracy or Provider quality is asserted.'
    block('footnote','footnote',text,'仅为人工编写的样例；不声称解析精度或Provider质量。',2,draw(text,570,size=10),parent='section-two')
    text = 'Reference: local acceptance fixture, two original PDF pages.'
    block('reference','reference',text,None,2,draw(text,610,size=10),parent='section-two')
    pdf.showPage(); pdf.save()
    pdf_bytes = pdf_path.read_bytes()
    source['sha256'] = digest(pdf_bytes)
    source['assets'][0].update(sha256=digest(pdf_bytes), storage_key='fixtures/complex-reader/complex-reader.pdf', byte_size=len(pdf_bytes))
    validate_ir(base, asset_root=ROOT)
    (DEST/'document-ir.json').write_text(json.dumps(base,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (DEST/'authored-source-manifest.json').write_text(json.dumps({'purpose':'M0 authored renderer fixture, never M1 parser gold',
        'pdf_sha256':digest(pdf_bytes),'page_count':2,'blocks':locations},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'pdf':str(pdf_path),'blocks':len(source['blocks']),'source_sha256':digest(pdf_bytes),'external_calls':0}))


if __name__ == '__main__':
    main()
