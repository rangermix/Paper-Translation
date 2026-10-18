"""Artifact UI language is part of publication, never a browser preference."""
import ast
from copy import deepcopy
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import zipfile

import pytest
from lxml import html

from packages.editorial.drafts import QUALITY_MESSAGES, render_input
from packages.ir import digest
from packages.paths import ROOT
from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact
from packages.publisher.reader_locales import (MESSAGES, SUPPORTED_READER_LOCALES, _ROWS, _DIAGNOSTIC_ROWS,
    reader_messages_json, resolve_reader_locale, translate, translate_diagnostic)
from packages.publisher.renderer import render_html
from test_reader_navigation import navigation_fixture
from test_reader_sidenotes import refresh, set_inline


@pytest.mark.parametrize(('target', 'expected'), [
    ('zh', 'zh-Hans'), ('zh-CN', 'zh-Hans'), ('zh-SG', 'zh-Hans'),
    ('zh-TW', 'zh-Hant'), ('zh-HK', 'zh-Hant'), ('zh-MO', 'zh-Hant'),
    ('zh-Hans-TW', 'zh-Hans'), ('zh-Hant-CN', 'zh-Hant'),
    ('zh-x-hant', 'zh-Hans'), ('en-AU', 'en'), ('ja-JP', 'ja'),
    ('ko-KR', 'ko'), ('fr-CA', 'fr'), ('de-AT', 'de'), ('es-MX', 'es'),
    ('pt-BR', 'en'), ('ar', 'en'), (None, 'en'),
])
def test_reader_locale_resolution(target, expected):
    assert resolve_reader_locale(target) == expected


