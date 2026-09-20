"""Numeric footnotes require the native PDF's raised glyph occurrence."""
import builtins
from copy import deepcopy

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from packages.ir import flatten_inline, validate_source
from packages.parsers import inspect_pdf
from packages.parsers.pdf_docling import DoclingParser


def authored_pdf(path, *, marker='1', before='Research.', after=' is discussed with ordinary 1.',
                 marker_size=7, rise=5, note='1 Supporting detail.', note_page=1, second_reference=False):
    writer = PdfWriter()
    for number in range(1, note_page + 1):
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): font})})
        commands = ['BT /F1 16 Tf 40 760 Td (Footnote paper) Tj ET']
        if number == 1:
            commands.append(f'BT /F1 12 Tf 40 700 Td ({before}) Tj /F1 {marker_size} Tf '
                f'{rise} Ts ({marker}) Tj /F1 12 Tf 0 Ts ({after}) Tj ET')
            if second_reference:
                commands.append(commands[-1].replace('40 700 Td', '40 660 Td'))
        if number == note_page:
            commands.append(f'BT /F1 9 Tf 40 70 Td ({note}) Tj ET')
        stream = DecodedStreamObject()
        stream.set_data('\n'.join(commands).encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as handle:
        writer.write(handle)
    return path


def item(ref, label, text, bbox, *, page=1):
    return {'self_ref': ref, 'label': label, 'orig': text, 'text': text,
        'prov': [{'page_no': page, 'bbox': dict(zip(('l', 't', 'r', 'b'), bbox), coord_origin='TOPLEFT'),
                  'charspan': [0, len(text)]}]}


def adapt(tmp_path, **options):
    pdf = authored_pdf(tmp_path / 'footnotes.pdf', **options)
    text = options.get('before', 'Research.') + options.get('marker', '1') + options.get('after', ' is discussed with ordinary 1.')
    items = [item('title', 'title', 'Footnote paper', [38, 25, 300, 45]),
        item('body', 'text', text, [38, 78, 580, 110]),
        item('note', 'footnote', options.get('note', '1 Supporting detail.'), [38, 715, 580, 735],
             page=options.get('note_page', 1))]
    if options.get('second_reference'):
        items.insert(2, item('second_body', 'text', text, [38, 118, 580, 150]))
    inspection = inspect_pdf(pdf)
    result = DoclingParser().adapt(items, inspection, pdf, 'original', tmp_path / 'output')
    return result['source_revision'], result['inspection']


def test_native_raised_numeric_marker_becomes_source_xref(tmp_path):
    source, inspection = adapt(tmp_path)
    body = next(block for block in source['blocks'] if block['kind'] == 'paragraph')
    note = next(block for block in source['blocks'] if block['kind'] == 'footnote')
    assert [node for node in body['source_inline'] if node['type'] == 'xref'] == [
        {'type': 'xref', 'label': '1', 'target_block_id': note['id']}]
    assert body['raw_text'] == body['normalized_text'] == 'Research.1 is discussed with ordinary 1.'
    assert flatten_inline(body['source_inline'], source['protected_atoms']) == body['normalized_text']
    assert any(node['type'] == 'protected_ref' and source['protected_atoms'][node['ref']]['value'] == '1'
               for node in body['source_inline'])
    assert inspection['pages'][0].get('footnote_markers')
    validate_source(source, asset_root=tmp_path / 'output')


def test_native_multidigit_marker_keeps_its_label(tmp_path):
    source, _ = adapt(tmp_path, marker='12', note='12 Supporting detail.')
    body = next(block for block in source['blocks'] if block['kind'] == 'paragraph')
    assert [node['label'] for node in body['source_inline'] if node['type'] == 'xref'] == ['12']


def test_each_native_citing_block_links_the_same_note(tmp_path):
    source, inspection = adapt(tmp_path, second_reference=True)
    paragraphs = [block for block in source['blocks'] if block['kind'] == 'paragraph']
    note = next(block for block in source['blocks'] if block['kind'] == 'footnote')
    assert len(paragraphs) == 2
    assert all([node['target_block_id'] for node in block['source_inline'] if node['type'] == 'xref'] == [note['id']]
               for block in paragraphs)
    assert len(inspection['footnote_links']) == 2


@pytest.mark.parametrize('before', ['Research.', 'Research?'])
def test_marker_after_punctuation_preserves_other_inline_content(tmp_path, before):
    source, _ = adapt(tmp_path, before=before, after=' See https://example.org and [2].')
    body = next(block for block in source['blocks'] if block['kind'] == 'paragraph')
    assert [node['label'] for node in body['source_inline'] if node['type'] == 'xref'] == ['1']
    assert [node['href'] for node in body['source_inline'] if node['type'] == 'link'] == ['https://example.org']
    assert any(node['type'] == 'protected_ref' and source['protected_atoms'][node['ref']]['value'] == '[2]'
               for node in body['source_inline'])
    assert flatten_inline(body['source_inline'], source['protected_atoms']) == body['raw_text']
    validate_source(source, asset_root=tmp_path / 'output')


@pytest.mark.parametrize('options', [
    {'marker_size': 12, 'rise': 0}, {'marker_size': 12, 'rise': 5},
    {'marker_size': 7, 'rise': 0}, {'marker_size': 7, 'rise': -3}, {'marker_size': 7, 'rise': 1},
    {'before': 'x'}, {'before': '10'}, {'before': 'cm'}, {'before': 'log'}, {'before': 'sin'},
    {'before': 'GHz'}, {'before': 'Research.', 'after': ' = 42.'},
    {'before': 'Research'}, {'before': 'Research!'},
    {'before': 'The squared norm', 'marker': '2', 'after': ' is bounded.', 'note': '2 An unrelated note.'},
    {'before': 'ReLU', 'marker': '2', 'after': ' is bounded.', 'note': '2 An unrelated note.'},
    {'before': 'rank', 'marker': '2', 'after': ' is bounded.', 'note': '2 An unrelated note.'},
])
def test_unproven_numbers_and_mathematical_exponents_stay_unlinked(tmp_path, options):
    source, inspection = adapt(tmp_path, **options)
    assert not inspection['pages'][0]['footnote_markers']
    assert not [node for block in source['blocks'] for node in block['source_inline'] if node['type'] == 'xref']
    body = next(block for block in source['blocks'] if block['kind'] == 'paragraph')
    assert flatten_inline(body['source_inline'], source['protected_atoms']) == body['normalized_text'] == body['raw_text']


def test_note_number_on_another_page_is_not_a_target(tmp_path):
    source, inspection = adapt(tmp_path, note_page=2)
    assert inspection['pages'][0]['footnote_markers']
    assert not [node for block in source['blocks'] for node in block['source_inline'] if node['type'] == 'xref']


def test_fresh_parser_links_do_not_import_source_correction_or_domain_modules(tmp_path, monkeypatch):
    original_import = builtins.__import__
    def parser_import(name, *args, **kwargs):
        if name.startswith(('packages.source_revisions', 'packages.domain.errors')):
            raise ModuleNotFoundError('Module is not included in the parser image: ' + name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', parser_import)
    source, _ = adapt(tmp_path)
    assert any(node['type'] == 'xref' for block in source['blocks'] for node in block['source_inline'])


def unlinked_source(tmp_path):
    from packages.parsers.pdf_docling import _source_nodes
    source, inspection = adapt(tmp_path)
    for block in source['blocks']:
        block['source_inline'] = _source_nodes(block['normalized_text'], block['id'], source['protected_atoms'], block['kind'])
        block.pop('source_hash')
    body = next(block for block in source['blocks'] if block['kind'] == 'paragraph')
    note = next(block for block in source['blocks'] if block['kind'] == 'footnote')
    return source, inspection, body, note


@pytest.mark.parametrize('case', ['duplicate_note', 'duplicate_body', 'moved_marker', 'moved_body',
    'moved_note', 'changed_note', 'missing_indices', 'wrong_marker_index', 'wrong_context_index'])
def test_ambiguous_or_misaligned_evidence_cannot_link_an_occurrence(tmp_path, case):
    from packages.parsers.footnotes import link_native_footnotes
    from packages.parsers.pdf_docling import _source_nodes
    source, inspection, body, note = unlinked_source(tmp_path)
    if case in {'duplicate_note', 'duplicate_body'}:
        duplicate = deepcopy(note if case == 'duplicate_note' else body)
        duplicate['id'] = 'duplicate'
        source['blocks'].append(duplicate)
    elif case == 'moved_marker':
        body['normalized_text'] = body['raw_text'] = 'Research. is discussed1 with ordinary 1.'
        body['source_inline'] = _source_nodes(body['normalized_text'], body['id'], source['protected_atoms'], body['kind'])
    elif case in {'moved_body', 'moved_note'}:
        block = body if case == 'moved_body' else note
        block['provenance'][0]['bbox'] = [38, 200, 580, 230]
    elif case == 'changed_note':
        note['normalized_text'] = note['raw_text'] = '1 Unsupported note text.'
    elif case == 'missing_indices':
        for region in inspection['pages'][0]['text_regions']:
            region.pop('native_indices')
    elif case == 'wrong_marker_index':
        ordinary = next(region for region in inspection['pages'][0]['text_regions'] if 'ordinary' in region['text'])
        inspection['pages'][0]['footnote_markers'][0]['native_indices'] = [ordinary['native_indices'][-2]]
    else:
        inspection['pages'][0]['footnote_markers'][0]['context']['native_indices'][0] += 1
    assert link_native_footnotes(source, inspection) == []
    assert all(node['type'] != 'xref' for node in body['source_inline'])


@pytest.mark.parametrize('case', ['different_pdf', 'existing_source', 'code_block', 'math_block',
    'linked_span', 'code_span', 'missing_native_markers'])
def test_existing_or_unsupported_sources_stay_untouched(tmp_path, case):
    from packages.parsers.footnotes import link_native_footnotes
    source, inspection, body, _ = unlinked_source(tmp_path)
    if case == 'different_pdf':
        inspection['sha256'] = 'f' * 64
    elif case == 'existing_source':
        body['source_hash'] = 'f' * 64
    elif case in {'code_block', 'math_block'}:
        body['kind'] = case.removesuffix('_block')
    elif case == 'linked_span':
        body['source_inline'] = [{'type': 'link', 'href': 'https://example.org', 'text': body['normalized_text']}]
    elif case == 'code_span':
        body['source_inline'] = [{'type': 'text', 'marks': ['code'], 'text': body['normalized_text']}]
    else:
        inspection['pages'][0].pop('footnote_markers')
    before = deepcopy(source)
    assert link_native_footnotes(source, inspection) == []
    assert source == before
