"""Recognition must reach the IR without erasing independent PDF evidence."""
from pathlib import Path

from packages.ir import validate_source
from packages.parsers import inspect_pdf
from packages.parsers.pdf_docling import DoclingParser, coverage_report

ROOT = Path(__file__).resolve().parents[2]
MODEL = {'model': 'docling-project/CodeFormulaV2', 'revision': 'a' * 40}


def item(ref, label, original, text, box):
    return {'self_ref': ref, 'label': label, 'orig': original, 'text': text,
            'prov': [{'page_no': 1, 'bbox': dict(zip(('l', 't', 'r', 'b'), box), coord_origin='TOPLEFT')}]}


def adapt(tmp_path, label, original, recognized):
    pdf = ROOT / 'fixtures/sample.pdf'
    items = [item('title', 'title', 'Publication', 'Publication', [20, 20, 200, 40]),
             item('content', label, original, recognized, [20, 80, 300, 140])]
    return DoclingParser().adapt(items, inspect_pdf(pdf), pdf, 'original', tmp_path,
                                 enrichment=MODEL)['source_revision']


def test_formula_recognition_and_original_evidence_survive(tmp_path):
    source = adapt(tmp_path, 'formula', 'a b', r'\frac{a}{b}')
    block = next(b for b in source['blocks'] if b['kind'] == 'math')
    assert block['raw_text'] == block['normalized_text'] == r'\frac{a}{b}'
    assert block['attributes']['representation'] == 'latex'
    assert block['attributes']['recognition'] == MODEL | {'original_text': 'a b'}
    assert block['attributes']['asset_id']
    assert source['protected_atoms'][block['id'] + '-atom']['value'] == r'\frac{a}{b}'
    validate_source(source, asset_root=tmp_path)


def test_code_preserves_recognized_newlines_and_indentation(tmp_path):
    code = 'for x in xs:\n    print(x)'
    source = adapt(tmp_path, 'code', 'for x in xs: print(x)', code)
    block = next(b for b in source['blocks'] if b['kind'] == 'code')
    assert block['raw_text'] == code
    assert block['attributes']['representation'] == 'plain'
    assert block['attributes']['recognition']['original_text'] == 'for x in xs: print(x)'


def test_image_only_formula_can_gain_recognized_text(tmp_path):
    source = adapt(tmp_path, 'formula', '', 'x^2')
    assert next(b for b in source['blocks'] if b['kind'] == 'math')['raw_text'] == 'x^2'


def test_failed_enrichment_keeps_original_crop(tmp_path):
    source = adapt(tmp_path, 'formula', 'a b', '')
    block = next(b for b in source['blocks'] if b['kind'] == 'math')
    assert block['raw_text'] == 'a b'
    assert block['attributes']['representation'] == 'image'
    assert 'recognition' not in block['attributes']


def test_native_coverage_uses_original_evidence_for_enriched_blocks(tmp_path):
    source = adapt(tmp_path, 'formula', 'a b', r'\frac{a}{b}')
    block = next(b for b in source['blocks'] if b['kind'] == 'math')
    page = {'page': 1, 'page_size': [612, 792], 'text_characters': 3, 'scan_suspected': False,
            'text_regions': [{'bbox': [20, 80, 300, 140], 'text': 'a b'}]}
    assert coverage_report([page], [block], [])['can_translate']
    page['text_regions'][0]['text'] = 'a b missing body'
    assert not coverage_report([page], [block], [])['can_translate']


def test_ocr_scan_output_is_available_but_not_native_certified():
    page = {'page': 1, 'page_size': [612, 792], 'text_characters': 0, 'scan_suspected': True,
            'text_regions': [], 'ocr_attempted': True}
    report = coverage_report([page], [], [])
    assert not report['can_translate']
    assert report['unresolved'][0]['code'] == 'SOURCE_PARSE_REVIEW'


def test_empty_failed_formula_retains_image_without_empty_atom(tmp_path):
    source = adapt(tmp_path, 'formula', '', '')
    block = next(b for b in source['blocks'] if b['kind'] == 'math')
    assert block['attributes']['representation'] == 'image'
    assert block['source_inline'] == []
    validate_source(source, asset_root=tmp_path)


def test_recognition_html_is_escaped_and_original_crop_is_accessible(tmp_path):
    import json
    from packages.ir import block_hash
    from packages.parsers.pdf_docling import _source_nodes
    from packages.publisher.renderer import render_html
    ir = json.loads((ROOT / 'fixtures/sample-document-v3.json').read_text('utf-8'))
    source = ir['source_revision']
    block = next(b for b in source['blocks'] if b['kind'] == 'code')
    block['attributes'].update(representation='plain', recognition=MODEL | {'original_text': block['raw_text']},
                               asset_id=next(a['id'] for a in source['assets'] if a['media_type'] == 'image/png'))
    block['raw_text'] = block['normalized_text'] = '<script>alert(1)</script>'
    block['source_inline'] = _source_nodes(block['raw_text'], block['id'], source['protected_atoms'], 'code')
    block['warnings'] = ['Machine recognized code.']
    block['source_hash'] = block_hash(block, source['protected_atoms'])
    next(r for r in ir['translation_revision']['results'] if r['block_id'] == block['id'])['source_hash'] = block['source_hash']
    html = render_html(ir, {a['id']: 'assets/' + a['id'] + '.png' for a in source['assets']}).decode('utf-8')
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '查看原PDF裁图' in html


def test_model_fingerprint_changes_with_model_revision():
    from packages.parsers.config import pipeline_fingerprint
    before = {'pipeline_revision': 'v1', 'repositories': [{'revision': 'a'}]}
    after = {'pipeline_revision': 'v1', 'repositories': [{'revision': 'b'}]}
    assert pipeline_fingerprint(before) != pipeline_fingerprint(after)


def test_native_source_correction_clears_stale_recognition_label(tmp_path):
    from packages.source_revisions.native import apply_native_corrections
    source = adapt(tmp_path, 'formula', 'a b', r'\frac{a}{b}')
    block = next(b for b in source['blocks'] if b['kind'] == 'math')
    box = block['provenance'][0]['bbox']
    evidence = {'page': 1, 'bbox': box, 'quote': 'a b'}
    inspection = {'sha256': source['sha256'], 'pages': [{'page': 1, 'page_size': [612, 792],
        'text_characters': 3, 'scan_suspected': False, 'text_regions': [{'bbox': box, 'text': 'a b'}]}]}
    result = apply_native_corrections(source, inspection, [{'kind': 'replace_text', 'block_id': block['id'],
        'start': 0, 'end': len(block['normalized_text']), 'text': 'a b'}], evidence, 'Restore native source', [])
    corrected = next(b for b in result['source']['blocks'] if b['id'] == block['id'])
    assert 'recognition' not in corrected['attributes']
    assert corrected['attributes']['representation'] == 'image'
    assert block['attributes']['recognition']  # Prior source remains immutable.
