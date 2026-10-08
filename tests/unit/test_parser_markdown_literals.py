"""Markdown formatting must not invalidate IR or consume printed PDF symbols."""
import json
from pathlib import Path

import pytest

from packages.ir import validate_source
from packages.parsers.pdf_vlm import VisionParser
from packages.parsers.semantic import markdown_semantics
from packages.parsers.vlm_output import json_items


PAGE = {'page': 1, 'page_size': [600, 800]}


def decode(text, role='text', native=None, native_bbox=None):
    page = dict(PAGE)
    if native is not None:
        page['text_regions'] = [{'text': native, 'bbox': native_bbox or [0, 80, 600, 720]}]
    warnings = []
    items = json_items(json.dumps([{'category': role, 'bbox': [0, 100, 1000, 900], 'text': text}]), page, warnings)
    return items[0], warnings


@pytest.mark.parametrize(('text', 'outer', 'inner'), [
    ('*outer _inner_ tail* done', ['emphasis'], ['emphasis']),
    ('**outer __inner__ tail** done', ['strong'], ['strong']),
    ('*outer **inner _deep_ tail** end* done', ['emphasis'], ['emphasis', 'strong']),
])
def test_nested_marks_validate_and_keep_outer_style_after_inner_close(tmp_path, text, outer, inner):
    runs = markdown_semantics(text, [])['runs']
    assert next(r for r in runs if r['text'] == 'outer ')['marks'] == outer
    assert next(r for r in runs if r['text'].startswith('inner'))['marks'] == inner
    assert next(r for r in runs if r['text'] == ' tail')['marks'] == inner
    assert 'marks' not in runs[-1]
    raw = json.dumps([
        {'category': 'title', 'bbox': [0, 0, 1000, 80], 'text': 'Fixture title'},
        {'category': 'text', 'bbox': [0, 100, 1000, 900], 'text': text},
    ])
    source = VisionParser(inference_factory=lambda *args: lambda image, prompt: raw).parse(
        Path('tests/fixtures/sample.pdf'), 'source_pdf', tmp_path,
        {'parser_profile_revision': 'infinity-parser2-flash-v1'})['source_revision']
    validate_source(source, asset_root=tmp_path)
    assert all(len(n.get('marks', [])) == len(set(n.get('marks', [])))
               for b in source['blocks'] for n in b['source_inline'])


@pytest.mark.parametrize('role', ['code', 'code-block', 'algorithm'])
def test_explicit_code_is_literal_without_markdown_or_whitespace_loss(role):
    text = '  float* p = &value;\n  *p = left * right;\n\n  # heading **literal** _name_\n'
    item, warnings = decode(text, role)
    assert item['label'] == 'code'
    assert item['text'] == text
    assert item['_semantic']['kind'] == 'code'
    assert item['_semantic']['runs'] == [{'type': 'code', 'text': text, 'path': '/0/text'}]
    assert not warnings


@pytest.mark.parametrize('role', ['text', 'code', 'code-block', 'algorithm'])
def test_markdown_code_fence_uses_protected_physical_code_path(role):
    item, _ = decode('```python\n  x = a * b\n  print(x)\n```', role)
    assert item['label'] == 'code'
    assert item['_semantic']['text'] == '  x = a * b\n  print(x)\n'
    assert item['_semantic']['attrs']['code_language'] == 'python'


def test_native_pdf_proves_printed_delimiters_without_guessing_code_role():
    text = '*printed asterisks* and _literal underscores_'
    item, warnings = decode(text, native=text)
    assert item['label'] == 'text' and item['_semantic']['kind'] == 'paragraph'
    assert item['text'] == text
    assert all('marks' not in r for r in item['_semantic']['runs'])
    assert [d['code'] for d in warnings] == ['PRINTED_MARKDOWN_LITERAL']


def test_native_context_preserves_unfenced_operators_despite_other_ocr_errors():
    text = 'unrelated OCR typo\nfloat A[TM, TK] = check_a ? *pa : 0;\nfloat B[TN, TK] = check_b ? *pb : 0;\npa = pa + TK*M;\npb = pb + TK*N;\n}\n// write-back accumulators\nfloat* pc = c;'
    native = text.replace('OCR typo', 'original text').replace('*', '∗').replace('write-back', 'write−back')
    item, warnings = decode(text, native=native)
    assert item['text'] == text
    assert item['_semantic']['kind'] == 'paragraph'
    assert all('marks' not in r for r in item['_semantic']['runs'])
    assert [d['code'] for d in warnings] == ['PRINTED_MARKDOWN_LITERAL']


def test_printed_operators_keep_neighboring_real_markdown_and_block_structure():
    code = 'float A[TM, TK] = check_a ? *pa : 0;\nfloat B[TN, TK] = check_b ? *pb : 0;\npa = pa + TK*M;\npb = pb + TK*N;'
    text = '**Important**\n\n' + code
    item, warnings = decode(text, native='Important\n\n' + code)
    tree = item['_semantic']
    assert tree['kind'] == 'group'
    assert tree['children'][0]['text'] == 'Important'
    assert any(r.get('marks') == ['strong'] for r in tree['children'][0]['runs'])
    assert tree['children'][1]['text'] == code
    assert all('marks' not in r for r in tree['children'][1]['runs'])
    assert [d['code'] for d in warnings] == ['PRINTED_MARKDOWN_LITERAL']


@pytest.mark.parametrize('native', [None, 'A bold word', 'unrelated *printed* text'])
def test_missing_or_unrelated_native_text_does_not_disable_markdown(native):
    item, warnings = decode('A **bold** word', native=native)
    assert item['text'] == 'A bold word'
    assert any(r.get('marks') == ['strong'] for r in item['_semantic']['runs'])
    assert not warnings


def test_native_text_outside_crop_cannot_change_markdown():
    item, warnings = decode('A **bold** word', native='A **bold** word', native_bbox=[0, 0, 600, 40])
    assert item['text'] == 'A bold word'
    assert not warnings


@pytest.mark.parametrize('text', ['* First\n* Second', '***', '___'])
def test_printed_block_markers_keep_their_markdown_structure(text):
    item, warnings = decode(text, native=text)
    assert item['_semantic']['kind'] == 'group'
    assert not warnings


def test_printed_inline_stars_do_not_turn_list_markers_into_prose():
    text = '* First with *printed* symbols\n* Other'
    item, warnings = decode(text, native=text)
    tree = item['_semantic']
    assert tree['kind'] == 'group' and tree['attrs']['group_type'] == 'list'
    assert len(tree['children']) == 2
    assert tree['children'][0]['text'] == 'First with *printed* symbols'
    assert [d['code'] for d in warnings] == ['PRINTED_MARKDOWN_LITERAL']


def test_printed_inline_stars_do_not_turn_separators_into_prose():
    text = '***\n\nA *printed* symbol'
    item, warnings = decode(text, native=text)
    tree = item['_semantic']
    assert tree['children'][0]['attrs']['separator'] == 'horizontal'
    assert tree['children'][1]['text'] == 'A *printed* symbol'
    assert [d['code'] for d in warnings] == ['PRINTED_MARKDOWN_LITERAL']
