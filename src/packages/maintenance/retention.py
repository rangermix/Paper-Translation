"""Bounded retention under the same exclusive session lock as backup/restore.

The public entry produces a dry-run plan unless apply=True. It never accepts a
caller-supplied deletion plan or arbitrary target paths. Registered artifacts,
including historical ones, remain referenced independently of current pointers.
"""
from datetime import datetime, timedelta
import os
from pathlib import Path
import re

from sqlalchemy import select, text

from packages.domain.errors import DomainError, require
from packages.domain.models import Artifact, Export, Idempotency, Settings, SourceDraft, Task, Upload, now
from packages.ir import digest, strict_loads
from packages.storage import safe_path

from packages.domain.workflow import TERMINAL_STATES
TERMINAL = TERMINAL_STATES
POLICY = {'upload_hours': 24, 'orphan_hours': 24, 'idempotency_days': 7, 'backup_days': 30}
MAX_SCANNED = 100_000


def _require_lock(connection, db):
    held = connection.scalar(text("""SELECT EXISTS (SELECT 1 FROM pg_locks
        WHERE locktype='advisory' AND pid=pg_backend_pid() AND classid=0
        AND objid=798205424 AND objsubid=1 AND mode='ExclusiveLock' AND granted)"""))
    require(held, 'MAINTENANCE_LOCK_REQUIRED', 'Retention requires the exclusive backup/maintenance lock.')
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        require(settings is not None and settings.maintenance and settings.dispatch_disabled, 'MAINTENANCE_REQUIRED')


