"""Printed boundaries, never lexical guesses, repair native prose and lists."""
from copy import deepcopy

from packages.parsers.recovery import recover_items
from packages.parsers.semantic import node
from tests.unit.test_academic_layout_recovery import row, pages_for


def test_completed_run_in_heading_joins_body_without_repeating_native_suffix():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('heading', 'Using Specific Hardware Abstractions.', [40, 198, 270, 211]),
             row('body', 'DL accelerators implement primitives for efficient code.', [40, 211, 270, 235])]
    pages = pages_for(items)[:1]
    pages[0]['text_regions'][1:] = [
        dict(text='Using Specific Hardware Abstrac\x02', bbox=[40, 200, 265, 209]),
        dict(text='tions.', bbox=[40, 213, 62, 220]),
        dict(text='DL accelerators implement primi\x02', bbox=[67, 213, 265, 222]),
        dict(text='tives for efficient code.', bbox=[40, 225, 190, 234])]
    before = deepcopy(items)
    result, audit = recover_items(items, pages)
    assert items == before
    assert next(r for r in result if r['self_ref'] == 'heading')['text'] == (
        'Using Specific Hardware Abstractions. DL accelerators implement primitives for efficient code.')
    assert not any(r['self_ref'] == 'body' for r in result)
    assert any(r['action'] == 'native_run_in_paragraph' for r in audit)


def test_separate_heading_or_unproven_native_suffix_does_not_join():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('heading', 'Using Specific Hardware Abstractions.', [40, 198, 270, 211]),
             row('body', 'DL accelerators implement primitives.', [40, 215, 270, 235])]
    result, audit = recover_items(items, pages_for(items)[:1])
    assert result == items
    assert not any(r['action'] == 'native_run_in_paragraph' for r in audit)


def test_semantic_list_bullets_are_covered_without_inserting_them_into_prose():
    paragraph = 'We support several backends.\nWe preserve every original example.'
    children = [node('list_item', [dict(type='text', text=t, path='/list')]) for t in paragraph.split('\n')]
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('list', paragraph, [40, 100, 280, 132], _semantic=node('group', children=children, attrs={'group_type':'list'}))]
    pages = pages_for(items)[:1]
    pages[0]['text_regions'][1:] = [
        dict(text='•', bbox=[40, 104, 42, 106]),
        dict(text=paragraph.split('\n')[0], bbox=[50, 101, 265, 110]),
        dict(text='•', bbox=[40, 124, 42, 126]),
        dict(text=paragraph.split('\n')[1], bbox=[50, 121, 275, 130])]
    result, _ = recover_items(items, pages)
    assert next(r for r in result if r['self_ref'] == 'list')['text'] == paragraph
    assert not any(r['text'] == '•' for r in result)


def test_punctuation_reconciliation_does_not_reinsert_semantic_list_markers():
    from packages.parsers.fidelity import reconcile_items
    paragraphs = ['We support several backends.', 'We preserve every original example.']
    children = [node('list_item', children=[node('paragraph', [dict(type='text', text=t, path='/list')])]) for t in paragraphs]
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('list', '\n'.join(paragraphs), [40, 100, 280, 132], _semantic=node('group', children=children, attrs={'group_type':'list'}))]
    pages = pages_for(items)[:1]
    pages[0]['text_regions'][1:] = [
        dict(text='•', bbox=[40, 104, 42, 106]),
        dict(text=paragraphs[0], bbox=[50, 101, 265, 110]),
        dict(text='•', bbox=[40, 124, 42, 126]),
        dict(text=paragraphs[1], bbox=[50, 121, 275, 130])]
    reconciled, _ = reconcile_items(items, pages)
    result, _ = recover_items(reconciled, pages)
    assert next(r for r in result if r['self_ref'] == 'list')['text'] == '\n'.join(paragraphs)


def test_flattened_bullets_split_only_with_distinct_native_baselines():
    text = '• Can this support more hardware? • Can it optimize existing programs?'
    semantic = node('paragraph', [dict(type='text', text=text, path='/paragraph', marks=['emphasis'])])
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('questions', text, [40, 100, 280, 133], _semantic=semantic)]
    pages = pages_for(items)[:1]
    pages[0]['text_regions'][1:] = [
        dict(text='•', bbox=[40, 104, 42, 106]),
        dict(text='Can this support more hardware?', bbox=[50, 101, 265, 110]),
        dict(text='•', bbox=[40, 124, 42, 126]),
        dict(text='Can it optimize existing programs?', bbox=[50, 121, 275, 130])]
    result, audit = recover_items(items, pages)
    lists = [r for r in result if r['label'] == 'list_item']
    assert [r['text'] for r in lists] == ['Can this support more hardware?', 'Can it optimize existing programs?']
    assert all(r['_semantic']['runs'][0]['marks'] == ['emphasis'] for r in lists)
    assert all(r['_semantic']['kind'] == 'list_item' for r in lists)
    assert any(r['action'] == 'native_bullet_list' for r in audit)
    unchanged, _ = recover_items(items, pages_for(items)[:1])
    assert unchanged == items


