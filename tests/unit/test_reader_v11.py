"""Schema 4 readers keep contextual notes and original scholarly metadata."""
from copy import deepcopy

from lxml import html

from packages.publisher.renderer import render_html
from tests.unit.test_parser_semantics import parse, document, layout
from tests.unit.test_semantic_consumers import render_snapshot


def rich_sidenote_fixture(tmp_path):
    raw = document(
        layout('Text','<p>Jane Smith<sup>1,∗</sup> John Doe<sup>2,†</sup></p>', '50 100 950 140')
        + layout('Text','<p><sup>1</sup>Example University <sup>2</sup>Research Institute</p>', '50 150 950 190')
        + layout('Section-Header','<h2>1 Introduction</h2>', '50 200 950 240')
        + layout('Text','<p>Our implementation<sup>3</sup> uses prior work [1]. Also <a href="#reference-two">[2]</a>.</p>', '50 250 950 300')
        + layout('Text','<ul><li>Nested citation [2] and note <a href="#note-three"><sup>3</sup></a>.</li></ul>', '50 310 950 350')
        + layout('Text','<p>Keep x<sup>3</sup> as a mathematical exponent.</p>', '50 360 950 400')
        + layout('Footnote','<p>*Equal contribution.</p><p>†Corresponding authors.</p><p id="note-three"><sup>3</sup>Implementation details.</p><p>Unlinked printed note.</p>', '50 410 950 490')
        + layout('Section-Header','<h2>References</h2>', '50 500 950 540')
        + layout('Reference','<p>[1] Jane Smith. 2024. First result.</p><p id="reference-two">[2] John Doe. 2025. Second result.</p>', '50 550 950 700'))
    source = parse(raw,tmp_path)['source_revision']
    source['language']='en'
    for block in source['blocks']:block['language']='en'
    return render_snapshot(source)


def markup(ir):
    return html.fromstring(render_html(ir,{a['id']:a['storage_key'] for a in ir['source_revision']['assets']}))


def test_nested_reference_and_explicit_xref_both_have_sidebar_targets(tmp_path):
    ir=rich_sidenote_fixture(tmp_path);tree=markup(ir)
    links=tree.xpath('//a[@data-reference-targets]')
    assert len(links)>=6
    for link in links:
        assert link.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," reader-block ")]')
        for bid in link.get('data-reference-targets').split():
            target=tree.get_element_by_id('b-'+bid)
            assert target.get('data-original-only')=='original_reference'
    assert any(''.join(link.itertext())=='[2]' for link in links)


def test_notes_have_collected_canonical_entries_and_context_cards(tmp_path):
    ir=rich_sidenote_fixture(tmp_path);before=deepcopy(ir);tree=markup(ir)
    source=ir['source_revision']
    notes=[b for b in source['blocks'] if b['kind']=='footnote']
    assert len(notes)==4
    for note in notes:
        target=tree.get_element_by_id('b-'+note['id'])
        assert target.get('class')=='footnote-entry'
        assert target.xpath('ancestor::section[@role="doc-endnotes"]')
    links=tree.xpath('//a[@data-footnote-target]')
    assert len(links)>=6
    for link in links:
        row=link.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," reader-block ") or contains(concat(" ",normalize-space(@class)," ")," reader-header ")][1]')[0]
        cards=row.xpath('.//*[@data-note-target=$target]',target=link.get('data-footnote-target'))
        assert cards and cards[0].xpath('.//a[@class="reference-source"]/@href')==[link.get('href')]
        assert tree.get_element_by_id(link.get('href')[1:]) is not None
    exponent=next(b for b in source['blocks'] if 'mathematical exponent' in b['normalized_text'])
    assert not tree.get_element_by_id('b-'+exponent['id']).xpath('.//a[@data-footnote-target]')
    assert len(tree.xpath('//@id'))==len(set(tree.xpath('//@id')))
    assert ir==before


