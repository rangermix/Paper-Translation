"""Tombstones take effect at API time; cleanup removes all derivative content."""
from pathlib import Path
import shutil

from sqlalchemy import delete, select, text, update

from packages.domain.errors import require
from packages.domain.db import writable
from packages.domain.models import (Artifact, Attempt, Candidate, Document, Draft, Edition, Event, Export, Glossary,
    Idempotency, IssueResolution, Job, Publication, QA, ReadingPosition, ReviewRecord, SearchEntry, SegmentVersion,
    SourceAsset, SourceDraft, SourceRevision, Task, TaskLog, TranslationCache, TranslationMemory, TranslationRevision, Upload)
from packages.jobs.queue import assert_current, finish
from packages.storage import atomic_write, safe_path


def remove_tree(root, key):
    target = safe_path(root, key)
    require(target.resolve().is_relative_to(Path(root).resolve()) and target.resolve() != Path(root).resolve(), 'UNSAFE_CLEANUP_PATH')
    require(not target.is_symlink(), 'UNSAFE_CLEANUP_PATH')
    if target.is_dir():
        shutil.rmtree(target)
    elif target.is_file():
        target.unlink()


def erase_parser_task(cfg, task_id):
    # A read-only parser observes this marker and terminates its child before
    # removing late output. Keep the marker until retention's orphan grace.
    atomic_write(cfg.parser_inputs, task_id + '/cancelled.json', b'{"cancelled":true}', immutable=False)
    task_root = safe_path(cfg.parser_inputs, task_id)
    for entry in task_root.iterdir():
        if entry.name != 'cancelled.json':
            remove_tree(cfg.parser_inputs, entry.relative_to(cfg.parser_inputs).as_posix())
    remove_tree(cfg.parser_outputs, task_id)


def erase_job_content(session, job):
    job.payload = {}
    job.title_snapshot = None
    job.error = {'code': job.error['code']} if job.error and job.error.get('code') else None
    job.progress = {key: value for key, value in job.progress.items() if type(value) in (int, float, bool)} | {'content_deleted': True}
    session.execute(update(TaskLog).where(TaskLog.job_id == job.id).values(unit_id=None))
    for event in session.scalars(select(Event).where(Event.job_id == job.id)):
        event.payload = {'stage': job.stage, 'status': job.status, 'content_deleted': True}
    for attempt in session.scalars(select(Attempt).where(Attempt.job_id == job.id)):
        attempt.evidence = [{key: value for key, value in entry.items() if key in
            {'kind', 'at', 'origin', 'unit_hash', 'decision', 'request_id'}} for entry in attempt.evidence]


