import argparse
from contextlib import contextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote, urlsplit

from sqlalchemy import select, text

from packages.domain.config import Config
from packages.domain.db import Database, SCHEMA_VERSION
from packages.domain.errors import require
from packages.domain.models import Artifact, Attempt, Export, Job, Permit, Settings, SourceAsset, SourceDraft, SourceRevision, Task, TranslationRevision, Upload, new_id, now
from packages.ir import canonical_bytes, digest, strict_loads
from packages.publisher import verify_artifact
from packages.storage import atomic_write, file_hash, read_snapshot, safe_path


def init_volumes():
    require(os.name == 'posix' and os.getuid() == 0, 'INIT_REQUIRES_COMPOSE_ROOT')
    # These are fixed named-volume mountpoints; never enumerate or modify a host tree.
    for target in ('/data', '/uploads', '/internal', '/parser_inputs', '/parser_outputs', '/backups'):
        path = Path(target)
        require(path.is_dir() and not path.is_symlink(), 'VOLUME_MISSING')
        os.chown(path, 10001, 10001)
        os.chmod(path, 0o755)
    provider_config = Path('/provider_config')
    require(provider_config.is_dir() and not provider_config.is_symlink(), 'VOLUME_MISSING')
    os.chown(provider_config, 10001, 10001)
    os.chmod(provider_config, 0o700)
    pgdata = Path('/pgdata')
    require(pgdata.is_dir() and not pgdata.is_symlink(), 'VOLUME_MISSING')
    os.chown(pgdata, 999, 999)
    os.chmod(pgdata, 0o700)
    password_path = Path('/internal/db_password')
    if not password_path.exists():
        atomic_write('/internal', 'db_password', secrets.token_urlsafe(40).encode())
    os.chown(password_path, 10001, 10001)
    # Only db/app/worker/migrate/maintenance receive this internal named volume.
    os.chmod(password_path, 0o644)
    config = Path('/internal/database.json')
    if not config.exists():
        password = password_path.read_text()
        atomic_write('/internal', 'database.json', canonical_bytes({'url': 'postgresql+psycopg://library_runtime:' + quote(password, safe='') + '@db:5432/library'}))
    os.chown(config, 10001, 10001)
    os.chmod(config, 0o600)
    print(json.dumps({'status': 'initialized', 'secrets': 'not displayed'}))


def uncertain_inflight(session):
    for permit in session.scalars(select(Permit).where(Permit.state == 'reserved').with_for_update()):
        permit.state = 'unknown'
        attempt = session.get(Attempt, permit.attempt_id)
        attempt.state = 'outcome_unknown'
        task = session.get(Task, attempt.task_id)
        task.status = 'outcome_unknown'
        job = session.get(Job, permit.job_id)
        job.status = 'outcome_unknown'
        job.control_epoch += 1
        job.generation += 1


def set_maintenance(db, enabled, *, dispatch_disabled=True):
    with db.engine.connect() as connection:
        acquire_maintenance_lock(connection)
        try:
            with db.session_factory(bind=connection) as session, session.begin():
                settings = session.scalar(select(Settings).where(Settings.id == 'singleton').with_for_update())
                settings.maintenance = enabled
                settings.dispatch_disabled = dispatch_disabled
                settings.generation += 1
                if enabled:
                    uncertain_inflight(session)
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(798205424)'))
            connection.commit()


def acquire_maintenance_lock(connection):
    # Never enqueue an exclusive waiter: a worker holds a shared session lock
    # while its short transactions use other connections, which must be able
    # to reacquire shared locks until that worker reaches a safe checkpoint.
    deadline = time.monotonic() + 960
    while True:
        acquired = connection.scalar(text('SELECT pg_try_advisory_lock(798205424)'))
        connection.commit()
        if acquired:
            return
        require(time.monotonic() < deadline, 'MAINTENANCE_DRAIN_TIMEOUT')
        time.sleep(.1)


def pg_environment(config):
    """Credentials go in child environment, never argv, logs, or backup files."""
    from urllib.parse import unquote
    parsed = urlsplit(config.database_url.replace('postgresql+psycopg:', 'postgresql:', 1))
    env = os.environ.copy()
    env.update(PGHOST=parsed.hostname, PGPORT=str(parsed.port or 5432), PGDATABASE=parsed.path.lstrip('/'),
        PGUSER=unquote(parsed.username or ''), PGPASSWORD=unquote(parsed.password or ''))
    return env


