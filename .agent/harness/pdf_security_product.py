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
from packages.domain.models import Document, Permit, SourceAsset, SourceRevision
from smoke_library import request, upload, etag

BASE = 'http://127.0.0.1:8080'
FIXTURES = Path('/security-fixtures')
OUTPUT = Path('/security-evidence/result.json')


def main():
    manifest = json.loads((FIXTURES / 'manifest.json').read_text())
    result = {'status': 'running', 'cases': [], 'provider_calls': 0}
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
            'source_language': 'en', 'target_language': 'zh-Hans'}, {'Idempotency-Key': uuid.uuid4().hex}, 201)
        original, original_headers = request(BASE, 'GET', '/api/v1/documents/' + doc['id'] + '/original')
        assert original == data and any(key.lower() == 'content-security-policy' and 'sandbox' in value for key, value in original_headers.items())
        case['document_id'] = doc['id']
        if 'OCR_REQUIRED' in item['expected']:
            parsed, _ = request(BASE, 'POST', '/api/v1/documents/' + doc['id'] + '/parse', {'source_asset_id': doc['source_asset_id']},
                {'Idempotency-Key': uuid.uuid4().hex, 'If-Match': etag(headers)}, 202)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                job, _ = request(BASE, 'GET', '/api/v1/jobs/' + parsed['job_id'])
                if job['status'] in ('needs_review', 'succeeded', 'failed'):
                    break
                time.sleep(.3)
            assert job['status'] == 'needs_review' and job['import_id'], job
            preflight, _ = request(BASE, 'GET', '/api/v1/imports/' + job['import_id'] + '/preflight')
            assert preflight['can_translate'] is False and any(row['code'] == 'OCR_REQUIRED' for row in preflight['unresolved']), preflight
            case.update(preflight='blocked', unresolved=preflight['unresolved'])
        case['status'] = 'passed'
        record(case)
    db = Database(Config.load())
    with db.transaction() as session:
        counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model)) for model in (SourceAsset, Document, SourceRevision, Permit)}
    assert counts == {'source_assets': 3, 'documents': 3, 'source_revisions': 0, 'dispatch_permits': 0}, counts
    # The inert embedded attachment remains inside the original PDF only.
    assert not list(Path('/data').rglob('embedded-source-must-not-be-imported.txt'))
    assert not Path('/tmp/pdf-action-must-not-run').exists()
    result.update(status='passed', counts=counts, exact_originals=3,
        scope='real isolated inspector; scan and mixed-scan full-document translation blocked; no Provider configured',
        action_evidence='Native inspection retained original bytes; no attachment SourceAsset or output file. Parser network-none is separately recorded by Docker driver.')
    OUTPUT.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
