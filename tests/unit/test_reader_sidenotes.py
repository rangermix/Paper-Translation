"""Contextual footnotes and bibliography links without changing stored content."""
from copy import deepcopy
from pathlib import Path

import pytest

from packages.ir import block_hash
from packages.ir.validator import flatten_inline
from packages.publisher import Publisher, export_single_html
from packages.publisher.renderer import render_html
from packages.templates.registry import get_template
from test_reader_v5 import ReaderMarkup, reader_fixture


def refresh(ir):
    source = ir['source_revision']
    for index, block in enumerate(source['blocks']):
        block['order'] = index
        block['source_hash'] = block_hash(block, source['protected_atoms'])
        next(row for row in ir['translation_revision']['results'] if row['block_id'] == block['id'])['source_hash'] = block['source_hash']
    return ir


def set_inline(ir, bid, nodes):
    source = ir['source_revision']
    block = next(block for block in source['blocks'] if block['id'] == bid)
    text = flatten_inline(nodes, source['protected_atoms'])
    block.update(raw_text=text, normalized_text=text, source_inline=nodes, normalization_edits=[])
    row = next(row for row in ir['translation_revision']['results'] if row['block_id'] == bid)
    row.update(status='translated', target_inline=deepcopy(nodes))


def add_reference(ir, bid, text):
    source = ir['source_revision']
    block = deepcopy(next(block for block in source['blocks'] if block['id'] == 'ref1'))
    block.update(id=bid, raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
    source['blocks'].append(block)
    source['reading_order'].append(bid)
    row = deepcopy(next(row for row in ir['translation_revision']['results'] if row['block_id'] == 'ref1'))
    row.update(block_id=bid)
    ir['translation_revision']['results'].append(row)


def sidenote_fixture(template='reader-v8'):
    ir = reader_fixture(template)
    source = ir['source_revision']
    source['protected_atoms']['citations'] = {'kind': 'citation', 'value': '[1–2]'}
    source['protected_atoms']['author_citation'] = {'kind': 'citation', 'value': '(Smith et al., 2020)'}
    set_inline(ir, 'p1', [
        {'type': 'text', 'text': 'A result with a footnote'},
        {'type': 'xref', 'target_block_id': 'fn1', 'label': '1'},
        {'type': 'text', 'text': ' and supporting work '},
        {'type': 'protected_ref', 'ref': 'citations'},
        {'type': 'text', 'text': '. See also '},
        {'type': 'protected_ref', 'ref': 'author_citation'},
        {'type': 'text', 'text': '. Unresolved [99] stays readable.'},
    ])
    set_inline(ir, 'item2', [{'type': 'text', 'text': 'A list citation [2].'}])
    set_inline(ir, 'figcap', [{'type': 'text', 'text': 'A caption citation [1].'}])
    set_inline(ir, 'c1', [{'type': 'text', 'text': 'A cell citation [2].'}])
    ref = next(block for block in source['blocks'] if block['id'] == 'ref1')
    text = '[1] Alice Smith, Bob Jones. 2020. A useful result. Journal of Examples.'
    ref.update(raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
    add_reference(ir, 'ref2', '[2] Doe, J. 2021. Another result. https://example.org/paper')
    orphan = deepcopy(next(block for block in source['blocks'] if block['id'] == 'fn1'))
    orphan.update(id='unlinked-note', raw_text='An unlinked footnote.', normalized_text='An unlinked footnote.', source_inline=[{'type': 'text', 'text': 'An unlinked footnote.'}])
    source['blocks'].insert(source['blocks'].index(ref), orphan)
    source['reading_order'].insert(source['reading_order'].index('ref1'), orphan['id'])
    row = deepcopy(next(row for row in ir['translation_revision']['results'] if row['block_id'] == 'fn1'))
    row.update(block_id=orphan['id'], target_inline=deepcopy(orphan['source_inline']))
    ir['translation_revision']['results'].append(row)
    return refresh(ir)


def table_reference_fixture():
    ir = sidenote_fixture()
    source, translation = ir['source_revision'], ir['translation_revision']
    for old_id, bid, text in [('intro', 'references-heading', 'References'), ('table', 'references-table', ''), ('c1', 'reference-cell', '[3] Alice Example. 2023. A bibliography entry extracted into a table.')]:
        block = deepcopy(next(block for block in source['blocks'] if block['id'] == old_id))
        block.update(id=bid, raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}] if text else [])
        if old_id == 'c1':
            block['owner_id'] = 'references-table'
        if old_id == 'table':
            block['attributes'] = {'representation': 'structured', 'rows': 1, 'columns': 1, 'caption_block_ids': [],
                'cells': [{'row': 0, 'column': 0, 'row_span': 1, 'column_span': 1, 'content_block_id': 'reference-cell'}]}
        source['blocks'].append(block)
        if not block['owner_id']:
            source['reading_order'].append(bid)
        row = deepcopy(next(row for row in translation['results'] if row['block_id'] == old_id))
        row.update(block_id=bid)
        if row['status'] == 'translated':
            row['target_inline'] = deepcopy(block['source_inline'])
        translation['results'].append(row)
    set_inline(ir, 'p2', [{'type': 'text', 'text': 'This citation [3] points to a table cell.'}])
    return refresh(ir)


