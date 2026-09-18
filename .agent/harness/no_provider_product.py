"""Real image HTTP/parser chain with missing profile, then unavailable credentials.

Only run in an independently inspected, fresh, fully offline Compose project.
No Provider transport is constructed or mocked by this helper.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import hashlib
import json
from pathlib import Path
import time

from sqlalchemy import func, select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Attempt, Document, Job, Permit, SourceDraft, SourceRevision, Task
from smoke_library import etag, request

BASE = 'http://127.0.0.1:8080'
OUT = Path('/no-provider-evidence')
CONTROLLED = Path('/no-provider-fixtures')


def wait_job(job_id, states, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job, _ = request(BASE, 'GET', '/api/v1/jobs/' + job_id)
        (OUT / ('job-' + job_id + '.json')).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        if job['status'] in states:
            return job
        if job['status'] in {'failed', 'outcome_unknown', 'cancelled'}:
            raise RuntimeError('Unexpected terminal status: ' + job['status'])
        time.sleep(.3)
    raise TimeoutError('Job deadline: ' + job_id)


def no_price(db):
    manifest = json.loads((CONTROLLED / 'manifest.json').read_text('utf-8'))
    controlled = next(doc for doc in manifest['documents'] if doc['id'] == 'controlled-en')
    data = (CONTROLLED / 'controlled-en.pdf').read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    assert sha == controlled['sha256']
    caps, _ = request(BASE, 'GET', '/api/v1/capabilities')
    assert caps['provider_configured'] is False
    upload, headers = request(BASE, 'POST', '/api/v1/uploads', {'filename': 'interrupted.pdf',
        'byte_size': len(data), 'media_type': 'application/pdf'}, {'Idempotency-Key': 'no-provider-upload'}, 201)
    url = '/api/v1/uploads/' + upload['id']
    split = len(data) // 2
    first_headers = {'If-Match': etag(headers), 'Content-Range': f'bytes 0-{split-1}/{len(data)}',
        'Content-Type': 'application/octet-stream', 'X-Chunk-SHA256': hashlib.sha256(data[:split]).hexdigest()}
    first, _ = request(BASE, 'PUT', url + '/chunks/0', data[:split], first_headers)
    # A new HTTP request recovers server acknowledgement after a lost response.
    recovered, headers = request(BASE, 'GET', url)
    assert recovered['received_bytes'] == split and recovered['generation'] == first['generation']
    replay, _ = request(BASE, 'PUT', url + '/chunks/0', data[:split], first_headers)
    assert replay == first
    _, headers = request(BASE, 'PUT', url + '/chunks/1', data[split:], {'If-Match': etag(headers),
        'Content-Range': f'bytes {split}-{len(data)-1}/{len(data)}', 'Content-Type': 'application/octet-stream',
        'X-Chunk-SHA256': hashlib.sha256(data[split:]).hexdigest()})
    final_body = {'expected_sha256': sha, 'total_bytes': len(data)}
    final_headers = {'If-Match': etag(headers), 'Idempotency-Key': 'no-provider-finalize'}
    finalized, _ = request(BASE, 'POST', url + '/finalize', final_body, final_headers, 202)
    replay, _ = request(BASE, 'POST', url + '/finalize', final_body, final_headers, 202)
    assert replay == finalized
    wait_job(finalized['job_id'], {'succeeded'})
    verified, _ = request(BASE, 'GET', url)
    assert verified['status'] == 'verified' and verified['sha256'] == sha
    import_body = {'source': {'kind': 'pdf_upload', 'upload_id': upload['id']}, 'source_language': 'en'}
    import_headers = {'Idempotency-Key': 'no-provider-import'}
    document, doc_headers = request(BASE, 'POST', '/api/v1/imports', import_body, import_headers, 201)
    same, _ = request(BASE, 'POST', '/api/v1/imports', import_body, import_headers, 201)
    assert same == document
    original, _ = request(BASE, 'GET', document['original_url'])
    assert original == data
    parse_body = {'source_asset_id': document['source_asset_id']}
    parse_headers = {'If-Match': etag(doc_headers), 'Idempotency-Key': 'no-provider-parse'}
    parsed, _ = request(BASE, 'POST', '/api/v1/documents/' + document['id'] + '/parse', parse_body, parse_headers, 202)
    replay, _ = request(BASE, 'POST', '/api/v1/documents/' + document['id'] + '/parse', parse_body, parse_headers, 202)
    assert replay == parsed
    job = wait_job(parsed['job_id'], {'needs_review', 'succeeded'})
    preflight, preflight_headers = request(BASE, 'GET', '/api/v1/imports/' + job['import_id'] + '/preflight')
    assert preflight['can_translate'] and not preflight['unresolved']
    assert [b['normalized_text'] for b in preflight['blocks']] == controlled['source_text']
    page, _ = request(BASE, 'GET', preflight['pages'][0]['page_image_url'])
    assert page.startswith(b'\x89PNG\r\n\x1a\n')
    rejected, _ = request(BASE, 'POST', '/api/v1/imports/' + preflight['id'] + '/confirm', {
        'source_hash': preflight['source_hash'], 'preflight_generation': preflight['generation'],
        'profile_revision': 'unconfigured', 'profile_hash': preflight['profile_hash'], 'locale': 'zh-Hans',
        'budget_micro': 1000000, 'external_processing_confirmed': True},
        {'If-Match': etag(preflight_headers), 'Idempotency-Key': 'no-price-blocked'}, 409)
    assert rejected['error']['code'] == 'PROVIDER_CONFIG'
    with db.transaction() as session:
        counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Document, SourceDraft, SourceRevision, Permit)}
        tasks = list(session.scalars(select(Task)))
        attempts = list(session.scalars(select(Attempt)))
        assert counts == {'documents': 1, 'source_drafts': 1, 'source_revisions': 0, 'dispatch_permits': 0}, counts
        assert sorted(t.kind for t in tasks) == ['inspect', 'parse']
        assert all(t.attempts == 1 and t.status == 'succeeded' for t in tasks)
        assert len(attempts) == 2
    result = {'status': 'passed', 'phase': 'no_price', 'document_id': document['id'], 'import_id': preflight['id'],
        'sha256': sha, 'parse_job_id': job['id'], 'inspect_job_id': finalized['job_id'],
        'single_actual_parse_after_replays': True, 'exact_four_controlled_blocks': True,
        'original_and_page_readable': True, 'counts': counts, 'external_provider_requests': 0}
    (OUT / 'no-price.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


def no_key(db):
    prior = json.loads((OUT / 'no-price.json').read_text('utf-8'))
    preflight, headers = request(BASE, 'GET', '/api/v1/imports/' + prior['import_id'] + '/preflight')
    assert preflight['profile']['configured'] and preflight['profile']['model_id'] == 'offline-no-key-fixture'
    created, _ = request(BASE, 'POST', '/api/v1/imports/' + preflight['id'] + '/confirm', {
        'source_hash': preflight['source_hash'], 'preflight_generation': preflight['generation'],
        'profile_revision': preflight['profile']['profile_revision'], 'profile_hash': preflight['profile_hash'],
        'locale': 'zh-Hans', 'budget_micro': 1000000, 'external_processing_confirmed': True,
        'publish_policy': 'manual_approval'}, {'If-Match': etag(headers), 'Idempotency-Key': 'no-key-confirm'}, 202)
    job = wait_job(created['job_id'], {'waiting_config'})
    assert job['error']['code'] == 'PROVIDER_CONFIG' and job['request_count'] == 0
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
        assert session.scalar(select(func.count()).select_from(Task).where(Task.kind == 'parse')) == 1
        assert all(a.usage is None and a.request_id is None for a in session.scalars(select(Attempt)))
    original, _ = request(BASE, 'GET', '/api/v1/documents/' + prior['document_id'] + '/original')
    assert hashlib.sha256(original).hexdigest() == prior['sha256']
    request(BASE, 'GET', '/health/ready')
    request(BASE, 'GET', '/api/v1/documents')
    result = {'status': 'passed', 'phase': 'no_key', 'job_id': job['id'], 'status_observed': job['status'],
        'error': job['error']['code'], 'request_count': 0, 'permit_count': 0, 'source_parse_count': 1,
        'original_still_readable': True, 'external_provider_requests': 0}
    (OUT / 'no-key.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['no-price', 'no-key'])
    args = parser.parse_args()
    db = Database(Config.load())
    (no_price if args.phase == 'no-price' else no_key)(db)
