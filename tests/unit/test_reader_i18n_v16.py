"""Cross-module product notices are UI; model/PDF evidence remains literal data."""
import ast
from copy import deepcopy
import re
import zipfile

import pytest
from lxml import html

from packages.editorial.drafts import render_input
from packages.ir import digest
from packages.paths import ROOT
from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact
from packages.publisher.reader_locales_v16 import (MESSAGES, SUPPORTED_READER_LOCALES,
    _ROWS, _DIAGNOSTIC_ROWS, _PARSER_ROWS, _ANNOTATION_ROWS, _AUTHORED_ANNOTATIONS,
    _ANNOTATION_LABELS, translate, translate_diagnostic, translate_annotation, annotation_label)
from packages.publisher.renderer import render_html
from test_reader_i18n import localized_fixture, html_literals
from test_reader_sidenotes import refresh


def authored_parser_notices():
    """Follow warning-producing helpers, not merely renderer translation calls."""
    found = set()
    for filename in ('rich_ir.py', 'source_adapter.py'):
        tree = ast.parse((ROOT / 'src/packages/parsers' / filename).read_text('utf-8'))
        constants = {node.targets[0].id: node.value.value for node in tree.body
                     if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                     and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'append' and 'warnings' in ast.unparse(node.func.value)
                    and node.args):
                continue
            value = node.args[0]
            if isinstance(value, ast.Name) and value.id in constants:
                found.add(constants[value.id])
            elif isinstance(value, ast.JoinedStr):
                # The current warning has one page argument. Adding a different
                # dynamic shape requires this producer audit to be expanded.
                arguments = [part for part in value.values if isinstance(part, ast.FormattedValue)]
                assert len(arguments) == 1 and 'page' in ast.unparse(arguments[0].value)
                found.add(''.join(part.value if isinstance(part, ast.Constant) else '{page}' for part in value.values))
            else:
                found.update(part.value for part in ast.walk(value)
                             if isinstance(part, ast.Constant) and isinstance(part.value, str)
                             and re.search(r'[\u3400-\u9fff]', part.value))
    return found


def test_parser_authored_notice_producers_are_fully_catalogued():
    required = authored_parser_notices()
    assert len(required) == 21
    all_rows = _ROWS + _DIAGNOSTIC_ROWS + _PARSER_ROWS + _ANNOTATION_ROWS
    assert len({row[0] for row in all_rows}) == len(all_rows)
    for row in all_rows:
        assert len(row) == len(SUPPORTED_READER_LOCALES)
        expected = set(re.findall(r'\{[A-Za-z][A-Za-z0-9_]*\}', row[0]))
        assert all(value and set(re.findall(r'\{[A-Za-z][A-Za-z0-9_]*\}', value)) == expected for value in row)
    for locale in SUPPORTED_READER_LOCALES:
        assert required <= MESSAGES[locale].keys()
        for key in required:
            original = key.format(page=7)
            assert translate_diagnostic(locale, original) == translate(locale, key, page=7)
    # Baseline excerpts inside warning values must not allow accidental blanket
    # replacement of arbitrary text or another producer's technical diagnostics.
    unknown = '此处是用户原文：保留原PDF图像；图内文字未翻译。'
    assert translate_diagnostic('en', unknown) == unknown


@pytest.mark.parametrize('locale', SUPPORTED_READER_LOCALES)
def test_parser_notices_keep_recorded_review_reasons_verbatim(locale):
    reason = '目录 原文 <script>literal</script> {page} 已记录核对说明：second $&'
    for key in authored_parser_notices():
        original = key.format(page=2)
        expected = translate(locale, key, page=2)
        rendered = translate_diagnostic(locale, original + ' 已记录核对说明：' + reason)
        assert rendered.startswith(expected)
        assert rendered.endswith(reason)