def native_sidenote_fixture(tmp_path):
    from packages.editorial.drafts import context_hash, render_input
    from test_native_footnote_links import adapt
    source, inspection = adapt(tmp_path, second_reference=True)
    translation = deepcopy(sidenote_fixture()['translation_revision'])
    row = deepcopy(next(row for row in translation['results'] if row['block_id'] == 'p1'))
    translation.update(source_revision_id=source['id'], title='Footnote paper', results=[])
    for block in source['blocks']:
        assert block['translatable']  # This authored PDF contains prose only.
        result = deepcopy(row)
        result.update(block_id=block['id'], source_hash=block['source_hash'],
            context_hash=context_hash(source, block['id']), status='fallback', target_inline=[],
            reason='translation_unavailable', fallback={'mode': 'source_text'}, warnings=[],
            review_state='not_reviewed', review_record=None)
        translation['results'].append(result)
    return render_input('native-footnotes', source, translation, 'reader-v9'), inspection


def markup(ir):
    return ReaderMarkup(render_html(ir, {'figure_png': 'figure.png'}).decode())


def margin(tree, bid):
    return tree.parents[tree.by_id(bid)].find('./aside[@class="reader-notes"]')


def test_footnotes_follow_each_citing_block_with_one_canonical_anchor():
    ir = sidenote_fixture()
    before = deepcopy(ir)
    tree = markup(ir)
    for origin in ['p1', 'p2']:
        note = margin(tree, origin).find('.//*[@data-note-target="fn1"]')
        assert note is not None
        assert 'manually authored fixture' in ''.join(note.itertext())
        assert note.find('.//a[@href="#b-' + origin + '"]') is not None
    assert len(tree.root.findall('.//*[@id="b-fn1"]')) == 1
    assert tree.ancestor(tree.by_id('fn1'), 'aside') is not None
    assert tree.ancestor(tree.by_id('unlinked-note'), 'aside') is None
    assert ir == before


def test_resolved_inline_citations_have_real_links_in_both_languages_and_children():
    tree = markup(sidenote_fixture())
    block = tree.by_id('p1')
    for language in ['source', 'target']:
        content = block.find(f'.//*[@data-language="{language}"]')
        links = content.findall('.//a[@data-reference-targets]')
        assert [(''.join(link.itertext()), link.get('data-reference-targets')) for link in links] == [('[1–2]', 'ref1 ref2'), ('(Smith et al., 2020)', 'ref1')]
        assert links[0].get('href') == '#b-ref1'
        assert '[99]' in ''.join(content.itertext())
    for bid in ['item2', 'figcap', 'c1']:
        assert tree.by_id(bid).find('.//a[@data-reference-targets]') is not None
    assert tree.by_id('ref1').get('data-original-only') == 'original_reference'
    assert not tree.by_id('ref1').findall('.//a[@data-reference-targets]')


@pytest.mark.parametrize('label', ['[1, 2]', '[1; 2]', '[1-2]', '(Smith et al., 2020; Doe, 2021)', 'Smith et al. (2020)'])
def test_plain_text_citations_preserve_the_exact_visible_label(label):
    ir = sidenote_fixture()
    set_inline(ir, 'p2', [{'type': 'text', 'text': f'Before {label} after.'}])
    tree = markup(refresh(ir))
    link = tree.by_id('p2').find('.//a[@data-reference-targets]')
    assert link is not None and link.text == label


