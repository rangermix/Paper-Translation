"""Real concurrent PDF receipts, native inspection, deduplication and rejection."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import uuid

from sqlalchemy import func, select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Document, Permit, SourceAsset, SourceRevision
from smoke_library import etag, request, upload

BASE = 'http://127.0.0.1:8080'
FIXTURES = Path('/batch-fixtures')
OUTPUT = Path('/batch-evidence/result.json')


def main():
    caps, _ = request(BASE, 'GET', '/api/v1/capabilities')
    assert caps['provider_configured'] is False
    inputs = [FIXTURES / name for name in ('sample.pdf', 'live-provider/controlled-en.pdf',
        'live-provider/controlled-zh.pdf', 'security/malformed.pdf')]
    data = [path.read_bytes() for path in inputs]
    # All four requests share one visible filename. Content must determine identity.
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(lambda content: upload(BASE, content, 'same-name.pdf'), data))
    assert [state['status'] for state in states] == ['verified', 'verified', 'verified', 'failed'], states
    assert states[3]['error']['code'] == 'PDF_INVALID'
    docs = []
    for state, content in zip(states[:3], data[:3]):
        doc, _ = request(BASE, 'POST', '/api/v1/imports', {'source': {'kind': 'pdf_upload', 'upload_id': state['id']}},
            {'Idempotency-Key': uuid.uuid4().hex}, 201)
        actual, _ = request(BASE, 'GET', doc['original_url'])
        assert actual == content
        docs.append(doc)
    assert len({doc['id'] for doc in docs}) == len({doc['source_asset_id'] for doc in docs}) == 3
    request(BASE, 'POST', '/api/v1/imports', {'source': {'kind': 'pdf_upload', 'upload_id': states[3]['id']}},
        {'Idempotency-Key': uuid.uuid4().hex}, 409)
    duplicate = upload(BASE, data[0], 'renamed-copy.pdf')
    assert duplicate['source_asset_id'] == states[0]['source_asset_id']
    assert {row['id'] for row in duplicate['duplicates']} == {docs[0]['id']}
    independent, _ = request(BASE, 'POST', '/api/v1/imports', {'source': {'kind': 'pdf_upload', 'upload_id': duplicate['id']}},
        {'Idempotency-Key': uuid.uuid4().hex}, 201)
    assert independent['id'] != docs[0]['id'] and independent['source_asset_id'] == docs[0]['source_asset_id']
    # Explicit reuse requires the document generation; filename alone never replaces it.
    reuse_body = {'source': {'kind': 'pdf_upload', 'upload_id': duplicate['id']}, 'document_id': docs[0]['id']}
    request(BASE, 'POST', '/api/v1/imports', reuse_body, {'Idempotency-Key': uuid.uuid4().hex}, 428)
    reused, _ = request(BASE, 'POST', '/api/v1/imports', reuse_body,
        {'Idempotency-Key': uuid.uuid4().hex, 'If-Match': '"1"'}, 201)
    assert reused['id'] == docs[0]['id'] and reused['generation'] == 2
    # A rejected finalize can be corrected while the valid chunks remain intact.
    content = data[1]
    receipt, headers = request(BASE, 'POST', '/api/v1/uploads', {'filename': 'hash-check.pdf',
        'media_type': 'application/pdf', 'byte_size': len(content)}, {'Idempotency-Key': uuid.uuid4().hex}, 201)
    receipt_path = '/api/v1/uploads/' + receipt['id']
    chunk, headers = request(BASE, 'PUT', receipt_path+'/chunks/0', content,
        {'If-Match': etag(headers), 'Content-Range': f'bytes 0-{len(content)-1}/{len(content)}',
         'X-Chunk-SHA256': hashlib.sha256(content).hexdigest(), 'Content-Type': 'application/octet-stream'})
    request(BASE, 'POST', receipt_path+'/finalize', {'expected_sha256': '0'*64, 'total_bytes': len(content)},
        {'Idempotency-Key': uuid.uuid4().hex, 'If-Match': etag(headers)}, 422)
    rejected, _ = request(BASE, 'GET', receipt_path)
    assert rejected['status'] == 'receiving' and rejected['job_id'] is None and rejected['generation'] == chunk['generation']
    with Database(Config.load()).transaction() as session:
        counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Document, SourceAsset, SourceRevision, Permit)}
    assert counts == {'documents': 4, 'source_assets': 3, 'source_revisions': 0, 'dispatch_permits': 0}, counts
    result = {'status': 'passed', 'scope': 'actual HTTP, worker and native inspector in offline Compose; no translation',
        'batch_size': 4, 'verified': 3, 'failed': 1, 'independent_documents': 4,
        'same_filename_distinct_assets': 3, 'renamed_same_bytes_shared_asset': True,
        'reuse_requires_generation': True, 'hash_mismatch_has_no_job': True, 'counts': counts,
        'inputs': [{'path': str(path.relative_to(FIXTURES)), 'sha256': hashlib.sha256(content).hexdigest(),
            'upload_id': state['id'], 'status': state['status']} for path, content, state in zip(inputs, data, states)],
        'documents': [{'id': doc['id'], 'asset_id': doc['source_asset_id'], 'sha256': doc['sha256']} for doc in docs]}
    OUTPUT.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
