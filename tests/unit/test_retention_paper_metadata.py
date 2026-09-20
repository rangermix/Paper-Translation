"""Retention regressions for parsed academic bylines and table values."""
from copy import deepcopy

import pytest

from packages.ir.retention import original_only_blocks
from packages.translation.planner import plan_units
from tests.unit.test_academic_inline import parsed
from tests.unit.test_original_only import paper, planned_ids
from tests.unit.test_translation import profile


def test_tex_affiliation_markers_identify_consecutive_author_blocks_without_source_edits():
    src = paper([
        ('first_authors', 'paragraph',
            'Aaron Harlap $ ^{\\dagger*} $\nDeepak Narayanan $ ^{\\ddagger*} $'),
        ('more_authors', 'paragraph',
            r'Amar Phanishayee $ ^{*} $ Vivek Seshadri $ ^{*} $ '
            r'Nikhil Devanur $ ^{*} $ Greg Ganger $ ^{\dagger} $ Phil Gibbons $ ^{\dagger} $'),
        ('orgs', 'paragraph',
            '?Microsoft Research † Carnegie Mellon University ‡ Stanford University'),
        ('abstract', 'heading', 'Abstract'),
        ('body', 'paragraph', 'PipeDream reduces communication during training.'),
    ])
    before = deepcopy(src)

    assert original_only_blocks(src) == {
        'first_authors': 'original_author_list',
        'more_authors': 'original_author_list',
        'orgs': 'original_affiliation',
    }
    assert planned_ids(src) == {src['title_block_id'], 'abstract', 'body'}
    assert src == before


def test_tex_markers_on_affiliations_do_not_hide_organisation_evidence():
    src = paper([
        ('authors', 'paragraph', r'Alice Smith $^{1,2}$ Bob Jones $^{2}$'),
        ('orgs', 'paragraph', r'$^{1}$ Example University; $^{2}$ Microsoft Research'),
        ('abstract', 'heading', 'Abstract'),
    ])
    assert original_only_blocks(src) == {
        'authors': 'original_author_list', 'orgs': 'original_affiliation',
    }


@pytest.mark.parametrize('text', [
    r'Neural Networks $x^2$',
    r'Model Confidence $^{p}$',
    'Deep Learning and Natural Language Processing',
])
def test_ordinary_capitalized_text_and_math_are_not_author_evidence(text):
    src = paper([('body', 'paragraph', text)])
    assert 'body' in planned_ids(src)


def test_author_markers_do_not_retain_names_in_body_prose():
    src = paper([
        ('intro', 'heading', 'Introduction'),
        ('body', 'paragraph', r'Alice Smith $^{*}$ Bob Jones $^{\dagger}$'),
    ])
    assert 'body' in planned_ids(src)


@pytest.mark.parametrize('text,reason', [
    (r'$ 1.47 \times $', 'original_math_cell'),
    (r'$x^2$', 'original_math_cell'),
    ('4 (A)', 'original_numeric_cell'),
    ('16 (B)', 'original_numeric_cell'),
    ('2-1-1', 'original_numeric_cell'),
    ('VGG16', 'original_identifier_cell'),
    ('Inception-v3', 'original_identifier_cell'),
    ('S2VT', 'original_identifier_cell'),
    ('ResNet-50', 'original_identifier_cell'),
])
def test_table_values_need_no_model_request_and_preserve_source(text, reason):
    src, block = parsed(text, 'table_cell')
    before = deepcopy(src)
    assert original_only_blocks(src).get(block['id']) == reason
    assert plan_units(src, 'zh-Hans', profile(), [block['id']]) == []
    assert src == before


@pytest.mark.parametrize('text', [
    'DNN Model', 'PipeDream Config', '8 GPUs', '8GPUs',
    'Number of parameters (billions)', '4 (Average)', '4 (A) machines',
    r'$1.47$ faster', r'$4$ GPUs', 'not 3',
])
def test_table_headers_and_prose_still_translate(text):
    src, block = parsed(text, 'table_cell')
    assert block['id'] not in original_only_blocks(src)
    assert plan_units(src, 'zh-Hans', profile(), [block['id']])


def test_model_identifier_in_body_remains_translatable():
    src, block = parsed('VGG16')
    assert block['id'] not in original_only_blocks(src)


@pytest.mark.parametrize('text', ['(a) VGG16', '(b) Inception-v3', '(A) ResNet-50', 'S2VT'])
def test_isolated_model_subcaptions_are_retained_without_source_edits(text):
    src, block = parsed(text, 'caption')
    before = deepcopy(src)
    assert original_only_blocks(src).get(block['id']) == 'original_identifier_label'
    assert plan_units(src, 'zh-Hans', profile(), [block['id']]) == []
    assert src == before


@pytest.mark.parametrize('text', [
    '(a) VGG16 accuracy', 'Figure 10: VGG16', '(a) DNN Training', '8 GPUs',
    '(a) Inception-v3 outperforms VGG16', 'A model with 2 layers',
])
def test_prose_captions_with_identifiers_still_translate(text):
    src, block = parsed(text, 'caption')
    assert block['id'] not in original_only_blocks(src)
    assert plan_units(src, 'zh-Hans', profile(), [block['id']])


def test_prose_footnote_with_an_organisation_is_not_retained_as_a_whole():
    src, block = parsed('Work started as part of an internship at Microsoft Research.', 'footnote')
    assert block['id'] not in original_only_blocks(src)
    assert plan_units(src, 'zh-Hans', profile(), [block['id']])


