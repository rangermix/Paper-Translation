"""Original-only policy exercises real planning without a model request."""
import copy
import json
import re
from pathlib import Path

import pytest

from packages.ir import block_hash, validate_ir, validate_source
from packages.translation.planner import plan_units
from tests.unit.test_translation import profile, source


def paper(rows):
    result = source()
    template = copy.deepcopy(result['blocks'][1])
    blocks = [copy.deepcopy(result['blocks'][0])]
    parent = blocks[0]['id']
    for index, (bid, kind, text) in enumerate(rows, 1):
        block = copy.deepcopy(template)
        attributes = {'level': 2} if kind == 'heading' else {'list_ordered': True} if kind == 'list_item' else {}
        block.update(id=bid, kind=kind, order=index, parent_id=parent, owner_id=None,
            translatable=kind != 'reference', raw_text=text, normalized_text=text,
            normalization_edits=[], source_inline=[{'type': 'text', 'text': text}],
            attributes=attributes, warnings=[])
        block['source_hash'] = block_hash(block, result['protected_atoms'])
        blocks.append(block)
        if kind == 'heading':
            parent = bid
    result.update(blocks=blocks, reading_order=[b['id'] for b in blocks])
    validate_source(result)
    return result


def academic_paper():
    return paper([
        ('authors', 'paragraph', 'Alice Smith¹, Bob Jones² and Carol Lee¹'),
        ('affiliation', 'paragraph', '¹ Department of Computing, Example University, Sydney, Australia'),
        ('contact', 'paragraph', 'Email: alice@example.edu, bob@example.edu'),
        ('abstract', 'heading', 'Abstract'),
        ('body', 'paragraph', 'We evaluate the method and compare it with prior research.'),
        ('refs', 'heading', '7. References'),
        ('ref1', 'paragraph', '[1] A. Author. A useful paper. Example Journal, 2024.'),
        ('ref2', 'list_item', 'B. Writer. Another paper. Example Conference, 2025.'),
        ('appendix', 'heading', 'Appendix A: Further results'),
        ('extra', 'paragraph', 'Additional experiments support the conclusion.'),
    ])


def planned_ids(src):
    return {u['owner_block_id'] for u in plan_units(src, 'zh-Hans', profile())}


def test_planner_skips_metadata_and_references_without_rewriting_source():
    src = academic_paper()
    before = copy.deepcopy(src)
    assert planned_ids(src) == {src['title_block_id'], 'abstract', 'body', 'appendix', 'extra'}
    assert src == before


@pytest.mark.parametrize('heading', ['References', '8 REFERENCES', 'IV. Bibliography',
    'Works Cited:', 'Literature Cited', '参考文献', '参考文献：', 'Références bibliographiques',
    'Literaturverzeichnis', 'Bibliografía', '参考文献一覧'])
@pytest.mark.parametrize('kind', ['heading', 'paragraph'])
def test_reference_heading_variants_and_list_entries(heading, kind):
    src = paper([('body', 'paragraph', 'Ordinary prose remains translatable.'),
        ('refs', kind, heading), ('entry', 'list_item', '[1] A. Author. A paper, 2024.'),
        ('appendix', 'heading', 'Appendix'), ('more', 'paragraph', 'More prose.')])
    assert planned_ids(src) == {src['title_block_id'], 'body', 'appendix', 'more'}


@pytest.mark.parametrize('text', [
    'We thank the authors at Example University for their contributions.',
    'Our organisation list includes universities and research institutes.',
    'References to earlier studies improve the analysis.',
    'Reference models and bibliography extraction are evaluated here.',
    'This paper was written by Alice Smith and Bob Jones.',
    'Contact alice@example.edu for access to the experimental data.',
    'University researchers evaluated this approach and found better results.',
])
def test_prose_is_never_skipped_just_for_metadata_keywords(text):
    src = paper([('body', 'paragraph', text)])
    assert 'body' in planned_ids(src)


