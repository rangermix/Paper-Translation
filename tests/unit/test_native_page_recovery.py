"""NB-AT07/08 controlled equivalents of missing columns/pages and table typos."""
import copy

from packages.parsers.recovery import recover_items


def region(text, bbox):
    return {'text': text, 'bbox': bbox}


def item(ref, text, bbox, page, label='text', **extra):
    return {'self_ref': ref, 'label': label, 'orig': text, 'text': text,
            'prov': [{'page_no': page, 'bbox': dict(zip(('l', 't', 'r', 'b'), bbox), coord_origin='TOPLEFT')}], **extra}


def test_missing_column_and_page_are_recovered_from_native_geometry():
    pages = [{'page': n, 'page_size': [600, 800], 'text_regions': []} for n in range(1, 15)]
    pages[0]['text_regions'] = [region('Controlled paper', [20, 20, 550, 40])]
    pages[4]['text_regions'] = [region('Left column first.', [20, 50, 270, 70]), region('Left column second.', [20, 80, 270, 100]),
        region('Right column first.', [320, 50, 570, 70])]
    pages[13]['text_regions'] = [region('Missing final page.', [20, 50, 550, 80])]
    original = [item('title', 'Controlled paper', [20, 20, 550, 40], 1, 'title'),
                item('right', 'Right column first.', [320, 50, 570, 70], 5)]
    before = copy.deepcopy(original)
    recovered, audit = recover_items(original, pages)
    assert original == before
    page5 = [row['text'] for row in recovered if row['prov'][0]['page_no'] == 5 and row['label'] == 'text']
    assert page5 == ['Left column first.', 'Left column second.', 'Right column first.']
    assert any(row['text'] == 'Missing final page.' for row in recovered)
    assert {5, 14} <= {row['page'] for row in audit if row['action'] == 'native_page_recovery'}
    assert all(row['origin'] == 'automatic_recovery' for row in audit)


def test_table_configuration_punctuation_uses_unique_native_evidence():
    pages = [{'page': 11, 'page_size': [600, 800], 'text_regions': [region('Configuration 9-5-1-1', [20, 50, 500, 100])]}]
    original = [item('table', '', [20, 50, 500, 100], 11, 'table', data={'table_cells': [{'text': '9.5-1-1'}]})]
    recovered, audit = recover_items(original, pages)
    table = next(row for row in recovered if row['label'] == 'table')
    assert table['data']['table_cells'][0]['text'] == '9-5-1-1'
    assert original[0]['data']['table_cells'][0]['text'] == '9.5-1-1'
    assert any(row['before'] == '9.5-1-1' and row['after'] == '9-5-1-1' for row in audit)


def test_failed_local_recovery_runs_once_and_retains_original_page():
    calls = []
    def local(page):
        calls.append(page)
        raise RuntimeError('private decoder body')
    pages = [{'page': 1, 'page_size': [600, 800], 'text_regions': [], 'scan_suspected': True}]
    recovered, audit = recover_items([], pages, local_reparse=local)
    assert calls == [1]
    assert any(row.get('_nb_page_fallback') for row in recovered)
    assert any(row['action'] == 'page_image_fallback' for row in audit)
    assert 'private decoder body' not in str(audit)


def test_expired_budget_never_calls_local_model():
    calls = []
    pages = [{'page': 1, 'page_size': [600, 800], 'text_regions': []}]
    recovered, audit = recover_items([], pages, local_reparse=lambda p: calls.append(p), remaining_seconds=lambda: 0)
    assert calls == []
    assert any(row.get('_nb_page_fallback') for row in recovered)