def verify_data(db, cfg):
    checked = 0
    with db.transaction() as session:
        for asset in session.scalars(select(SourceAsset)):
            path = safe_path(cfg.data, asset.storage_key, must_exist=True)
            require(path.stat().st_size == asset.byte_size and file_hash(path) == asset.sha256, 'SOURCE_ASSET_CORRUPT')
            checked += 1
        for model in (SourceRevision, TranslationRevision):
            for entity in session.scalars(select(model)):
                snapshot = read_snapshot(cfg.data, entity)
                if model == SourceRevision:
                    for asset in snapshot['assets']:
                        path = safe_path(cfg.data, asset['storage_key'], must_exist=True)
                        require(file_hash(path) == asset['sha256'], 'SOURCE_DERIVATIVE_CORRUPT')
                checked += 1
        for artifact in session.scalars(select(Artifact)):
            manifest = verify_artifact(safe_path(cfg.data, artifact.storage_key))
            require(digest(manifest) == artifact.manifest_hash, 'ARTIFACT_CORRUPT')
            checked += 1
        for export in session.scalars(select(Export)):
            if export.draft_snapshot_key:
                require(file_hash(safe_path(cfg.data, export.draft_snapshot_key, must_exist=True)) == export.draft_snapshot_hash, 'DRAFT_EXPORT_CORRUPT')
                checked += 1
            if export.status == 'succeeded':
                path = safe_path(cfg.data, export.storage_key, must_exist=True)
                require(file_hash(path) == export.sha256, 'EXPORT_CORRUPT')
                checked += 1
    return {'status': 'verified', 'objects': checked}


@contextmanager
def maintenance_window(db):
    # A session lock covers the entire file/pg_dump/restore interval and blocks
    # another maintenance-off command as well as every worker/file producer.
    with db.engine.connect() as connection:
        acquire_maintenance_lock(connection)
        try:
            with db.session_factory(bind=connection) as session, session.begin():
                settings = session.scalar(select(Settings).with_for_update())
                settings.maintenance = True
                settings.dispatch_disabled = True
                settings.generation += 1
                uncertain_inflight(session)
            yield connection
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(798205424)'))
            connection.commit()


def referenced_files(db, cfg):
    files = set()
    def add_data(key):
        files.add(('data', key))
    with db.transaction() as session:
        for asset in session.scalars(select(SourceAsset)):
            add_data(asset.storage_key)
        for model in (SourceRevision, TranslationRevision):
            for entity in session.scalars(select(model)):
                add_data(entity.storage_key)
                if model == SourceRevision:
                    source = read_snapshot(cfg.data, entity)
                    for asset in source['assets']:
                        add_data(asset['storage_key'])
        for draft in session.scalars(select(SourceDraft)):
            for asset in draft.source.get('assets', []):
                add_data(asset['storage_key'])
            # This directory was validated and wholly copied before SourceDraft
            # was committed. Unreferenced staging and partial worker output are excluded.
            if draft.evidence.get('parser_output'):
                parent = safe_path(cfg.data, draft.evidence['parser_output'], must_exist=True).parent
                for path in parent.rglob('*'):
                    if path.is_file():
                        require(not path.is_symlink(), 'BACKUP_SYMLINK')
                        add_data(path.relative_to(cfg.data).as_posix())
        for artifact in session.scalars(select(Artifact)):
            manifest = verify_artifact(safe_path(cfg.data, artifact.storage_key))
            for entry in manifest['files']:
                add_data(artifact.storage_key + '/' + entry['path'])
            add_data(artifact.storage_key + '/manifest.json')
        for export in session.scalars(select(Export)):
            if export.draft_snapshot_key:
                add_data(export.draft_snapshot_key)
            if export.status == 'succeeded':
                add_data(export.storage_key)
        for upload in session.scalars(select(Upload)):
            for index in range(len(upload.chunks)):
                path = f'{upload.id}/chunks/{index}.bin'
                if safe_path(cfg.uploads, path).is_file():
                    files.add(('uploads', path))
            original = f'{upload.id}/original.pdf'
            if safe_path(cfg.uploads, original).is_file():
                files.add(('uploads', original))
    return sorted(files)


def backup(db, cfg, backups):
    with maintenance_window(db):
        return backup_locked(db, cfg, backups)


