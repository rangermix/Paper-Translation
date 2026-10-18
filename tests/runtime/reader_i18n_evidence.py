"""Generate offline, authored reader-v15 localization fixtures without model calls.

Run from the repository root with PYTHONPATH=src and locked test dependencies.
Each output must be a new directory beneath the caller's temporary evidence path.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests/unit')]

LOCALES = ('zh-Hans', 'zh-Hant', 'en', 'ja', 'ko', 'fr', 'de', 'es')
SOURCE_TITLE = '原文 主题 返回文档 · literal UI words in document content'
TARGET_TITLE = '译文 主題 Theme テーマ 테마 Thème Design Tema · <script>literal</script> · $&'


def generate(root):
    from test_reader_sidenotes import refresh, set_inline, sidenote_fixture
    from test_reader_v11 import rich_sidenote_fixture
    from packages.editorial.drafts import render_input
    from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact

    root.mkdir(parents=True, exist_ok=False)
    for version in ('3.0', '4.0'):
        for locale in LOCALES:
            folder = root / f'{version}-{locale}'
            assets = folder / 'assets-input'
            assets.mkdir(parents=True)
            fixture = sidenote_fixture() if version == '3.0' else rich_sidenote_fixture(assets)
            source, translation = fixture['source_revision'], fixture['translation_revision']
            title_id = source['title_block_id']
            set_inline(fixture, title_id, [{'type': 'text', 'text': SOURCE_TITLE}])
            refresh(fixture)
            title_result = next(row for row in translation['results'] if row['block_id'] == title_id)
            title_result['target_inline'] = [{'type': 'text', 'text': TARGET_TITLE}]
            translation.update(target_language=locale, title=TARGET_TITLE)
            ir = render_input(fixture['document']['id'], source, translation, 'reader-v15')
            Publisher().build(ir, ROOT / 'tests' if version == '3.0' else assets,
                              folder / 'published', include_source=True)
            export_single_html(folder / 'published', folder / 'single.html', include_source=False)
            export_bundle(folder / 'published', folder / 'bundle.zip', include_source=False)
            with zipfile.ZipFile(folder / 'bundle.zip') as bundle:
                bundle.extractall(folder / 'bundle')
            verify_artifact(folder / 'published')
            verify_artifact(folder / 'bundle')
            (folder / 'fixture.json').write_text(json.dumps({
                'document_id': ir['document']['id'], 'target_language': locale,
                'source_title': SOURCE_TITLE, 'target_title': TARGET_TITLE,
                'template_id': 'reader-v15', 'schema_version': version,
            }, ensure_ascii=False), 'utf-8')


class ArtifactRoutes(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?', 1)[0] == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def translate_path(self, path):
        for version in ('3.0', '4.0'):
            for locale in LOCALES:
                key = f'{version}-{locale}'
                path = path.replace(f'/artifacts/{key}/', f'/{key}/published/', 1)
        return super().translate_path(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--serve', type=int, metavar='PORT', help='Serve existing fixtures on loopback')
    args = parser.parse_args()
    if args.serve:
        if not args.output.is_dir():
            parser.error('Evidence directory does not exist')
        ThreadingHTTPServer(('127.0.0.1', args.serve),
                            partial(ArtifactRoutes, directory=str(args.output.resolve()))).serve_forever()
    else:
        generate(args.output.resolve())
