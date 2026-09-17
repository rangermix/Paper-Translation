"""Production worker: durable PostgreSQL jobs, isolated parser spool, immutable files."""
import argparse
from packages.parsers.models import parser_version
from packages.parsers.profiles import selected_profile
from packages.parsers.timeouts import PARSER_RESULT_GRACE_SECONDS, task_timeout_seconds
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import shutil
import signal
import threading
import time

from sqlalchemy import select, text

from packages.domain.config import Config
from packages.domain.db import Database, get_document, get_entity, lock_lifecycle, writable
from packages.domain.errors import DomainError, require
from packages.domain.models import (Artifact, Document, Edition, Export, Heartbeat, Job,
    SourceAsset, SourceDraft, SourceRevision, Task, TranslationRevision, Upload, new_id, now)
from packages.ir import canonical_bytes, digest, strict_loads, validate_source
from packages.jobs.queue import assert_current, claim, emit, finish, recover_expired, renew
from packages.parsers.spool import verify_result, write_request
from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact
from packages.storage import atomic_write, file_hash, read_snapshot, safe_path


log = logging.getLogger('library.worker')


def parse_spool(db, cfg, lease):
    with db.transaction() as session:
        job, task = assert_current(session, lease)
        if lease.kind == 'inspect' and lease.payload.get('upload_id'):
            upload = get_entity(session, Upload, lease.payload['upload_id'])
            source_pdf = safe_path(cfg.uploads, f'{upload.id}/original.pdf', must_exist=True)
            sha, asset_id, language = upload.sha256, None, 'und'
        else:
            doc = get_document(session, lease.document_id)
            asset = get_entity(session, SourceAsset, lease.payload['source_asset_id'])
            require(doc.source_asset_id == asset.id, 'SOURCE_STALE')
            source_pdf = safe_path(cfg.data, asset.storage_key, must_exist=True)
            sha, asset_id, language = asset.sha256, asset.id, lease.payload.get('source_language', doc.source_language)
        timeout_seconds = task_timeout_seconds(lease.payload, lease.kind)
        expires_at = now() + timedelta(seconds=timeout_seconds)
        descriptor = {'task_id': lease.task_id, 'fence': lease.fence, 'source_sha256': sha,
            'max_pages': cfg.max_pages, 'deadline': expires_at.isoformat(), 'timeout_seconds': timeout_seconds,
            'parser_version': 'inspector-v1' if lease.kind == 'inspect' else parser_version(selected_profile(lease.payload)),
            'operation': lease.kind, 'profile': {'language': language if language != 'auto' else 'und'}}
        if asset_id:
            descriptor['asset_id'] = asset_id
        if lease.kind == 'parse':
            descriptor['profile']['parser_profile_revision'] = selected_profile(lease.payload)
            if lease.payload.get('parser_accelerator'):
                descriptor['accelerator'] = lease.payload['parser_accelerator']
    write_request(cfg.parser_inputs, descriptor, source_pdf)
    output_dir = cfg.parser_outputs / lease.task_id / str(lease.fence)
    deadline = time.monotonic() + max(0, (expires_at - now()).total_seconds()) + PARSER_RESULT_GRACE_SECONDS
    progress_cursor = 0
    while time.monotonic() < deadline:
        from packages.parsers.progress import read_progress
        from packages.jobs.history import record_log, set_actual_model
        try:
            updates = read_progress(output_dir, descriptor, progress_cursor)
        except (ValueError, OSError):
            updates = []
        if updates:
            with db.transaction() as session:
                job, task = assert_current(session, lease)
                for event in updates:
                    record_log(session, job, event_key=f'parser:{lease.task_id}:{lease.fence}:{event["sequence"]}',
                        operation=event['operation'], task_id=lease.task_id, attempt_id=lease.attempt_id,
                        page=event.get('page'), at=datetime.fromisoformat(event['at']),
                        details={'sequence': event['sequence'], 'fence': lease.fence})
                    if event.get('model') and event['operation'] != 'loading_model':
                        set_actual_model(session, lease, event['model'])
                progress_cursor = updates[-1]['sequence']
        if (output_dir / 'result.json').exists():
            result = verify_result(output_dir, descriptor)
            require(result['status'] == 'succeeded', (result.get('error') or {}).get('code', 'PARSER_FAILED'))
            require('payload.json' in {f['path'] for f in result['files']}, 'PARSER_OUTPUT_MISSING_PAYLOAD')
            payload_entry = next(entry for entry in result['files'] if entry['path'] == 'payload.json')
            payload_bytes = safe_path(output_dir, 'payload.json', must_exist=True).read_bytes()
            require(len(payload_bytes) == payload_entry['byte_size'] and digest(payload_bytes) == payload_entry['sha256'], 'PARSER_OUTPUT_HASH_MISMATCH')
            payload = strict_loads(payload_bytes)
            if lease.kind == 'parse':
                require(selected_profile(payload) == selected_profile(lease.payload), 'PARSER_PROFILE_MISMATCH')
            break
        with db.transaction() as session:
            assert_current(session, lease)
        time.sleep(.4)
    else:
        raise DomainError('PARSER_TIMEOUT')
    if lease.kind == 'inspect':
        with db.transaction() as session:
            writable(session)
            session.execute(text('SELECT pg_advisory_xact_lock(798205425)'))
            job, task = assert_current(session, lease)
            upload = get_entity(session, Upload, lease.payload['upload_id'], lock=True) if lease.payload.get('upload_id') else None
            require(payload.get('valid') and payload['sha256'] == sha and (not upload or payload['byte_size'] == upload.byte_size) and 0 < payload['page_count'] <= cfg.max_pages, 'PDF_INVALID')
            if lease.document_id:
                require(get_document(session, lease.document_id, lock=True).source_asset_id == lease.payload['source_asset_id'], 'SOURCE_STALE')
            session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': int(sha[:15], 16)})
            asset = session.scalar(select(SourceAsset).where(SourceAsset.sha256 == sha))
            if asset is None:
                asset_id = new_id('asset')
                key = f'sources/{asset_id}/original.pdf'
                atomic_write(cfg.data, key, source_pdf.read_bytes())
                asset = SourceAsset(id=asset_id, sha256=sha, byte_size=payload['byte_size'], page_count=payload['page_count'], storage_key=key)
                session.add(asset)
                session.flush()
            if not asset.doi_discovery:
                asset.doi_discovery = payload.get('doi_discovery') or {'status': 'no_doi', 'selected': None, 'candidates': []}
            if upload:
                upload.source_asset_id, upload.status = asset.id, 'verified'
                upload.doi_discovery = asset.doi_discovery
                upload.generation += 1
            from packages.metadata.execution import enqueue_metadata
            enqueue_metadata(session, asset, parent_job_id=job.id, document_id=lease.document_id)
            job.progress = {'checked_pages': asset.page_count, 'total_pages': asset.page_count}
            finish(session, lease, {'source_asset_id': asset.id})
        return
    prefix = f'documents/{lease.document_id}/parser/{lease.task_id}/{lease.fence}'
    with db.transaction() as session:
        job, task = assert_current(session, lease)
        doc = get_document(session, lease.document_id, lock=True)
        require(doc.source_asset_id == lease.payload['source_asset_id'], 'SOURCE_STALE')
        require(doc.current_source_id == lease.payload.get('base_revision_id'), 'SOURCE_BASE_STALE')
        # Copy only after fencing, and keep cleanup excluded until every local
        # output is committed. A late parser must not recreate deleted bytes.
        for entry in result['files']:
            file = safe_path(output_dir, entry['path'], must_exist=True)
            data = file.read_bytes()
            require(len(data) == entry['byte_size'] and digest(data) == entry['sha256'], 'PARSER_OUTPUT_HASH_MISMATCH')
            atomic_write(cfg.data, prefix + '/' + entry['path'], data)
        source = payload.get('source_revision')
        if source:
            for asset in source['assets']:
                asset['storage_key'] = prefix + '/' + asset['storage_key']
            validate_source(source, asset_root=cfg.data)
        images = {str(p['page']): prefix + '/' + p['page_image'] for p in payload['inspection']['pages'] if p.get('page_image')}
        doc.generation += 1
        draft = SourceDraft(id=new_id('srcdraft'), document_id=doc.id, asset_id=doc.source_asset_id,
            source=source or {}, base_revision_id=doc.current_source_id, coverage=payload['coverage'], evidence={'page_images': images,
                'document_generation': doc.generation, 'job_id': job.id, 'attempt_id': lease.attempt_id,
                'inspection': payload['inspection'], 'parser_output': prefix + '/payload.json'})
        session.add(draft)
        doc.status = 'preflight'
        job.progress = {'checked_pages': payload['inspection']['page_count'], 'total_pages': payload['inspection']['page_count'],
            'blocks': len(source['blocks']) if source else 0, 'unresolved': len(payload['coverage']['unresolved'])}
        from packages.quality.issues import aggregate_source_issues
        diagnostics = aggregate_source_issues(payload['coverage'], source or {})
        job.quality_summary = diagnostics['quality']
        session.flush()
        from packages.jobs.stages import completed_stage, record_recovery
        recoveries = record_recovery(session, job, draft, payload['inspection'].get('automatic_recovery', []))
        if recoveries:
            job.progress = job.progress | {'recovery_job_ids': recoveries}
        check = payload['inspection'].get('quality_check')
        if check:
            receipt = completed_stage(session, stage='quality_check', document_id=doc.id, parent_job_id=job.id,
                started_at=datetime.fromisoformat(check['started_at']), finished_at=datetime.fromisoformat(check['finished_at']),
                status='failed' if check['state'] == 'failed' else 'succeeded', code='CHECK_FAILED' if check['state'] == 'failed' else None,
                payload={'source_draft_id': draft.id}, result={'issues': len(diagnostics['issues'])})
            receipt.quality_summary = diagnostics['quality']
        from packages.translation.pipeline import advance_parse
        advance_parse(session, cfg, draft, job)
        asset = session.get(SourceAsset, draft.asset_id)
        if source and not (asset.doi_discovery or {}).get('selected'):
            from packages.metadata.discovery import discover_doi
            from packages.metadata.execution import enqueue_metadata
            pages = []
            for number in range(1, min(2, payload['inspection']['page_count'])+1):
                regions = [{'text': block['normalized_text'], 'bbox': loc['bbox']} for block in source['blocks']
                    for loc in block['provenance'] if loc['page'] == number and block['normalized_text']]
                pages.append({'page': number, 'text_regions': regions, 'links': []})
            supplement = discover_doi({}, pages)
            if supplement.get('selected'):
                supplement['origin'] = 'local_parser_output'
                asset.doi_discovery = supplement
                enqueue_metadata(session, asset, parent_job_id=job.id, document_id=doc.id)
        finish(session, lease, {'import_id': draft.id}, status='completed_with_warnings' if diagnostics['issues'] else 'succeeded')


