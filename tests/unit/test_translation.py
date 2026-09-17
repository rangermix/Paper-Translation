import copy
import json
from pathlib import Path
import pytest

from packages.translation.planner import plan_units, reassemble, cache_key
from packages.providers.contract import validate_output, validate_review, ProviderFailure
from packages.billing.price import reserve_cost, actual_cost, validate_profile

ROOT=Path(__file__).resolve().parents[2]


def profile():
    return {'configured':True,'provider':'openai','model_id':'fixture-model-2026-01-01','profile_revision':'test-v1','prompt_version':'translate-v1','privacy_revision':'test-v1','enabled_pairs':[['en','zh-Hans']],'max_input_tokens':16384,'max_output_tokens':4096,'max_unit_characters':80,'price':{'revision':'test','currency':'USD','input_micro_per_million':1000000,'cached_input_micro_per_million':500000,'output_micro_per_million':2000000,'output_includes_reasoning':True,'input_bound_rule':'utf8-byte-ceiling-v1'}}


def source():return json.loads((ROOT/'tests/fixtures/sample-document.json').read_text('utf-8'))['source_revision']


def test_planner_never_splits_protected_atom():
    src=source();units=plan_units(src,'zh-Hans',profile())
    assert len(units)>0
    for unit in units:
        refs=[n['ref'] for n in unit['source_inline'] if n['type']=='protected_ref']
        assert set(refs)==set(unit['protected_atoms'])


def test_oversized_protected_atom_rejected():
    src=source();src['protected_atoms']['n64']['value']='x'*100
    with pytest.raises(ValueError,match='UNIT_TOO_LARGE'):plan_units(src,'zh-Hans',profile())


def test_response_order_and_bijection():
    units=plan_units(source(),'zh-Hans',profile())[:2]
    output={'results':[{'unit_id':u['unit_id'],'target_inline':u['source_inline']} for u in reversed(units)]}
    assert set(validate_output(output,units))=={u['unit_id'] for u in units}
    output['results'].append(output['results'][0])
    with pytest.raises(ProviderFailure):validate_output(output,units)


def test_provider_cannot_emit_html_or_human_review():
    unit=plan_units(source(),'zh-Hans',profile())[0]
    for extra in [{'human_reviewed':True},{'source':'rewrite'}]:
        output={'results':[{'unit_id':unit['unit_id'],'target_inline':[{'type':'text','text':'ok'}]}|extra]}
        with pytest.raises(ProviderFailure):validate_output(output,[unit])


def test_duplicate_protected_atom_rejected():
    unit=next(u for u in plan_units(source(),'zh-Hans',profile()) if u['protected_atoms'])
    nodes=unit['source_inline']+[{'type':'protected_ref','ref':next(iter(unit['protected_atoms']))}]
    with pytest.raises(ProviderFailure):validate_output({'results':[{'unit_id':unit['unit_id'],'target_inline':nodes}]},[unit])


def test_cache_context_and_profile_sensitive():
    p=profile();u=plan_units(source(),'zh-Hans',p)[0]
    a=cache_key(u,p,'empty-v1');v=copy.deepcopy(u);v['context_hash']='f'*64
    assert a!=cache_key(v,p,'empty-v1')
    q=p|{'model_id':'another-model'}
    assert a!=cache_key(u,q,'empty-v1')


def test_ceil_integer_budget_and_reasoning_not_double_counted():
    p=profile();assert reserve_cost(p)==16384+4096*2
    assert actual_cost(p['price'],{'input_tokens':100,'output_tokens':50,'input_tokens_details':{'cached_tokens':20},'output_tokens_details':{'reasoning_tokens':30}})==190


def test_missing_price_fails_but_unknown_source_language_can_translate():
    p=profile();p['price'].pop('output_includes_reasoning')
    with pytest.raises(ValueError):validate_profile(p)
    assert plan_units(source()|{'language':'und'},'zh-Hans',profile())


def test_review_only_allows_located_exact_quote_issues():
    unit=plan_units(source(),'zh-Hans',profile())[0]|{'review_target_text':'出版契约样例'}
    issue={'unit_id':unit['unit_id'],'rule':'terminology','severity':'warning','source_quote':'Publication','target_quote':'出版','explanation':'Verify this term in context'}
    assert validate_review({'issues':[issue]},[unit])==[issue]
    with pytest.raises(ProviderFailure):validate_review({'issues':[issue|{'accuracy':100}]},[unit])
    with pytest.raises(ProviderFailure):validate_review({'issues':[issue|{'source_quote':'invented'}]},[unit])
