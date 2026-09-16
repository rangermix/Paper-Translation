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


def test_small_omission_preserves_other_parser_paragraphs():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('Correct first line', [20, 50, 260, 60]),
        region('and second line.', [20, 63, 220, 73]),
        region('Recovered missing sentence.', [20, 100, 270, 110])]}
    paragraph = item('paragraph', 'Correct first line and second line.', [18, 48, 275, 76], 1)
    title = item('title', 'Paper', [20, 10, 200, 30], 1, 'title')
    recovered, audit = recover_items([title, paragraph], [page])
    assert next(row for row in recovered if row['self_ref'] == 'paragraph') == paragraph
    assert [row['text'] for row in recovered if row['label'] == 'text'] == [
        paragraph['text'], 'Recovered missing sentence.']
    assert audit[0]['before'] == [paragraph['text']]
    assert audit[0]['after'] == [paragraph['text'], 'Recovered missing sentence.']


def test_native_line_wrap_artifacts_do_not_destroy_complete_paragraph():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('We demonstrate train\x02', [20, 50, 270, 60]),
        region('ing models with 12 layers.', [20, 63, 270, 73])]}
    paragraph = item('paragraph', 'We demonstrate training models with 12 layers.', [18, 48, 275, 76], 1)
    recovered, audit = recover_items([item('title', 'Paper', [20, 10, 200, 30], 1, 'title'), paragraph], [page])
    assert recovered[-1] == paragraph
    assert audit == []


def test_recovery_repairs_only_affected_paragraph_and_keeps_it_grouped():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('First complete paragraph.', [20, 50, 260, 60]),
        region('Second paragraph has', [20, 100, 260, 110]),
        region('an omitted middle line', [20, 113, 260, 123]),
        region('and ends here.', [20, 126, 200, 136])]}
    original = [item('title', 'Paper', [20, 10, 200, 30], 1, 'title'),
        item('first', 'First complete paragraph.', [18, 48, 275, 63], 1),
        item('second', 'Second paragraph has and ends here.', [18, 98, 275, 139], 1)]
    recovered, audit = recover_items(original, [page])
    assert recovered[1] == original[1]
    assert len(recovered) == 3
    assert ' '.join(recovered[2]['text'].split()) == 'Second paragraph has an omitted middle line and ends here.'
    assert audit[0]['rule_version'] != 'native-page-recovery-v1'


def test_missing_native_prose_groups_lines_and_style_fragments_without_crossing_columns():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('Left first line continues', [20, 50, 270, 60]),
        region('with', [20, 63, 47, 73]), region('styled words.', [51, 63, 150, 73]),
        region('New paragraph.', [20, 98, 210, 108]),
        region('Right first line continues', [320, 50, 570, 60]),
        region('in the same column.', [320, 63, 500, 73])]}
    recovered, _ = recover_items([item('title', 'Paper', [20, 10, 550, 30], 1, 'title')], [page])
    paragraphs = [' '.join(row['text'].split()) for row in recovered if row['label'] == 'text']
    assert paragraphs == ['Left first line continues with styled words.', 'New paragraph.',
        'Right first line continues in the same column.']


def test_recovery_does_not_duplicate_retained_heading_or_complex_content():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('Heading ligature differs', [20, 10, 200, 30]),
        region('Table values', [20, 50, 270, 80]),
        region('Missing paragraph.', [20, 100, 270, 110])]}
    original = [item('title', 'Heading', [20, 10, 200, 30], 1, 'title'),
        item('table', 'Table', [20, 50, 270, 80], 1, 'table', data={'table_cells': []})]
    recovered, _ = recover_items(original, [page])
    assert recovered[:2] == original
    assert [row['text'] for row in recovered if row['label'] == 'text'] == ['Missing paragraph.']


def test_uncertain_math_or_sparse_native_evidence_cannot_replace_a_paragraph():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('This partition gives Y = GeLU(X1 A1 + X2 A2).', [20, 50, 270, 60]),
        region('Only a sparse native fragment.', [20, 100, 260, 110])]}
    original = [item('title', 'Paper', [20, 10, 200, 30], 1, 'title'),
        item('math-prose', 'This partition gives $Y = GeLU(X_1A_1 + X_2A_2)$.', [18, 48, 275, 80], 1),
        item('sparse', 'A complete paragraph with important content absent from the native text layer.', [18, 98, 275, 150], 1)]
    recovered, audit = recover_items(original, [page])
    assert recovered == original
    assert audit and audit[0]['result'] == 'retained_page'
    assert audit[0]['before'] == audit[0]['after']


def test_parser_bbox_rounding_does_not_duplicate_a_line_already_in_paragraph():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('First line of paragraph', [20, 50, 270, 60]),
        region('has an existing final line.', [20, 63, 230, 73])]}
    paragraph = item('paragraph', 'First line of paragraph has an existing final line.', [18, 48, 275, 62], 1)
    original = [item('title', 'Paper', [20, 10, 200, 30], 1, 'title'), paragraph]
    recovered, _ = recover_items(original, [page])
    assert recovered == original


def test_narrow_column_gutter_is_not_joined_as_font_runs():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('Left first.', [20, 50, 293, 60]), region('Left second.', [20, 63, 291, 73]),
        region('Right first.', [307, 50, 570, 60]), region('Right second.', [307, 63, 566, 73])]}
    recovered, _ = recover_items([item('title', 'Paper', [20, 10, 550, 30], 1, 'title')], [page])
    assert [row['text'] for row in recovered if row['label'] == 'text'] == [
        'Left first. Left second.', 'Right first. Right second.']


def test_fragmented_font_runs_still_respect_column_gutter():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('Left', [20, 50, 150, 60]), region('first.', [154, 50, 293, 60]),
        region('Right', [307, 50, 440, 60]), region('first.', [444, 50, 570, 60]),
        region('Left', [20, 63, 150, 73]), region('second.', [154, 63, 293, 73]),
        region('Right', [307, 63, 440, 73]), region('second.', [444, 63, 570, 73])]}
    recovered, _ = recover_items([item('title', 'Paper', [20, 10, 550, 30], 1, 'title')], [page])
    assert [row['text'] for row in recovered if row['label'] == 'text'] == [
        'Left first. Left second.', 'Right first. Right second.']


def test_broad_parser_box_does_not_interleave_columns_during_repair():
    page = {'page': 1, 'page_size': [600, 800], 'text_regions': [
        region('Left first.', [20, 50, 270, 60]), region('Left second.', [20, 63, 270, 73]),
        region('Right first.', [320, 50, 570, 60]), region('Right second.', [320, 63, 570, 73])]}
    original = [item('title', 'Paper', [20, 10, 550, 30], 1, 'title'),
        item('ambiguous', 'Left first. Left second.', [18, 48, 572, 75], 1)]
    recovered, audit = recover_items(original, [page])
    assert recovered == original
    assert audit[0]['result'] == 'retained_page'
