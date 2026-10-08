"""Theme controls must not change stored content or historical reader output."""
from copy import deepcopy

import pytest
from lxml import html

from packages.editorial.drafts import render_input
from packages.publisher.renderer import render_html
from test_reader_sidenotes import sidenote_fixture
from test_reader_v11 import rich_sidenote_fixture


def typography_fixture(tmp_path):
    from test_parser_semantics import parse, document, layout
    from test_semantic_consumers import render_snapshot
    raw = document(layout('Complex-Block',
        '<h2>Reading preferences</h2><p>Adjust the reading font, code font and line spacing. '
        'Inline code: <code>result = translate(document)</code>.</p>'
        '<pre class="language-python">def translate(document):\n    return document.text\n</pre>'))
    source = parse(raw, tmp_path)['source_revision']
    source['language'] = 'en'
    for block in source['blocks']:
        block['language'] = 'en'
    return render_snapshot(source)


@pytest.mark.parametrize('version', ['3.0', '4.0'])
def test_theme_reader_preserves_content_and_input(tmp_path, version):
    ir = rich_sidenote_fixture(tmp_path) if version == '4.0' else sidenote_fixture()
    ir = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v13')
    before = deepcopy(ir)
    paths = {a['id']: a['storage_key'] for a in ir['source_revision']['assets']}
    new = html.fromstring(render_html(ir, paths))
    old_ir = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v12')
    old = html.fromstring(render_html(old_ir, paths))
    assert old.xpath('//button[@data-action="theme"]')
    assert not old.xpath('//select[@data-theme-select]')
    assert not new.xpath('//button[@data-action="theme"]')
    assert new.xpath('//label[select[@data-theme-select]]/text()') == ['主题']
    assert new.xpath('//select[@data-theme-select]/option/@value') == ['system', 'light', 'dark']
    assert new.xpath('//select[@data-theme-select]/option/text()') == ['跟随系统', '浅色', '深色']
    assert new.xpath('//select[@data-font-select]/option[@value="default"]/text()') == ['默认（MiSans）']
    assert new.xpath('//select[@data-code-font-select]/option/@value') == [
        'default', 'fira-code', 'cascadia-code', 'source-code-pro', 'ibm-plex-mono', 'consolas', 'menlo', 'monospace']
    assert new.xpath('//select[@data-code-font-select]/option[@value="default"]/text()') == ['JetBrains Mono（默认）']
    assert new.xpath('//select[@data-line-height-select]/option/@value') == ['1.4', '1.72', '2', '2.4']
    assert new.xpath('//select[@data-line-height-select]/option[@selected]/@value') == ['1.72']
    for selector in ('//header', '//article'):
        assert html.tostring(new.xpath(selector)[0]) == html.tostring(old.xpath(selector)[0])
    assert ir == before


@pytest.mark.parametrize('include_source', [False, True])
def test_fonts_are_pinned_and_embedded_in_both_exports(tmp_path, include_source):
    import base64
    import zipfile
    from pathlib import Path
    from packages.ir import digest
    from packages.publisher import Publisher, export_single_html, export_bundle, verify_artifact
    ir = sidenote_fixture()
    ir = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v13')
    artifact = tmp_path / 'published'
    manifest = Publisher().build(ir, Path('tests'), artifact, include_source=True)
    original = {entry['path']: entry['sha256'] for entry in manifest['files']}
    fonts = [entry for entry in manifest['files'] if entry['media_type'] == 'font/woff2']
    assert len(fonts) == 6
    single = export_single_html(artifact, tmp_path / 'single.html', include_source=include_source).read_text('utf-8')
    export_bundle(artifact, tmp_path / 'bundle.zip', include_source=include_source)
    with zipfile.ZipFile(tmp_path / 'bundle.zip') as bundle:
        bundle.extractall(tmp_path / 'bundle')
    verify_artifact(tmp_path / 'bundle')
    css = (tmp_path / 'bundle/reader.css').read_text('utf-8')
    for font in fonts:
        data_url = 'data:font/woff2;base64,' + base64.b64encode((artifact / font['path']).read_bytes()).decode('ascii')
        assert data_url in css and data_url in single
        assert 'url("' + font['path'] + '")' not in css
    assert "font-src 'self' data:" in single
    assert 'MiSans Font Intellectual Property License Agreement' in single
    assert 'SIL OPEN FONT LICENSE Version 1.1' in single
    assert all(digest((artifact / name).read_bytes()) == sha for name, sha in original.items())


def test_font_hint_update_does_not_replace_paper_text():
    from test_reader_sidenotes import set_inline, refresh
    ir = sidenote_fixture()
    text = '使用本机字体；未安装时使用备用字体。'
    set_inline(ir, 'p1', [{'type': 'text', 'text': text}])
    refresh(ir)
    ir = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v13')
    tree = html.fromstring(render_html(ir, {a['id']: a['storage_key'] for a in ir['source_revision']['assets']}))
    assert ''.join(tree.get_element_by_id('b-p1').itertext()).count(text) == 2
