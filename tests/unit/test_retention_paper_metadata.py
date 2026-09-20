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