def test_catalogs_cover_every_authored_python_and_javascript_message():
    rows = _ROWS + _DIAGNOSTIC_ROWS
    assert len({row[0] for row in rows}) == len(rows)
    placeholders = lambda value: set(re.findall(r'\{[A-Za-z][A-Za-z0-9_]*\}', value))
    for row in rows:
        assert len(row) == len(SUPPORTED_READER_LOCALES)
        for value in row:
            assert value.strip()
            assert placeholders(value) == placeholders(row[0]), row[0]
    required = set(QUALITY_MESSAGES.values())
    tree = ast.parse((ROOT / 'src/packages/publisher/reader_v15.py').read_text('utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 't':
            if node.args:
                required.update(child.value for child in ast.walk(node.args[0])
                                if isinstance(child, ast.Constant) and isinstance(child.value, str)
                                and re.search(r'[\u3400-\u9fff]', child.value))
    javascript = (ROOT / 'src/packages/templates/reader-v15.js').read_text('utf-8')
    required.update(re.findall(r"readerTranslate\('([^']+)'", javascript))
    # Includes conditional source-key branches (bundled/local font tooltips).
    required.update(re.findall(r"['\"]([^'\"\n]*[\u3400-\u9fff][^'\"\n]*)['\"]", javascript))
    for locale in SUPPORTED_READER_LOCALES:
        assert required <= MESSAGES[locale].keys(), (locale, required - MESSAGES[locale].keys())


def html_literals(source):
    """Audit authored template fragments; interpolated content is handled separately."""
    found = set()
    class TextLiterals(HTMLParser):
        def handle_data(self, text):
            text = text.replace('i18nvalue', '')
            if any(character.isalpha() for character in text):
                found.add(text.strip())

        def handle_starttag(self, tag, attrs):
            for name, value in attrs:
                if name in {'alt', 'title', 'aria-label', 'aria-description', 'placeholder'} and value:
                    literal = value.replace('i18nvalue', '')
                    if literal.strip():
                        found.add(literal)

    syntax = ast.parse(source)
    format_pieces = {id(child) for parent in ast.walk(syntax) if isinstance(parent, ast.JoinedStr)
                     for child in parent.values if isinstance(child, ast.Constant)}
    for node in ast.walk(syntax):
        value = None
        if isinstance(node, ast.JoinedStr):
            value = ''.join(child.value if isinstance(child, ast.Constant) else 'i18nvalue' for child in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in format_pieces:
            value = node.value
        if value and '<' in value:
            # Concatenated strings can begin halfway through an opening tag.
            # Discard that attribute fragment, but audit text after its `>`.
            prefix = value.split('<', 1)[0]
            if '>' in prefix and ('=' in prefix or prefix.startswith(('"', "'"))):
                value = value.split('>', 1)[1]
            TextLiterals().feed(value)
    return found


def test_reader_authored_html_cannot_bypass_i18n_with_english_or_chinese_literals():
    assert html_literals('page = \'<button aria-label="Close">关闭</button><p>Ready</p>\'') == {'Close', '关闭', 'Ready'}
    source = (ROOT / 'src/packages/publisher/reader_v15.py').read_text('utf-8')
    # Font identities and standard size-control glyphs are the only authored text
    # permitted outside the catalog. Never exempt entire regions or ASCII text.
    identities = {'MiSans', 'Noto Sans Simplified Chinese', 'Fira Code', 'Cascadia Code',
                  'Source Code Pro', 'IBM Plex Mono', 'Consolas', 'Menlo', 'A−', 'A＋'}
    assert html_literals(source) <= identities


def test_interpolation_and_inert_payload_do_not_interpret_text(monkeypatch):
    literal = '</script><img src=x onerror=alert(1)> {label} $& \\1'
    assert translate('en', '脚注 · {label}', label=literal) == 'Footnote · ' + literal
    monkeypatch.setitem(MESSAGES['en'], '安全测试', literal + '\u2028\u2029')
    encoded = reader_messages_json('en')
    assert '<' not in encoded and '>' not in encoded and '\u2028' not in encoded
    assert json.loads(encoded)['messages']['安全测试'] == literal + '\u2028\u2029'


def test_known_diagnostics_translate_without_rewriting_evidence_or_review_notes():
    user_reason = '目录 原文 <script>evidence</script> {notice} $&'
    known = QUALITY_MESSAGES['NUMBER_MISMATCH']
    for locale in SUPPORTED_READER_LOCALES:
        assert translate_diagnostic(locale, known) == MESSAGES[locale][known]
        rendered = translate_diagnostic(locale, known + ' 已记录核对说明：' + user_reason)
        assert rendered.endswith(user_reason)
        assert rendered.startswith(MESSAGES[locale][known])
        assert translate_diagnostic(locale, user_reason) == user_reason
        assert translate_diagnostic(locale, '第 7 页文字未完整提取') == translate(locale, '第 {page} 页文字未完整提取', page=7)


def localized_fixture(tmp_path, locale, version='3.0'):
    ir = navigation_fixture(tmp_path, version)
    ir['translation_revision']['target_language'] = locale
    # Source and target deliberately equal UI keys: only authored labels translate.
    heading = next(block for block in ir['source_revision']['blocks']
                   if block['kind'] == 'heading' and block['id'] != ir['source_revision']['title_block_id'])
    set_inline(ir, heading['id'], [{'type': 'text', 'text': '目录 原文 译文 <script>literal</script>'}])
    refresh(ir)
    return render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v15')


@pytest.mark.parametrize('version', ['3.0', '4.0'])
@pytest.mark.parametrize('locale', SUPPORTED_READER_LOCALES)
def test_rendered_controls_follow_translation_and_preserve_paper(tmp_path, version, locale):
    ir = localized_fixture(tmp_path, locale, version)
    before = deepcopy(ir)
    paths = {asset['id']: asset['storage_key'] for asset in ir['source_revision']['assets']}
    output = render_html(ir, paths, include_source=True)
    tree = html.fromstring(output)
    assert tree.get('lang') == locale
    assert tree.xpath('//nav[@class="toolbar"]/@aria-label') == [MESSAGES[locale]['阅读设置']]
    assert tree.xpath('//button[@data-action="both"]/text()') == [MESSAGES[locale]['双语']]
    assert tree.xpath('//a[@data-return-document]/text()') == [MESSAGES[locale]['返回文档']]
    assert json.loads(tree.get_element_by_id('reader-i18n-data').text)['locale'] == locale
    assert '目录 原文 译文 <script>literal</script>' in tree.xpath('//article')[0].text_content()
    assert not tree.xpath('//article//script')
    old_ir = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v14')
    old = html.fromstring(render_html(old_ir, paths, include_source=True))
    assert tree.xpath('//*[@data-block-id]/@id') == old.xpath('//*[@data-block-id]/@id')
    for selector in ('//*[@data-language="source"]', '//footer//pre'):
        def paper_texts(page):
            elements = deepcopy(page.xpath(selector))
            for element in elements:
                for label in element.xpath('.//span[@class="label"]'):
                    label.drop_tree()
            return [element.text_content() for element in elements]
        assert paper_texts(tree) == paper_texts(old)
    assert ir == before


@pytest.mark.parametrize('locale', SUPPORTED_READER_LOCALES)
@pytest.mark.parametrize('include_source', [False, True])
def test_exports_keep_artifact_language_and_immutable_publication(tmp_path, locale, include_source):
    ir = localized_fixture(tmp_path, locale)
    published = tmp_path / 'published'
    manifest = Publisher().build(ir, Path('tests'), published, include_source=True)
    before = {entry['path']: entry['sha256'] for entry in manifest['files']}
    single = export_single_html(published, tmp_path / 'single.html', include_source=include_source)
    archive = export_bundle(published, tmp_path / 'bundle.zip', include_source=include_source)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(tmp_path / 'bundle')
    verify_artifact(tmp_path / 'bundle')
    for file in (single, tmp_path / 'bundle/index.html'):
        tree = html.fromstring(file.read_bytes(), parser=html.HTMLParser(huge_tree=True))
        assert tree.get('lang') == locale
        assert tree.xpath('//button[@data-action="both"]/text()') == [MESSAGES[locale]['双语']]
        assert not tree.xpath('//nav[@data-online-reader]')
        assert bool(tree.xpath('//a[@download]')) == include_source
        assert not tree.xpath('//a[starts-with(@href,"/#/")]')
        assert json.loads(tree.get_element_by_id('reader-i18n-data').text)['messages'] == MESSAGES[locale]
    assert manifest['target_locale'] == locale
    assert all(digest((published / name).read_bytes()) == sha for name, sha in before.items())


def test_v14_resources_remain_frozen():
    for name, sha in {
        'src/packages/publisher/reader_v14.py': '97f3e41ac2dd7ed55586908059b2628a9cc33865de7115d702fad897c23ba4ad',
        'src/packages/templates/reader-v14.css': '33040019fbdea0846e2527bbd266fd4c1b387d9539e041d954b2a4c46bff6f69',
        'src/packages/templates/reader-v14.js': '6700da2b1467302652e935eb7327a7693aec8382ea5cdd0201b3384022f7550e',
    }.items():
        assert digest((ROOT / name).read_bytes().replace(b'\r\n', b'\n')) == sha


@pytest.mark.parametrize(('locale', 'ui_locale'), [('fr-CA', 'fr'), ('zh-Hant-HK', 'zh-Hant'), ('pt-BR', 'en')])
def test_fallback_and_regional_controls_keep_actual_document_language(tmp_path, locale, ui_locale):
    ir = localized_fixture(tmp_path, locale)
    paths = {asset['id']: asset['storage_key'] for asset in ir['source_revision']['assets']}
    tree = html.fromstring(render_html(ir, paths))
    assert tree.get('lang') == ui_locale
    assert tree.xpath('//header/h1/@lang') == [locale]
    assert tree.xpath('//div[@class="para zh"][@data-language="target"]/@lang')
    assert set(tree.xpath('//div[@class="para zh"][@data-language="target"]/@lang')) == {locale}
    assert ir['translation_revision']['target_language'] == locale


def test_export_missing_image_fallback_uses_frozen_localized_notice(tmp_path, monkeypatch):
    import packages.publisher.renderer as renderer
    ir = localized_fixture(tmp_path, 'fr-CA')
    original_renderer = renderer.render_html
    original_id = ir['source_revision']['original_asset_id']
    # Exercise the supported missing-comparison-image renderer path in an authored
    # fixture. The original PDF remains available until the export excludes it.
    monkeypatch.setattr(renderer, 'render_html', lambda ir, paths, **options:
                        original_renderer(ir, {original_id: paths[original_id]}, **options))
    published = tmp_path / 'published'
    Publisher().build(ir, Path('tests'), published, include_source=True)
    tree = html.fromstring((published / 'index.html').read_bytes())
    links = tree.xpath('//a[@data-original-reference]')
    assert links
    expected = links[0].get('data-missing-source-label')
    assert expected.startswith('Image de comparaison indisponible')
    monkeypatch.setitem(MESSAGES['fr'], '对照图暂不可用；本次导出未包含原 PDF。', 'CHANGED AFTER PUBLICATION')
    output = export_single_html(published, tmp_path / 'single.html', include_source=False)
    exported = html.fromstring(output.read_bytes(), parser=html.HTMLParser(huge_tree=True))
    assert not exported.xpath('//a[@data-original-reference]|//a[@download]')
    assert expected in exported.text_content()
    assert 'CHANGED AFTER PUBLICATION' not in exported.text_content()