def _link(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _under(key, prefixes):
    return any(key == prefix or key.startswith(prefix + '/') for prefix in prefixes)


def _fingerprint(path):
    stat = path.stat(follow_symlinks=False)
    return {'byte_size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'device': stat.st_dev, 'inode': stat.st_ino}


def retention_locked(db, cfg, backups, connection, *, apply=False, now_at=None, limit=1000):
    """Call only inside maintenance_window; apply replans in that same window."""
    require(type(limit) is int and 1 <= limit <= 10000, 'RETENTION_LIMIT_INVALID', status=422)
    _require_lock(connection, db)
    at = now_at or now()
    require(at.tzinfo is not None, 'RETENTION_TIME_INVALID', status=422)
    cutoff = (at - timedelta(hours=POLICY['orphan_hours'])).timestamp()
    backup_cutoff = at - timedelta(days=POLICY['backup_days'])
    roots = {'data': Path(cfg.data), 'uploads': Path(cfg.uploads), 'parser_inputs': Path(cfg.parser_inputs),
        'parser_outputs': Path(cfg.parser_outputs), 'backups': Path(backups)}
    for name, root in roots.items():
        require(not _link(root), 'RETENTION_UNSAFE_ROOT', details={'root': name})
        roots[name] = root.resolve()
    from packages.maintenance.__main__ import referenced_files
    references = set(referenced_files(db, cfg))
    protected_data = set()
    with db.transaction() as session:
        tasks = list(session.scalars(select(Task).where(Task.status.not_in(TERMINAL))))
        active_ids = {t.id for t in tasks}
        active_jobs = {t.job_id for t in tasks}
        heartbeat_path = roots['parser_outputs'] / 'heartbeat.json'
        if heartbeat_path.is_file() and not _link(heartbeat_path):
            try:
                heartbeat = strict_loads(heartbeat_path.read_bytes())
                if heartbeat.get('timestamp', 0) > at.timestamp() - 60 and isinstance(heartbeat.get('active_task'), str):
                    active_ids.add(heartbeat['active_task'])
            except (OSError, ValueError, TypeError):
                pass
        for artifact in session.scalars(select(Artifact)):
            # Keep every registered artifact directory, including extra evidence
            # files and historical/legacy versions not in the current pointer.
            safe_path(cfg.data, artifact.storage_key)
            protected_data.add(artifact.storage_key)
        for export in session.scalars(select(Export)):
            protected_data.add('exports/' + export.id)
        for draft in session.scalars(select(SourceDraft)):
            if draft.evidence.get('parser_output'):
                protected_data.add(safe_path(cfg.data, draft.evidence['parser_output']).parent.relative_to(roots['data']).as_posix())
        for task in tasks:
            artifact = task.payload.get('artifact_id')
            if artifact:
                # Publisher temporary directories have random names, so protect
                # the entire document artifact parent while a task is resumable.
                from packages.domain.models import Job
                job = session.get(Job, task.job_id)
                if job and job.document_id:
                    protected_data.add(f'documents/{job.document_id}/artifacts')
            if task.payload.get('export_id'):
                protected_data.add('exports/' + task.payload['export_id'])
        expired_rows = [u for u in session.scalars(select(Upload).where(Upload.expires_at <= at).order_by(Upload.expires_at, Upload.id))
            if u.status != 'expired' or safe_path(cfg.uploads, u.id).exists()]
        expired_uploads = [u.id for u in expired_rows if u.job_id not in active_jobs and not any(t.payload.get('upload_id') == u.id for t in tasks)][:limit]
        current_uploads = {u.id for u in session.scalars(select(Upload))} - set(expired_uploads)
        receipts = list(session.scalars(select(Idempotency).where(Idempotency.expires_at <= at).order_by(Idempotency.expires_at, Idempotency.key).limit(limit + 1)))
        expired_receipts = [{'key': r.key, 'method': r.method, 'path': r.path} for r in receipts[:limit]]
    plan = {'format': 'bilingual-retention-plan-v1', 'mode': 'apply' if apply else 'dry_run', 'at': at.isoformat(),
        'policy': POLICY.copy(), 'limit': limit, 'max_scanned_entries': MAX_SCANNED, 'files': [],
        'expired_upload_ids': expired_uploads, 'expired_idempotency': expired_receipts,
        'truncated': len(expired_rows) > limit or len(receipts) > limit, 'scanned_entries': 0,
        'skipped_links': 0, 'warnings': [], 'protected_active_tasks': len(active_ids)}
    selected = set()
    stopped = False

    def candidate(root_name, path, reason, *, age=True, protect=True):
        nonlocal stopped
        root = roots[root_name]
        key = path.relative_to(root).as_posix()
        if (root_name, key) in selected:
            return
        # Check resolved containment and every ancestor immediately before
        # including a path in a reviewable plan. No shell-built deletion occurs.
        checked = safe_path(root, key)
        if _link(checked) or not checked.is_file():
            return
        if protect and ((root_name, key) in references or root_name == 'data' and _under(key, protected_data)):
            return
        stat = checked.stat()
        if age and stat.st_mtime > cutoff:
            return
        if len(plan['files']) >= limit:
            plan['truncated'], stopped = True, True
            return
        plan['files'].append({'root': root_name, 'key': key, 'reason': reason, **_fingerprint(checked)})
        selected.add((root_name, key))

    def walk(root_name, start_key, reason, predicate=None, *, age=True, protect=True):
        nonlocal stopped
        root = roots[root_name]
        start = safe_path(root, start_key)
        if not start.exists() or _link(start):
            return
        stack = [start]
        while stack and not stopped:
            folder = stack.pop()
            with os.scandir(folder) as entries:
                for entry in entries:
                    plan['scanned_entries'] += 1
                    if plan['scanned_entries'] > MAX_SCANNED:
                        plan['truncated'], stopped = True, True
                        break
                    path = Path(entry.path)
                    if _link(path):
                        plan['skipped_links'] += 1
                        continue
                    key = path.relative_to(root).as_posix()
                    if predicate and not predicate(key):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        # Resolve containment before descending a directory.
                        safe_path(root, key)
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        candidate(root_name, path, reason, age=age, protect=protect)
                    if stopped:
                        break

    for upload_id in expired_uploads:
        walk('uploads', upload_id, 'upload_expired_24h', age=False, protect=False)
    for root_name in ('parser_inputs', 'parser_outputs'):
        root = roots[root_name]
        if not root.exists():
            plan['warnings'].append(root_name + ' volume is not mounted; parser-spool cleanup was not performed')
            continue
        for directory in root.iterdir():
            if stopped:
                break
            if _link(directory):
                plan['skipped_links'] += 1
                continue
            if directory.is_dir() and directory.name not in active_ids and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', directory.name):
                walk(root_name, directory.name, 'unreferenced_parser_fence_24h')
    # Orphan upload directories without DB rows are also temporary input. A
    # still-current Upload always protects its entire directory, not just chunks.
    if roots['uploads'].exists():
        for directory in roots['uploads'].iterdir():
            if directory.is_dir() and not _link(directory) and directory.name not in current_uploads and directory.name not in expired_uploads:
                walk('uploads', directory.name, 'orphan_upload_24h')
    if not active_ids:
        walk('data', 'staging', 'unreferenced_staging_24h')
    walk('data', 'artifacts', 'unregistered_artifact_24h')
    walk('data', 'exports', 'unreferenced_export_24h')
    documents = roots['data'] / 'documents'
    if documents.is_dir() and not _link(documents):
        for doc in documents.iterdir():
            if not doc.is_dir() or _link(doc) or stopped:
                continue
            walk('data', f'documents/{doc.name}/artifacts', 'unregistered_artifact_24h')
            walk('data', f'documents/{doc.name}/parser', 'unreferenced_parser_copy_24h',
                predicate=lambda key: not any('/parser/' + task + '/' in key + '/' for task in active_ids))
    # Only product-created backups have a retention policy. Unknown directories
    # and malformed finished manifests are preserved, not guessed disposable.
    if roots['backups'].is_dir():
        for directory in roots['backups'].iterdir():
            if stopped or not directory.is_dir() or _link(directory):
                continue
            if re.fullmatch(r'\.backup_[0-9a-f]{32}\.tmp', directory.name):
                walk('backups', directory.name, 'failed_backup_staging_24h')
            elif re.fullmatch(r'backup_[0-9a-f]{32}', directory.name):
                try:
                    manifest_path = safe_path(roots['backups'], directory.name + '/manifest.json', must_exist=True)
                    require(manifest_path.stat().st_size <= 20_000_000, 'BACKUP_MANIFEST_LIMIT')
                    manifest = strict_loads(manifest_path.read_bytes())
                    created = datetime.fromisoformat(manifest['created_at'].replace('Z', '+00:00'))
                    require(manifest.get('format') == 'bilingual-compose-backup-v1' and created.tzinfo, 'BACKUP_VERSION')
                    if created <= backup_cutoff:
                        links_before = plan['skipped_links']
                        walk('backups', directory.name, 'backup_retention_30_days', predicate=lambda key: key != directory.name + '/manifest.json', age=False)
                        # Keep the manifest until the last bounded pass. Without
                        # it the next run cannot prove the remaining backup age.
                        if not stopped and links_before == plan['skipped_links']:
                            candidate('backups', manifest_path, 'backup_retention_30_days', age=False)
                except (OSError, ValueError, KeyError, TypeError, DomainError):
                    plan['warnings'].append('Unrecognized backup preserved: ' + directory.name)
    plan['total_bytes'] = sum(f['byte_size'] for f in plan['files'])
    plan['plan_hash'] = digest({k: v for k, v in plan.items() if k != 'mode'})
    if not apply:
        return plan
    _require_lock(connection, db)
    # Mark input invalid before removing bytes; a filesystem failure can leave
    # harmless expired bytes, never a supposedly valid but partially deleted input.
    with db.transaction() as session:
        for uid in expired_uploads:
            upload = session.get(Upload, uid, with_for_update=True)
            require(upload is not None and upload.expires_at <= at, 'RETENTION_PLAN_STALE')
            if upload.status != 'expired':
                upload.status = 'expired'
                upload.generation += 1
        for item in expired_receipts:
            receipt = session.get(Idempotency, (item['key'], item['method'], item['path']), with_for_update=True)
            if receipt is not None and receipt.expires_at <= at:
                session.delete(receipt)
    removed = 0
    for item in plan['files']:
        root = roots[item['root']]
        target = safe_path(root, item['key'])
        if not target.exists():
            continue
        require(not _link(target) and target.is_file() and _fingerprint(target) == {k: item[k] for k in ('byte_size', 'mtime_ns', 'device', 'inode')}, 'RETENTION_PLAN_STALE')
        require(target.resolve().is_relative_to(root) and target.resolve() != root, 'RETENTION_UNSAFE_PATH')
        target.unlink()
        removed += 1
        parent = target.parent
        while parent != root and parent.resolve().is_relative_to(root) and not _link(parent):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return {**plan, 'removed_files': removed, 'maintenance': True, 'dispatch_disabled': True}
