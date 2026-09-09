"""Upload expiry, bad digest recovery and immutable acknowledged chunks."""
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from packages.domain.models import Job, Upload, now
from packages.ir import digest

pytestmark = pytest.mark.postgres


def start(client):
    data = Path('fixtures/sample.pdf').read_bytes()
    response = client.post('/api/v1/uploads', json={'filename': 'sample.pdf', 'media_type': 'application/pdf',
        'byte_size': len(data)}, headers={'Idempotency-Key': 'receipt'})
    assert response.status_code == 201
    return data, response


def headers(response, content, start, total):
    return {'If-Match': response.headers['etag'], 'X-Chunk-SHA256': digest(content),
        'Content-Range': f'bytes {start}-{start+len(content)-1}/{total}', 'Content-Type': 'application/octet-stream'}


def test_expired_partial_upload_cannot_append_replay_or_finalize(client, database):
    db, cfg = database
    data, created = start(client)
    upload_id = created.json()['id']
    prefix, suffix = data[:1000], data[1000:]
    route = f'/api/v1/uploads/{upload_id}'
    first = client.put(route+'/chunks/0', content=prefix, headers=headers(created, prefix, 0, len(data)))
    assert first.status_code == 200
    with db.transaction() as session:
        session.get(Upload, upload_id).expires_at = now()-timedelta(seconds=1)
    for index, content, offset in [(0, prefix, 0), (1, suffix, len(prefix))]:
        rejected = client.put(route+f'/chunks/{index}', content=content, headers=headers(first, content, offset, len(data)))
        assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'UPLOAD_EXPIRED'
    final = client.post(route+'/finalize', json={'expected_sha256': digest(data), 'total_bytes': len(data)},
        headers={'If-Match': first.headers['etag'], 'Idempotency-Key': 'expired-finalize'})
    assert final.status_code == 409 and final.json()['error']['code'] == 'UPLOAD_EXPIRED'
    state = client.get(route).json()
    assert state['received_bytes'] == 1000 and state['job_id'] is None
    assert (cfg.uploads / upload_id / 'chunks/0.bin').read_bytes() == prefix
    assert not (cfg.uploads / upload_id / 'chunks/1.bin').exists()


def test_bad_chunk_and_total_hash_do_not_create_job_and_correct_retry_works(client, database):
    db, cfg = database
    data, created = start(client)
    upload_id = created.json()['id']
    route = f'/api/v1/uploads/{upload_id}'
    chunk_headers = headers(created, data, 0, len(data))
    rejected = client.put(route+'/chunks/0', content=data, headers={**chunk_headers, 'X-Chunk-SHA256': '0'*64})
    assert rejected.status_code == 422 and rejected.json()['error']['code'] == 'CHUNK_HASH_MISMATCH'
    assert client.get(route).json()['received_bytes'] == 0
    accepted = client.put(route+'/chunks/0', content=data, headers=chunk_headers)
    assert accepted.status_code == 200
    bad = client.post(route+'/finalize', json={'expected_sha256': '0'*64, 'total_bytes': len(data)},
        headers={'If-Match': accepted.headers['etag'], 'Idempotency-Key': 'bad-finalize'})
    assert bad.status_code == 422 and bad.json()['error']['code'] == 'UPLOAD_HASH_MISMATCH'
    assert client.get(route).json()['status'] == 'receiving'
    with db.transaction() as session:
        assert not list(session.scalars(select(Job)))
    fixed = client.post(route+'/finalize', json={'expected_sha256': digest(data), 'total_bytes': len(data)},
        headers={'If-Match': accepted.headers['etag'], 'Idempotency-Key': 'fixed-finalize'})
    assert fixed.status_code == 202 and fixed.json()['status'] == 'inspecting'
    assert (cfg.uploads / upload_id / 'original.pdf').read_bytes() == data
    with db.transaction() as session:
        assert len(list(session.scalars(select(Job)))) == 1
