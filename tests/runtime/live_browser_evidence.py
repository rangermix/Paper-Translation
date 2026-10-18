"""Create controlled browser evidence in an explicitly isolated running instance.

The source/target IR is an authored test fixture, not parser or model output.
HTTP mutations, PostgreSQL rows, immutable snapshots and publish/export workers
are real. This script never reads a Provider key or invokes a model.
Run inside the disposable Compose evidence service, with its fresh data volumes.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import delete, select

from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Artifact, Document, Draft, Edition, SegmentVersion, SourceAsset, SourceRevision
from packages.editorial.drafts import context_hash
from packages.ir import block_hash, digest, validate_source
from packages.storage import write_snapshot
from tests.unit.test_original_only import retained_ir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['draft', 'original'])
    parser.add_argument('output', type=Path)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--confirm-disposable-instance', required=True)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    if args.base_url != 'http://127.0.0.1:8080':
        raise SystemExit('Use only the isolated evidence container sharing the app network.')
    if not args.confirm_disposable_instance.strip() or not re.fullmatch(r'[0-9a-f]{7,40}', args.source_revision):
        raise SystemExit('Explicit disposable-instance confirmation and Git revision are required.')
    args.output.mkdir(parents=True, exist_ok=False)
    cfg, events = Config.load(), []
    db = Database(cfg)
    client = httpx.Client(base_url=args.base_url, headers={'X-Library-Request': '1'}, timeout=20)

    def bind_existing_asset(fixture):
        """Reuse an uploaded identical PDF without deleting or rewriting its row."""
        source = fixture['source_revision']
        original_id = source['original_asset_id']
        original = next(asset for asset in source['assets'] if asset['id'] == original_id)
        pdf_bytes = (Path('tests') / original['storage_key']).read_bytes()
        assert digest(pdf_bytes) == source['sha256']
        with db.transaction() as session:
            asset = session.scalar(select(SourceAsset).where(SourceAsset.sha256 == source['sha256']))
            if asset is None:
                asset = SourceAsset(id='source_browser_fixture', sha256=source['sha256'], byte_size=len(pdf_bytes),
                    page_count=1, storage_key=original['storage_key'])
                session.add(asset)
                session.flush()
            else:
                assert digest((cfg.data / asset.storage_key).read_bytes()) == source['sha256']
            asset_id = asset.id
        # All fixture evidence references use the shared original asset identity.
        def remap(value):
            if isinstance(value, dict):
                return {key: remap(child) for key, child in value.items()}
            if isinstance(value, list):
                return [remap(child) for child in value]
            return asset_id if value == original_id else value
        fixture = remap(fixture)
        source = fixture['source_revision']
        for asset in source['assets']:
            destination = cfg.data / asset['storage_key']
            original_path = Path('tests') / asset['storage_key']
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                assert destination.read_bytes() == original_path.read_bytes()
            else:
                shutil.copyfile(original_path, destination)
        hashes = {}
        for block in source['blocks']:
            block['source_hash'] = block_hash(block, source['protected_atoms'])
            hashes[block['id']] = block['source_hash']
        for row in fixture['translation_revision']['results']:
            row['source_hash'] = hashes[row['block_id']]
        validate_source(source)
        return fixture

    def seed(fixture, document_id, edition_id, draft_id, source_id):
        fixture = bind_existing_asset(fixture)
        source = fixture['source_revision']
        source['id'] = source_id
        key = f'documents/{document_id}/sources/{source_id}/{digest(source)}.json'
        sha = write_snapshot(cfg.data, key, source)
        with db.transaction() as session:
            assert session.get(Document, document_id) is None, 'Never overwrite existing fixture data.'
            session.add(Document(id=document_id, title='Publication fixture', source_asset_id=source['original_asset_id'],
                current_source_id=source_id, source_language='en'))
            session.flush()
            session.add(SourceRevision(id=source_id, document_id=document_id, asset_id=source['original_asset_id'],
                snapshot_hash=sha, storage_key=key))
            session.flush()
            session.add(Edition(id=edition_id, document_id=document_id, target_locale='zh-Hans', current_draft_id=draft_id))
            session.flush()
            session.add(Draft(id=draft_id, document_id=document_id, edition_id=edition_id, source_revision_id=source_id))
            session.flush()
            for row in fixture['translation_revision']['results']:
                if row['status'] == 'translated':
                    session.add(SegmentVersion(id=draft_id + '_' + row['block_id'], draft_id=draft_id,
                        block_id=row['block_id'], sequence=1, target_inline=row['target_inline'], source_hash=row['source_hash'],
                        context_hash=context_hash(source, row['block_id']), origin='manual_ui',
                        reason='Authored browser fixture; no model request or human review claim.'))
        return fixture

    def request(method, path, body=None, etag=None):
        headers = {'Idempotency-Key': 'browser-evidence-' + uuid.uuid4().hex} if method != 'GET' else {}
        if etag:
            headers['If-Match'] = etag
        response = client.request(method, path, json=body, headers=headers)
        events.append({'method': method, 'path': path, 'status': response.status_code})
        response.raise_for_status()
        return response

    def wait_export(export_id):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            value = request('GET', '/api/v1/exports/' + export_id).json()
            if value['status'] == 'succeeded':
                return value
            if value['status'] == 'failed':
                raise AssertionError(value)
            time.sleep(.25)
        raise TimeoutError(export_id)

    try:
        if args.kind == 'draft':
            with db.transaction() as session:
                assert session.get(Document, 'doc_fixture') is None, 'Never overwrite existing fixture data.'
            seed(json.loads(Path('tests/fixtures/sample-document.json').read_text('utf-8')),
                'doc_fixture', 'edition_fixture', 'draft_fixture', 'src_fixture')
            with db.transaction() as session:
                session.execute(delete(SegmentVersion).where(SegmentVersion.draft_id == 'draft_fixture', SegmentVersion.block_id == 'item'))
            queued = request('POST', '/api/v1/drafts/draft_fixture/exports', {
                'format': 'single_html', 'include_source': False, 'confirm_draft': False,
            }, '"1"').json()
            assert queued['missing_blocks'] == 1
            request('PATCH', '/api/v1/drafts/draft_fixture/segments/item', {
                'base_segment_version': 0, 'reason': 'Later controlled test edit',
                'target_inline': [{'type': 'text', 'text': 'Later target sentinel'}],
            }, '"1"')
            exported = wait_export(queued['export_id'])
            html = request('GET', exported['download_url']).content
            assert b'Later target sentinel' not in html and '缺失 1 块译文'.encode() in html
            (args.output / 'reading.html').write_bytes(html)
            receipt = {'draft_id': 'draft_fixture', 'export': exported, 'queued': queued}
        else:
            seed(retained_ir(), 'doc_browser_retained', 'edition_browser_retained',
                'draft_browser_retained', 'src_browser_retained')
            validated = request('POST', '/api/v1/drafts/draft_browser_retained/validate', {}, '"1"').json()
            draft = request('GET', '/api/v1/drafts/draft_browser_retained')
            generation = draft.json()['generation']
            sealed = request('POST', '/api/v1/drafts/draft_browser_retained/seal', {
                'generation': generation, 'qa_id': validated['id'], 'qa_fingerprint': validated['fingerprint'],
            }, draft.headers['etag']).json()
            queued = request('POST', '/api/v1/editions/edition_browser_retained/publish', {
                'translation_revision_id': sealed['id'], 'template_id': 'reader-v14', 'expected_generation': 1,
            }, '"1"').json()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                job = request('GET', '/api/v1/jobs/' + queued['job_id']).json()
                if job['status'] in {'succeeded', 'completed_with_warnings'}:
                    break
                assert job['status'] != 'failed', job
                time.sleep(.25)
            else:
                raise TimeoutError(queued['job_id'])
            document = request('GET', '/api/v1/documents/doc_browser_retained').json()
            artifact_id = document['editions'][0]['current_artifact_id']
            with db.transaction() as session:
                artifact = session.get(Artifact, artifact_id)
                shutil.copytree(cfg.data / artifact.storage_key, args.output / 'artifact')
            queued_export = request('POST', '/api/v1/artifacts/' + artifact_id + '/exports', {
                'format': 'single_html', 'include_source': True,
            }).json()
            exported = wait_export(queued_export['export_id'])
            (args.output / 'reading.html').write_bytes(request('GET', exported['download_url']).content)
            receipt = {'document_id': document['id'], 'artifact_id': artifact_id, 'publication_job': job,
                'translation_revision_id': sealed['id'], 'export': exported}
        receipt.update({'kind': 'real_HTTP_PostgreSQL_and_worker_with_authored_IR', 'source_commit': args.source_revision,
            'confirmed_disposable_instance': args.confirm_disposable_instance,
            'real_parser_inference': False, 'real_provider_calls': 0, 'browser_fixture_not_translation_quality': True,
            'events': events})
        (args.output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps({'kind': args.kind, 'output': str(args.output), 'result': 'generated', 'requests': len(events)}))
    finally:
        client.close()
        db.engine.dispose()


if __name__ == '__main__':
    main()