def test_authored_annotations_require_matching_kind_and_exact_value():
    authored = set()
    kinds = set()
    for file in (ROOT / 'src/packages/parsers').glob('*.py'):
        for node in ast.walk(ast.parse(file.read_text('utf-8'))):
            if not isinstance(node, ast.Dict):
                continue
            fields = {key.value: value for key, value in zip(node.keys, node.values)
                      if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            if {'kind', 'value', 'output_path'} <= fields.keys():
                kinds.update(part.value for part in ast.walk(fields['kind'])
                             if isinstance(part, ast.Constant) and isinstance(part.value, str)
                             and part.value != 'chemical-block')
                if all(isinstance(fields[key], ast.Constant) and isinstance(fields[key].value, str)
                       for key in ('kind', 'value')):
                    authored.add((fields['kind'].value, fields['value'].value))
    assert authored == _AUTHORED_ANNOTATIONS.keys()
    assert kinds == _ANNOTATION_LABELS.keys()
    for locale in SUPPORTED_READER_LOCALES:
        for kind, key in _ANNOTATION_LABELS.items():
            assert annotation_label(locale, kind) == MESSAGES[locale][key]
        assert annotation_label(locale, 'unrecognized-kind') == MESSAGES[locale]['辅助信息']
    for (kind, value), key in _AUTHORED_ANNOTATIONS.items():
        annotation = {'kind': kind, 'value': value}
        for locale in SUPPORTED_READER_LOCALES:
            assert translate_annotation(locale, annotation) == MESSAGES[locale][key]
            assert translate_annotation(locale, {'kind': 'code_transcription', 'value': value}) == value
            assert translate_annotation(locale, {'kind': kind, 'value': value + ' model details'}) == value + ' model details'


def notice_fixture(tmp_path, locale, version='4.0'):
    ir = localized_fixture(tmp_path, locale, version)
    block = next(block for block in ir['source_revision']['blocks'] if block['kind'] == 'paragraph')
    block['warnings'] = [key.format(page=3) for key in sorted(authored_parser_notices())]
    if version == '4.0':
        block['attributes']['annotations'] = [
            {'kind': kind, 'value': value, 'output_path': '/audit'} for kind, value in _AUTHORED_ANNOTATIONS
        ] + [{'kind': 'code_transcription', 'value': '保留原PDF图像；图内文字未翻译。 <code>original</code>', 'output_path': '/audit'},
             {'kind': 'unrecognized-kind', 'value': '原文 evidence', 'output_path': '/audit'}]
    refresh(ir)
    return render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], 'reader-v16')


@pytest.mark.parametrize('locale', SUPPORTED_READER_LOCALES)
@pytest.mark.parametrize('version', ['3.0', '4.0'])
def test_rendered_notices_follow_target_without_touching_saved_evidence(tmp_path, locale, version):
    ir = notice_fixture(tmp_path, locale, version)
    before = deepcopy(ir)
    paths = {asset['id']: asset['storage_key'] for asset in ir['source_revision']['assets']}
    tree = html.fromstring(render_html(ir, paths))
    visible_notes = tree.xpath('//details[@class="block-notes"]//p/text()')
    for key in authored_parser_notices():
        assert translate(locale, key, page=3) in visible_notes
    if version == '4.0':
        annotations = tree.xpath('//details[@class="parser-annotation"]//pre/text()')
        for key in _AUTHORED_ANNOTATIONS.values():
            assert MESSAGES[locale][key] in annotations
        assert '保留原PDF图像；图内文字未翻译。 <code>original</code>' in annotations
        assert tree.xpath('//details[@data-annotation-kind="code_transcription"]/pre/@lang') == ['und']
        assert tree.xpath('//details[@data-annotation-kind="decoder_limit"]/pre/@lang') == [locale]
        assert tree.xpath('//details[@data-annotation-kind="unrecognized-kind"]/summary/text()') == [MESSAGES[locale]['辅助信息']]
        assert tree.xpath('//details[@data-annotation-kind="unrecognized-kind"]/pre/text()') == ['原文 evidence']
        assert set(tree.xpath('//details[@class="parser-annotation"]/@lang')) == {locale}
    assert set(tree.xpath('//details[@class="block-notes"]/@lang')) == {locale}
    assert set(tree.xpath('//span[@class="label"]/@lang')) == {locale}
    assert tree.xpath('//div[@class="reference-entry"][@lang="en"]')
    assert ir == before


