from copy import deepcopy
import pytest

from packages.ir import block_hash, flatten_inline
from packages.ir.retention import original_only_blocks
from packages.parsers.pdf_docling import _source_nodes
from packages.translation.planner import plan_units, restore_inline
from tests.unit.test_translation import source, profile


def parsed(text, kind='paragraph'):
    src=source();block=src['blocks'][1]
    block.update(kind=kind, raw_text=text, normalized_text=text)
    block['source_inline']=_source_nodes(text,block['id'],src['protected_atoms'],kind)
    block['source_hash']=block_hash(block,src['protected_atoms'])
    return src,block


def test_author_year_groups_and_math_are_indivisible_source_atoms():
    citation='(Mikolov et al., 2013; Pennington et al., 2014; Radford et al., 2017; 2019)'
    formula=r'$Y=\mathrm{GeLU}(X_1A_1+X_2A_2)$'
    text=f'Prior work {citation} derives {formula}.'
    src,block=parsed(text)
    atoms=[src['protected_atoms'][n['ref']] for n in block['source_inline'] if n['type']=='protected_ref']
    assert {'kind':'citation','value':citation} in atoms
    assert {'kind':'math','value':formula} in atoms
    assert flatten_inline(block['source_inline'],src['protected_atoms'])==text


def test_narrative_citation_is_preserved_but_ordinary_parentheses_are_prose():
    src,block=parsed('Smith & Jones (2021) compare sizes (studied up to 8.3 billion parameters).')
    atoms=[src['protected_atoms'][n['ref']] for n in block['source_inline'] if n['type']=='protected_ref']
    assert {'kind':'citation','value':'Smith & Jones (2021)'} in atoms
    assert not any(a['kind']=='citation' and 'studied' in a['value'] for a in atoms)


@pytest.mark.parametrize('citation', ['[16, 17, 21, 22, 44]', '[10, 25, 7]', '[36]', '[1–3, 7]', '[2-4; 9]'])
def test_numeric_citations_keep_the_entire_original_bracket_and_separator_format(citation):
    from packages.providers.local_translation import source_text, target_inline
    src, block = parsed(f'Prior work {citation} supports the result.')
    unit = plan_units(src, 'zh-Hans', profile(), [block['id']])[0]
    atoms = list(unit['protected_atoms'].values())
    assert atoms == [{'kind': 'citation', 'value': citation}]
    _, markers = source_text(unit)
    translated = target_inline('此前的研究' + next(iter(markers)) + '支持这一结果。', unit)
    assert flatten_inline(restore_inline(unit, translated), src['protected_atoms']) == f'此前的研究{citation}支持这一结果。'
    assert flatten_inline(block['source_inline'], src['protected_atoms']) == block['normalized_text']


def test_bracketed_prose_is_not_mistaken_for_a_numeric_citation():
    src, block = parsed('Keep [see 16 and 17] readable and translate [a short note].')
    assert not any(src['protected_atoms'][n['ref']]['kind'] == 'citation'
                   for n in block['source_inline'] if n['type'] == 'protected_ref')


@pytest.mark.parametrize('original,target', [('8.3 billion','83亿'),('3.9B','39亿'),('355M','3.55亿'),('1.2 billion','12亿')])
def test_chinese_quantities_restore_exact_values_without_mutating_source(original,target):
    src,block=parsed(f'A model with {original} parameters.')
    before=deepcopy(src)
    unit=plan_units(src,'zh-Hans',profile(),[block['id']])[0]
    translated=restore_inline(unit,unit['source_inline'])
    assert target in flatten_inline(translated,src['protected_atoms'])
    assert 'parameters' in flatten_inline(translated,src['protected_atoms'])
    assert src==before


