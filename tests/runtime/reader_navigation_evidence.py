"""Generate current reader fixtures, or serve them with the online artifact route.

Run from the repository root with PYTHONPATH=src and the locked test environment.
Outputs must be a new directory under the caller's temporary evidence folder.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests/unit')]


def long_toc_fixture(assets):
    from test_parser_semantics import document, layout, parse
    from test_semantic_consumers import render_snapshot

    sections = ''.join(
        f'<h{index % 6 + 1}>Section {index + 1}: Long English chapter title for accessible navigation, multilingual typography and nested document structure</h{index % 6 + 1}>'
        f'<p>Readable evidence for section {index + 1}.</p>'
        for index in range(42))
    source = parse(document(layout('Complex-Block', sections)), assets)['source_revision']
    source['language'] = 'en'
    for block in source['blocks']:
        block['language'] = 'en'
    fixture = render_snapshot(source)
    results = {result['block_id']: result for result in fixture['translation_revision']['results']}
    for index, block in enumerate(block for block in source['blocks'] if block['kind'] == 'heading' and block['id'] != source['title_block_id']):
        results[block['id']].update(status='translated', target_inline=[{
            'type': 'text', 'text': f'第 {index + 1} 节：面向移动阅读的长中文标题、双语目录层级和复杂文档章节定位验证',
        }])
    return fixture


def generate(root, *, long_only=False):
    from test_reader_sidenotes import sidenote_fixture
    from test_reader_theme import typography_fixture
    from packages.editorial.drafts import render_input
    from packages.publisher import Publisher, export_single_html, export_bundle, verify_artifact

    root.mkdir(parents=True, exist_ok=False)
    for version in (['long'] if long_only else ['3.0', '4.0', 'long']):
        folder = root / version
        assets = folder / 'assets-input'
        assets.mkdir(parents=True)
        fixture = sidenote_fixture() if version == '3.0' else long_toc_fixture(assets) if version == 'long' else typography_fixture(assets)
        source, translation = fixture['source_revision'], fixture['translation_revision']
        heading = next(block for block in source['blocks'] if block['kind'] == 'heading' and block['id'] != source['title_block_id'])
        result = next(result for result in translation['results'] if result['block_id'] == heading['id'])
        if version != 'long':
            result.update(status='translated', target_inline=[{'type': 'text', 'text': '阅读偏好与章节导航'}])
        ir = render_input(fixture['document']['id'], source, translation, 'reader-v14')
        Publisher().build(ir, ROOT / 'tests' if version == '3.0' else assets, folder / 'published', include_source=True)
        export_single_html(folder / 'published', folder / 'single.html', include_source=False)
        export_bundle(folder / 'published', folder / 'bundle.zip', include_source=False)
        with zipfile.ZipFile(folder / 'bundle.zip') as bundle:
            bundle.extractall(folder / 'bundle')
        verify_artifact(folder / 'published')
        verify_artifact(folder / 'bundle')
        (folder / 'fixture.json').write_text(json.dumps({
            'document_id': ir['document']['id'], 'heading_id': heading['id'], 'template_id': 'reader-v14',
            'heading_ids': [block['id'] for block in source['blocks'] if block['kind'] == 'heading' and block['id'] != source['title_block_id']],
        }), 'utf-8')


class ArtifactRoutes(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        for version in ['3.0', '4.0', 'long']:
            path = path.replace(f'/artifacts/{version}/', f'/{version}/published/', 1)
        return super().translate_path(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--serve', type=int, metavar='PORT', help='Serve existing evidence on loopback instead of generating it')
    parser.add_argument('--long-only', action='store_true', help='Generate only the 42-section, six-level mobile outline fixture')
    args = parser.parse_args()
    if args.serve:
        if not args.output.is_dir():
            parser.error('Evidence directory does not exist')
        ThreadingHTTPServer(('127.0.0.1', args.serve), partial(ArtifactRoutes, directory=str(args.output.resolve()))).serve_forever()
    else:
        generate(args.output.resolve(), long_only=args.long_only)
