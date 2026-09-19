"""M1-R04/R05: official table HTML becomes verified, translatable IR cells."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from packages.ir import validate_ir, validate_source
from packages.parsers.inspect import inspect_pdf
from packages.parsers.pdf_docling import DoclingParser, vlm_text_issues
from packages.parsers.pdf_paddleocr import page_items
from packages.parsers.profiles import PADDLE_MODEL
from packages.parsers.table_html import parse_table_html
from packages.publisher.renderer import render_html
from packages.translation.planner import plan_units
from tests.unit.test_translation import profile


MERGED = '<table><tr><th rowspan="2">State group</th><th colspan="2">Combined columns</th></tr><tr><td>Left</td><td>Right</td></tr><tr><td>A</td><td></td><td>64</td></tr></table>'


def test_merged_grid_preserves_spans_headers_and_explicit_blank_cells():
    data = parse_table_html(MERGED)
    assert (data['num_rows'], data['num_cols']) == (3, 3)
    cells = data['table_cells']
    assert [c['text'] for c in cells] == ['State group', 'Combined columns', 'Left', 'Right', 'A', '', '64']
    assert [(c['row_span'], c['col_span']) for c in cells[:2]] == [(2, 1), (1, 2)]
    assert cells[0]['column_header'] is True
    assert cells[-1]['start_row_offset_idx'] == cells[-1]['start_col_offset_idx'] == 2


def test_html_entities_wrappers_and_line_breaks_are_text_only():
    data = parse_table_html('<html><body><table class="x"><thead><tr><th>Name</th></tr></thead><tbody><tr><td><b>A &amp; B</b><br/>x &lt; 3</td></tr></tbody></table></body></html>')
    assert data['table_cells'][1]['text'] == 'A & B\nx < 3'
    assert '<b>' not in str(data)


@pytest.mark.parametrize('html', [
    '<table><tr><td>cut off',
    '<table><tr><td>A</td><td>B</td></tr><tr><td>C</td></tr></table>',
    '<table><tr><td rowspan="2">A</td><td>B</td></tr></table>',
    '<table><tr><td>A</td><td rowspan="2">B</td></tr><tr><td colspan="2">C</td></tr></table>',
    '<table><tr><td colspan="999999999">A</td></tr></table>',
    '<table><tr><td rowspan="0">A</td></tr></table>',
    '<table><tr><td rowspan="-1">A</td></tr></table>',
    '<table><tr><td colspan="1.5">A</td></tr></table>',
    '<table><tr><td rowspan="1" rowspan="2">A</td></tr></table>',
    '<table><tr><td><table><tr><td>A</td></tr></table></td></tr></table>',
    '<table><tr><td>A<script>alert(1)</script></td></tr></table>',
    '<table><tr><td><img src="https://example.com/private"></td></tr></table>',
    '<table><caption>Lost caption</caption><tr><td>A</td></tr></table>',
    '<table><tr><td>x<sup>2</sup></td></tr></table>',  # Do not flatten semantic notation.
    '<table><tr><td>A</tr></td></table>',
    '<table><tr><td>A</td></tr></table>extra text',
    '<table><tr><td>A</td></tr></table><table><tr><td>B</td></tr></table>',
    '<!DOCTYPE html><table><tr><td>A</td></tr></table>',
    '<table></table>',
])
def test_incomplete_unsafe_or_unsupported_structure_falls_back_whole(html):
    assert parse_table_html(html) is None


def test_span_resource_limit_is_bounded():
    assert parse_table_html('<table>' + '<tr><td colspan="1000">A</td></tr>' * 11 + '</table>') is None


def adapt_table(tmp_path, html=MERGED):
    """An actual native-text PDF; the HTML is a controlled model-output double."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    texts = [(50, 750, 'Table parsing sample'), (50, 680, 'State group'), (220, 680, 'Combined columns'),
        (220, 640, 'Left'), (390, 640, 'Right'), (50, 600, 'A'), (390, 600, '64')]
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(f'BT /F1 12 Tf 1 0 0 1 {x} {y} Tm ({s}) Tj ET' for x, y, s in texts).encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    pdf = tmp_path / 'table.pdf'
    writer.write(pdf)
    inspection = inspect_pdf(pdf)
    page_info = inspection['pages'][0]
    result = {'parsing_res_list': [
        {'block_label': 'doc_title', 'block_content': 'Table parsing sample', 'block_bbox': [45, 35, 500, 60]},
        {'block_label': 'table', 'block_content': html, 'block_bbox': [45, 100, 500, 220]},
    ]}
    items = page_items(result, page_info, [600, 800])
    return DoclingParser().adapt(items, inspection, pdf, 'asset_test', tmp_path / 'parsed',
        profile={'language': 'en'}, parser_name='paddleocr', parser_version='3.7.0',
        enrichment={'model': PADDLE_MODEL, 'revision': 'a' * 40})


