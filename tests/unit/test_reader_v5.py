"""Original section labels, grouped academic metadata/lists and reader margins."""
from copy import deepcopy
import json
from pathlib import Path

from html.parser import HTMLParser
from xml.etree.ElementTree import Element

from packages.editorial.drafts import render_input
from packages.ir import block_hash, digest
from packages.publisher import Publisher, export_single_html
from packages.publisher.renderer import render_html
from packages.templates.registry import get_template


def reader_fixture(template='reader-v5'):
    ir = json.loads(Path('tests/fixtures/sample-document.json').read_text())
    source, translation = ir['source_revision'], ir['translation_revision']
    translation['content_policy'] = 'nonblocking-v1'
    paragraph = deepcopy(next(block for block in source['blocks'] if block['id'] == 'p1'))
    result = deepcopy(next(row for row in translation['results'] if row['block_id'] == 'p1'))
    rows = [
        ('authors', 'paragraph', 'Alice Smith¹, Bob Jones²', {}),
        ('affiliation', 'paragraph', '¹ Example University, Sydney, Australia', {}),
        ('abstract', 'heading', 'Abstract', {'level': 2}),
        ('intro', 'heading', '1 Introduction', {'level': 2}),
        ('background', 'heading', '2 Background & Related Work', {'level': 2}),
        ('training', 'heading', '2.1 DNN Training', {'level': 3}),
    ]
    extra = []
    for bid, kind, text, attributes in rows:
        block = deepcopy(paragraph)
        block.update(id=bid, kind=kind, raw_text=text, normalized_text=text,
            source_inline=[{'type': 'text', 'text': text}], attributes=attributes,
            normalization_edits=[], warnings=[])
        extra.append(block)
        row = deepcopy(result)
        row.update(block_id=bid, status='translated', target_inline=[{'type': 'text', 'text': '译文 ' + text}], warnings=[])
        translation['results'].append(row)
    source['blocks'][1:1] = extra
    source['reading_order'][1:1] = [block['id'] for block in extra]
    item = next(block for block in source['blocks'] if block['id'] == 'item')
    item_result = next(row for row in translation['results'] if row['block_id'] == 'item')
    item2 = deepcopy(item)
    item2.update(id='item2', raw_text='Keep the symbols.', normalized_text='Keep the symbols.',
        source_inline=[{'type': 'text', 'text': 'Keep the symbols.'}], attributes={'list_ordered': True, 'list_index': 2})
    source['blocks'].insert(source['blocks'].index(item) + 1, item2)
    source['reading_order'].insert(source['reading_order'].index('item') + 1, 'item2')
    row = deepcopy(item_result)
    row.update(block_id='item2', target_inline=[{'type': 'text', 'text': '保留符号。'}])
    translation['results'].append(row)
    p1 = next(block for block in source['blocks'] if block['id'] == 'p1')
    p1['warnings'] = ['请对照原 PDF 核对本段。']
    p1['attributes'].update(comparison_asset_id='figure_png', comparison_scope='page')
    for index, block in enumerate(source['blocks']):
        block['order'] = index
        block['source_hash'] = block_hash(block, source['protected_atoms'])
        next(row for row in translation['results'] if row['block_id'] == block['id'])['source_hash'] = block['source_hash']
    # The renderer contracts can fail independently of registering the template.
    ir = render_input(ir['document']['id'], source, translation, 'reader-v4')
    ir['render']['template_id'] = template
    return ir