def test_abbreviations_require_quantity_context_and_do_not_match_identifiers_or_bytes():
    src,block=parsed('V100 32GB, 8.3B/s, version 3.9B and Model-355M are identifiers.')
    unit=plan_units(src,'zh-Hans',profile(),[block['id']])[0]
    assert flatten_inline(restore_inline(unit,unit['source_inline']),src['protected_atoms'])==block['normalized_text']


@pytest.mark.parametrize('text',['1536','1.2','-0.35','66.5%','1,024','1.5e-4','1 ± 0.2'])
def test_numeric_cells_are_retained_and_not_sent_to_translation(text):
    src,block=parsed(text,'table_cell')
    assert original_only_blocks(src).get(block['id'])=='original_numeric_cell'
    assert plan_units(src,'zh-Hans',profile(),[block['id']])==[]


@pytest.mark.parametrize('text',['Hidden size','8 GPUs','Number of parameters (billions)','not 3'])
def test_numeric_cell_retention_never_swallows_translatable_words(text):
    src,block=parsed(text,'table_cell')
    assert block['id'] not in original_only_blocks(src)


def test_quantity_equivalence_does_not_hide_missing_citations_or_repeated_values():
    from packages.ir.quantities import protected_counts
    atoms={'a':{'kind':'number','value':'8.3 billion'},'b':{'kind':'number','value':'8.3 billion'},
           'c':{'kind':'citation','value':'(Smith, 2020)'},'m':{'kind':'math','value':'$x$'}}
    src=[{'type':'protected_ref','ref':'a'},{'type':'text','text':' and '},*({'type':'protected_ref','ref':k} for k in ['b','c','m'])]
    good=[{'type':'text','text':'83亿和83亿'},*src[3:]]
    assert protected_counts(src,good,atoms,'zh-Hans') == ({'c':1,'m':1},{'c':1,'m':1})
    for bad in ([{'type':'text','text':'83亿'},*src[3:]], [{'type':'text','text':'8.3亿和83亿'},*src[3:]],
                [{'type':'text','text':'183亿和83亿'},*src[3:]], [{'type':'text','text':'83亿和83亿'},src[4]]):
        left,right=protected_counts(src,bad,atoms,'zh-Hans')
        assert left!=right


def test_traditional_locale_and_decimal_conversion_are_exact():
    from packages.ir.quantities import localize_quantity
    assert localize_quantity('8.3 billion','zh-Hant-TW')=='83億'
    assert localize_quantity('-1.23456789 million','zh-Hans')=='-123.456789万'
    assert localize_quantity('8.3 billion','ja') is None


def test_currency_and_unbalanced_math_remain_literal():
    for text in [r'Pay \$30 or \$40.', 'Pay $30 and $40.', 'An unclosed $x+1 formula.']:
        src,block=parsed(text)
        assert not any(src['protected_atoms'][n['ref']]['kind']=='math' for n in block['source_inline'] if n['type']=='protected_ref')
        assert flatten_inline(block['source_inline'],src['protected_atoms'])==text


@pytest.mark.parametrize('target',['−83亿','83亿%','83亿‰','83亿 ‰','83亿'])
def test_numeric_localization_preserves_sign_units_and_residual_occurrences(target):
    from packages.ir.quantities import protected_counts
    atoms={'n':{'kind':'number','value':'8.3 billion'}}
    src=([{'type':'text','text':'83亿 plus '}] if target=='83亿' else [])+[{'type':'protected_ref','ref':'n'}]
    left,right=protected_counts(src,[{'type':'text','text':target}],atoms,'zh-Hans')
    assert left!=right


@pytest.mark.parametrize('text',['Pay $30 + tax, then $40 for handling.','Pay $30 and $40.','$x$$'])
def test_rejected_math_does_not_swallow_currency_numbers(text):
    src,block=parsed(text)
    atoms=[src['protected_atoms'][n['ref']] for n in block['source_inline'] if n['type']=='protected_ref']
    assert not any(a['kind']=='math' for a in atoms)
    if '30' in text: assert [a['value'] for a in atoms]==['30','40']