def publish(db, cfg, lease):
    from packages.editorial.drafts import render_input
    from packages.publisher.history import commit_publication
    with db.transaction() as session:
        job, _ = assert_current(session, lease)
        tr_entity = get_entity(session, TranslationRevision, lease.payload['translation_revision_id'])
        source_entity = get_entity(session, SourceRevision, tr_entity.source_revision_id)
        translation = read_snapshot(cfg.data, tr_entity)
        source = read_snapshot(cfg.data, source_entity)
        ir = render_input(lease.document_id, source, translation, lease.payload['template_id'])
        qa_fingerprint = tr_entity.qa_fingerprint
        artifact_id = lease.payload['artifact_id']
        key = f'documents/{lease.document_id}/artifacts/{artifact_id}'
        directory = safe_path(cfg.data, key)
        if directory.exists():
            manifest = verify_artifact(directory)
            require(manifest['source_snapshot_hash'] == digest(source) and manifest['translation_snapshot_hash'] == digest(translation), 'ARTIFACT_CONFLICT')
        else:
            manifest = Publisher().build(ir, cfg.data, directory, include_source=True, qa_fingerprint=qa_fingerprint)
    with db.transaction() as session:
        job, _ = assert_current(session, lease)
        get_document(session, lease.document_id, lock=True)
        edition = get_entity(session, Edition, lease.payload['edition_id'], lock=True)
        require(edition.document_id == lease.document_id and edition.id == tr_entity.edition_id, 'EDITION_MISMATCH')
        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            artifact = Artifact(id=artifact_id, document_id=lease.document_id, edition_id=edition.id,
                source_revision_id=source_entity.id, translation_revision_id=tr_entity.id,
                template_id=lease.payload['template_id'], storage_key=key, manifest_hash=digest(manifest))
            session.add(artifact)
            session.flush()
        if not lease.payload.get('preview_only'):
            commit_publication(session, cfg, edition, artifact, lease.payload['expected_generation'], 'publish')
        finish(session, lease, {'artifact_id': artifact.id, 'preview_only': bool(lease.payload.get('preview_only'))},
            status=job.payload.get('result_status', 'succeeded'))


