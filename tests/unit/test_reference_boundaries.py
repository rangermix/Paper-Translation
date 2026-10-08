"""Printed hanging labels repair merged references without altering source text."""
from copy import deepcopy

import pytest

from packages.parsers.reference_recovery import recover_references
from packages.parsers.semantic import node
from packages.publisher.references import ReferenceIndex


def row(ref, text, bounds, label='text'):
    return {'self_ref': ref, 'label': label, 'orig': text, 'text': text,
            'prov': [{'page_no': 1, 'bbox': dict(zip(('l', 't', 'r', 'b'), bounds), coord_origin='TOPLEFT')}]}


def case():
    entries = ['[1] Alice Example. Original paper, 2020.',
               '[12] Bob Writer. In [1990] Proceedings of Examples, 2021.',
               '[21] Carol Author. Another result, 2022.']
    text = ' '.join(entries)
    item = row('merged', text, [70, 100, 290, 180])
    item['_semantic'] = node('paragraph', [
        {'type': 'text', 'text': entries[0] + ' ', 'marks': ['strong'], 'path': '/0'},
        {'type': 'text', 'text': entries[1] + ' ', 'marks': ['emphasis'], 'path': '/1'},
        {'type': 'text', 'text': entries[2], 'path': '/2'},
    ], path='/refs')
    page = {'page': 1, 'page_size': [612, 792], 'text_regions': [
        {'text': entry, 'bbox': [72 if index == 0 else 70, 100 + index * 30, 290, 110 + index * 30]}
        for index, entry in enumerate(entries)]}
    return [row('heading', 'References', [70, 80, 200, 90], 'title'), item], [page], entries


def test_native_markers_split_entries_preserving_source_marks_and_precise_bounds():
    items, pages, entries = case()
    before = deepcopy(items)
    fixed, audit = recover_references(items, pages)
    refs = fixed[1:]
    assert [r['orig'] for r in refs] == entries
    assert [r['_semantic']['text'] for r in refs] == entries
    assert [r['_semantic']['kind'] for r in refs] == ['reference'] * 3
    assert refs[0]['_semantic']['runs'][0]['marks'] == ['strong']
    assert refs[1]['_semantic']['runs'][0]['marks'] == ['emphasis']
    assert [r['prov'][0]['bbox']['t'] for r in refs] == [100, 130, 160]
    assert [r['prov'][0]['charspan'] for r in refs] == [[0, len(entry)] for entry in entries]
    assert items == before
    assert audit[0]['action'] == 'native_reference_boundaries'
    assert audit[0]['native_evidence']


def test_recovered_references_enable_grouped_citations_and_ranges_without_partial_links():
    items, pages, _ = case()
    fixed, _ = recover_references(items, pages)
    blocks = [{'id': row['self_ref'], 'normalized_text': row['orig']} for row in fixed[1:]]
    index = ReferenceIndex(blocks, {block['id']: 'original_reference' for block in blocks})
    assert index.resolve('[1, 12, 21]') == [block['id'] for block in blocks]
    assert list(index.matches('支持 [1, 12, 21]。')) == [(3, 14, [block['id'] for block in blocks])]
    assert index.resolve('[1, 12, 99]') == []
    assert index.resolve('[1990]') == []


@pytest.mark.parametrize('template', ['reader-v11', 'reader-v12'])
def test_recovered_references_publish_complete_grouped_links_in_both_languages(template):
    from packages.publisher.renderer import render_html
    from test_reader_sidenotes import add_reference, refresh, set_inline, sidenote_fixture
    from test_reader_v5 import ReaderMarkup
    items, pages, _ = case()
    recovered, _ = recover_references(items, pages)
    ir = sidenote_fixture(template)
    set_inline(ir, 'ref1', [{'type': 'text', 'text': recovered[1]['orig']}])
    add_reference(ir, 'ref12', recovered[2]['orig'])
    add_reference(ir, 'ref21', recovered[3]['orig'])
    set_inline(ir, 'p2', [{'type': 'text', 'text': 'Supporting work [1, 12, 21].'}])
    refresh(ir)
    before = deepcopy(ir)
    tree = ReaderMarkup(render_html(ir, {'figure_png': 'figure.png'}).decode())
    for language in ['source', 'target']:
        content = tree.by_id('p2').find(f'.//*[@data-language="{language}"]')
        link = content.find('.//a[@data-reference-targets]')
        assert ''.join(link.itertext()) == '[1, 12, 21]'
        assert link.get('data-reference-targets') == 'ref1 ref12 ref21'
        assert all(tree.by_id(bid).get('data-original-only') == 'original_reference'
                   for bid in link.get('data-reference-targets').split())
    assert ir == before


