"""Runs inside exact old/new app images; no external Provider is constructed."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import json
from pathlib import Path
import time

from sqlalchemy import func, select, text

from packages.domain.config import Config
from packages.domain.db import Database, SCHEMA_VERSION
from packages.domain.models import Artifact, Attempt, Document, Edition, Export, Job, Permit, Settings, Task
from packages.billing.ledger import budget_totals
from packages.jobs.queue import claim
from packages.maintenance.__main__ import referenced_files
from packages.storage import file_hash
from smoke_library import request

OUT = Path('/upgrade-evidence')
BASE = 'http://127.0.0.1:8080'


def prepare(db, cfg):
    from tests.support import seed_editor
    from apps.api.library import enqueue
    from workers.main import execute
    if SCHEMA_VERSION != 5:
        raise RuntimeError('The old application must actually declare schema5')
    seed_editor(db, cfg, legacy_schema=True)
    metadata = {'title': 'Controlled old schema5 library', 'tags': ['upgrade', 'same-backup'], 'starred': True}
    request(BASE, 'PATCH', '/api/v1/documents/doc_fixture', metadata, {'If-Match': '"1"'})
    qa, _ = request(BASE, 'POST', '/api/v1/drafts/draft_fixture/validate', {},
        {'If-Match': '"1"', 'Idempotency-Key': 'old-schema-qa'})
    if not qa['valid']:
        raise RuntimeError('Authored old-source QA failed')
    tr, _ = request(BASE, 'POST', '/api/v1/drafts/draft_fixture/seal',
        {'qa_id': qa['id'], 'qa_fingerprint': qa['fingerprint'], 'generation': 1},
        {'If-Match': '"1"', 'Idempotency-Key': 'old-schema-seal'}, 201)
    request(BASE, 'POST', '/api/v1/editions/edition_fixture/publish',
        {'translation_revision_id': tr['id'], 'expected_generation': 1},
        {'If-Match': '"1"', 'Idempotency-Key': 'old-schema-publish'}, 202)
    publication = claim(db)
    if publication is None or publication.kind != 'publish':
        raise RuntimeError('Expected an old binary publication lease')
    execute(db, cfg, publication)
    # Drain the real publication index, before adding the deliberately unfinished
    # local task that must survive this same backup.
    for _ in range(10):
        lease = claim(db)
        if not lease:
            break
        execute(db, cfg, lease)
    with db.transaction() as session:
        edition = session.get(Edition, 'edition_fixture')
        artifact = session.get(Artifact, edition.current_artifact_id)
        if not artifact:
            raise RuntimeError('Old worker did not produce an actual artifact')
        artifact_id, artifact_key, generation = artifact.id, artifact.storage_key, edition.generation
    export, _ = request(BASE, 'POST', '/api/v1/artifacts/'+artifact_id+'/exports',
        {'format': 'bundle', 'include_source': True}, {'Idempotency-Key': 'old-schema-export'}, 202)
    lease = claim(db)
    if lease is None or lease.kind != 'export':
        raise RuntimeError('Expected an actual old worker export')
    execute(db, cfg, lease)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.instance_budget_micro, settings.dispatch_disabled = 150000, True
        local = enqueue(session, 'index', {'edition_id': 'edition_fixture', 'generation': generation}, 'doc_fixture')
        local_job_id = local.id
        session.add(Job(id='upgrade_unknown_job', document_id='doc_fixture', stage='translate',
            status='outcome_unknown', budget_micro=150000,
            payload={'fixture_scope': 'Explicit synthetic ledger, never dispatched externally'}))
        session.flush()
        session.add(Task(id='upgrade_unknown_task', job_id='upgrade_unknown_job', kind='translate',
            status='outcome_unknown', fence=1, attempts=1))
        session.flush()
        session.add(Attempt(id='upgrade_unknown_attempt', job_id='upgrade_unknown_job',
            task_id='upgrade_unknown_task', fence=1, control_epoch=0, state='outcome_unknown',
            evidence=[{'kind': 'synthetic_unknown_fixture', 'reason': 'Controlled migration ledger; zero real requests'}]))
        session.flush()
        session.add(Permit(id='upgrade_unknown_permit', job_id='upgrade_unknown_job',
            attempt_id='upgrade_unknown_attempt', control_epoch=0, reserved_micro=80000, state='unknown',
            price_snapshot={'revision': 'synthetic-upgrade-fixture', 'currency': 'USD'}))
        session.flush()
        local_task = session.scalar(select(Task).where(Task.job_id == local_job_id))
        exported = session.get(Export, export['id'])
        if exported.status != 'succeeded':
            raise RuntimeError('Old application export failed')
        state = {'old_application_schema': SCHEMA_VERSION, 'document_id': 'doc_fixture',
            'source_revision_id': 'src_fixture', 'translation_revision_id': tr['id'],
            'artifact_id': artifact_id, 'artifact_key': artifact_key, 'export_id': export['id'],
            'export_key': exported.storage_key, 'local_job_id': local_job_id, 'local_task_id': local_task.id,
            'metadata': metadata, 'attempt_count': session.scalar(select(func.count()).select_from(Attempt)),
            'unknown_micro': 80000, 'external_provider_requests': 0,
            'scope': 'Authored source/translation fixture; old binary actually sealed, published and exported. The unknown Permit is explicitly synthetic.'}
    state['files'] = {name+'/'+key: file_hash((cfg.data if name == 'data' else cfg.uploads)/key)
        for name, key in referenced_files(db, cfg)}
    data, _ = request(BASE, 'GET', '/api/v1/documents/doc_fixture/original')
    if data != (cfg.data/'fixtures/sample.pdf').read_bytes():
        raise RuntimeError('Old original HTTP bytes disagree')
    (OUT/'old-state.json').write_text(json.dumps(state, indent=2)+'\n')
    print(json.dumps({'status': 'old_fixture_prepared', 'schema': SCHEMA_VERSION,
        'file_count': len(state['files']), 'artifact_id': artifact_id,
        'pending_local_task': local_task.id, 'synthetic_unknown_micro': 80000, 'external_provider_requests': 0}))


def verify(db, cfg, resumed):
    state = json.loads((OUT/'old-state.json').read_text())
    if SCHEMA_VERSION != 10:
        raise RuntimeError('The new binary must actually declare schema10')
    for path, expected in state['files'].items():
        volume, key = path.split('/', 1)
        if file_hash((cfg.data if volume == 'data' else cfg.uploads)/key) != expected:
            raise RuntimeError('Restored immutable file differs: '+path)
    with db.transaction() as session:
        schema = session.scalar(text('SELECT max(version) FROM schema_migrations'))
        if schema != 10:
            raise RuntimeError('The restored database was not migrated to schema10')
        settings = session.get(Settings, 'singleton')
        if settings.maintenance != (not resumed) or not settings.dispatch_disabled:
            raise RuntimeError('Restore dispatch/maintenance policy was not preserved')
        document = session.get(Document, state['document_id'])
        if any(getattr(document, key) != value for key, value in state['metadata'].items()):
            raise RuntimeError('Catalog metadata did not survive the same old backup')
        task = session.get(Task, state['local_task_id'])
        if task.status != ('succeeded' if resumed else 'pending') or task.fence != (1 if resumed else 0):
            raise RuntimeError('Unfinished local task did not stay fenced or resume exactly once')
        if session.get(Job, 'upgrade_unknown_job').status != 'outcome_unknown' or session.get(Task, 'upgrade_unknown_task').status != 'outcome_unknown':
            raise RuntimeError('Unknown remote outcome was automatically resumed')
        attempt = session.get(Attempt, 'upgrade_unknown_attempt')
        if attempt.usage is not None or attempt.request_id is not None or attempt.state != 'outcome_unknown':
            raise RuntimeError('Synthetic unknown attempt acquired invented evidence')
        totals = budget_totals(session)
        if totals != {'actual_micro': 0, 'reserved_micro': 0, 'unknown_micro': 80000}:
            raise RuntimeError('Unknown risk was dropped or altered')
        if session.scalar(select(func.count()).select_from(Permit)) != 1:
            raise RuntimeError('An additional external dispatch permit was created')
        count = session.scalar(select(func.count()).select_from(Attempt))
        if count != state['attempt_count']+int(resumed):
            raise RuntimeError('Unexpected task attempts after restore')
        edition = session.get(Edition, 'edition_fixture')
        if edition.experimental is not False or edition.current_artifact_id != state['artifact_id']:
            raise RuntimeError('Edition migration default/current pointer changed')
    if not resumed and claim(db) is not None:
        raise RuntimeError('Maintenance did not prevent actual queue claim')
    original, _ = request(BASE, 'GET', '/api/v1/documents/doc_fixture/original')
    html, _ = request(BASE, 'GET', '/artifacts/'+state['artifact_id']+'/index.html')
    exported, _ = request(BASE, 'GET', '/api/v1/exports/'+state['export_id']+'/download')
    if original != (cfg.data/'fixtures/sample.pdf').read_bytes() or html != (cfg.data/state['artifact_key']/'index.html').read_bytes() or exported != (cfg.data/state['export_key']).read_bytes():
        raise RuntimeError('Restored public bytes differ from frozen old originals')
    result = {'status': 'passed', 'phase': 'resumed' if resumed else 'held', 'schema': schema,
        'all_old_files_equal': True, 'file_count': len(state['files']), 'local_task': task.status,
        'local_fence': task.fence, 'attempt_count': count, 'unknown_micro': 80000,
        'maintenance': not resumed, 'dispatch_disabled': True, 'external_provider_requests': 0}
    (OUT/('verify-resumed.json' if resumed else 'verify-held.json')).write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'verify-held', 'verify-resumed'])
    args = parser.parse_args()
    cfg = Config.load()
    db = Database(cfg)
    if args.phase == 'prepare':
        prepare(db, cfg)
    else:
        if args.phase == 'verify-resumed':
            deadline = time.monotonic()+20
            while time.monotonic() < deadline:
                state = json.loads((OUT/'old-state.json').read_text())
                with db.transaction() as session:
                    if session.get(Task, state['local_task_id']).status == 'succeeded':
                        break
                time.sleep(.2)
        verify(db, cfg, args.phase == 'verify-resumed')


if __name__ == '__main__':
    main()
