"""Actual API/worker/DB observations around the injected isolated child failures."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import json
from pathlib import Path
import time
import uuid

from sqlalchemy import func, select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Permit, SourceRevision
from smoke_library import request, upload, etag

BASE = 'http://127.0.0.1:8080'
OUTPUT = Path('/fault-evidence')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'queue', 'verify'])
    parser.add_argument('--case', choices=['resource', 'timeout', 'path', 'stale'])
    args = parser.parse_args()
    if args.phase == 'prepare':
        data = Path('/app/fixtures/sample.pdf').read_bytes()
        checked = upload(BASE, data, 'isolated-parser-fault.pdf')
        assert checked['status'] == 'verified', checked
        doc, _ = request(BASE, 'POST', '/api/v1/imports', {'source': {'kind': 'pdf_upload', 'upload_id': checked['id']},
            'source_language': 'en', 'target_language': 'zh-Hans'}, {'Idempotency-Key': uuid.uuid4().hex}, 201)
        (OUTPUT / 'document.json').write_text(json.dumps(doc))
        print(json.dumps({'document_id': doc['id'], 'original_verified': True}))
        return
    doc = json.loads((OUTPUT / 'document.json').read_text())
    if args.phase == 'queue':
        current, headers = request(BASE, 'GET', '/api/v1/documents/' + doc['id'])
        queued, _ = request(BASE, 'POST', '/api/v1/documents/' + doc['id'] + '/parse', {'source_asset_id': current['source_asset_id']},
            {'If-Match': etag(headers), 'Idempotency-Key': uuid.uuid4().hex}, 202)
        (OUTPUT / (args.case + '-job.json')).write_text(json.dumps(queued))
        print(json.dumps(queued))
        return
    queued = json.loads((OUTPUT / (args.case + '-job.json')).read_text())
    until = time.monotonic() + 20
    while time.monotonic() < until:
        job, _ = request(BASE, 'GET', '/api/v1/jobs/' + queued['job_id'])
        if job['status'] == 'failed':
            break
        time.sleep(.2)
    expected = {'resource': 'PARSER_RESOURCE_LIMIT', 'timeout': 'PARSER_TIMEOUT',
        'path': 'WORKER_FAILED', 'stale': 'WORKER_FAILED'}[args.case]
    assert job['status'] == 'failed' and job['error']['code'] == expected, job
    ready, _ = request(BASE, 'GET', '/health/ready')
    assert isinstance(ready, dict) and ready.get('status') == 'ready', ready
    original, _ = request(BASE, 'GET', '/api/v1/documents/' + doc['id'] + '/original')
    assert original == Path('/app/fixtures/sample.pdf').read_bytes()
    db = Database(Config.load())
    with db.transaction() as session:
        counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model)) for model in (Permit, SourceRevision)}
    assert all(count == 0 for count in counts.values()), counts
    result = {'status': 'passed', 'case': args.case, 'error_code': expected,
        'job': job, 'readiness': ready, 'database_counts': counts, 'original_unchanged': True,
        'scope': 'Actual isolated child resource/deadline failure and untrusted protocol injection; not a malicious-PDF organic OOM or valid parsed source'}
    (OUTPUT / (args.case + '-result.json')).write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
