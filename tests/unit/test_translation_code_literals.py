"""Printed variable labels remain literal without freezing ordinary prose."""
from copy import deepcopy

import pytest

from packages.ir import block_hash, flatten_inline
from packages.translation.planner import cache_key, plan_units, reassemble
from tests.unit.test_translation import profile, source


def code_source(text='The graph (graph), operators (lib), and parameters (params) can be deployed.',
                code='graph, lib, params = compiler.build(model)\ntarget = "cpu"', *, rich=True):
    result = source()
    title, prose = deepcopy(result['blocks'][:2])
    listing = deepcopy(prose)
    listing.update(id='listing', kind='code', raw_text=code, normalized_text=code,
                   source_inline=[{'type':'protected_ref', 'ref':'listing-code'}],
                   translatable=False, attributes={'code_language':'python'})
    prose.update(raw_text=text, normalized_text=text, source_inline=[{'type':'text', 'text':text}])
    result.update(schema_version='4.0' if rich else '3.0', blocks=[title,listing,prose],
                  reading_order=[title['id'],listing['id'],prose['id']],
                  protected_atoms={'listing-code':{'kind':'code', 'value':code}})
    for index, block in enumerate(result['blocks']):
        block['order'] = index
        block['source_hash'] = block_hash(block, result['protected_atoms'])
    return result


def planned(src):
    return plan_units(src, 'zh-Hans', profile() | {'max_unit_characters':2000}, ['p1'])


@pytest.mark.parametrize('rich', [False, True])
def test_adjacent_declared_code_names_preserve_complete_parentheses_without_source_mutation(rich):
    src = code_source(rich=rich)
    original = deepcopy(src)
    units = planned(src)
    assert src == original
    assert len(units) == 1
    unit = units[0]
    assert {atom['value'] for atom in unit['protected_atoms'].values()} == {'(graph)','(lib)','(params)'}
    refs = {atom['value']:ref for ref,atom in unit['protected_atoms'].items()}
    target = [{'type':'text','text':'计算图'}, {'type':'protected_ref','ref':refs['(graph)']},
              {'type':'text','text':'、算子'}, {'type':'protected_ref','ref':refs['(lib)']},
              {'type':'text','text':'及参数'}, {'type':'protected_ref','ref':refs['(params)']}]
    restored = reassemble(units, {unit['unit_id']:target})['p1']
    assert flatten_inline(restored, src['protected_atoms']) == '计算图(graph)、算子(lib)及参数(params)'


def test_parenthesized_code_label_keeps_fullwidth_delimiters_and_printed_spaces():
    unit = planned(code_source('The graph（graph）uses parameters ( params ).'))[0]
    assert {atom['value'] for atom in unit['protected_atoms'].values()} == {'（graph）','( params )'}


@pytest.mark.parametrize('change', ['different_page','intervening_prose','unknown_language','invalid_code','image'])
def test_unrelated_or_unverified_code_does_not_freeze_prose(change):
    src = code_source()
    listing = src['blocks'][1]
    if change == 'different_page':
        listing['provenance'][0]['page'] = 2
    elif change == 'intervening_prose':
        intervening = deepcopy(src['blocks'][2])
        intervening.update(id='intervening', normalized_text='An unrelated paragraph.',
                           raw_text='An unrelated paragraph.',source_inline=[{'type':'text','text':'An unrelated paragraph.'}])
        src['blocks'].insert(2,intervening)
        src['reading_order'].insert(2,'intervening')
    elif change == 'unknown_language':
        listing['attributes']['code_language'] = 'unknown'
    elif change == 'invalid_code':
        listing['normalized_text'] = 'graph, lib, params ='
    else:
        listing['kind'] = 'figure'
    assert all(not unit['protected_atoms'] for unit in planned(src))


def test_natural_language_bare_names_comments_strings_and_read_only_identifiers_remain_prose():
    text = 'The graph (for example) may return output (output), results (results), or warnings (warnings).'
    code = '# results are returned\ngraph = "warnings"\nprint(output)'
    units = planned(code_source(text, code))
    assert all(not unit['protected_atoms'] for unit in units)
    assert ''.join(node.get('text','') for unit in units for node in unit['source_inline']) == text


def test_following_code_can_establish_the_local_identifier():
    src = code_source('The graph (graph) is constructed below.')
    src['blocks'][1], src['blocks'][2] = src['blocks'][2], src['blocks'][1]
    src['reading_order'][1], src['reading_order'][2] = src['reading_order'][2], src['reading_order'][1]
    assert list(planned(src)[0]['protected_atoms'].values()) == [{'kind':'variable','value':'(graph)'}]


def test_partial_source_does_not_invent_adjacency_across_missing_blocks():
    src = code_source()
    src['reading_order'].insert(2, 'missing-block')
    assert all(not unit['protected_atoms'] for unit in planned(src))
    src.pop('reading_order')
    assert all(not unit['protected_atoms'] for unit in planned(src))


def test_label_protection_preserves_rich_formatting_and_invalidates_previous_cache():
    src = code_source('Graph(graph) and explanation (in theory).')
    src['blocks'][2]['source_inline'][0]['marks'] = ['emphasis']
    unit = planned(src)[0]
    assert list(unit['protected_atoms'].values()) == [{'kind':'variable','value':'(graph)'}]
    restored = reassemble([unit], {unit['unit_id']:unit['source_inline']})['p1']
    assert all(node['marks'] == ['emphasis'] for node in restored)
    assert flatten_inline(restored, src['protected_atoms']) == src['blocks'][2]['normalized_text']
    prior = deepcopy(unit)
    prior['planner_version'] = 'semantic-abbreviation-units-v8'
    assert cache_key(unit, profile(), 'empty-v1') != cache_key(prior, profile(), 'empty-v1')


def test_local_provider_restores_parenthesized_labels_from_protected_markers():
    from packages.providers.local_translation import source_text, target_inline
    unit = planned(code_source())[0]
    _, markers = source_text(unit)
    translated = target_inline('计算图和算子以及参数：' + '、'.join(markers), unit)
    restored = reassemble([unit], {unit['unit_id']:translated})['p1']
    assert set(value['value'] for value in unit['protected_atoms'].values()) == {'(graph)','(lib)','(params)'}
    assert all(label in flatten_inline(restored, {}) for label in ['(graph)','(lib)','(params)'])