def test_body_names_and_organisations_and_acknowledgments_still_translate():
    src = paper([('intro', 'heading', 'Introduction'),
        ('names', 'paragraph', 'Alice Smith, Bob Jones'),
        ('org', 'paragraph', 'Department of Computing, Example University'),
        ('ack', 'heading', 'Acknowledgments'),
        ('thanks', 'paragraph', 'We thank Example University for funding this work.'),
        ('caption', 'caption', 'Author and organisation list used in the experiment.'),
        ('note', 'footnote', 'The reference implementation differs from our method.')])
    assert planned_ids(src) == {b['id'] for b in src['blocks']}


@pytest.mark.parametrize('authors,affiliation', [
    ('Alice Smith', 'Example University'),
    ('A. Smith*, B. Jones†', 'Department of Physics, Example Institute'),
    ('María García; Jean Dupont', 'Université Exemple, Paris, France'),
    ('张三，李四', '北京示例大学计算机学院'),
    ('Authors: alice smith and bob jones', 'Affiliations: Example Research'),
])
def test_author_and_affiliation_variants(authors, affiliation):
    src = paper([('authors', 'paragraph', authors), ('org', 'paragraph', affiliation),
        ('abstract', 'heading', 'Abstract'), ('body', 'paragraph', 'The abstract describes our work.')])
    assert planned_ids(src) == {src['title_block_id'], 'abstract', 'body'}


@pytest.mark.parametrize('text', ['doi:10.1234/example.2026', 'https://doi.org/10.1234/example',
    'ORCID: 0000-0002-1825-0097', 'https://orcid.org/0000-0002-1825-0097',
    'Corresponding author: alice@example.edu'])
def test_identifier_only_lines_are_retained(text):
    src = paper([('identifier', 'paragraph', text), ('body', 'paragraph', 'Normal content.')])
    assert 'identifier' not in planned_ids(src)


def test_selected_retained_blocks_cannot_become_candidate_units():
    src = academic_paper()
    assert plan_units(src, 'zh-Hans', profile(), ['authors', 'ref1']) == []


def test_title_is_always_translated_even_when_it_is_a_metadata_word():
    src = paper([('body', 'paragraph', 'This paper explains bibliography extraction.')])
    title = src['blocks'][0]
    title.update(raw_text='Bibliography', normalized_text='Bibliography', source_inline=[{'type': 'text', 'text': 'Bibliography'}])
    title['source_hash'] = block_hash(title, src['protected_atoms'])
    assert planned_ids(src) == {title['id'], 'body'}


RETAINED = {'authors': 'original_author_list', 'affiliation': 'original_affiliation',
    'contact': 'original_contact', 'refs': 'original_bibliography_heading',
    'ref1': 'original_reference', 'ref2': 'original_reference'}


def retained_ir():
    ir = json.loads(Path('tests/fixtures/sample-document.json').read_text('utf-8'))
    src = academic_paper()
    tr = ir['translation_revision']
    base = tr['results'][0]
    results = []
    for block in src['blocks']:
        row = copy.deepcopy(base)
        reason = RETAINED.get(block['id'])
        row.update(block_id=block['id'], source_hash=block['source_hash'],
            status='retained' if reason else 'translated', reason=reason or '',
            target_inline=[] if reason else [{'type': 'text', 'text': '译文 ' + block['id']}],
            warnings=[], review_state='not_reviewed', review_record=None)
        row['generation']['kind'] = 'retained' if reason else 'model'
        results.append(row)
    tr.update(results=results, title='译文 ' + src['title_block_id'])
    ir['source_revision'] = src
    return ir


def test_validator_accepts_detected_retention_without_relaxing_prose_guards():
    ir = retained_ir()
    validate_ir(ir)
    row = next(r for r in ir['translation_revision']['results'] if r['block_id'] == 'body')
    row.update(status='retained', target_inline=[], reason='original_author_list')
    with pytest.raises(ValueError, match='required prose cannot be retained'):
        validate_ir(ir)


