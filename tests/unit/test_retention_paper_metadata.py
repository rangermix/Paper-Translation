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


def test_numeric_affiliation_markers_delimit_full_names_without_commas():
    from packages.ir.retention import metadata_literals
    src = paper([
        ('authors', 'paragraph',
            'Alice Smith1,∗ Bob Jones1,∗ Carol Lee2,∗ David Wu1 Eve Zhao1 Frank Li1\n'
            'Grace Chen1 Harry Wang2,† Iris Liu1,†'),
        ('orgs', 'paragraph', '1ByteDance 2Peking University'),
        ('abstract', 'heading', 'Abstract'),
        ('body', 'paragraph', 'We evaluate the system.'),
    ])
    before = deepcopy(src)
    assert original_only_blocks(src) == {
        'authors': 'original_author_list', 'orgs': 'original_affiliation',
    }
    assert planned_ids(src) == {src['title_block_id'], 'abstract', 'body'}
    assert {'Alice Smith', 'Bob Jones', 'Carol Lee', 'David Wu', 'Eve Zhao',
        'Frank Li', 'Grace Chen', 'Harry Wang', 'Iris Liu'} <= set(metadata_literals(src))
    assert src == before


def test_semantic_superscript_byline_skips_translation_without_changing_source(tmp_path):
    from tests.unit.test_parser_semantics import document, layout, parse
    raw = document(layout('Text', '<p>Alice Smith<sup>1,∗</sup> '
        'Bob Jones<sup>1,∗</sup> Carol Lee<sup>2</sup> David Wu<sup>1</sup> '
        'Eve Zhao<sup>1</sup> Frank Li<sup>1,†</sup></p>')
        + layout('Text', '<p><sup>1</sup>ByteDance <sup>2</sup>Peking University</p>')
        + layout('Section-Header', '<h2>Abstract</h2>')
        + layout('Text', '<p>We evaluate the system.</p>'))
    src = parse(raw, tmp_path)['source_revision']
    before = deepcopy(src)
    by_text = {b['normalized_text']: b for b in src['blocks']}
    authors = next(b for b in src['blocks'] if b['normalized_text'].startswith('Alice Smith'))
    organisations = by_text['1ByteDance 2Peking University']
    assert any('superscript' in node.get('marks', []) for node in authors['source_inline'])
    assert original_only_blocks(src) == {
        authors['id']: 'original_author_list', organisations['id']: 'original_affiliation',
    }
    assert not {authors['id'], organisations['id']} & planned_ids(src)
    assert by_text['We evaluate the system.']['id'] in planned_ids(src)
    assert src == before


@pytest.mark.parametrize('text', [
    'Global Batch Size4 Micro Batch Size8',
    'Image Recognition Model1 Neural Language Model2',
    'We train models on 100 GPUs and report 3 runs.',
    'Model 3 performs better than model 2.',
])
def test_plain_numeric_front_matter_without_metadata_evidence_remains_translatable(text):
    src = paper([('body', 'paragraph', text),
        ('next', 'paragraph', 'We evaluate the results.')])
    assert 'body' not in original_only_blocks(src)
    assert 'body' in planned_ids(src)


def test_plain_numeric_author_line_still_requires_neighbouring_affiliation():
    src = paper([('authors', 'paragraph', 'Alice Smith1 Bob Jones2 Carol Lee1 David Wu1'),
        ('orgs', 'paragraph', '1Example University 2Example Institute')])
    assert original_only_blocks(src) == {
        'authors': 'original_author_list', 'orgs': 'original_affiliation',
    }


@pytest.mark.parametrize('after_heading', [False, True])
def test_semantic_superscripts_provide_front_matter_evidence_but_not_body_metadata(tmp_path, after_heading):
    from tests.unit.test_parser_semantics import document, layout, parse
    section = layout('Section-Header', '<h2>Introduction</h2>') if after_heading else ''
    raw = document(section + layout('Text', '<p>Alice Smith<sup>1</sup> '
        'Bob Jones<sup>2</sup> Carol Lee<sup>1</sup> David Wu<sup>1</sup></p>')
        + layout('Text', '<p>We evaluate the results.</p>'))
    src = parse(raw, tmp_path)['source_revision']
    authors = next(b for b in src['blocks'] if b['normalized_text'].startswith('Alice Smith'))
    assert (original_only_blocks(src).get(authors['id']) == 'original_author_list') is not after_heading
    assert (authors['id'] in planned_ids(src)) is after_heading


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
