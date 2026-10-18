"""Register two controlled v13 artifacts in an explicitly disposable API instance.

Run with the instance's isolated data volume and database configuration. This is
fixture setup for reader-font-cache.spec.ts, not a translation or publication
workflow acceptance test. No provider, parser or model requests are made.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests/unit')]


def generate(output):
    from packages.domain.config import Config
    from packages.domain.db import Database
    from packages.domain.models import Artifact, Document, Edition, new_id
    from packages.editorial.drafts import render_input
    from packages.ir import digest
    from packages.publisher import Publisher, verify_artifact
    from test_reader_theme import typography_fixture

    output.mkdir(parents=True, exist_ok=False)
    assets = output / 'input-assets'
    assets.mkdir()
    fixture = typography_fixture(assets)
    cfg = Config.load()
    db = Database(cfg)
    document_id, edition_id = new_id('doc_font_cache'), new_id('edition_font_cache')
    ir = render_input(document_id, fixture['source_revision'], fixture['translation_revision'], 'reader-v13')
    artifacts = []
    for _ in range(2):
        artifact_id = new_id('artifact_font_cache')
        key = f'font-cache-evidence/{artifact_id}'
        directory = cfg.data / key
        manifest = Publisher().build(ir, assets, directory, include_source=True)
        assert verify_artifact(directory) == manifest
        artifacts.append({'id': artifact_id, 'storage_key': key, 'manifest_hash': digest(manifest),
                          'url': f'/artifacts/{artifact_id}/index.html'})
    try:
        with db.transaction() as session:
            session.add(Document(id=document_id, title='Controlled font-cache fixture', source_language='en'))
            session.flush()
            session.add(Edition(id=edition_id, document_id=document_id, target_locale='zh-Hans'))
            session.flush()
            for artifact in artifacts:
                session.add(Artifact(id=artifact['id'], document_id=document_id, edition_id=edition_id,
                                     template_id='reader-v13', storage_key=artifact['storage_key'],
                                     manifest_hash=artifact['manifest_hash']))
        receipt = {'template_id': 'reader-v13', 'document_id': document_id, 'artifacts': artifacts,
                   'scope': 'Authored fixture artifacts registered for actual FastAPI font/cache routes; no model inference.'}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    finally:
        db.engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New evidence directory; existing directories are refused')
    parser.add_argument('--confirm-disposable-instance', action='store_true',
                        help='Confirm DATA_DIR and database config belong to the designated test instance')
    args = parser.parse_args()
    if not args.confirm_disposable_instance:
        parser.error('Fixture setup requires --confirm-disposable-instance; never use the installed instance.')
    generate(args.output.resolve())
