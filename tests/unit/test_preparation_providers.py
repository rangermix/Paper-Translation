import copy
import json

import pytest

from packages.providers.contract import ProviderFailure
from packages.providers.registry import request_body
from test_translation import profile
from test_preparation import paper


def prepared_request():
    from packages.preparation.analysis import make_request
    from packages.preparation.collection import collect
    return make_request(collect(paper()), 'zh-Hans', profile(), [])


@pytest.mark.parametrize('protocol,provider', [('responses', 'openai'), ('chat_completions', 'openai'),
    ('gemini_interactions', 'gemini'), ('claude_messages', 'anthropic')])
def test_analysis_uses_bound_protocol_and_analysis_schema(protocol, provider):
    unit = prepared_request()
    p = profile() | {'api_protocol': protocol, 'provider': provider}
    body = request_body([unit], p, [])
    encoded = json.dumps(body)
    assert 'technical interpretation' in encoded
    assert 'evidence_ids' in encoded and 'target_inline' not in encoded
    assert body['model'] == p['model_id']


def test_validated_analysis_rejects_invented_evidence_and_preserves_scope():
    from packages.preparation.analysis import validate_analysis
    request = prepared_request()
    concept = next(c for c in request['content']['concepts'] if c['source'] == 'rank')
    term = {'concept_id': concept['id'], 'source': 'rank', 'target': '进程编号',
            'evidence_ids': concept['evidence_ids']}
    value = {'summary': [], 'terms': [term]}
    validated = validate_analysis(value, request)
    assert validated['proposals'][concept['id']] == '进程编号'
    invalid = copy.deepcopy(value)
    invalid['terms'][0]['evidence_ids'] = ['invented']
    with pytest.raises(ProviderFailure, match='PREPARATION_EVIDENCE'):
        validate_analysis(invalid, request)
    invalid = copy.deepcopy(value)
    invalid['terms'][0]['source'] = 'unseen concept'
    with pytest.raises(ProviderFailure):
        validate_analysis(invalid, request)


def test_analysis_can_identify_new_grounded_terms_but_cannot_claim_human_review():
    from packages.preparation.analysis import validate_analysis
    request = prepared_request()
    evidence = next(e for e in request['content']['evidence'] if 'rank' in e['quote'])
    value = {'summary': [], 'terms': [{'concept_id': '', 'source': 'rank', 'target': '编号', 'evidence_ids': [evidence['id']]}]}
    result = validate_analysis(value, request)
    assert result['additional_concepts'][0]['scope'] == evidence['scope']
    value['terms'][0]['human_reviewed'] = True
    with pytest.raises(ProviderFailure, match='PREPARATION_SCHEMA'):
        validate_analysis(value, request)


def test_analysis_preserves_new_source_spelling_and_bounds_raw_summary():
    from packages.preparation.analysis import validate_analysis
    request = prepared_request()
    evidence = next(e for e in request['content']['evidence'] if 'rank' in e['quote'])
    with pytest.raises(ProviderFailure, match='PREPARATION_EVIDENCE'):
        validate_analysis({'summary': [], 'terms': [{'concept_id': '', 'source': 'RANK', 'target': '编号',
                           'evidence_ids': [evidence['id']]}]}, request)
    with pytest.raises(ProviderFailure, match='PREPARATION_SCHEMA'):
        validate_analysis({'summary': [{'text': 'x' + ' ' * 10000, 'evidence_ids': [evidence['id']]}], 'terms': []}, request)


def test_off_mode_preserves_legacy_instructions():
    from packages.providers.openai_responses import INSTRUCTIONS
    from packages.translation.planner import plan_units
    from test_translation import source
    p = profile()
    unit = plan_units(source(), 'zh-Hans', p)[0]
    assert request_body([unit], p, [])['instructions'] == INSTRUCTIONS


def test_preparation_overhead_cannot_break_a_previously_fitting_request():
    from packages.preparation.collection import collect
    from packages.preparation.context import apply_to_units, freeze
    from packages.translation.planner import plan_units
    from packages.ir import canonical_bytes
    from test_translation import source
    src, p = source(), profile()
    unit = plan_units(src, 'zh-Hans', p)[0]
    p['max_input_tokens'] = len(canonical_bytes(request_body([unit], p, []))) + 4096
    pack = freeze(collect(src), 'zh-Hans', 'empty-v1', [])
    prepared = apply_to_units(pack, src, [unit], p)[0]
    request_body([prepared], p, prepared['glossary_entries'])
    assert prepared['preparation_revision'] == pack['revision']
    assert prepared['preparation_context_omitted'] is True


def test_context_changes_cache_identity_and_reports_terms_only_adapter():
    from packages.preparation.collection import collect
    from packages.preparation.context import apply_to_units, freeze
    from packages.translation.planner import cache_key, plan_units
    from test_local_translation_provider import profile as local_profile
    src, p = paper(), local_profile('milmmt-46-4b-q4')
    collection = collect(src)
    packs = [freeze(collection, 'zh-Hans', 'empty-v1', [], summary=summary)
             for summary in ([], [{'text': 'Additional brief', 'evidence_ids': [collection['evidence'][0]['id']]}])]
    units = [apply_to_units(pack, src, plan_units(src, 'zh-Hans', p, ['use1']), p)[0] for pack in packs]
    assert cache_key(units[0], p, 'empty-v1') != cache_key(units[1], p, 'empty-v1')
    assert all(u['preparation_context_mode'] == 'terms_only' for u in units)