def test_number_in_a_reference_title_is_not_an_entry_boundary():
    items, pages, entries = case()
    # An independent font run beginning with a year remains indented body text.
    pages[0]['text_regions'][1:2] = [
        {'text': '[12] Bob Writer. In', 'bbox': [70, 130, 150, 140]},
        {'text': '[1990] Proceedings of Examples, 2021.', 'bbox': [95, 141, 290, 151]},
    ]
    fixed, _ = recover_references(items, pages)
    assert [r['orig'] for r in fixed[1:]] == entries


@pytest.mark.parametrize('fault', ['not_bibliography', 'missing_native', 'missing_marker', 'duplicate_marker', 'wrong_opening', 'two_columns'])
def test_uncertain_boundaries_preserve_the_original(fault):
    items, pages, _ = case()
    if fault == 'not_bibliography':
        items[0]['orig'] = 'Related Work'
    elif fault == 'missing_native':
        pages[0]['text_regions'] = []
    elif fault == 'missing_marker':
        items[1]['orig'] = items[1]['orig'].replace('[12]', '[13]')
    elif fault == 'duplicate_marker':
        items[1]['orig'] += ' See also [12] Bob Writer.'
    elif fault == 'wrong_opening':
        pages[0]['text_regions'][1]['text'] = '[12] Different author and paper, 2021.'
    else:
        items[1]['prov'][0]['bbox']['r'] = 550
        pages[0]['text_regions'][-1]['bbox'] = [320, 100, 550, 110]
    before = deepcopy(items)
    fixed, audit = recover_references(items, pages)
    assert fixed == before and not audit


def test_column_head_reference_continuation_keeps_its_native_text_and_bounds():
    items, pages, _ = case()
    prefix = 'and Pattern Recognition, 2016, pp. 4013–4021.'
    items[1]['orig'] = prefix + '\n' + items[1]['orig']
    items[1]['_semantic'] = node('paragraph', [{'type': 'text', 'text': items[1]['orig'], 'path': '/refs'}], path='/refs')
    items[1]['prov'][0]['bbox']['t'] = 80
    pages[0]['text_regions'].insert(0, {'text': prefix, 'bbox': [85, 80, 290, 90]})
    fixed, _ = recover_references(items, pages)
    assert fixed[1]['orig'] == prefix
    assert fixed[1]['label'] == 'reference'
    assert fixed[1]['prov'][0]['bbox']['t'] == 80
    assert fixed[2]['orig'].startswith('[1]')


def test_small_cap_author_runs_share_one_native_baseline():
    items, pages, entries = case()
    pages[0]['text_regions'][:1] = [
        {'text': '[1]', 'bbox': [72, 100, 81, 107]},
        {'text': 'A', 'bbox': [87, 100, 93, 106]},
        {'text': 'lice', 'bbox': [94, 101, 109, 106]},
        {'text': 'Example. Original paper, 2020.', 'bbox': [110, 100, 290, 107]},
    ]
    fixed, _ = recover_references(items, pages)
    assert [r['orig'] for r in fixed[1:]] == entries


def test_existing_semantic_groups_get_entry_bounds_without_losing_marks():
    items, pages, entries = case()
    children = [node('paragraph', [{'type': 'text', 'text': entry, 'marks': ['emphasis'], 'path': f'/{index}'}], path=f'/{index}')
                for index, entry in enumerate(entries)]
    items[1]['_semantic'] = node('group', children=children, attrs={'group_type': 'layout'}, path='/refs')
    items[1]['orig'] = items[1]['_semantic']['text']
    fixed, _ = recover_references(items, pages)
    assert [r['_semantic']['kind'] for r in fixed[1:]] == ['reference'] * 3
    assert all(r['_semantic']['runs'][0]['marks'] == ['emphasis'] for r in fixed[1:])


def test_small_author_ocr_difference_does_not_rewrite_source_or_hide_other_entries():
    items, pages, entries = case()
    items[1]['orig'] = items[1]['orig'].replace('Alice Example', 'Allice Example')
    fixed, _ = recover_references(items, pages)
    assert [r['orig'] for r in fixed[1:]] == [entries[0].replace('Alice', 'Allice'), *entries[1:]]
