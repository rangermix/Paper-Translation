"""Escaped model line breaks need native table-row evidence before decoding."""
from packages.parsers.recovery import recover_items
from tests.unit.test_native_page_recovery import item, region


def table_page(texts, native):
    table = item('table', '', [60, 80, 540, 180], 1, 'table',
                 data={'table_cells': [{'text': text} for text in texts]})
    return [table], [{'page': 1, 'page_size': [612, 792], 'text_regions': native}]


def test_escaped_header_linebreaks_are_recovered_from_consecutive_native_rows():
    items, pages = table_page([r'DNN\nModel', r'BSP speedup\nover 1 machine', r'PipeDream\nConfig'], [
        region('DNN BSP speedup PipeDream', [80, 89, 520, 96]),
        region('Model over 1 machine Config', [80, 98, 520, 105])])
    recovered, audit = recover_items(items, pages)
    table = next(row for row in recovered if row['self_ref'] == 'table')
    assert [cell['text'] for cell in table['data']['table_cells']] == [
        'DNN\nModel', 'BSP speedup\nover 1 machine', 'PipeDream\nConfig']
    records = [row for row in audit if row['action'] == 'native_table_linebreak']
    assert len(records) == 3
    assert all(len(row['native_evidence']) == 2 for row in records)
    assert items[0]['data']['table_cells'][0]['text'] == r'DNN\nModel'


def test_literal_code_escapes_and_tex_commands_are_not_decoded():
    texts = [r'Use \n in code', r'Gradient \nabla f', r'\nu', r'DNN\nUnproved']
    items, pages = table_page(texts, [
        region(r'Use \n in code', [80, 89, 300, 96]),
        region('Gradient ∇ f', [80, 109, 300, 116]),
        region('ν', [80, 129, 100, 136]),
        region('DNN Model', [320, 89, 520, 96])])
    recovered, audit = recover_items(items, pages)
    table = next(row for row in recovered if row['self_ref'] == 'table')
    assert [cell['text'] for cell in table['data']['table_cells']] == texts
    assert not any(row['action'] == 'native_table_linebreak' for row in audit)


def test_words_in_unrelated_native_rows_are_not_linebreak_proof():
    items, pages = table_page([r'DNN\nModel'], [
        region('DNN', [80, 89, 180, 96]), region('Model', [380, 150, 500, 157])])
    recovered, _ = recover_items(items, pages)
    table = next(row for row in recovered if row['self_ref'] == 'table')
    assert table['data']['table_cells'][0]['text'] == r'DNN\nModel'


def test_wrapped_literal_backslash_n_in_original_table_is_not_decoded():
    items, pages = table_page([r'Use \n in code'], [
        region(r'Use \n', [80, 89, 250, 99]),
        region('in code', [80, 102, 250, 112])])
    recovered, audit = recover_items(items, pages)
    table = next(row for row in recovered if row['self_ref'] == 'table')
    assert table['data']['table_cells'][0]['text'] == r'Use \n in code'
    assert not any(row['action'] == 'native_table_linebreak' for row in audit)


def test_printed_escape_vetoes_matching_words_in_another_column():
    items, pages = table_page([r'Use \n in code'], [
        region(r'Use \n', [80, 89, 250, 99]),
        region('in code', [80, 102, 250, 112]),
        region('Use', [380, 89, 520, 99]),
        region('in code', [380, 102, 520, 112])])
    recovered, audit = recover_items(items, pages)
    table = next(row for row in recovered if row['self_ref'] == 'table')
    assert table['data']['table_cells'][0]['text'] == r'Use \n in code'
    assert not any(row['action'] == 'native_table_linebreak' for row in audit)
