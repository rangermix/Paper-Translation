"""Known byline names remain literal inside otherwise translated prose."""
from copy import deepcopy

from packages.ir import flatten_inline
from packages.translation.planner import plan_units, restore_inline, cache_encode, cache_decode
from tests.unit.test_original_only import paper
from tests.unit.test_translation import profile


def sample(text):
    return paper([
        ('authors', 'paragraph', r'Alice Smith $^{*}$ Bob Jones $^{\dagger}$'),
        ('orgs', 'paragraph', 'Microsoft Research † Example University'),
        ('intro', 'heading', 'Introduction'),
        ('note', 'footnote', text),
    ])


def test_known_names_are_protected_inside_prose_and_restore_without_source_changes():
    text = 'Alice Smith started an internship at Microsoft Research. Microsoft Research funded it.'
    src = sample(text)
    before = deepcopy(src)
    units = plan_units(src, 'zh-Hans', profile() | {'max_unit_characters': 500}, ['note'])
    assert len(units) == 1
    unit = units[0]
    literals = [unit['protected_atoms'][n['ref']]['value'] for n in unit['source_inline'] if n['type'] == 'protected_ref']
    assert literals == ['Alice Smith', 'Microsoft Research', 'Microsoft Research']
    refs = [n for n in unit['source_inline'] if n['type'] == 'protected_ref']
    target = [refs[0], {'type': 'text', 'text': '在'}, refs[1], {'type': 'text', 'text': '实习。'}, refs[2], {'type': 'text', 'text': '提供资助。'}]
    restored = restore_inline(unit, cache_decode(unit, cache_encode(unit, target)))
    assert flatten_inline(restored, src['protected_atoms']) == 'Alice Smith在Microsoft Research实习。Microsoft Research提供资助。'
    assert src == before


def test_name_protection_requires_full_phrase_and_word_boundaries():
    text = 'Alice Smithson joined Other University. Smith and a Microsoft Researcher agree.'
    src = sample(text)
    units = plan_units(src, 'zh-Hans', profile() | {'max_unit_characters': 500}, ['note'])
    assert not units[0]['protected_atoms']
    assert flatten_inline(units[0]['source_inline'], {}) == text
