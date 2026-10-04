import copy
import json

import pytest

from packages.ir import block_hash, flatten_inline
from packages.translation.planner import cache_key, plan_units, reassemble
from test_preparation import paper
from test_translation import profile


def abbreviation_source(*, rich=False):
    source = paper()
    source['schema_version'] = '4.0' if rich else '3.0'
    for block_id, text in [('abbr', 'Large language models (LLMs) generate text.'),
                           ('use1', 'An LLM can train LLMs. LLMs differ from LLMsize and llms.')]:
        block = next(b for b in source['blocks'] if b['id'] == block_id)
        block.update(normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
        block['source_hash'] = block_hash(block, {})
    return source


@pytest.mark.parametrize('rich', [False, True])
def test_source_defined_abbreviations_restore_exact_spelling_without_expansion(rich):
    source = abbreviation_source(rich=rich)
    original = copy.deepcopy(source)
    units = plan_units(source, 'zh-Hans', profile(), ['abbr', 'use1'])
    assert source == original
    literals = [atom['value'] for unit in units for atom in unit['protected_atoms'].values()]
    assert sorted(literals) == ['LLM', 'LLMs', 'LLMs', 'LLMs']
    definition = next(unit for unit in units if unit['owner_block_id'] == 'abbr')
    assert 'Large language models' in ''.join(node.get('text', '') for node in definition['source_inline'])
    results = {unit['unit_id']: unit['source_inline'] for unit in units}
    # Simulate translating the prose only; restoration keeps each occurrence
    # and never substitutes a glossary's full expression for the abbreviation.
    results[definition['unit_id']] = [dict(node, text=node['text'].replace('Large language models', '大型语言模型'))
        if node['type'] == 'text' else node for node in definition['source_inline']]
    restored = reassemble(units, results)
    assert flatten_inline(restored['abbr'], {}) == '大型语言模型 (LLMs) generate text.'
    assert flatten_inline(restored['use1'], {}) == original['blocks'][5]['normalized_text']


def test_unknown_parentheses_and_uppercase_words_do_not_become_protected_metadata():
    from packages.translation.abbreviations import source_literals
    assert source_literals([{'normalized_text': 'Translate this title (ABC). ALL ordinary words.'}]) == []
    assert source_literals([{'normalized_text': 'Large language models (LLMs) are useful.'}]) == ['LLMs', 'LLM']
    assert source_literals([{'normalized_text': 'Large language\nmodels (LLMs) are useful.'}]) == ['LLMs', 'LLM']


@pytest.mark.parametrize('node', [
    {'type': 'text', 'text': 'LLMs', 'marks': ['emphasis'], 'output_path': '/p/em'},
    {'type': 'link', 'text': 'LLMs', 'href': 'https://example.invalid/models'},
    {'type': 'xref', 'label': 'LLMs', 'target_block_id': 'abbr'},
])
def test_rich_abbreviation_retains_formatting_and_link_binding(node):
    source = abbreviation_source(rich=True)
    block = next(b for b in source['blocks'] if b['id'] == 'use1')
    block.update(source_inline=[node], normalized_text='LLMs')
    units = plan_units(source, 'zh-Hans', profile(), ['use1'])
    assert [atom['value'] for atom in units[0]['protected_atoms'].values()] == ['LLMs']
    assert reassemble(units, {u['unit_id']: u['source_inline'] for u in units})['use1'] == [node]


@pytest.mark.parametrize('protocol,provider', [('responses', 'openai'), ('chat_completions', 'openai'),
    ('gemini_interactions', 'gemini'), ('claude_messages', 'anthropic')])
def test_every_api_protocol_instructs_source_faithful_abbreviation_usage(protocol, provider):
    from packages.providers.registry import request_body
    from packages.translation.abbreviations import INSTRUCTIONS
    p = profile() | {'api_protocol': protocol, 'provider': provider}
    unit = plan_units(abbreviation_source(), 'zh-Hans', profile(), ['abbr'])[0]
    assert INSTRUCTIONS in json.dumps(request_body([unit], p, []))


@pytest.mark.parametrize('model', ['hy-mt2-1.8b-q8', 'milmmt-46-4b-q4'])
def test_local_models_preserve_source_abbreviation_nodes_and_rule(model):
    from packages.providers.local_translation import request_body, source_text, target_inline
    from packages.translation.abbreviations import INSTRUCTIONS
    from test_local_translation_provider import profile as local_profile
    p = local_profile(model)
    unit = plan_units(abbreviation_source(), 'zh-Hans', p, ['abbr'])[0]
    body = request_body([unit], p, [])
    assert INSTRUCTIONS in json.dumps(body)
    source, markers = source_text(unit)
    assert len(markers) == 1
    target = target_inline(source.replace('Large language models', '大型语言模型'), unit)
    restored = reassemble([unit], {unit['unit_id']: target})
    assert flatten_inline(restored['abbr'], {}) == '大型语言模型 (LLMs) generate text.'


def test_api_prompt_change_invalidates_cached_expansions(monkeypatch):
    from packages.providers import content
    p = profile()
    unit = plan_units(abbreviation_source(), 'zh-Hans', p, ['abbr'])[0]
    old_key = cache_key(unit, p, 'empty-v1')
    monkeypatch.setattr(content, 'REQUEST_FORMAT_VERSION', 'another-policy')
    assert cache_key(unit, p, 'empty-v1') != old_key
