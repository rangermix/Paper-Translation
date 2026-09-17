"""Image-contained real HTTP→worker→network-none parser PDF acceptance matrix."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import hashlib
import json
from pathlib import Path
import time
import uuid

from sqlalchemy import func, select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Document, Permit, SourceAsset, SourceDraft, SourceRevision
from packages.domain.workflow import TERMINAL_STATES
from smoke_library import request, upload, etag

BASE = 'http://127.0.0.1:8080'
FIXTURES = Path('/security-fixtures')
OUTPUT = Path('/security-evidence/result.json')


def main():
    manifest = json.loads((FIXTURES / 'manifest.json').read_text())
    result = {'status': 'running', 'cases': [], 'provider_calls': 0}
    completed_import_ids = set()
    def record(case):
        result['cases'].append(case)
        OUTPUT.write_text(json.dumps(result, indent=2))
    caps, _ = request(BASE, 'GET', '/api/v1/capabilities')
    assert caps['provider_configured'] is False
    too_big, _ = request(BASE, 'POST', '/api/v1/uploads', {'filename': 'too-large.pdf',
        'media_type': 'application/pdf', 'byte_size': 50 * 1024 * 1024 + 1},
        {'Idempotency-Key': uuid.uuid4().hex}, 422)
    record({'case': 'over-50MiB-declaration', 'status': 'passed', 'rejected_before_file_storage': True})
    excessive_chunk = b'%PDF-' + b' ' * (4 * 1024 * 1024 - 4)
    chunk_upload, chunk_headers = request(BASE, 'POST', '/api/v1/uploads', {'filename': 'over-chunk.pdf',
        'media_type': 'application/pdf', 'byte_size': len(excessive_chunk)}, {'Idempotency-Key': uuid.uuid4().hex}, 201)
    request(BASE, 'PUT', '/api/v1/uploads/' + chunk_upload['id'] + '/chunks/0', excessive_chunk,
        {'If-Match': etag(chunk_headers), 'Content-Range': f'bytes 0-{len(excessive_chunk)-1}/{len(excessive_chunk)}',
         'X-Chunk-SHA256': hashlib.sha256(excessive_chunk).hexdigest(), 'Content-Type': 'application/octet-stream'}, 413)
    untouched, _ = request(BASE, 'GET', '/api/v1/uploads/' + chunk_upload['id'])
    assert untouched['received_bytes'] == 0
    record({'case': 'streaming-chunk-over-4MiB', 'status': 'passed', 'received_bytes_after_rejection': 0})
    for item in manifest['files']:
        data = (FIXTURES / item['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['sha256']
        state = upload(BASE, data, item['path'])
        case = {'case': item['path'], 'upload_id': state['id'], 'sha256': item['sha256'], 'inspector': state['status']}
        if item['expected'].startswith('PDF_'):
            assert state['status'] == 'failed' and state['error']['code'] == item['expected'], state
            case.update(status='passed', rejection_code=state['error']['code'])
            record(case)
            continue
        assert state['status'] == 'verified', state
        doc, headers = request(BASE, 'POST', '/api/v1/imports', {'source': {'kind': 'pdf_upload', 'upload_id': state['id']},
            'source_language': 'en', 'target_language': 'zh-Hans', 'workflow': None}, {'Idempotency-Key': uuid.uuid4().hex}, 201)
        assert doc['status'] == 'source_only', doc
        original, original_headers = request(BASE, 'GET', '/api/v1/documents/' + doc['id'] + '/original')
        assert original == data and any(key.lower() == 'content-security-policy' and 'sandbox' in value for key, value in original_headers.items())
        case['document_id'] = doc['id']
        if 'OCR_REQUIRED' in item['expected']:
            # This probe checks local scan diagnostics without starting a
            # translation/publication workflow or inheriting the default model.
            parsed, _ = request(BASE, 'POST', '/api/v1/documents/' + doc['id'] + '/parse',
                {'source_asset_id': doc['source_asset_id'], 'parser_profile_revision': 'docling-v1', 'workflow': None},
                {'Idempotency-Key': uuid.uuid4().hex, 'If-Match': etag(headers)}, 202)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                job, _ = request(BASE, 'GET', '/api/v1/jobs/' + parsed['job_id'])
                if job['status'] in TERMINAL_STATES:
                    break
                time.sleep(.3)
            assert job['status'] == 'completed_with_warnings' and job['import_id'], job
            preflight, _ = request(BASE, 'GET', '/api/v1/imports/' + job['import_id'] + '/preflight')
            assert preflight['status'] == 'ready' and preflight['can_translate'] is True, preflight
            scanned_pages = {page['page'] for page in preflight['coverage']['pages'] if page.get('scan_suspected')}
            scan_warnings = [row for row in preflight['unresolved'] if row['code'] == 'OCR_REQUIRED' or
                row['code'] == 'SOURCE_PARSE_REVIEW' and 'scan completeness' in row.get('reason', '')]
            assert scanned_pages and scanned_pages <= {row['page'] for row in scan_warnings}, preflight
            assert preflight['issues'] and preflight['quality']['blocking'] is False, preflight
            assert all(issue['blocking'] is False for issue in preflight['issues']), preflight
            assert preflight['quality']['diagnostic_count'] == len(preflight['unresolved']), preflight
            assert all(page['covered_blocks'] and page['page_image_url'] for page in preflight['pages']
                if page['page'] in scanned_pages), preflight
            completed_import_ids.add(job['import_id'])
            case.update(parse_status=job['status'], parser_profile_revision='docling-v1', import_id=job['import_id'],
                preflight=preflight['status'], can_translate=preflight['can_translate'], unresolved=preflight['unresolved'],
                issues=preflight['issues'], quality=preflight['quality'])
        case['status'] = 'passed'
        record(case)
    db = Database(Config.load())
    with db.transaction() as session:
        counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model)) for model in (SourceAsset, Document, SourceRevision, Permit)}
        drafts = list(session.scalars(select(SourceDraft)))
        assert {draft.id for draft in drafts} == completed_import_ids and len(drafts) == 2
        sealed_revision_ids = {draft.evidence['sealed_revision_id'] for draft in drafts if draft.evidence.get('sealed_revision_id')}
        revision_ids = set(session.scalars(select(SourceRevision.id)))
        assert revision_ids == sealed_revision_ids, (revision_ids, sealed_revision_ids)
    # Ready parse drafts are unsealed because workflow=None is explicit above.
    # Reconcile stored revisions with evidence instead of assuming a stage count.
    assert counts == {'source_assets': 3, 'documents': 3, 'source_revisions': len(sealed_revision_ids), 'dispatch_permits': 0}, counts
    # The inert embedded attachment remains inside the original PDF only.
    assert not list(Path('/data').rglob('embedded-source-must-not-be-imported.txt'))
    assert not Path('/tmp/pdf-action-must-not-run').exists()
    result.update(status='passed', counts=counts, exact_originals=3, source_revision_ids=sorted(revision_ids),
        scope='real isolated inspector and explicit Docling parse; scan warnings retained in ready preflights; no translation/publication workflow or Provider calls',
        action_evidence='Native inspection retained original bytes; no attachment SourceAsset or output file. Parser network-none is separately recorded by Docker driver.')
    OUTPUT.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