def test_static_retention_is_one_original_without_a_translation_placeholder():
    from packages.publisher.renderer import render_html
    content = render_html(retained_ir(), {}).decode()
    for bid in RETAINED:
        # Inspect only this block, excluding the independently rendered TOC.
        section = re.search(r'<(section|li)[^>]*data-block-id="' + bid + r'"[^>]*>(.*?)</\1>', content, re.S)[2]
        assert 'data-original-only=' in section
        assert 'data-language=' not in section
        assert 'data-language="target"' not in section
        assert '暂无译文' not in section and '此段尚无译文' not in section
    assert content.count('Alice Smith¹, Bob Jones² and Carol Lee¹') == 1
    assert 'data-language="target"' in content.split('data-block-id="body"')[1].split('</section>')[0]


def test_old_translated_metadata_is_still_rendered_from_its_sealed_result():
    from packages.publisher.renderer import render_html
    ir = retained_ir()
    row = next(r for r in ir['translation_revision']['results'] if r['block_id'] == 'authors')
    row.update(status='translated', target_inline=[{'type': 'text', 'text': 'Previously sealed author translation'}], reason='')
    row['generation']['kind'] = 'model'
    assert 'Previously sealed author translation' in render_html(ir, {}).decode()


def test_retained_metadata_is_not_sent_as_neighbouring_context():
    src = academic_paper()
    units = plan_units(src, 'zh-Hans', profile())
    contexts = ' '.join(value for unit in units for value in unit['context'].values())
    assert 'Alice Smith' not in contexts and 'References' not in contexts
    assert 'alice@example.edu' not in contexts and 'Another paper' not in contexts


@pytest.mark.parametrize('text', [
    'Example University results improve segmentation performance.',
    'Department networks improve retrieval accuracy.',
    'Alice Smith, Bob Jones\nAbstract\nA novel architecture improves segmentation.',
    'Example University\nAbstract\nA novel architecture improves segmentation.',
])
def test_metadata_looking_prose_or_merged_abstract_is_not_retained(text):
    src = paper([('body', 'paragraph', text)])
    assert 'body' in planned_ids(src)


@pytest.mark.parametrize('organisation', ['OpenAI', 'Google DeepMind', 'Microsoft Research', 'Meta AI'])
def test_company_affiliations_in_author_front_matter(organisation):
    src = paper([('authors', 'paragraph', 'Alice Smith, Bob Jones'),
        ('org', 'paragraph', organisation), ('abstract', 'heading', 'Abstract')])
    assert planned_ids(src) == {src['title_block_id'], 'abstract'}


@pytest.mark.parametrize('text', ['Deep Learning and Natural Language Processing', 'Neural Networks, Deep Learning'])
def test_ambiguous_capitalized_prose_requires_positive_author_evidence(text):
    src = paper([('subtitle', 'paragraph', text), ('body', 'paragraph', 'An ordinary introduction.')])
    assert 'subtitle' in planned_ids(src)


@pytest.mark.parametrize('heading', ['Appendix A Additional Proofs', 'Author Contributions',
    '9. Acknowledgments', 'Data Availability', 'Conflict of Interest'])
def test_paragraph_section_boundaries_end_the_bibliography(heading):
    src = paper([('intro', 'heading', 'Introduction'), ('refs', 'heading', 'References'),
        ('ref', 'paragraph', '[1] A. Author, 2024.'), ('after', 'paragraph', heading),
        ('body', 'paragraph', 'Additional statements must still be translated.')])
    assert planned_ids(src) == {src['title_block_id'], 'intro', 'after', 'body'}


@pytest.mark.parametrize('text', ['文' * 32000, 'a' * 32000 + '@example.'], ids=['long-cjk', 'malformed-email'])
def test_long_prose_does_not_trigger_quadratic_contact_detection(text):
    from time import perf_counter
    src = paper([('body', 'paragraph', text)])
    started = perf_counter()
    assert 'body' in planned_ids(src)
    assert perf_counter() - started < 1.0
