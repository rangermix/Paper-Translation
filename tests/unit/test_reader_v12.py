"""List containers must not render empty bilingual paragraphs."""
from copy import deepcopy

from lxml import html

from packages.editorial.drafts import render_input
from packages.publisher.renderer import render_html
from tests.unit.test_parser_semantics import parse, document, layout
from tests.unit.test_semantic_consumers import render_snapshot


def test_nested_list_keeps_one_marker_per_item_without_empty_source_cards(tmp_path):
    raw = document(layout('Text', '<ul><li><p>First contribution.</p><p>More detail.</p></li>'
                          '<li><p>Second contribution.</p><ul><li>Nested detail.</li></ul></li></ul>'))
    source = parse(raw, tmp_path)['source_revision']
    snapshot = render_snapshot(source)
    snapshot = render_input('document-rich', source, snapshot['translation_revision'], 'reader-v12')
    before = deepcopy(snapshot)
    tree = html.fromstring(render_html(snapshot, {a['id']: a['storage_key'] for a in source['assets']}))
    items = tree.xpath('//li[@data-kind="list_item"]')
    assert len(items) == 3
    assert all(''.join(card.itertext()).strip() != '原文' for card in tree.xpath('//div[contains(@class,"para")]'))
    assert 'First contribution.' in ''.join(items[0].itertext())
    assert 'More detail.' in ''.join(items[0].itertext())
    assert len(tree.xpath('//@id')) == len(set(tree.xpath('//@id')))
    assert snapshot == before


def test_old_reader_keeps_its_frozen_list_rendering(tmp_path):
    source = parse(document(layout('Text', '<ul><li><p>Contribution.</p></li></ul>')), tmp_path)['source_revision']
    snapshot = render_snapshot(source)
    old = render_input('document-rich', source, snapshot['translation_revision'], 'reader-v11')
    tree = html.fromstring(render_html(old, {a['id']: a['storage_key'] for a in source['assets']}))
    assert any(''.join(card.itertext()).strip() == '原文' for card in tree.xpath('//div[contains(@class,"para")]'))
