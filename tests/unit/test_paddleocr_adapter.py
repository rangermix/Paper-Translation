"""Official output mapping: geometry, protected content and native evidence."""
from pathlib import Path

from packages.parsers.inspect import inspect_pdf
from packages.parsers.pdf_docling import DoclingParser
from packages.parsers.pdf_docling import vlm_text_issues
from packages.parsers.pdf_paddleocr import page_items
from packages.parsers.profiles import PADDLE_MODEL, GRANITE_MODEL
import pytest


def test_pixel_boxes_map_to_pdf_points_and_tables_never_inject_html():
    page = {'page': 2, 'page_size': [600, 800], 'text_regions': [{'text': 'Table cell', 'bbox': [10, 20, 100, 40]}]}
    result = {'parsing_res_list': [
        {'block_label': 'algorithm', 'block_content': 'if x:\n    return x', 'block_bbox': [20, 100, 200, 200]},
        {'block_label': 'table', 'block_content': '<script>attack</script>', 'block_bbox': [10, 20, 400, 200]},
    ]}
    items = page_items(result, page, [1200, 1600])
    assert items[0]['label'] == 'code'
    assert items[0]['text'] == 'if x:\n    return x'
    assert items[0]['prov'] == [{'page_no': 2, 'bbox': {'l': 10, 't': 50, 'r': 100, 'b': 100, 'coord_origin': 'TOPLEFT'}}]
    assert items[1]['text'] == 'Table cell'
    assert '<script>' not in str(items)


def test_generated_prose_cannot_add_text_to_a_complete_native_region():
    pages = [{'text_characters': 14, 'text_regions': [{'text': 'Original text.', 'bbox': [10, 20, 100, 40]}]}]
    block = {'id': 'b', 'kind': 'paragraph', 'raw_text': 'Original text. Invented sentence.',
        'provenance': [{'page': 1, 'bbox': [10, 20, 100, 40]}]}
    assert vlm_text_issues(pages, [block])[0]['code'] == 'SOURCE_PARSE_REVIEW'
    block['raw_text'] = 'Original text.'
    assert vlm_text_issues(pages, [block]) == []


def test_formula_contradictions_are_reported_without_rewriting_model_output():
    block = {'id': 'b', 'kind': 'math', 'raw_text': r'\begin{array}{r} 1 \\ + 6 \\ 2 \end{array}',
        'attributes': {'recognition': {'original_text': 'x + 1'}}, 'provenance': [{'page': 1, 'bbox': [10, 20, 100, 40]}]}
    assert 'formula numbers' in vlm_text_issues([], [block])[0]['reason']
    block['attributes']['recognition']['original_text'] = '1 2'
    block['raw_text'] = r'\frac{1}{2}'
    assert vlm_text_issues([], [block]) == []


@pytest.mark.parametrize('model', [PADDLE_MODEL, GRANITE_MODEL])
def test_full_page_vlm_code_uses_native_evidence_and_remains_protected(tmp_path, model):
    pdf = Path('fixtures/sample.pdf')
    inspection = inspect_pdf(pdf)
    page = inspection['pages'][0]
    title, code = page['text_regions'][:2]
    def item(ref, label, region, text):
        return {'self_ref': ref, 'label': label, 'orig': text, 'text': text,
            'prov': [{'page_no': 1, 'bbox': dict(zip(('l', 't', 'r', 'b'), region['bbox']), coord_origin='TOPLEFT')}]}
    generated = 'if generated_code:\n    return 123'
    result = DoclingParser().adapt([item('title', 'title', title, title['text']), item('code', 'code', code, generated)],
        inspection, pdf, 'asset_test', tmp_path, enrichment={'model': model, 'revision': 'a' * 40})
    block = next(b for b in result['source_revision']['blocks'] if b['kind'] == 'code')
    assert block['raw_text'] == generated
    assert block['attributes']['recognition']['original_text'] == code['text']
    assert block['translatable'] is False
    assert block['attributes']['asset_id']
    assert result['coverage']['can_translate'] is False  # Omitted body still blocks.
