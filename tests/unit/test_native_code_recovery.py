"""Code identity and PDF baselines survive malformed full-page output."""
import json

import pytest

from packages.parsers.code_recovery import recover_code_regions
from packages.parsers.semantic import markdown_semantics
from packages.parsers.vlm_output import json_items


def region(text, box):
    return {'text':text, 'bbox':box}


def listing(text, native, *, graphics=True, category='text'):
    page = {'page':1, 'page_size':[600,800], 'text_regions':native,
            'graphic_regions':[{'bbox':[60,80,300,160]}] if graphics else []}
    raw = json.dumps([{'category':category, 'bbox':[100,100,500,200], 'text':text}])
    rows = json_items(raw, page)
    return recover_code_regions(rows, [page])


def test_single_line_fence_retains_code_identity_but_not_an_invented_layout():
    diagnostics = []
    tree = markdown_semantics('```python import engine as e output = e.run() ```', diagnostics)
    assert tree['kind'] == 'code'
    assert tree['text'] == 'import engine as e output = e.run()'
    assert tree['attrs']['code_language'] == 'python'
    assert diagnostics[0]['code'] == 'CODE_FENCE_LINEBREAKS_MISSING'
    # An inline example inside a sentence is still inline content.
    assert markdown_semantics('Use ```python x``` as a literal example.', [])['kind'] == 'paragraph'


def test_native_font_fragments_and_small_operator_boxes_restore_code_line_breaks():
    original = '```python import engine as e output = e.run() print(output) ```'
    native = [region('import', [70,90,95,97]), region('engine as e', [100,90,160,97]),
              region('output', [70,111,102,118]), region('=', [105,114,109,116]),
              region('e.run()', [113,110,150,117]), region('print(output)', [70,130,145,137])]
    rows, audit = listing(original, native)
    assert rows[0]['label'] == 'code'
    assert rows[0]['text'] == 'import engine as e\noutput = e.run()\nprint(output)'
    assert rows[0]['_semantic']['runs'][0]['type'] == 'code'
    assert audit[0]['action'] == 'native_code_layout'


def test_native_assignment_statements_recover_unfenced_listing():
    rows, _ = listing('result = e.run() value = result.value', [
        region('result = e.run()', [70,90,180,97]), region('value = result.value', [70,115,205,122])])
    assert rows[0]['label'] == 'code'
    assert rows[0]['text'] == 'result = e.run()\nvalue = result.value'


@pytest.mark.parametrize('transcription', [
    '```python\nx = source.other()\nprint(x)\n```',
    '```python\ndef invented():\n    x = source.value()\nprint(x)\n```',
])
def test_changed_or_missing_code_uses_original_graphic_without_rewriting(transcription):
    rows, audit = listing(transcription, [region('x = source.value()', [70,90,200,97]),
                                         region('print(x)', [70,115,120,122])])
    assert rows[0]['label'] == 'picture' and rows[0]['text'] == ''
    assert rows[0]['_semantic']['kind'] == 'figure'
    assert audit[0]['action'] == 'native_code_original_raster'
    assert rows[0]['_semantic']['attrs']['annotations'][-1]['kind'] == 'code_transcription'


def test_annotated_listing_retains_one_original_crop_not_an_extra_translated_label():
    rows, _ = listing('```python\nx = source.value()\nprint(x)\n```\nresult value', [
        region('x = source.value()', [70,90,200,97]), region('print(x)', [70,115,120,122]),
        region('result value', [200,120,280,130])])
    assert rows[0]['_semantic']['kind'] == 'figure'
    assert rows[0]['_semantic']['children'] == []
    assert rows[0]['prov'][0]['bbox'] == {'l':60,'t':80,'r':300,'b':160,'coord_origin':'TOPLEFT'}


def test_incorrect_or_flattened_indentation_is_not_guessed():
    native = [region('for x in values:', [70,90,180,97]), region('print(x)', [90,115,140,122])]
    for text in ['```python for x in values: print(x) ```', '```python\nfor x in values:\nprint(x)\n```']:
        rows, _ = listing(text, native)
        assert rows[0]['label'] == 'picture'
    rows, _ = listing('```python\nfor x in values:\n    print(x)\n```', native)
    assert rows[0]['label'] == 'code'
    assert rows[0]['text'] == 'for x in values:\n    print(x)'


def test_unrelated_compound_content_does_not_become_a_code_image():
    rows, audit = listing('A paragraph.\n\n```python\nx = 1\n```\n\nA second paragraph.',
                          [region('Different native paragraph.', [70,90,230,100])], graphics=False)
    assert rows[0]['_semantic']['kind'] == 'group'
    assert audit == []


def test_prose_describing_code_stays_prose():
    rows, audit = listing('The call engine.run() returns result = 1.', [
        region('The call engine.run()', [70,90,200,97]), region('returns result = 1.', [70,115,200,122])])
    assert rows[0]['label'] == 'text'
    assert audit == []


def test_spaces_inside_native_code_strings_are_not_silently_lost():
    rows, _ = listing('```python\nprint("helloworld")\n```',
                      [region('print("hello world")', [70,90,220,97])])
    assert rows[0]['label'] == 'picture'


@pytest.mark.parametrize('native', [
    [region('return x', [70,90,150,97])],
    [region('return', [70,90,105,97]), region('x', [111,90,118,97])],
])
def test_native_word_separators_survive_font_changes(native):
    rows, _ = listing('```python\nreturnx\n```', native)
    assert rows[0]['label'] == 'picture'
    rows, _ = listing('```python\nreturn x\n```', native)
    assert rows[0]['label'] == 'code'


def test_scan_without_native_evidence_keeps_code_literal():
    rows, audit = listing('```python\nx = 1\n```', [], graphics=False)
    assert rows[0]['label'] == 'code' and rows[0]['text'] == 'x = 1\n'
    assert audit == []


def test_adapter_does_not_overwrite_native_code_layout_with_model_recognition(tmp_path):
    from pathlib import Path
    from packages.ir import validate_source
    from packages.parsers.inspect import inspect_pdf
    from packages.parsers.source_adapter import SourceAdapter
    pdf = Path('tests/fixtures/sample.pdf')
    inspection = inspect_pdf(pdf)
    page = inspection['pages'][0]
    # Authored geometry isolates code-layout plumbing from inference quality.
    page['text_regions'] = [region('value = engine.run()', [70,90,200,97]),
                            region('print(value)', [70,115,150,122])]
    page['graphic_regions'] = [{'bbox':[60,80,300,160]}]
    page['image_regions'] = []
    width, height = page['page_size']
    raw = json.dumps([{'category':'title', 'bbox':[0,0,900,70], 'text':'Test title'},
                     {'category':'text', 'bbox':[60/width*1000,80/height*1000,300/width*1000,160/height*1000],
                      'text':'```python value = engine.run() print(value) ```'}])
    source = SourceAdapter().adapt(json_items(raw, page), inspection, pdf, 'original', tmp_path,
        semantic=True, model_generated_source=True,
        enrichment={'model':'authored-test', 'revision':'fixture'})['source_revision']
    validate_source(source, asset_root=tmp_path)
    code = next(block for block in source['blocks'] if block['kind'] == 'code')
    assert code['normalized_text'] == 'value = engine.run()\nprint(value)'
    assert code['translatable'] is False
    assert source['protected_atoms'][code['source_inline'][0]['ref']]['value'] == code['normalized_text']