def test_fallback_heading_keeps_original_and_ui_language_boundaries(tmp_path):
    ir = notice_fixture(tmp_path, 'fr')
    heading = next(block for block in ir['source_revision']['blocks']
                   if block['kind'] == 'heading' and block['id'] != ir['source_revision']['title_block_id'])
    result = next(result for result in ir['translation_revision']['results'] if result['block_id'] == heading['id'])
    result.update(status='fallback', target_inline=[], reason='translation_unavailable',
                  review_state='not_reviewed', review_record=None, fallback={'mode': 'source_text'})
    paths = {asset['id']: asset['storage_key'] for asset in ir['source_revision']['assets']}
    tree = html.fromstring(render_html(ir, paths))
    target = tree.xpath('//*[@data-block-id=$block]//span[@class="zh-title"]', block=heading['id'])[0]
    assert target.xpath('./span/@lang') == ['en']
    assert target.xpath('./small[@class="fallback-label"]/@lang') == ['fr']
    assert target.xpath('./small/text()') == [MESSAGES['fr']['（原文，暂无译文）']]


@pytest.mark.parametrize('include_source', [False, True])
def test_new_notice_locales_survive_all_export_formats(tmp_path, include_source):
    ir = notice_fixture(tmp_path, 'ja')
    published = tmp_path / 'published'
    manifest = Publisher().build(ir, tmp_path, published, include_source=True)
    before = {entry['path']: entry['sha256'] for entry in manifest['files']}
    single = export_single_html(published, tmp_path / 'single.html', include_source=include_source)
    bundle = export_bundle(published, tmp_path / 'bundle.zip', include_source=include_source)
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(tmp_path / 'bundle')
    verify_artifact(tmp_path / 'bundle')
    for file in (single, tmp_path / 'bundle/index.html'):
        tree = html.fromstring(file.read_bytes(), parser=html.HTMLParser(huge_tree=True))
        assert tree.get('lang') == 'ja'
        notes = tree.xpath('//details[@class="block-notes"]//p/text()')
        assert MESSAGES['ja']['表格结构未恢复；原图和响应证据完整保留。'] in notes
        assert not tree.xpath('//nav[@data-online-reader]')
        assert bool(tree.xpath('//a[@download]')) == include_source
    assert all(digest((published / path).read_bytes()) == sha for path, sha in before.items())


def test_v16_literals_stay_catalogued_and_v15_resources_stay_frozen():
    identities = {'MiSans', 'Noto Sans Simplified Chinese', 'Fira Code', 'Cascadia Code',
                  'Source Code Pro', 'IBM Plex Mono', 'Consolas', 'Menlo', 'A−', 'A＋'}
    assert html_literals((ROOT / 'src/packages/publisher/reader_v16.py').read_text('utf-8')) <= identities
    for filename, sha in {
        'src/packages/publisher/reader_v15.py': 'ca64cb6bddc00de35343eea0af5dcf7acb234241114418b95a82c7692fed09c1',
        'src/packages/publisher/reader_locales.py': 'ab3b2da9feb6d253de28ae9b92035ed90b32961b18abc2c3f90e1250990fb186',
        'src/packages/templates/reader-v15.js': 'a26fe3649ec4808f13941fd12298cabe01773aaa0ee849591e0c14112418d0b3',
        'src/packages/templates/reader-v15.css': '33040019fbdea0846e2527bbd266fd4c1b387d9539e041d954b2a4c46bff6f69',
    }.items():
        assert digest((ROOT / filename).read_bytes().replace(b'\r\n', b'\n')) == sha