def test_metadata_in_header_uses_original_even_with_older_translated_results(tmp_path):
    ir=rich_sidenote_fixture(tmp_path)
    author=next(b for b in ir['source_revision']['blocks'] if b['normalized_text'].startswith('Jane Smith1'))
    result=next(r for r in ir['translation_revision']['results'] if r['block_id']==author['id'])
    result.update(status='translated',reason='',target_inline=[{'type':'text','text':'错误的作者译名'}])
    tree=markup(ir)
    authors=tree.xpath('//header//div[@data-original-only="original_author_list"]')
    affiliations=tree.xpath('//header//div[@data-original-only="original_affiliation"]')
    assert authors and affiliations
    assert 'Jane Smith' in ''.join(authors[0].itertext())
    assert '错误的作者译名' not in ''.join(tree.itertext())
    assert tree.xpath('//header//a[@data-footnote-target]')


def test_same_page_duplicate_note_markers_stay_unlinked(tmp_path):
    from packages.publisher.semantic_notes import FootnoteIndex
    ir=rich_sidenote_fixture(tmp_path);source=ir['source_revision']
    numeric=next(b for b in source['blocks'] if b['kind']=='footnote' and b['normalized_text'].startswith('3'))
    duplicate=deepcopy(numeric);duplicate['id']='ambiguous-note';source['blocks'].append(duplicate)
    body=next(b for b in source['blocks'] if b['normalized_text'].startswith('Our implementation'))
    nodes=FootnoteIndex(source,{}).nodes(body['source_inline'],body['id'])
    assert not any(n['type']=='xref' and n['target_block_id']==numeric['id'] for n in nodes)


def test_v11_accepts_existing_v3_snapshots_and_keeps_note_links():
    from test_reader_sidenotes import sidenote_fixture
    ir=sidenote_fixture('reader-v11');before=deepcopy(ir);tree=markup(ir)
    assert tree.get_element_by_id('b-fn1').xpath('ancestor::section[@role="doc-endnotes"]')
    assert tree.get_element_by_id('b-p1').xpath('.//a[@data-footnote-target="fn1"]')
    assert tree.get_element_by_id('b-p2').xpath('.//a[@data-footnote-target="fn1"]')
    assert len(tree.xpath('//@id'))==len(set(tree.xpath('//@id')))
    assert ir==before


def test_target_language_does_not_turn_a_source_exponent_into_a_note(tmp_path):
    ir=rich_sidenote_fixture(tmp_path)
    block=next(b for b in ir['source_revision']['blocks'] if 'mathematical exponent' in b['normalized_text'])
    result=next(r for r in ir['translation_revision']['results'] if r['block_id']==block['id'])
    result['target_inline'][0]['text']='保留x'
    tree=markup(ir)
    assert not tree.get_element_by_id('b-'+block['id']).xpath('.//a[@data-footnote-target]')


def test_numeric_note_prefix_needs_printed_boundary_or_superscript(tmp_path):
    from packages.publisher.semantic_notes import FootnoteIndex
    raw=document(layout('Text','<p>Our implementation<sup>3</sup> is available.</p>')
        +layout('Footnote','<p>3D methods are related.</p>'))
    source=parse(raw,tmp_path)['source_revision']
    body=next(b for b in source['blocks'] if b['normalized_text'].startswith('Our implementation'))
    assert FootnoteIndex(source,{}).nodes(body['source_inline'],body['id'])==body['source_inline']


def test_code_caption_note_card_has_only_one_anchor(tmp_path):
    raw=document(layout('Code','<pre>x=1</pre><figcaption>Source note<sup>3</sup></figcaption>')
        +layout('Footnote','<p><sup>3</sup>Printed note.</p>'))
    source=parse(raw,tmp_path)['source_revision'];ir=render_snapshot(source);before=deepcopy(ir);tree=markup(ir)
    assert tree.xpath('//a[@data-footnote-target]')
    assert len(tree.xpath('//@id'))==len(set(tree.xpath('//@id')))
    assert ir==before


def test_contact_footnote_is_not_duplicated_in_metadata_header(tmp_path):
    raw=document(layout('Text','<p>Alice Smith<sup>*</sup></p>', '50 100 950 140')
        +layout('Footnote','<p>alice@example.edu</p>', '50 150 950 190')
        +layout('Section-Header','<h2>Abstract</h2>', '50 200 950 240'))
    source=parse(raw,tmp_path)['source_revision'];tree=markup(render_snapshot(source))
    contact=next(b for b in source['blocks'] if b['normalized_text']=='alice@example.edu')
    assert not tree.get_element_by_id('b-'+contact['id']).xpath('ancestor::header')
    assert len(tree.xpath('//@id'))==len(set(tree.xpath('//@id')))