@pytest.mark.parametrize('label', ['[99]', '[1, 99]', '[1-999999999]', '(Unknown, 2020)'])
def test_unresolved_or_unbounded_citations_are_not_given_misleading_links(label):
    ir = sidenote_fixture()
    set_inline(ir, 'p2', [{'type': 'text', 'text': f'Before {label} after.'}])
    tree = markup(refresh(ir))
    assert not tree.by_id('p2').findall('.//a[@data-reference-targets]')


def test_duplicate_reference_labels_and_author_years_are_ambiguous():
    ir = sidenote_fixture()
    add_reference(ir, 'ambiguous', '[1] Alice Smith, Carol James. 2020. A different result.')
    tree = markup(refresh(ir))
    assert not tree.by_id('p1').findall('.//a[@data-reference-targets]')


def test_older_citations_split_across_text_and_number_atoms_remain_clickable():
    ir = sidenote_fixture()
    ir['source_revision']['protected_atoms']['ref_number'] = {'kind': 'number', 'value': '1'}
    set_inline(ir, 'p2', [
        {'type': 'text', 'text': 'Earlier work [', 'marks': ['emphasis']},
        {'type': 'protected_ref', 'ref': 'ref_number'},
        {'type': 'text', 'text': '] still applies.', 'marks': ['strong']},
    ])
    tree = markup(refresh(ir))
    link = tree.by_id('p2').find('.//a[@data-reference-targets]')
    assert link is not None
    assert ''.join(link.itertext()) == '[1]'
    assert link.find('./em') is not None and link.find('./strong') is not None
    assert link.find('./span[@data-kind="number"]') is not None


def test_enormous_numeric_range_does_not_abort_publication():
    ir = sidenote_fixture()
    label = '[1-' + '9' * 5000 + ']'
    set_inline(ir, 'p2', [{'type': 'text', 'text': label}])
    tree = markup(refresh(ir))
    assert not tree.by_id('p2').findall('.//a[@data-reference-targets]')
    assert label in ''.join(tree.by_id('p2').itertext())


