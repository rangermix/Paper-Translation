"""Title-declared identifiers stay literal inside translated table cells."""
from copy import deepcopy

import pytest

from packages.ir import block_hash, flatten_inline
from packages.translation.planner import cache_decode, cache_encode, plan_units, restore_inline
from tests.unit.test_translation import profile, source


def titled_paper(title='PipeDream: Fast and Efficient Pipeline Parallel DNN Training'):
    src = source()
    for bid, text in [('title', title), ('c1', 'PipeDream\nConfig'), ('c2', 'PipeDream speedup'),
            ('p1', 'PipeDream reduces communication.')]:
        block = next(b for b in src['blocks'] if b['id'] == bid)
        block.update(raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
        block['source_hash'] = block_hash(block, src['protected_atoms'])
    return src


@pytest.mark.parametrize('title,expected', [
    ('PipeDream: Fast training', ('PipeDream',)),
    ('ResNet：Residual learning', ('ResNet',)),
    ('GPT-3: Language models', ('GPT-3',)),
    ('  T5 : Text-to-text models', ('T5',)),
    ('Training: Fast and efficient', ()),
    ('Results: Model evaluation', ()),
    ('Deep Learning: An introduction', ()),
    ('TRAINING: Fast models', ()),
    ('PipeDream without a subtitle delimiter', ()),
    ('PipeDream:', ()),
    ('How to use PipeDream: A guide', ()),
    ('Pipe' + 'D' * 80 + ': A model', ()),
])
def test_only_explicit_title_identifier_prefixes_supply_literals(title, expected):
    from packages.ir.retention import title_identifier_literals
    src = titled_paper(title)
    before = deepcopy(src)
    assert title_identifier_literals(src) == expected
    assert src == before


def test_title_identifier_requires_the_document_title_not_a_nearby_heading():
    from packages.ir.retention import title_identifier_literals
    src = titled_paper()
    src['title_block_id'] = None
    assert title_identifier_literals(src) == ()


def test_table_protection_restores_system_name_while_translating_descriptive_text():
    src = titled_paper()
    before = deepcopy(src)
    unit = plan_units(src, 'zh-Hans', profile(), ['c1'])[0]
    assert len(unit['protected_atoms']) == 1
    ref = next(iter(unit['protected_atoms']))
    assert unit['protected_atoms'][ref] == {'kind': 'variable', 'value': 'PipeDream'}
    assert unit['source_inline'] == [{'type': 'protected_ref', 'ref': ref}, {'type': 'text', 'text': '\nConfig'}]
    target = [{'type': 'protected_ref', 'ref': ref}, {'type': 'text', 'text': '\n配置'}]
    restored = restore_inline(unit, cache_decode(unit, cache_encode(unit, target)))
    assert flatten_inline(restored, src['protected_atoms']) == 'PipeDream\n配置'
    assert src == before


def test_title_identifier_protection_is_limited_to_table_cells():
    src = titled_paper()
    units = plan_units(src, 'zh-Hans', profile() | {'max_unit_characters': 500}, ['title', 'p1', 'c1', 'c2'])
    for unit in units:
        assert bool(unit['protected_atoms']) == (unit['owner_block_id'] in {'c1', 'c2'})
    assert {u['owner_block_id'] for u in units} == {'title', 'p1', 'c1', 'c2'}


def test_table_identifiers_require_exact_spelling_and_word_boundaries():
    src = titled_paper()
    block = next(b for b in src['blocks'] if b['id'] == 'c1')
    text = 'PipeDreamer, pipeDream and PipeDream Config'
    block.update(raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
    block['source_hash'] = block_hash(block, src['protected_atoms'])
    unit = plan_units(src, 'zh-Hans', profile(), ['c1'])[0]
    assert [node.get('text') for node in unit['source_inline'] if node['type'] == 'text'] == [
        'PipeDreamer, pipeDream and ', ' Config']
    assert len(unit['protected_atoms']) == 1


def test_ordinary_title_prefix_does_not_protect_table_prose():
    src = titled_paper('Training: Fast and efficient')
    block = next(b for b in src['blocks'] if b['id'] == 'c1')
    block.update(raw_text='Training Config', normalized_text='Training Config',
        source_inline=[{'type': 'text', 'text': 'Training Config'}])
    block['source_hash'] = block_hash(block, src['protected_atoms'])
    unit = plan_units(src, 'zh-Hans', profile(), ['c1'])[0]
    assert not unit['protected_atoms']
    assert unit['source_inline'] == block['source_inline']
