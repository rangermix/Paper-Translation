"""Executable exit checks; PostgreSQL evidence is never replaced with SQLite."""
import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.postgres


def test_pdf_only_and_no_identity(client):
    caps = client.get('/api/v1/capabilities')
    assert caps.status_code == 200
    assert caps.json()['source_mime_types'] == ['application/pdf']
    schema = client.get('/openapi.json').json()
    assert not schema.get('components', {}).get('securitySchemes')
    for route in ('login', 'users', 'workspaces', 'roles', 'imports/ir', 'imports/text'):
        assert client.post('/api/v1/' + route, json={}).status_code == 404
    bad = client.post('/api/v1/uploads', json={'filename': 'a.pdf', 'media_type': 'text/html', 'byte_size': 12}, headers={'Idempotency-Key': 'bad'})
    assert bad.status_code in (415, 422)


def test_upload_chunks_idempotency_and_preconditions(client):
    data = Path('tests/fixtures/sample.pdf').read_bytes()
    payload = {'filename': 'sample.pdf', 'media_type': 'application/pdf', 'byte_size': len(data)}
    headers = {'Idempotency-Key': 'upload-one'}
    first = client.post('/api/v1/uploads', json=payload, headers=headers)
    assert first.status_code == 201
    assert client.post('/api/v1/uploads', json=payload, headers=headers).json() == first.json()
    assert client.post('/api/v1/uploads', json={**payload, 'filename': 'other.pdf'}, headers=headers).status_code == 409
    uid = first.json()['id']
    path = f'/api/v1/uploads/{uid}/chunks/0'
    chunk_headers = {'Content-Range': f'bytes 0-{len(data)-1}/{len(data)}', 'X-Chunk-SHA256': hashlib.sha256(data).hexdigest(), 'Content-Type': 'application/octet-stream', 'If-Match': first.headers['etag']}
    put = client.put(path, content=data, headers=chunk_headers)
    assert put.status_code == 200
    assert client.put(path, content=data, headers=chunk_headers).status_code == 200
    done = client.post(f'/api/v1/uploads/{uid}/finalize', json={'expected_sha256': hashlib.sha256(data).hexdigest(), 'total_bytes': len(data)}, headers={'Idempotency-Key': 'finalize', 'If-Match': put.headers['etag']})
    assert done.status_code == 202
    assert done.json()['status'] == 'inspecting'
    # Until the isolated inspector finishes, the public import may not succeed.
    assert client.post('/api/v1/imports', json={'source': {'kind': 'pdf_upload', 'upload_id': uid}}, headers={'Idempotency-Key': 'import-early'}).status_code == 409


def test_host_origin_and_unknown_fields(client):
    assert client.get('/api/v1/capabilities', headers={'Host': 'attacker.invalid'}).status_code == 400
    assert client.post('/api/v1/uploads', json={}, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    assert client.post('/api/v1/uploads', json={'filename': 'a.pdf', 'media_type': 'application/pdf', 'byte_size': 1, 'workspace_id': 'x'}, headers={'Idempotency-Key': 'unknown-field'}).status_code == 422