@pytest.mark.parametrize('label', ['(Smith, 2019)', '(Smith, 2020)'])
def test_years_in_titles_do_not_get_guessed_as_publication_years(label):
    ir = sidenote_fixture()
    ref = next(block for block in ir['source_revision']['blocks'] if block['id'] == 'ref1')
    text = '[1] Alice Smith. The 2019 Benchmark. Journal of Examples, 2020.'
    ref.update(raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
    set_inline(ir, 'p2', [{'type': 'text', 'text': label}])
    assert not markup(refresh(ir)).by_id('p2').findall('.//a[@data-reference-targets]')


def test_words_in_reference_titles_are_not_treated_as_secondary_authors():
    ir = sidenote_fixture()
    ref = next(block for block in ir['source_revision']['blocks'] if block['id'] == 'ref1')
    text = '[1] Alice Smith. Transformer and other models. Journal of Examples, 2020.'
    ref.update(raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
    set_inline(ir, 'p2', [{'type': 'text', 'text': '(Smith & Transformer, 2020)'}])
    assert not markup(refresh(ir)).by_id('p2').findall('.//a[@data-reference-targets]')


def test_unproven_superscript_footnote_markers_are_preserved_without_guessing():
    ir = sidenote_fixture()
    set_inline(ir, 'p2', [{'type': 'text', 'text': 'A parsed footnote¹ appears here.'}])
    set_inline(ir, 'fn1', [{'type': 'text', 'text': '1 Details from the original footnote.'}])
    tree = markup(refresh(ir))
    assert tree.by_id('p2').find('.//a[@role="doc-noteref"]') is None
    assert 'footnote¹' in ''.join(tree.by_id('p2').itertext())


def test_same_footnote_marker_on_another_page_is_not_guessed():
    ir = sidenote_fixture()
    set_inline(ir, 'p2', [{'type': 'text', 'text': 'A parsed footnote¹ appears here.'}])
    set_inline(ir, 'fn1', [{'type': 'text', 'text': '1 Details from the original footnote.'}])
    next(block for block in ir['source_revision']['blocks'] if block['id'] == 'fn1')['provenance'][0]['page'] += 1
    tree = markup(refresh(ir))
    assert tree.by_id('p2').find('.//a[@role="doc-noteref"]') is None


def test_title_footnotes_have_clickable_markers_and_a_title_margin():
    ir = sidenote_fixture()
    nodes = [{'type': 'text', 'text': 'A paper title'}, {'type': 'xref', 'target_block_id': 'fn1', 'label': '1'}]
    set_inline(ir, 'title', nodes)
    ir['document']['title'] = ir['translation_revision']['title'] = 'A paper title1'
    tree = markup(refresh(ir))
    assert tree.by_id('title').find('.//a[@role="doc-noteref"]') is not None
    assert margin(tree, 'title').find('.//*[@data-note-target="fn1"]') is not None


@pytest.mark.parametrize('text', ['The value of x² is 9.', '25 cm² was used.', 'log² in this notation.', 'Plain code¹ is literal.'])
def test_math_exponents_and_code_marks_are_not_guessed_as_footnote_citations(text):
    ir = sidenote_fixture()
    nodes = [{'type': 'text', 'text': text, **({'marks': ['code']} if 'code' in text else {})}]
    set_inline(ir, 'p2', nodes)
    set_inline(ir, 'fn1', [{'type': 'text', 'text': ('1' if 'code' in text else '2') + ' Details.'}])
    assert markup(refresh(ir)).by_id('p2').find('.//a[@role="doc-noteref"]') is None


@pytest.mark.parametrize('text', [
    '[1] Alice Smith. Forecasting through 2030. Technical report, n.d.',
    '[1] Smith, J. Forecasting through 2030. Technical report, n.d.',
])
def test_a_sole_year_in_a_title_is_not_assumed_to_be_a_publication_date(text):
    ir = sidenote_fixture()
    ref = next(block for block in ir['source_revision']['blocks'] if block['id'] == 'ref1')
    ref.update(raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
    set_inline(ir, 'p2', [{'type': 'text', 'text': '(Smith, 2030)'}])
    assert not markup(refresh(ir)).by_id('p2').findall('.//a[@data-reference-targets]')


@pytest.mark.parametrize('authors', ['Alice Q. Smith, Bob Jones.', 'Smith, A. Q., Jones, B.', 'Alice Smith and Bob Jones'])
def test_author_lists_with_initials_resolve_both_named_authors(authors):
    ir = sidenote_fixture()
    ref = next(block for block in ir['source_revision']['blocks'] if block['id'] == 'ref1')
    text = f'[1] {authors} (2020). A useful result.'
    ref.update(raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
    set_inline(ir, 'p2', [{'type': 'text', 'text': '(Smith & Jones, 2020)'}])
    link = markup(refresh(ir)).by_id('p2').find('.//a[@data-reference-targets]')
    assert link is not None and link.get('data-reference-targets') == 'ref1'


def test_existing_templates_keep_footnotes_in_the_main_flow():
    tree = markup(sidenote_fixture('reader-v6'))
    assert tree.ancestor(tree.by_id('fn1'), 'aside') is None
    assert not tree.by_id('p1').findall('.//a[@data-reference-targets]')


def test_new_reader_is_registered_and_exports_offline(tmp_path):
    from packages.editorial.drafts import render_input
    ir = sidenote_fixture()
    template = get_template('reader-v8')
    assert template['version'] == '8'
    ir = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v8')
    Publisher().build(ir, Path('tests'), tmp_path / 'bundle', include_source=True)
    single = export_single_html(tmp_path / 'bundle', tmp_path / 'single.html', include_source=True).read_text()
    assert 'data-reference-targets' in single
    assert '<script src=' not in single


def test_native_pdf_markers_publish_beside_each_citing_block(tmp_path):
    ir, inspection = native_sidenote_fixture(tmp_path)
    source = ir['source_revision']
    before = deepcopy(source)
    Publisher().build(ir, tmp_path / 'output', tmp_path / 'bundle', include_source=True)
    single = export_single_html(tmp_path / 'bundle', tmp_path / 'single.html', include_source=True).read_text()
    tree = ReaderMarkup(single)
    note = next(block for block in source['blocks'] if block['kind'] == 'footnote')
    bodies = [block for block in source['blocks'] if block['kind'] == 'paragraph']
    assert len(bodies) == len(inspection['footnote_links']) == 2
    for block in bodies:
        content = tree.by_id(block['id'])
        assert content.find('.//a[@role="doc-noteref"]').text == '1'
        assert content.find('.//span[@data-kind="number"]').text == '1'
        card = margin(tree, block['id']).find('.//*[@data-note-target="' + note['id'] + '"]')
        assert card is not None and 'Supporting detail.' in ''.join(card.itertext())
    assert len(tree.root.findall('.//*[@id="b-' + note['id'] + '"]')) == 1
    assert source == before
