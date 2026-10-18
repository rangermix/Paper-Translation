"""Online navigation is versioned; offline exports and old readers stay independent."""
from copy import deepcopy
from pathlib import Path
import zipfile

import pytest
from lxml import html

from packages.editorial.drafts import render_input
from packages.ir import digest
from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact
from packages.publisher.renderer import render_html
from test_reader_sidenotes import sidenote_fixture
from test_reader_v11 import rich_sidenote_fixture


def navigation_fixture(tmp_path, version='3.0'):
    fixture = sidenote_fixture() if version == '3.0' else rich_sidenote_fixture(tmp_path)
    source, translation = fixture['source_revision'], fixture['translation_revision']
    heading = next(block for block in source['blocks'] if block['kind'] == 'heading' and block['id'] != source['title_block_id'])
    result = next(result for result in translation['results'] if result['block_id'] == heading['id'])
    result['status'] = 'translated'
    result['target_inline'] = [{'type': 'text', 'text': '中文章节 <script>只是文本</script>'}]
    return render_input(fixture['document']['id'], source, translation, 'reader-v14')


@pytest.mark.parametrize('version', ['3.0', '4.0'])
def test_navigation_keeps_content_and_anchors_without_retranslation(tmp_path, version):
    ir = navigation_fixture(tmp_path, version)
    before = deepcopy(ir)
    paths = {asset['id']: asset['storage_key'] for asset in ir['source_revision']['assets']}
    new = html.fromstring(render_html(ir, paths))
    old_ir = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v13')
    old = html.fromstring(render_html(old_ir, paths))
    assert new.xpath('//a[@data-return-document]/@href') == ['/#/documents/' + ir['document']['id']]
    assert new.xpath('//a[@data-return-search][@hidden]')
    assert not old.xpath('//*[@data-online-reader]')
    assert '中文章节 <script>只是文本</script> / ' in ''.join(new.xpath('//nav[@class="toc-sections"]')[0].itertext())
    assert not new.xpath('//nav[@class="toc-sections"]//script')
    assert new.xpath('//nav[@class="toc-sections"]//a/@href') == old.xpath('//nav[@class="toc-sections"]//a/@href')
    for selector in ('//header', '//article'):
        assert html.tostring(new.xpath(selector)[0]) == html.tostring(old.xpath(selector)[0])
    assert ir == before


@pytest.mark.parametrize('version', ['3.0', '4.0'])
@pytest.mark.parametrize('state', ['fallback', 'unresolved', 'retained', 'same_source'])
def test_toc_does_not_invent_translation_for_source_only_headings(tmp_path, version, state):
    from packages.ir.retention import original_only_blocks
    from test_reader_sidenotes import refresh, set_inline

    ir = navigation_fixture(tmp_path, version)
    source = ir['source_revision']
    retained = original_only_blocks(source)
    if state == 'retained' and not any(block['kind'] == 'heading' and block['id'] in retained for block in source['blocks']):
        # The schema-3 fixture has bibliography entries but no heading. Supply
        # an explicit printed heading so retention is supported by source facts.
        heading = next(block for block in source['blocks'] if block['kind'] == 'heading' and block['id'] != source['title_block_id'])
        set_inline(ir, heading['id'], [{'type': 'text', 'text': 'References'}])
        refresh(ir)
        retained = original_only_blocks(source)
    heading = next(block for block in source['blocks']
                   if block['kind'] == 'heading' and block['id'] != source['title_block_id']
                   and (state != 'retained' or block['id'] in retained))
    result = next(result for result in ir['translation_revision']['results'] if result['block_id'] == heading['id'])
    result.update(target_inline=[], review_state='not_reviewed', review_record=None)
    if state == 'same_source':
        result.update(status='translated', target_inline=deepcopy(heading['source_inline']))
    elif state == 'retained':
        result.update(status='retained', reason=retained[heading['id']])
    elif state == 'unresolved':
        ir['render']['mode'] = 'draft'
        result.update(status='unresolved')
    else:
        result.update(status='fallback', reason='translation_unavailable', fallback={'mode': 'source_text'})
    before = deepcopy(ir)
    tree = html.fromstring(render_html(ir, {asset['id']: asset['storage_key'] for asset in source['assets']}))
    links = tree.xpath('//nav[@class="toc-sections"]//a[@href=$anchor]', anchor='#b-' + heading['id'])
    assert len(links) == 1
    assert links[0].text_content() == heading['normalized_text'].strip()
    assert ir == before


@pytest.mark.parametrize('version', ['3.0', '4.0'])
def test_empty_target_cannot_be_published_as_a_translated_heading(tmp_path, version):
    ir = navigation_fixture(tmp_path, version)
    result = next(result for result in ir['translation_revision']['results']
                  if result['target_inline'] == [{'type': 'text', 'text': '中文章节 <script>只是文本</script>'}])
    result['target_inline'] = []
    with pytest.raises(ValueError, match='empty translation'):
        render_html(ir, {asset['id']: asset['storage_key'] for asset in ir['source_revision']['assets']})


@pytest.mark.parametrize('include_source', [False, True])
def test_offline_exports_remove_return_links_without_changing_published_files(tmp_path, include_source):
    ir = navigation_fixture(tmp_path)
    published = tmp_path / 'published'
    manifest = Publisher().build(ir, Path('tests'), published, include_source=True)
    original = {entry['path']: entry['sha256'] for entry in manifest['files']}
    single = export_single_html(published, tmp_path / 'single.html', include_source=include_source).read_text('utf-8')
    export_bundle(published, tmp_path / 'bundle.zip', include_source=include_source)
    with zipfile.ZipFile(tmp_path / 'bundle.zip') as archive:
        archive.extractall(tmp_path / 'bundle')
    verify_artifact(tmp_path / 'bundle')
    for text in [single, (tmp_path / 'bundle/index.html').read_text('utf-8')]:
        tree = html.fromstring(text, parser=html.HTMLParser(huge_tree=True))
        assert not tree.xpath('//nav[@data-online-reader]')
        assert not tree.xpath('//a[starts-with(@href,"/#/")]')
        assert tree.xpath('//article') and tree.xpath('//select[@data-theme-select]')
        assert tree.xpath('//nav[@class="toc-sections"]//a')
        assert bool(tree.xpath('//a[@download]')) == include_source
    assert all(digest((published / name).read_bytes()) == sha for name, sha in original.items())


def test_v13_resources_and_its_content_renderer_remain_frozen():
    from packages.paths import ROOT
    hashes = {
        'src/packages/publisher/reader_v12.py': '89f01f930d462d19e15a198cf1a977137f2e43bce2f1d2ea8181c095fa4d2fa5',
        'src/packages/publisher/reader_v13.py': 'b4654375ca5402ba4fc5c472132e92c0526f5941a4c9b4e1d2e6e3f75b90c6b0',
        'src/packages/templates/reader-v13.css': 'c8fb66b25404f4e190fe8f0bc595184a40b3ef1cff9d9e8fab88c66187f4a5bf',
        'src/packages/templates/reader-v13.js': 'd0434e374b27651c23c71b2bc09aeb0582833fa49792a7f2ccedd3be2dc1c046',
    }
    for name, expected in hashes.items():
        # Git freezes LF resources; Windows checkouts may materialize CRLF for Python.
        assert digest((ROOT / name).read_bytes().replace(b'\r\n', b'\n')) == expected