def test_retained_caption_still_ends_the_contiguous_author_front_matter():
    src = paper([
        ('label', 'caption', '(a) VGG16'),
        ('names', 'paragraph', 'Alice Smith, Bob Jones'),
        ('org', 'paragraph', 'Example University'),
    ])
    assert original_only_blocks(src) == {'label': 'original_identifier_label'}
    assert {'names', 'org'} <= planned_ids(src)


def test_metadata_literals_extract_full_marked_names_and_organisations():
    from packages.ir.retention import metadata_literals
    src = paper([
        ('authors', 'paragraph', r'Aaron Harlap $^{\dagger*}$ Deepak Narayanan $^{\ddagger*}$'),
        ('more_authors', 'paragraph', r'Amar Phanishayee $^{*}$ Vivek Seshadri $^{*}$ '
            r'Nikhil Devanur $^{*}$ Greg Ganger $^{\dagger}$ Phil Gibbons $^{\dagger}$'),
        ('orgs', 'paragraph', '?Microsoft Research † Carnegie Mellon University ‡ Stanford University'),
        ('abstract', 'heading', 'Abstract'),
        ('body', 'paragraph', 'Carol Lee at Other University proposed the idea.'),
    ])
    before = deepcopy(src)
    expected = {'Aaron Harlap', 'Deepak Narayanan', 'Amar Phanishayee', 'Vivek Seshadri',
        'Nikhil Devanur', 'Greg Ganger', 'Phil Gibbons', 'Microsoft Research',
        'Carnegie Mellon University', 'Stanford University'}
    assert metadata_literals(src) == tuple(sorted(expected, key=lambda value: (-len(value), value)))
    assert metadata_literals(src, original_only_blocks(src)) == metadata_literals(src)
    assert src == before


def test_metadata_literals_exclude_generic_affiliation_and_address_fragments():
    from packages.ir.retention import metadata_literals
    src = paper([
        ('authors', 'paragraph', 'Alice Smith¹, Bob Jones²'),
        ('org', 'paragraph', 'Affiliations: Department of Computing, Example University; '
            'Research; Research Centre; University of; Department of; Institute of; AI; Sydney; Australia'),
    ])
    assert metadata_literals(src) == (
        'Department of Computing', 'Example University', 'Alice Smith', 'Bob Jones',
    )


def test_metadata_literals_keep_exact_unicode_spelling_and_deduplicate():
    from packages.ir.retention import metadata_literals
    name = 'Jose\u0301 Garci\u0301a'
    src = paper([
        ('authors', 'paragraph', f'{name}¹, {name}²'),
        ('org', 'paragraph', '¹ Example University; ² Example University'),
    ])
    assert metadata_literals(src) == ('Example University', name)


def test_metadata_literals_do_not_infer_names_from_body_or_bibliography():
    from packages.ir.retention import metadata_literals
    src = paper([
        ('intro', 'heading', 'Introduction'),
        ('names', 'paragraph', 'Alice Smith, Bob Jones'),
        ('org', 'paragraph', 'Example University'),
        ('refs', 'heading', 'References'),
        ('ref', 'paragraph', '[1] Carol Lee. Research at Another University, 2025.'),
    ])
    assert metadata_literals(src) == ()


def test_explicit_lowercase_author_names_remain_exact_full_phrases():
    from packages.ir.retention import metadata_literals
    src = paper([('authors', 'paragraph', 'Authors: alice smith and bob jones'),
        ('org', 'paragraph', 'OpenAI')])
    assert metadata_literals(src) == ('alice smith', 'bob jones', 'OpenAI')


def test_metadata_literals_keep_confirmed_uncased_names_and_organisations():
    from packages.ir.retention import metadata_literals
    src = paper([('authors', 'paragraph', '张三，李四'),
        ('org', 'paragraph', '北京示例大学计算机学院')])
    assert set(metadata_literals(src)) == {'张三', '李四', '北京示例大学计算机学院'}


@pytest.mark.parametrize('marker', ['⋆', '∗'])
def test_native_star_affiliation_markers_preserve_exact_names_and_organisations(marker):
    from packages.ir.retention import metadata_literals
    src = paper([
        ('authors', 'paragraph', f'Alice Smith†{marker}\nBob Jones‡{marker}'),
        ('orgs', 'paragraph', f'{marker}Microsoft Research † Example University'),
        ('abstract', 'heading', 'Abstract'),
    ])
    before = deepcopy(src)
    assert original_only_blocks(src) == {'authors': 'original_author_list', 'orgs': 'original_affiliation'}
    assert set(metadata_literals(src)) == {'Alice Smith', 'Bob Jones', 'Microsoft Research', 'Example University'}
    assert src == before


def test_typeset_star_markers_are_affiliation_syntax_not_part_of_a_name():
    from packages.ir.retention import metadata_literals
    src = paper([
        ('authors', 'paragraph', r'Alice Smith $^{†⋆}$ Bob Jones $^{‡∗}$'),
        ('orgs', 'paragraph', r'$^{⋆}$ Microsoft Research; $^{∗}$ Example University'),
    ])
    assert set(metadata_literals(src)) == {'Alice Smith', 'Bob Jones', 'Microsoft Research', 'Example University'}