class ReaderMarkup(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.root = Element('root')
        self.stack = [self.root]
        self.parents = {}
        self.feed(content)

    def handle_starttag(self, tag, attributes):
        node = Element(tag, {key: value or '' for key, value in attributes})
        self.stack[-1].append(node)
        self.parents[node] = self.stack[-1]
        if tag not in {'meta', 'link', 'img', 'br', 'hr', 'input'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, value):
        self.stack[-1].text = (self.stack[-1].text or '') + value

    def by_id(self, bid):
        return self.root.find(f'.//*[@id="b-{bid}"]')

    def ancestor(self, node, tag):
        while node in self.parents:
            node = self.parents[node]
            if node.tag == tag:
                return node
        return None


def markup(ir):
    return ReaderMarkup(render_html(ir, {'figure_png': 'figure.png'}).decode())


def test_toc_uses_original_heading_labels_without_adding_section_numbers():
    tree = markup(reader_fixture())
    toc = tree.root.find('.//aside[@class="toc"]')
    assert not toc.findall('.//ol')
    assert [(link.get('href'), ''.join(link.itertext())) for link in toc.findall('.//nav//a')] == [
        ('#b-abstract', 'Abstract'), ('#b-intro', '1 Introduction'),
        ('#b-background', '2 Background & Related Work'), ('#b-training', '2.1 DNN Training')]


def test_recognized_names_and_affiliations_render_once_inside_title():
    tree = markup(reader_fixture())
    for bid, reason in [('authors', 'original_author_list'), ('affiliation', 'original_affiliation')]:
        block = tree.by_id(bid)
        assert tree.ancestor(block, 'header') is not None
        assert block.get('data-original-only') == reason
        assert not block.findall('.//*[@data-language="target"]')
        assert len(tree.root.findall(f'.//*[@id="b-{bid}"]')) == 1
    assert tree.ancestor(tree.by_id('p1'), 'header') is None


def test_consecutive_list_items_share_one_list_and_preserve_individual_anchors():
    tree = markup(reader_fixture())
    first, second = tree.by_id('item'), tree.by_id('item2')
    assert tree.parents[first] is tree.parents[second]
    assert tree.parents[first].tag == 'ol'
    assert tree.parents[first].get('start') == '1'
    assert len(tree.parents[first].findall('./li')) == 2
    assert 'reader-list' in tree.parents[tree.parents[first]].get('class', '').split()


def test_block_hints_and_source_comparison_have_one_adjacent_margin():
    tree = markup(reader_fixture())
    block = tree.by_id('p1')
    assert not block.findall('.//details')
    margin = tree.parents[block].findall('./aside[@class="reader-notes"]')
    assert len(margin) == 1
    assert len(margin[0].findall('./details')) == 2
    assert '内容提示' in ''.join(margin[0].itertext()) and '查看原文' in ''.join(margin[0].itertext())
    assert tree.root.find('.//aside[@class="toc"]//section[@class="issue-panel"]') is None


def test_original_list_markers_do_not_gain_a_second_browser_counter():
    ir = reader_fixture()
    block = next(block for block in ir['source_revision']['blocks'] if block['id'] == 'item')
    text = '1. Automatic Partitioning: the original numbered list item.'
    block.update(raw_text=text, normalized_text=text, source_inline=[{'type': 'text', 'text': text}])
    block['source_hash'] = block_hash(block, ir['source_revision']['protected_atoms'])
    next(row for row in ir['translation_revision']['results'] if row['block_id'] == 'item')['source_hash'] = block['source_hash']
    tree = markup(ir)
    assert tree.by_id('item').get('class') == 'list-literal-marker'
    assert text in ''.join(tree.by_id('item').itertext())
    assert tree.by_id('item2').get('class') != 'list-literal-marker'


def test_recognition_helpers_use_the_same_margin_as_original_comparison():
    ir = reader_fixture()
    block = next(block for block in ir['source_revision']['blocks'] if block['id'] == 'code')
    block['attributes'].update(comparison_asset_id='figure_png', comparison_scope='page')
    block['source_hash'] = block_hash(block, ir['source_revision']['protected_atoms'])
    next(row for row in ir['translation_revision']['results'] if row['block_id'] == 'code')['source_hash'] = block['source_hash']
    tree = markup(ir)
    code = tree.by_id('code')
    assert not code.findall('.//details')
    margin = tree.parents[code].find('./aside[@class="reader-notes"]')
    assert '识别文字' in ''.join(margin.itertext())
    assert '查看原文' in ''.join(margin.itertext())


def test_reader_v5_is_separate_and_does_not_change_frozen_template_assets(tmp_path):
    for name in ['reader-v1', 'reader-v2', 'reader-v3', 'reader-v4']:
        template = get_template(name)
        assert digest(Path(template['css_path']).read_bytes()) == template['css_sha256']
        assert digest(Path(template['js_path']).read_bytes()) == template['js_sha256']
    template = get_template('reader-v5')
    assert template['version'] == '5'
    ir = reader_fixture()
    ir = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v5')
    Publisher().build(ir, Path('tests'), tmp_path / 'bundle', include_source=True)
    single = export_single_html(tmp_path / 'bundle', tmp_path / 'reader.html', include_source=True).read_text()
    assert '<script src=' not in single
    assert 'reader-notes' in single and 'class="title-metadata"' in single


def test_reader_v4_keeps_existing_markup():
    tree = markup(reader_fixture('reader-v4'))
    assert tree.root.find('.//aside[@class="toc"]//ol') is not None
    assert tree.ancestor(tree.by_id('authors'), 'header') is None
    assert tree.parents[tree.by_id('item')] is not tree.parents[tree.by_id('item2')]
    assert tree.by_id('p1').findall('.//details')
