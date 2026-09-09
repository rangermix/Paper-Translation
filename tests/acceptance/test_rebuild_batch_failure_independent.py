"""Literal 20-document rebuild with one corrupted input; no Provider permitted."""
import copy
import json
from pathlib import Path
import shutil
import time
from unittest.mock import patch

import pytest
from sqlalchemy import event, func, select

from packages.domain.models import Artifact, Document, Edition, Job, Permit, Publication, SourceAsset, SourceRevision, TranslationCache, TranslationRevision
from packages.ir import digest
from packages.jobs.queue import claim
from packages.publisher import verify_artifact
from packages.storage import write_snapshot
from workers.main import execute

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.postgres


def test_twenty_api_rebuilds_isolate_one_corrupt_resource(client, database):
    db, cfg = database
    fixture = json.loads((ROOT / 'fixtures/sample-document-v3.json').read_text('utf-8'))
    original = next(a for a in fixture['source_revision']['assets'] if a['id'] == fixture['source_revision']['original_asset_id'])
    original_path = cfg.data / original['storage_key']
    original_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / original['storage_key'], original_path)
    private_images = {}
    with db.transaction() as session:
        session.add(SourceAsset(id=original['id'], sha256=original['sha256'], byte_size=original['byte_size'], page_count=1, storage_key=original['storage_key']))
        session.flush()
        for i in range(20):
            source, tr = copy.deepcopy(fixture['source_revision']), copy.deepcopy(fixture['translation_revision'])
            source['id'], tr['id'], tr['source_revision_id'] = f'source_{i}', f'translation_{i}', f'source_{i}'
            for asset in source['assets']:
                if asset['id'] == original['id']:
                    continue
                old_path = asset['storage_key']
                asset['storage_key'] = f'documents/doc_{i}/source-assets/{asset["id"]}.png'
                target = cfg.data / asset['storage_key']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / old_path, target)
                private_images[i] = target
            source_key, tr_key = f'documents/doc_{i}/source.json', f'documents/doc_{i}/translation.json'
            source_sha, tr_sha = write_snapshot(cfg.data, source_key, source), write_snapshot(cfg.data, tr_key, tr)
            session.add(Document(id=f'doc_{i}', title=f'Independent authored fixture {i}', source_asset_id=original['id'], current_source_id=source['id']))
            session.flush()
            session.add(SourceRevision(id=source['id'], document_id=f'doc_{i}', asset_id=original['id'], snapshot_hash=source_sha, storage_key=source_key))
            session.add(Edition(id=f'edition_{i}', document_id=f'doc_{i}', target_locale='zh-Hans'))
            session.flush()
            session.add(TranslationRevision(id=tr['id'], document_id=f'doc_{i}', edition_id=f'edition_{i}', source_revision_id=source['id'],
                snapshot_hash=tr_sha, storage_key=tr_key, qa_fingerprint=digest({'authored_fixture_not_semantic_review': i})))

    # Old readers are actually enqueued through the public API and built by
    # the real worker. Only the input bilingual snapshots are authored fixtures.
    for i in range(20):
        queued = client.post(f'/api/v1/editions/edition_{i}/publish', json={'translation_revision_id': f'translation_{i}', 'expected_generation': 1},
            headers={'If-Match': '"1"', 'Idempotency-Key': f'old-reader-{i}'})
        assert queued.status_code == 202, queued.text
    for count in range(100):
        lease = claim(db)
        if lease is None:
            break
        execute(db, cfg, lease)
    else:
        pytest.fail('Unexpected unbounded old-publication work')
    old, old_files = {}, {}
    with db.transaction() as session:
        for i in range(20):
            edition = session.get(Edition, f'edition_{i}')
            assert edition.generation == 2 and edition.current_artifact_id
            old[i] = edition.current_artifact_id
            artifact = session.get(Artifact, old[i])
            for path in (cfg.data / artifact.storage_key).rglob('*'):
                if path.is_file():
                    old_files[path] = digest(path.read_bytes())
    rebuilds = {}
    for i in range(20):
        queued = client.post(f'/api/v1/artifacts/{old[i]}/rebuild', json={'template_id': 'reader-v2', 'preview_only': False, 'expected_generation': 2},
            headers={'If-Match': '"2"', 'Idempotency-Key': f'rebuild-reader-{i}'})
        assert queued.status_code == 202, queued.text
        rebuilds[i] = queued.json()['job_id']
    damaged = 7
    private_images[damaged].write_bytes(b'Controlled corruption after enqueue; not a PNG.')
    cache_writes = []

    def observe(conn, cursor, statement, parameters, context, many):
        sql = statement.strip().lower()
        if sql.startswith(('insert ', 'update ', 'delete ')) and 'translation_cache' in sql:
            cache_writes.append(sql)

    event.listen(db.engine, 'before_cursor_execute', observe)
    completed = set()
    try:
        with patch('packages.providers.openai_responses.OpenAIResponses.__init__', side_effect=AssertionError('Provider forbidden')) as provider:
            for count in range(100):
                lease = claim(db)
                if lease is None:
                    break
                execute(db, cfg, lease)
                if lease.kind == 'rebuild':
                    i = next(i for i, job in rebuilds.items() if job == lease.job_id)
                    completed.add(i)
                with db.transaction() as session:
                    for i in range(20):
                        edition = session.get(Edition, f'edition_{i}')
                        if i == damaged or i not in completed:
                            assert edition.current_artifact_id == old[i] and edition.generation == 2
                        else:
                            assert edition.current_artifact_id != old[i] and edition.generation == 3
                            verify_artifact(cfg.data / session.get(Artifact, edition.current_artifact_id).storage_key)
            else:
                pytest.fail('Unexpected unbounded rebuild work')
            assert provider.call_count == 0
    finally:
        event.remove(db.engine, 'before_cursor_execute', observe)
    assert len(completed) == 20 and cache_writes == []
    assert all(digest(path.read_bytes()) == sha for path, sha in old_files.items())
    facts = []
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Artifact)) == 39
        assert session.scalar(select(func.count()).select_from(Publication)) == 39
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
        assert session.scalar(select(func.count()).select_from(TranslationCache)) == 0
        for i in range(20):
            job, edition = session.get(Job, rebuilds[i]), session.get(Edition, f'edition_{i}')
            assert job.status == ('failed' if i == damaged else 'succeeded')
            assert session.get(Artifact, job.payload['artifact_id']) is None if i == damaged else True
            assert client.get(f'/artifacts/{old[i]}/index.html').status_code == 200
            facts.append({'document_id': f'doc_{i}', 'job_id': job.id, 'status': job.status, 'old_artifact_id': old[i],
                'current_artifact_id': edition.current_artifact_id, 'generation': edition.generation, 'error': job.error})
    record = {'status': 'passed', 'scope': '20 actual API-to-worker old publications then API-to-worker rebuilds; authored input IR, no parser/model quality claim',
        'corrupted_document': f'doc_{damaged}', 'provider_calls': 0, 'cache_writes': 0, 'artifacts': 39,
        'old_files_unchanged': len(old_files), 'documents': facts}
    path = ROOT / '.agent/tmp/evidence/reviews' / f'rebuild-batch-failure-{time.time_ns()}.json'
    path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
