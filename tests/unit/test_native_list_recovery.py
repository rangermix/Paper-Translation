"""Numbered text becomes a list only with consecutive markers and hanging text."""
from packages.parsers.recovery import recover_items
from tests.unit.test_native_page_recovery import item, region


def numbered_source(numbers=(1, 2, 3), *, hanging=True):
    items = [item('title', 'Paper', [40, 40, 550, 60], 1, 'title')]
    regions = []
    for offset, number in enumerate(numbers):
        top = 500 + offset * 28
        text = f'{number}. A carefully described requirement for the model.'
        items.append(item(f'item-{offset}', text, [318, top, 544, top + 25], 1))
        regions.extend([
            region(f'{number}. A carefully described requirement', [323, top + 2, 540, top + 12]),
            region('for the model.', [335 if hanging else 323, top + 14, 440, top + 24])])
    return items, [{'page': 1, 'page_size': [612, 792], 'text_regions': regions}]


def test_consecutive_native_numbered_paragraphs_keep_markers_and_ordered_list_indexes():
    items, pages = numbered_source()
    result, audit = recover_items(items, pages)
    recovered = [row for row in result if row['self_ref'].startswith('item-')]
    assert [row['label'] for row in recovered] == ['list_item'] * 3
    assert [row['list_index'] for row in recovered] == [1, 2, 3]
    assert all(row['enumerated'] for row in recovered)
    assert [row['text'] for row in recovered] == [row['text'] for row in items[1:]]
    record = next(row for row in audit if row['action'] == 'native_list_sequence')
    assert record['before'] == record['after']
    assert record['native_evidence']


def test_disconnected_numbers_and_non_hanging_numbered_headings_stay_paragraphs():
    for numbers, hanging in [((1, 3), True), ((1, 2), False)]:
        items, pages = numbered_source(numbers, hanging=hanging)
        result, _ = recover_items(items, pages)
        assert result == items


def test_numbered_text_in_separate_columns_does_not_form_one_list():
    items, pages = numbered_source((1, 2))
    items[2]['prov'][0]['bbox'].update(l=40, r=266)
    for native in pages[0]['text_regions'][2:]:
        native['bbox'][0] -= 278
        native['bbox'][2] -= 278
    result, _ = recover_items(items, pages)
    assert not any(row['label'] == 'list_item' for row in result)


def test_native_list_indexes_survive_adapter_with_original_markers(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    from packages.parsers.inspect import inspect_pdf
    from packages.parsers.pdf_docling import DoclingParser
    from packages.ir import validate_source

    items, pages = numbered_source()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    native = [region('Paper', [40, 42, 90, 52]), *pages[0]['text_regions']]
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(f'BT /F1 10 Tf 1 0 0 1 {r["bbox"][0]} {792-r["bbox"][1]-8} Tm ({r["text"]}) Tj ET'
                              for r in native).encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    pdf = tmp_path / 'numbered-list.pdf'
    writer.write(pdf)
    output = tmp_path / 'parsed'
    source = DoclingParser().adapt(items, inspect_pdf(pdf), pdf, 'original', output,
                                  parser_version='test')['source_revision']
    validate_source(source, asset_root=output)
    blocks = [block for block in source['blocks'] if block['kind'] == 'list_item']
    assert [block['attributes'].get('list_index') for block in blocks] == [1, 2, 3]
    assert all(block['attributes']['list_ordered'] for block in blocks)
    assert [block['raw_text'] for block in blocks] == [row['text'] for row in items[1:]]