def backup_locked(db, cfg, backups):
    backup_id = new_id('backup')
    directory = safe_path(backups, backup_id)
    staging = safe_path(backups, '.' + backup_id + '.tmp')
    staging.mkdir(parents=True)
    try:
        verify_data(db, cfg)
        subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--no-acl', '--file', str(staging / 'database.dump')], env=pg_environment(cfg), check=True, capture_output=True)
        files = []
        for name, key in referenced_files(db, cfg):
            path = safe_path(cfg.data if name == 'data' else cfg.uploads, key, must_exist=True)
            relative = name + '/' + key
            destination = safe_path(staging, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            files.append({'path': relative, 'byte_size': destination.stat().st_size, 'sha256': file_hash(destination)})
        dump = staging / 'database.dump'
        files.append({'path': 'database.dump', 'byte_size': dump.stat().st_size, 'sha256': file_hash(dump)})
        manifest = {'format': 'bilingual-compose-backup-v1', 'schema_version': SCHEMA_VERSION,
            'created_at': now().isoformat(), 'dispatch_disabled': True, 'files': files}
        atomic_write(staging, 'manifest.json', canonical_bytes(manifest))
        staging.rename(directory)
        print(json.dumps({'backup_id': backup_id, 'status': 'verified', 'files': len(files), 'maintenance': True, 'dispatch_disabled': True}))
    except BaseException:
        # Failed backup remains a .tmp directory; it is never a restorable backup ID.
        raise


def verify_backup(backups, backup_id):
    directory = safe_path(backups, backup_id)
    manifest = strict_loads(safe_path(directory, 'manifest.json', must_exist=True).read_bytes())
    require(manifest['format'] == 'bilingual-compose-backup-v1' and manifest['schema_version'] <= SCHEMA_VERSION, 'BACKUP_VERSION')
    require(len({f['path'] for f in manifest['files']}) == len(manifest['files']), 'BACKUP_DUPLICATE_PATH')
    require('database.dump' in {f['path'] for f in manifest['files']}, 'BACKUP_INCOMPLETE')
    for entry in manifest['files']:
        require(entry['path'] == 'database.dump' or entry['path'].startswith(('data/', 'uploads/')), 'BACKUP_UNSAFE_PATH')
        path = safe_path(directory, entry['path'], must_exist=True)
        require(path.stat().st_size == entry['byte_size'] and file_hash(path) == entry['sha256'], 'BACKUP_CORRUPT')
    return directory, manifest


def restore(db, cfg, backups, backup_id, replace=False):
    directory, manifest = verify_backup(backups, backup_id)
    try:
        db.ready()
    except Exception:
        db.migrate()
    with maintenance_window(db) as connection:
        return restore_locked(db, cfg, directory, manifest, backup_id, replace, connection)


def restore_locked(db, cfg, directory, manifest, backup_id, replace, connection):
    nonempty = any(p.is_file() for root in (cfg.data, cfg.uploads) for p in root.rglob('*'))
    require(replace or not nonempty, 'RESTORE_REQUIRES_REPLACE')
    # Copy into fixed named volumes. Hash verification precedes every DB switch.
    for name, root in (('data', cfg.data), ('uploads', cfg.uploads)):
        require(root.resolve() in (Path('/data'), Path('/uploads')), 'RESTORE_REQUIRES_COMPOSE_VOLUME')
        for entry in manifest['files']:
            if entry['path'].startswith(name + '/'):
                relative = entry['path'][len(name) + 1:]
                target = safe_path(root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(root, relative, safe_path(directory, entry['path'], must_exist=True).read_bytes(), immutable=not replace)
    restore_database_atomic(cfg, directory / 'database.dump')
    db.engine.dispose()
    db.migrate()
    from packages.jobs.backfill import backfill_history
    backfill_history(db)
    # Restored dump was produced in maintenance mode. Reassert flags on the
    # connection already holding the session lock, avoiding a self-deadlock.
    with db.session_factory(bind=connection) as session, session.begin():
        settings = session.scalar(select(Settings).with_for_update())
        settings.maintenance = True
        settings.dispatch_disabled = True
        uncertain_inflight(session)
    verification = verify_data(db, cfg)
    print(json.dumps({**verification, 'backup_id': backup_id, 'maintenance': True, 'dispatch_disabled': True,
        'next': 'Inspect outcome_unknown attempts, then use maintenance-off; enable external API requests separately in Settings.'}))


def restore_database_atomic(cfg, dump):
    # pg_restore --clean only knows the OLD dump's constraints. Newer schema
    # foreign keys (including task logs and parent jobs) otherwise prevent an
    # old backup from replacing the current database. Reset this dedicated
    # application's public schema and restore it in ONE transaction: a failed
    # restore rolls back the reset as well. Materialize SQL before any change.
    with tempfile.TemporaryDirectory(prefix='library-restore-') as temporary:
        sql = Path(temporary) / 'restore.sql'
        reset = Path(temporary) / 'reset.sql'
        subprocess.run(['pg_restore', '--no-owner', '--no-acl', '--file', str(sql), str(dump)],
            env=pg_environment(cfg), check=True, capture_output=True)
        reset.write_text('DROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n', encoding='utf-8')
        subprocess.run(['psql', '--no-psqlrc', '--quiet', '--single-transaction', '--set', 'ON_ERROR_STOP=1',
            '--file', str(reset), '--file', str(sql)], env=pg_environment(cfg), check=True, capture_output=True)


def enable_dispatch(db, *, accept_unknown_risk=False, reason=None):
    from packages.billing.dispatch import update_dispatch
    with db.transaction() as session:
        return update_dispatch(session, False, accept_unknown_risk=accept_unknown_risk, reason=reason, origin='maintenance_cli')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init-volumes', 'migrate', 'verify', 'backup', 'restore', 'verify-backup', 'seed-legacy', 'maintenance-on', 'maintenance-off', 'enable-dispatch', 'set-budget', 'retention'])
    parser.add_argument('--backup-id')
    parser.add_argument('--replace', action='store_true')
    parser.add_argument('--budget-micro', type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--accept-unknown-risk', action='store_true')
    parser.add_argument('--reason')
    parser.add_argument('--target-version', type=int, default=SCHEMA_VERSION)
    args = parser.parse_args()
    if args.command == 'init-volumes':
        return init_volumes()
    cfg = Config.load()
    db = Database(cfg)
    backups = Path(os.environ.get('BACKUPS_DIR', '/backups'))
    from packages.maintenance.history import operation_receipt
    with operation_receipt(db, args.command):
        execute_command(args, db, cfg, backups)


def execute_command(args, db, cfg, backups):
    if args.command == 'migrate':
        db.migrate(args.target_version)
        if args.target_version >= 12:
            from packages.jobs.backfill import backfill_history
            print(json.dumps({'history_backfill': backfill_history(db)}))
        print(json.dumps({'schema_version': args.target_version, 'status': 'migrated'}))
    elif args.command == 'verify':
        print(json.dumps(verify_data(db, cfg)))
    elif args.command == 'backup':
        backup(db, cfg, backups)
    elif args.command == 'retention':
        from packages.maintenance.retention import retention_locked
        with maintenance_window(db) as connection:
            print(json.dumps(retention_locked(db, cfg, backups, connection, apply=args.apply, limit=args.limit), ensure_ascii=False))
    elif args.command in ('restore', 'verify-backup'):
        require(args.backup_id, 'BACKUP_ID_REQUIRED')
        if args.command == 'restore':
            restore(db, cfg, backups, args.backup_id, args.replace)
        else:
            _, manifest = verify_backup(backups, args.backup_id)
            print(json.dumps({'status': 'verified', 'files': len(manifest['files'])}))
    elif args.command in ('maintenance-on', 'maintenance-off'):
        set_maintenance(db, args.command == 'maintenance-on')
        print(json.dumps({'maintenance': args.command == 'maintenance-on', 'dispatch_disabled': True}))
    elif args.command == 'enable-dispatch':
        print(json.dumps(enable_dispatch(db, accept_unknown_risk=args.accept_unknown_risk, reason=args.reason)))
    elif args.command == 'set-budget':
        require(args.budget_micro is not None and args.budget_micro >= 0, 'BUDGET_REQUIRED')
        with db.transaction() as session:
            from packages.domain.db import writable
            writable(session)
            settings = session.scalar(select(Settings).with_for_update())
            settings.instance_budget_micro = args.budget_micro
            settings.generation += 1
        print(json.dumps({'instance_budget_micro': args.budget_micro}))
    elif args.command == 'seed-legacy':
        from packages.seed.legacy import seed_legacy
        print(json.dumps(seed_legacy(db, cfg)))


if __name__ == '__main__':
    main()