def test_sub_point_plot_markers_inside_a_figure_do_not_become_paragraphs():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('plot', '', [40, 100, 270, 300], label='picture')]
    pages = pages_for(items)[:1]
    pages[0]['text_regions'] += [dict(text='.', bbox=[90, y, 90.7, y + .7]) for y in [120, 140, 160]]
    result, _ = recover_items(items, pages)
    assert result == items


def test_centered_folio_straddling_margin_threshold_does_not_break_page_continuation():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'To enable graph optimiza', [310, 713, 550, 725]),
             row('folio', '1', [303, 750, 309, 758]),
             row('right', 'tions across diverse hardware.', [40, 80, 270, 100], 2)]
    pages = pages_for(items)
    pages[0]['text_regions'][1]['text'] += '\x02'
    result, audit = recover_items(items, pages)
    assert next(r for r in result if r['self_ref'] == 'folio')['label'] == 'page_footer'
    assert next(r for r in result if r['self_ref'] == 'left')['text'] == 'To enable graph optimizations across diverse hardware.'
    assert any(r['action'] == 'native_paragraph_continuation' for r in audit)


def test_list_item_continuation_across_column_retains_one_list_owner():
    first = 'How does this compare to existing frame'
    second = 'works on each hardware backend?'
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('question', first, [50, 700, 270, 715], label='list_item',
                 _semantic=node('list_item', [dict(type='text', text=first, path='/list')], attrs={'list_ordered':False})),
             row('plot', '', [310, 80, 550, 200], label='picture'),
             row('continued', second, [310, 215, 550, 235],
                 _semantic=node('paragraph', [dict(type='text', text=second, path='/body')]))]
    pages = pages_for(items)[:1]
    pages[0]['text_regions'][1]['text'] += '\x02'
    result, _ = recover_items(items, pages)
    question = next(r for r in result if r['self_ref'] == 'question')
    assert question['label'] == question['_semantic']['kind'] == 'list_item'
    assert question['text'] == 'How does this compare to existing frameworks on each hardware backend?'
    assert not any(r['self_ref'] == 'continued' for r in result)


def test_list_item_does_not_consume_a_separately_marked_next_item():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('first', 'A list entry without punctuation', [40, 700, 270, 715], label='list_item'),
             row('second', '• another list entry.', [310, 80, 550, 100])]
    result, _ = recover_items(items, pages_for(items)[:1])
    assert result == items


DUPLICATED_PARAGRAPH = ('This paragraph describes how a system cooperatively loads the data and then '
                        'synchronizes all threads before sharing the computed results.')


def duplicate_case():
    native_top = 'An earlier paragraph introduces the printed code example and explains its execution.'
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('top', native_top, [40, 100, 270, 120]),
             row('wrong', DUPLICATED_PARAGRAPH, [40, 100, 270, 120]),
             row('right', DUPLICATED_PARAGRAPH, [40, 250, 270, 280])]
    pages = pages_for([r for r in items if r['self_ref'] != 'wrong'])[:1]
    return items, pages


def test_misplaced_duplicate_requires_supported_occurrence_and_covered_native_content():
    items, pages = duplicate_case()
    original = deepcopy(items)
    result, audit = recover_items(items, pages)
    assert items == original
    assert [r['self_ref'] for r in result] == ['title', 'top', 'right']
    finding = next(r for r in audit if r['action'] == 'native_misplaced_duplicate')
    assert finding['item_ref'] == 'wrong' and finding['retained_ref'] == 'right'
    assert finding['native_evidence'] and finding['retained_native_evidence']


def test_repeated_native_paragraphs_are_retained_at_both_real_locations():
    items, pages = duplicate_case()
    items = [r for r in items if r['self_ref'] != 'top']
    pages[0]['text_regions'][1]['text'] = DUPLICATED_PARAGRAPH
    result, audit = recover_items(items, pages)
    assert result == items
    assert not any(r['action'] == 'native_misplaced_duplicate' for r in audit)


def test_unsupported_duplicate_cannot_hide_unrepresented_or_sparse_native_content():
    items, pages = duplicate_case()
    items = [r for r in items if r['self_ref'] != 'top']
    for native in [pages[0]['text_regions'][1]['text'], 'Short.']:
        pages[0]['text_regions'][1]['text'] = native
        result, audit = recover_items(items, pages)
        assert any(r['self_ref'] == 'wrong' for r in result)
        assert not any(r['action'] == 'native_misplaced_duplicate' for r in audit)


def test_other_page_content_cannot_prove_coverage_under_a_misplaced_duplicate():
    items, pages = duplicate_case()
    native_top = items[1]['text']
    items[1]['prov'][0]['page_no'] = 2
    pages.append(dict(page=2, page_size=[600, 800], text_regions=[
        dict(text=native_top, bbox=[40, 100, 270, 120])]))
    result, audit = recover_items(items, pages)
    assert any(r['self_ref'] == 'wrong' for r in result)
    assert not any(r['action'] == 'native_misplaced_duplicate' for r in audit)