def export(db, cfg, lease):
    with db.transaction() as session:
        assert_current(session, lease)
        export_entity = get_entity(session, Export, lease.payload['export_id'])
        draft_snapshot = None
        if export_entity.draft_snapshot_key:
            data = safe_path(cfg.data, export_entity.draft_snapshot_key, must_exist=True).read_bytes()
            require(digest(data) == export_entity.draft_snapshot_hash, 'DRAFT_EXPORT_CORRUPT')
            draft_snapshot = strict_loads(data)
            require(draft_snapshot['render']['mode'] == 'draft', 'DRAFT_EXPORT_INVALID')
            directory = safe_path(cfg.data, f'exports/{export_entity.id}/rendered')
        else:
            artifact = get_entity(session, Artifact, export_entity.artifact_id)
            directory = safe_path(cfg.data, artifact.storage_key)
        extension = '.html' if export_entity.format == 'single_html' else '.zip'
        key = f'exports/{export_entity.id}/document' + extension
        target = safe_path(cfg.data, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        include = export_entity.include_source
        if draft_snapshot:
            if not directory.exists():
                Publisher().build(draft_snapshot, cfg.data, directory, include_source=include)
            else:
                manifest = verify_artifact(directory)
                require(manifest['mode'] == 'draft' and manifest['source_snapshot_hash'] == digest(draft_snapshot['source_revision'])
                    and manifest['translation_snapshot_hash'] == digest(draft_snapshot['translation_revision']), 'DRAFT_EXPORT_CONFLICT')
        if not target.exists():
            temp = target.with_suffix('.tmp')
            temp.unlink(missing_ok=True)
            (export_single_html if extension == '.html' else export_bundle)(directory, temp, include_source=include)
            os.replace(temp, target)
        export_entity.storage_key, export_entity.sha256, export_entity.status = key, file_hash(target), 'succeeded'
        finish(session, lease, {'export_id': export_entity.id})


def execute(db, cfg, lease):
    # Hold only a session advisory lock, with no open transaction or row locks,
    # across local file production. Maintenance drains these bounded operations.
    guard = db.engine.connect()
    guard.execute(text('SELECT pg_advisory_lock_shared(798205424)'))
    guard.commit()
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(15):
            try:
                if not renew(db, lease, cfg.lease_seconds):
                    return
            except Exception:
                return
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        if lease.kind in ('inspect', 'parse'):
            parse_spool(db, cfg, lease)
        elif lease.kind in ('publish', 'rebuild'):
            publish(db, cfg, lease)
        elif lease.kind == 'export':
            export(db, cfg, lease)
        elif lease.kind in ('translate', 'candidate', 'semantic_review'):
            from packages.translation.execution import execute_translation
            execute_translation(db, cfg, lease)
        elif lease.kind == 'provider_test':
            from packages.providers.connection import execute_test
            execute_test(db, cfg, lease)
        elif lease.kind == 'metadata_lookup':
            from packages.metadata.execution import execute_metadata
            execute_metadata(db, cfg, lease)
        elif lease.kind == 'cleanup':
            from packages.privacy import cleanup_document
            cleanup_document(db, cfg, lease)
        elif lease.kind == 'index':
            from packages.search import update_index
            update_index(db, cfg, lease)
        else:
            raise DomainError('TASK_KIND_UNKNOWN')
    except Exception as exc:
        code = exc.code if isinstance(exc, DomainError) else 'WORKER_FAILED'
        log.error('task_failed task=%s fence=%s code=%s type=%s', lease.task_id, lease.fence, code, type(exc).__name__)
        with db.transaction() as session:
            lock_lifecycle(session, allow_maintenance=True)
            task = session.get(Task, lease.task_id)
            job = session.get(Job, lease.job_id)
            if task and task.fence == lease.fence and task.status == 'leased' and job.control_epoch == lease.control_epoch:
                # Paid execution classifies dispatch uncertainty before raising; never reset it here.
                from packages.domain.models import Attempt, Permit
                attempt = session.get(Attempt, lease.attempt_id)
                permit = session.scalar(select(Permit).where(Permit.attempt_id == attempt.id))
                if permit and permit.state in ('reserved', 'unknown'):
                    permit.state, attempt.state, task.status, job.status = 'unknown', 'outcome_unknown', 'outcome_unknown', 'outcome_unknown'
                elif code == 'CONTROL_CHANGED' and job.status in {'pending', 'paused', 'waiting_config', 'waiting_budget', 'outcome_unknown'}:
                    # A sibling unit can pause dispatch or yield capacity while
                    # this lease is already running. Preserve that scheduling
                    # state and its cause; it is not a failure of this job.
                    task.status = 'pending'
                    if permit is None:
                        task.attempts = max(0, task.attempts - 1)
                        attempt.state = 'not_executed'
                    attempt.finished_at = now()
                    emit(session, job)
                    return
                else:
                    task.status, job.status = 'failed', 'failed'
                job.error = {'code': code}
                if lease.kind == 'inspect' and lease.payload.get('upload_id'):
                    upload = session.get(Upload, lease.payload['upload_id'])
                    upload.status, upload.error = 'failed', {'code': code}
                    upload.generation += 1
                emit(session, job)
    finally:
        stop.set()
        thread.join(timeout=1)
        guard.execute(text('SELECT pg_advisory_unlock_shared(798205424)'))
        guard.commit()
        guard.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--health', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    cfg = Config.load()
    db = Database(cfg)
    if args.health:
        with db.transaction() as session:
            pulse = session.get(Heartbeat, 'worker')
            require(pulse and pulse.at > now() - timedelta(seconds=45), 'WORKER_UNHEALTHY', status=503)
        return
    stopping = threading.Event()
    def stop_claiming(_signum, _frame):
        stopping.set()
    signal.signal(signal.SIGTERM, stop_claiming)
    signal.signal(signal.SIGINT, stop_claiming)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = set()
        while not stopping.is_set():
            try:
                with db.transaction() as session:
                    pulse = session.get(Heartbeat, 'worker')
                    if pulse:
                        pulse.at = now()
                    else:
                        session.add(Heartbeat(id='worker'))
                    try:
                        timestamp = strict_loads((cfg.parser_outputs / 'heartbeat.json').read_bytes())['timestamp']
                        observed = datetime.fromtimestamp(timestamp, timezone.utc)
                        require(observed <= now() + timedelta(seconds=5), 'PARSER_CLOCK_INVALID')
                        parser_pulse = session.get(Heartbeat, 'parser')
                        if parser_pulse:
                            parser_pulse.at = observed
                        else:
                            session.add(Heartbeat(id='parser', at=observed))
                    except (OSError, ValueError, KeyError, TypeError, DomainError):
                        pass  # The previous pulse expires; invalid input cannot mark readiness.
                recover_expired(db)
                futures = {f for f in futures if not f.done()}
                if len(futures) < 4 and not stopping.is_set():
                    lease = claim(db, cfg.lease_seconds)
                    if lease:
                        futures.add(pool.submit(execute, db, cfg, lease))
                if args.once:
                    for future in futures:
                        future.result()
                    return
            except Exception as exc:
                log.error('worker_tick_failed type=%s', type(exc).__name__)
                if args.once:
                    raise
            stopping.wait(1)


if __name__ == '__main__':
    main()
