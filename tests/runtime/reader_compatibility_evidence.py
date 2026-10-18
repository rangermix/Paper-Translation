"""Generate fresh, version-correct evidence for conditional reader browser tests.

Run in the locked test image from the repository root. The output directory must
not exist. Fixtures are authored test data, never a deployed library or model call.
"""
import argparse
from pathlib import Path
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests/unit'), str(ROOT / 'tests/runtime')]


def build(ir, template_id, assets, folder):
    from packages.editorial.drafts import render_input
    from packages.ir import digest
    from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact
    from packages.templates.registry import get_template

    folder.mkdir(parents=True, exist_ok=False)
    selected = render_input(ir['document']['id'], ir['source_revision'], ir['translation_revision'], template_id)
    template = get_template(template_id)
    manifest = Publisher().build(selected, assets, folder / 'published', include_source=True)
    before = {entry['path']: entry['sha256'] for entry in manifest['files']}
    export_single_html(folder / 'published', folder / 'single.html', include_source=True)
    export_bundle(folder / 'published', folder / 'bundle.zip', include_source=True)
    with zipfile.ZipFile(folder / 'bundle.zip') as bundle:
        bundle.extractall(folder / 'bundle')
    verify_artifact(folder / 'published')
    verify_artifact(folder / 'bundle')
    assert all(digest((folder / 'published' / path).read_bytes()) == sha for path, sha in before.items())
    identity = {key: template[key] for key in ('id', 'css_path', 'css_sha256', 'js_path', 'js_sha256', 'renderer_version', 'renderer_sha256')}
    (folder / 'fixture.json').write_text(json.dumps({
        'template': identity, 'document_id': selected['document']['id'],
        'schema_version': selected['schema_version'], 'published_files': before,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


def generate(root):
    from test_reader_v5 import reader_fixture
    from test_reader_sidenotes import sidenote_fixture, table_reference_fixture, native_sidenote_fixture
    from test_reader_v11 import rich_sidenote_fixture
    from reader_navigation_evidence import generate as generate_navigation
    from packages.templates.registry import list_templates

    root.mkdir(parents=True, exist_ok=False)
    templates_before = list_templates()
    build(reader_fixture('reader-v5'), 'reader-v5', ROOT / 'tests', root / 'v5')
    build(reader_fixture('reader-v7'), 'reader-v7', ROOT / 'tests', root / 'v7')
    build(sidenote_fixture('reader-v9'), 'reader-v9', ROOT / 'tests', root / 'v9')
    build(table_reference_fixture(), 'reader-v9', ROOT / 'tests', root / 'v9-table')
    (root / 'v9/table.html').write_bytes((root / 'v9-table/single.html').read_bytes())
    native_assets = root / 'native-input'
    native_assets.mkdir()
    native, _ = native_sidenote_fixture(native_assets)
    build(native, 'reader-v9', native_assets / 'output', root / 'v9-native')
    (root / 'v9/native.html').write_bytes((root / 'v9-native/single.html').read_bytes())
    rich_assets = root / 'rich-input'
    rich_assets.mkdir()
    build(rich_sidenote_fixture(rich_assets), 'reader-v11', rich_assets, root / 'v11')
    generate_navigation(root / 'v14')
    assert list_templates() == templates_before
    (root / 'generation.json').write_text(json.dumps({
        'templates_unchanged': True,
        'template_ids': ['reader-v5', 'reader-v7', 'reader-v9', 'reader-v11', 'reader-v14'],
        'browser_groups': {'reader-v5': 'v5', 'reader-font': 'v7', 'reader-sidenotes': 'v9',
                           'reader-v11': 'v11', 'reader-navigation': 'v14', 'reader-theme': 'v14'},
        'registered_templates': templates_before,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    generate(parser.parse_args().output.resolve())