def cleanup_document(db, cfg, lease):
    with db.transaction() as session:
        writable(session)
        session.execute(text('SELECT pg_advisory_xact_lock(798205425)'))
        assert_current(session, lease)
        document = session.scalar(select(Document).where(Document.id == lease.document_id).with_for_update())
        require(document and document.deleted_at, 'TOMBSTONE_REQUIRED')
        session.execute(update(Idempotency).where(Idempotency.document_ids.contains([document.id])).values(response={'body': {}, 'status': 410}))
        asset_ids = {document.source_asset_id}
        for model in (SourceRevision, SourceDraft):
            asset_ids.update(session.scalars(select(model.asset_id).where(model.document_id == document.id)))
        asset_ids.discard(None)
        drafts = list(session.scalars(select(Draft.id).where(Draft.document_id == document.id)))
        editions = list(session.scalars(select(Edition.id).where(Edition.document_id == document.id)))
        for export in session.scalars(select(Export).where(Export.document_id == document.id)):
            remove_tree(cfg.data, 'exports/' + export.id)
        session.execute(delete(SearchEntry).where(SearchEntry.document_id == document.id))
        session.execute(delete(ReadingPosition).where(ReadingPosition.document_id == document.id))
        session.execute(delete(TranslationCache).where(TranslationCache.document_id == document.id))
        session.execute(delete(TranslationMemory).where(TranslationMemory.document_id == document.id, TranslationMemory.independent.is_(False)))
        session.execute(update(TranslationMemory).where(TranslationMemory.document_id == document.id, TranslationMemory.independent.is_(True)).values(document_id=None))
        for model in (Candidate, IssueResolution, ReviewRecord, QA, SegmentVersion):
            session.execute(delete(model).where(model.draft_id.in_(drafts)))
        session.execute(delete(Export).where(Export.document_id == document.id))
        session.execute(delete(Publication).where(Publication.edition_id.in_(editions)))
        session.execute(delete(Artifact).where(Artifact.document_id == document.id))
        session.execute(delete(Draft).where(Draft.document_id == document.id))
        session.execute(delete(TranslationRevision).where(TranslationRevision.document_id == document.id))
        session.execute(delete(SourceRevision).where(SourceRevision.document_id == document.id))
        session.execute(delete(SourceDraft).where(SourceDraft.document_id == document.id))
        session.execute(delete(Edition).where(Edition.document_id == document.id))
        session.execute(delete(Glossary).where(Glossary.document_id == document.id))
        jobs = list(session.scalars(select(Job).where(Job.document_id == document.id).with_for_update()))
        for job in jobs:
            erase_job_content(session, job)
            for task in session.scalars(select(Task).where(Task.job_id == job.id)):
                if task.kind in ('parse', 'inspect'):
                    erase_parser_task(cfg, task.id)
                task.payload, task.result = {}, None
                if task.id != lease.task_id and task.status not in ('succeeded', 'failed'):
                    task.status = 'cancelled'
        document.source_asset_id, document.current_source_id = None, None
        document.title, document.tags, document.status = 'Deleted document', [], 'deleted'
        document.original_filename, document.title_origin, document.title_user_edited = None, None, None
        document.starred = False
        session.flush()
        remove_tree(cfg.data, f'documents/{document.id}')
        for asset_id in sorted(asset_ids):
            referenced = session.scalar(select(Document.id).where(Document.source_asset_id == asset_id).limit(1))
            referenced = referenced or session.scalar(select(SourceRevision.id).where(SourceRevision.asset_id == asset_id).limit(1))
            referenced = referenced or session.scalar(select(SourceDraft.id).where(SourceDraft.asset_id == asset_id).limit(1))
            if referenced:
                continue
            # Verified upload receipts cannot resurrect a removed source after deletion.
            for upload in session.scalars(select(Upload).where(Upload.source_asset_id == asset_id)):
                for receipt in session.scalars(select(Idempotency).where(
                        (Idempotency.path.contains('/uploads/' + upload.id, autoescape=True))
                        | (Idempotency.response['body']['id'].astext == upload.id)
                        | (Idempotency.response['body']['upload_id'].astext == upload.id))):
                    receipt.response, receipt.document_ids = {'body': {}, 'status': 410}, [document.id]
                upload.source_asset_id, upload.status, upload.chunks, upload.received_bytes = None, 'deleted', [], 0
                upload.filename = 'Deleted upload'
                upload.doi_discovery = None
                upload.generation += 1
                if upload.job_id:
                    inspect_job = session.get(Job, upload.job_id)
                    if inspect_job:
                        erase_job_content(session, inspect_job)
                        for task in session.scalars(select(Task).where(Task.job_id == inspect_job.id)):
                            if task.kind == 'inspect':
                                erase_parser_task(cfg, task.id)
                            task.payload, task.result = {}, None
                remove_tree(cfg.uploads, upload.id)
            asset = session.get(SourceAsset, asset_id)
            if asset:
                safe_path(cfg.data, asset.storage_key).unlink(missing_ok=True)
                session.delete(asset)
        finish(session, lease, {'deleted': True, 'backups': 'Backups older than 30 days are removed by Compose retention --apply; downloaded copies remain outside this instance.'})
