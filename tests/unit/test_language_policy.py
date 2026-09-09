import copy

import pytest

from packages.translation.languages import canonical_locale, check_language_policy, public_profile, translation_profile
from packages.translation.planner import plan_units
from tests.unit.test_translation import profile, source


@pytest.mark.parametrize('value,expected', [('ZH-hans', 'zh-Hans'), ('zh-HANT', 'zh-Hant'),
    ('JA', 'ja'), ('ar', 'ar'), ('fr', 'fr'), ('EN-us', 'en-US'), ('pt-br', 'pt-BR'),
    ('sr-latn-rs', 'sr-Latn-RS'), ('fil', 'fil'), ('yue', 'yue'), ('zh', 'zh')])
def test_language_tags_preserve_scripts_regions_and_allow_all_languages(value, expected):
    assert canonical_locale(value) == expected


@pytest.mark.parametrize('value', ['und', 'auto', '', 'zh_Hans', '../en', 'en/US', 'en--US', 'en<script>', None])
def test_unknown_source_and_unsafe_language_tags_are_rejected(value):
    with pytest.raises(ValueError):
        canonical_locale(value)


@pytest.mark.parametrize('target', ['ja', 'zh-Hant', 'ar', 'fr', 'pt-BR', 'fil', 'yue'])
def test_all_pairs_plan_without_opt_in_or_mutating_frozen_provider(target):
    original, base = source(), profile()
    before = copy.deepcopy(base)
    mixed = copy.deepcopy(original)
    mixed['blocks'][1]['language'] = 'ko'
    selected = translation_profile(base, mixed, target)
    assert selected == base == before
    assert public_profile(selected) == base
    check_language_policy(selected, mixed, target)
    assert plan_units(mixed, target, selected)


def test_legacy_language_flags_do_not_gate_jobs_or_propagate_to_new_profiles():
    original, base = source(), profile()
    legacy = base | {'language_authorization': {'mode': 'experimental', 'confirmed': True}}
    check_language_policy(legacy, original, 'ar')
    assert translation_profile(legacy, original, 'fr') == base
    original['blocks'][1]['language'] = 'und'
    check_language_policy(base, original, 'fr')
