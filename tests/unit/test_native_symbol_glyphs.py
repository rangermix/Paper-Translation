"""An unknown PDFium glyph needs embedded-font and independent position proof."""
from copy import deepcopy

import pytest
from pypdf import PageObject
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                          NameObject, NumberObject)

from packages.parsers import glyphs
from packages.parsers.fidelity import reconcile_items


def symbol_page(*, name='ABCDEF+ExampleMath', glyph='star', code=63, text=b'?',
                origin=(100, 200), encoding_extra=b'', font_extra=None):
    """Minimal embedded encoding fixture; no third-party font is copied."""
    page = PageObject.create_blank_page(width=600, height=800)
    font_file = DecodedStreamObject()
    program = (b'%!PS-AdobeFont-1.0\n/FontName /' + name.encode() + b' def\n'
               b'/Encoding 256 array\n0 1 255 {1 index exch /.notdef put} for\n'
               + f'dup {code} /{glyph} put\n'.encode() + encoding_extra
               + b'readonly def\ncurrentfile eexec\n')
    font_file.set_data(program)
    font_file[NameObject('/Length1')] = NumberObject(len(program))
    descriptor = DictionaryObject({NameObject('/FontName'): NameObject('/' + name),
                                   NameObject('/FontFile'): font_file})
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/' + name),
        NameObject('/FontDescriptor'): descriptor,
        NameObject('/FirstChar'): NumberObject(code), NameObject('/LastChar'): NumberObject(code),
        NameObject('/Widths'): ArrayObject([NumberObject(600)])})
    font.update(font_extra or {})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): font})})
    content = DecodedStreamObject()
    content.set_data(f'BT /F1 12 Tf 1 0 0 1 {origin[0]} {origin[1]} Tm '.encode()
                     + b'(' + text + b') Tj ET')
    page[NameObject('/Contents')] = content
    return page


def native(text='?', *, origin=(100, 200), font='ExampleMath'):
    return {'index': 0, 'text': text, 'bbox': [100, 590, 108, 600],
            'origin': list(origin), 'font': font}


def recover(page, character=None):
    evidence = glyphs.embedded_symbol_evidence(page)
    return glyphs.native_regions([character or native()], [[99, 589, 110, 601]],
                                symbol_evidence=evidence)


def test_embedded_encoding_and_matching_origin_restore_unknown_symbol():
    page = symbol_page()
    assert page.extract_text() == '⋆'  # Independently decoded by the pinned pypdf.
    regions, audit = recover(page)
    assert regions[0]['text'] == '⋆'
    assert audit[0]['action'] == 'native_embedded_symbol_reconciliation'
    assert audit[0]['base']['text'] == '?'
    assert audit[0]['replacement'] == '⋆'
    assert audit[0]['evidence']['encoded_byte'] == 63
    assert audit[0]['evidence']['glyph_name'] == '/star'
    assert audit[0]['evidence']['origin'] == [100, 200]


@pytest.mark.parametrize('character', [native(origin=(100.2, 200)), native(font='OtherMath'),
                                      native(font='UVWXYZ+ExampleMath'),
                                      native(text='∗'), native(text='★'),
                                      {'index': 0, 'text': '?', 'bbox': [100, 590, 108, 600]}])
def test_absent_or_conflicting_native_identity_never_changes_text(character):
    regions, audit = recover(symbol_page(), character)
    assert regions[0]['text'] == character['text']
    assert not audit


@pytest.mark.parametrize('page', [symbol_page(glyph='question'), symbol_page(glyph='A'),
    symbol_page(glyph='star', code=64, text=b'@'), symbol_page(text=b'??'),
    symbol_page(encoding_extra=b'dup 63 /question put\n'),
    symbol_page(font_extra={NameObject('/Encoding'): NameObject('/StandardEncoding')})])
def test_unsupported_or_ambiguous_font_evidence_keeps_question_mark(page):
    regions, audit = recover(page)
    assert regions[0]['text'] == '?'
    assert not audit


def test_missing_embedded_font_does_not_use_font_name_as_a_guess():
    page = symbol_page()
    del page['/Resources']['/Font']['/F1']['/FontDescriptor']['/FontFile']
    assert recover(page) == ([{'bbox': [99, 589, 110, 601], 'text': '?', 'native_indices': [0]}], [])


def test_explicit_native_subset_identity_must_match_exactly():
    regions, audit = recover(symbol_page(), native(font='ABCDEF+ExampleMath'))
    assert regions[0]['text'] == '⋆'
    assert len(audit) == 1


def test_overlapping_independent_text_or_native_glyphs_is_ambiguous():
    page = symbol_page()
    page['/Contents'].set_data(page['/Contents'].get_data() + b'\n' + page['/Contents'].get_data())
    assert recover(page)[1] == []
    evidence = glyphs.embedded_symbol_evidence(symbol_page())
    first = native(); second = dict(native(), index=1)
    regions, audit = glyphs.native_regions([first, second], [[99, 589, 110, 601]], symbol_evidence=evidence)
    assert regions[0]['text'] == '??'
    assert not audit


def test_other_text_draw_at_same_origin_cannot_supply_ambiguous_proof():
    page = symbol_page()
    page['/Contents'].set_data(page['/Contents'].get_data()
        + b'\nBT /F1 12 Tf 1 0 0 1 100 200 Tm (A) Tj ET')
    regions, audit = recover(page)
    assert regions[0]['text'] == '?'
    assert not audit


def test_symbol_audit_cannot_authorize_unproven_latin_accent_changes():
    item = {'self_ref': 'authors', 'label': 'text', 'orig': 'Jose Research', 'text': 'Jose Research',
            'prov': [{'page_no': 1, 'bbox': {'l': 90, 't': 580, 'r': 300, 'b': 610, 'coord_origin': 'TOPLEFT'}}]}
    pages = [{'page': 1, 'page_size': [600, 800],
              'text_regions': [{'text': 'José Research', 'bbox': [100, 590, 280, 600]}],
              'glyph_reconciliations': [{'action': 'native_embedded_symbol_reconciliation',
                                         'base': native(), 'replacement': '⋆'}]}]
    recovered, _ = reconcile_items([deepcopy(item)], pages)
    assert recovered[0]['orig'] == 'Jose Research'


def test_native_symbol_reaches_source_without_model_inference():
    regions, audit = recover(symbol_page())
    regions.append({'text': 'Microsoft Research', 'bbox': [110, 590, 250, 600]})
    item = {'self_ref': 'affiliation', 'label': 'text', 'orig': '?Microsoft Research',
            'text': '?Microsoft Research',
            'prov': [{'page_no': 1, 'bbox': {'l': 90, 't': 580, 'r': 300, 'b': 610, 'coord_origin': 'TOPLEFT'}}]}
    pages = [{'page': 1, 'page_size': [600, 800], 'text_regions': regions, 'glyph_reconciliations': audit}]
    recovered, _ = reconcile_items([item], pages)
    assert recovered[0]['orig'] == '⋆Microsoft Research'