def as_ir(source):
    ir = json.loads(Path('tests/fixtures/sample-document.json').read_text('utf-8'))
    ir['source_revision'] = source
    ir['document']['title'] = source['blocks'][0]['normalized_text']
    template = ir['translation_revision']['results'][0]
    results = []
    for block in source['blocks']:
        result = deepcopy(template)
        translated = block['translatable']
        result.update(block_id=block['id'], source_hash=block['source_hash'],
            target_inline=deepcopy(block['source_inline']) if translated else [],
            status='translated' if translated else 'retained', reason='' if translated else 'source_retained',
            review_state='machine_checked', review_record=None)
        for node in result['target_inline']:
            if node.get('text') == 'State group': node['text'] = '状态组'
        results.append(result)
    ir['translation_revision'].update(source_revision_id=source['id'], results=results, title=ir['document']['title'])
    return ir


def test_adapter_to_translation_to_static_reader(tmp_path):
    result = adapt_table(tmp_path)
    source = result['source_revision']
    validate_source(source, asset_root=tmp_path / 'parsed')
    assert result['coverage']['can_translate'], result['coverage']['unresolved']
    table = next(b for b in source['blocks'] if b['kind'] == 'table')
    assert table['attributes']['representation'] == 'structured'
    assert table['attributes']['asset_id'] and table['warnings']
    cells = [b for b in source['blocks'] if b['kind'] == 'table_cell']
    assert len(cells) == 7
    blank = next(b for b in cells if b['raw_text'] == '')
    assert blank['translatable'] is False
    units = plan_units(source, 'zh-Hans', profile())
    owners = {u['owner_block_id'] for u in units}
    assert owners == {b['id'] for b in source['blocks'] if b['translatable'] and b['normalized_text'] != '64'}
    assert blank['id'] not in owners and table['id'] not in owners
    assert all(b['provenance'] == table['provenance'] for b in cells)  # Honest region-level locator.
    ir = as_ir(source)
    validate_ir(ir, asset_root=tmp_path / 'parsed')
    paths = {a['id']: a['storage_key'] for a in source['assets']}
    html = render_html(ir, paths).decode('utf-8')
    assert 'rowspan="2" colspan="1"' in html and 'rowspan="1" colspan="2"' in html
    assert '状态组' in html and '查看原 PDF 表格' in html
    assert f'colspan="1"></td>' in html
    for cell in cells: assert html.count(f'id="b-{cell["id"]}"') == 1


def test_empty_cell_exception_cannot_hide_real_prose(tmp_path):
    source = adapt_table(tmp_path)['source_revision']
    cell = next(b for b in source['blocks'] if b['kind'] == 'table_cell' and b['raw_text'])
    cell['translatable'] = False
    with pytest.raises(ValueError, match='prose cannot disable'): validate_source(source)
    cell['translatable'] = True
    ir = as_ir(source)
    target = next(r for r in ir['translation_revision']['results'] if r['block_id'] == cell['id'])
    target.update(status='retained', reason='empty_cell', target_inline=[])
    with pytest.raises(ValueError, match='required prose cannot'): validate_ir(ir)


@pytest.mark.parametrize('html', [MERGED.replace('64', '46'), MERGED.replace('Right', 'Right invented'), MERGED.replace('Left', '')])
def test_model_omissions_additions_and_wrong_numbers_block_preflight(tmp_path, html):
    result = adapt_table(tmp_path, html)
    assert not result['coverage']['can_translate']
    assert any('table' in i['reason'].lower() for i in result['coverage']['unresolved'])


def test_malformed_table_retains_pdf_crop_without_html(tmp_path):
    result = adapt_table(tmp_path, '<table><tr><td>truncated')
    table = next(b for b in result['source_revision']['blocks'] if b['kind'] == 'table')
    assert table['attributes']['representation'] == 'image'
    assert table['warnings'] and table['attributes']['asset_id']
    assert '<table>' not in table['raw_text']
    assert not any(b['kind'] == 'table_cell' for b in result['source_revision']['blocks'])


def test_generated_table_in_empty_region_cannot_bypass_native_check():
    pages = [{'text_characters': 20, 'text_regions': [{'text': 'Actual body', 'bbox': [10, 10, 100, 30]}]}]
    loc = {'page': 1, 'bbox': [10, 100, 100, 200]}
    table = {'id': 't', 'kind': 'table', 'attributes': {'representation': 'structured'}, 'provenance': [loc]}
    cell = {'id': 'c', 'owner_id': 't', 'kind': 'table_cell', 'raw_text': 'Invented 64', 'provenance': [loc]}
    assert vlm_text_issues(pages, [table, cell])[0]['code'] == 'SOURCE_PARSE_REVIEW'


def test_pdf_resource_crops_are_large_enough_for_reader_figures(tmp_path):
    from PIL import Image
    result=adapt_table(tmp_path)
    source=result['source_revision']
    table=next(b for b in source['blocks'] if b['kind']=='table')
    asset=next(a for a in source['assets'] if a['id']==table['attributes']['asset_id'])
    box=table['provenance'][0]['bbox']
    with Image.open(tmp_path/'parsed'/asset['storage_key']) as image:
        assert image.width >= int((box[2]-box[0])*3)-1
        assert image.height >= int((box[3]-box[1])*3)-1
