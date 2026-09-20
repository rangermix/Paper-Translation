"""Local citation transport keeps actual reference groups visible to the model."""
from copy import deepcopy

import pytest

from packages.ir import flatten_inline
from packages.providers.connection import TEST_UNIT
from packages.providers.local_translation import request_body, source_text, target_inline
from tests.unit.test_local_translation_provider import profile


def citation_unit(value='[14]'):
    return {**deepcopy(TEST_UNIT),
        'source_inline': [{'type': 'text', 'text': 'Prior work '},
            {'type': 'protected_ref', 'ref': 'cite'}, {'type': 'text', 'text': ' supports this.'}],
        'protected_atoms': {'cite': {'kind': 'citation', 'value': value}}}


def test_unique_short_numeric_citations_are_sent_as_original_literals():
    unit = citation_unit()
    unit['source_inline'] += [{'type': 'text', 'text': ' Also '},
        {'type': 'protected_ref', 'ref': 'other'}]
    unit['protected_atoms']['other'] = {'kind': 'citation', 'value': '[28, 9]'}
    before = deepcopy(unit)
    text, markers = source_text(unit)
    assert text == 'Prior work [14] supports this. Also [28, 9]'
    assert markers == {'[14]': 'cite', '[28, 9]': 'other'}
    prompt = request_body([unit], profile(), [])['messages'][0]['content']
    instructions, source = prompt.split('[Source Text]\n', 1)
    assert 'Copy every numeric citation exactly' in instructions
    assert '{{PT' not in prompt
    assert source == text
    assert unit == before


@pytest.mark.parametrize('rendered', ['[16,17,21,22,44]', '［16，17，21，22，44］',
    '【16、17、21、22、44】', '[ 16,\n17, 21, 22, 44 ]'])
def test_known_numeric_group_restores_exact_original_format(rendered):
    original = '[16, 17, 21, 22, 44]'
    unit = citation_unit(original)
    before = deepcopy(unit)
    nodes = target_inline('参见' + rendered + '。', unit)
    assert nodes == [{'type': 'text', 'text': '参见'},
        {'type': 'protected_ref', 'ref': 'cite'}, {'type': 'text', 'text': '。'}]
    assert flatten_inline(nodes, unit['protected_atoms']) == '参见' + original + '。'
    assert unit == before


def test_repeated_identical_ref_is_literal_each_time_and_restores_each_occurrence():
    unit = citation_unit()
    unit['source_inline'] += [{'type': 'text', 'text': ' and '}, {'type': 'protected_ref', 'ref': 'cite'}]
    text, markers = source_text(unit)
    assert text.count('[14]') == 2 and markers == {'[14]': 'cite'}
    nodes = target_inline('来源[14]，再次引用［14］。', unit)
    assert [node['ref'] for node in nodes if node['type'] == 'protected_ref'] == ['cite', 'cite']


@pytest.mark.parametrize('rendered', ['[1–3； 7]', '［1—3;7］', '【1−3; 7】'])
def test_range_dash_style_can_change_without_changing_range_meaning(rendered):
    unit = citation_unit('[1-3; 7]')
    assert target_inline(rendered, unit) == [{'type': 'protected_ref', 'ref': 'cite'}]
    assert flatten_inline(target_inline(rendered, unit), unit['protected_atoms']) == '[1-3; 7]'


@pytest.mark.parametrize('rendered', ['[1, 3; 7]', '[3-1; 7]', '[1-4; 7]', '[1-3, 7]',
    '[1-3; 8]', '[01-3; 7]', '(1-3; 7)', '[1-3; 7］', '1-3; 7'])
def test_changed_numbers_separator_meaning_and_ambiguous_brackets_remain_visible(rendered):
    unit = citation_unit('[1-3; 7]')
    assert target_inline(rendered, unit) == [{'type': 'text', 'text': rendered}]


def test_unknown_groups_stay_text_and_omitted_citations_are_not_appended():
    unit = citation_unit()
    assert target_inline('没有引文。', unit) == [{'type': 'text', 'text': '没有引文。'}]
    assert target_inline('未知[99]和已知[14]。', unit) == [
        {'type': 'text', 'text': '未知[99]和已知'},
        {'type': 'protected_ref', 'ref': 'cite'}, {'type': 'text', 'text': '。'}]


@pytest.mark.parametrize('literal', ['Literal [14]. ', 'Literal ［14］. ', 'Literal 【14】. '])
def test_literal_text_collision_keeps_citation_opaque(literal):
    unit = citation_unit()
    unit['source_inline'].insert(0, {'type': 'text', 'text': literal})
    text, markers = source_text(unit)
    assert '[14]' not in markers
    marker = next(iter(markers))
    assert marker.startswith('{{PT') and marker in text
    assert target_inline(literal + marker, unit) == [
        {'type': 'text', 'text': literal}, {'type': 'protected_ref', 'ref': 'cite'}]


@pytest.mark.parametrize('other_kind,other_value', [
    ('citation', '[14]'), ('citation', '［ 14 ］'), ('math', '$[14]$'),
])
def test_different_refs_with_the_same_literal_identity_remain_opaque(other_kind, other_value):
    unit = citation_unit()
    unit['source_inline'] += [{'type': 'text', 'text': ' and '}, {'type': 'protected_ref', 'ref': 'other'}]
    unit['protected_atoms']['other'] = {'kind': other_kind, 'value': other_value}
    text, markers = source_text(unit)
    assert len(markers) == 2 and all(marker.startswith('{{PT') for marker in markers)
    assert [n['ref'] for n in target_inline(text, unit) if n['type'] == 'protected_ref'] == ['cite', 'other']


@pytest.mark.parametrize('value', ['(Smith, 2020)', '[' + ', '.join(str(i) for i in range(25)) + ']'])
def test_non_numeric_and_long_citations_keep_opaque_placeholders(value):
    unit = citation_unit(value)
    _, markers = source_text(unit)
    assert list(markers.values()) == ['cite']
    assert next(iter(markers)).startswith('{{PT')


def test_mixed_literal_citations_and_opaque_atoms_keep_collision_free_markers():
    unit = citation_unit()
    unit['source_inline'].insert(0, {'type': 'text', 'text': 'Literal {{PT1}}; '})
    unit['source_inline'].append({'type': 'protected_ref', 'ref': 'math'})
    unit['protected_atoms']['math'] = {'kind': 'math', 'value': '$x^2$'}
    text, markers = source_text(unit)
    assert markers['[14]'] == 'cite'
    opaque = next(marker for marker in markers if marker.startswith('{{PT'))
    assert opaque != '{{PT1}}'
    nodes = target_inline('引用【14】和' + opaque[:-1] + '，原样 {{PT1}}', unit)
    assert [n['ref'] for n in nodes if n['type'] == 'protected_ref'] == ['cite', 'math']
    assert '{{PT1}}' in ''.join(n.get('text', '') for n in nodes)


def test_milmmt_also_receives_literal_numeric_citations():
    unit = citation_unit()
    prompt = request_body([unit], profile('milmmt-46-4b-q4'), [])['prompt']
    assert 'English: Prior work [14] supports this.' in prompt
    assert 'Copy every numeric citation exactly' in prompt
