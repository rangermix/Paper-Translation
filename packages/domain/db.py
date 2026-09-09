from contextlib import contextmanager
import os
import re
from pathlib import Path

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from .config import Config
from .errors import DomainError, require
from .models import Document, Settings


SCHEMA_VERSION = 12


def migration_history():
    from packages.ir import digest, strict_loads
    directory = Path(__file__).with_name('migrations')
    index = strict_loads((directory / 'index.json').read_bytes())
    require([entry['version'] for entry in index] == list(range(1, SCHEMA_VERSION + 1)), 'MIGRATION_HISTORY_INVALID')
    result = {}
    for entry in index:
        require(entry['file'] == f'{entry["version"]:03}.json', 'MIGRATION_HISTORY_INVALID')
        content = (directory / entry['file']).read_bytes()
        require(digest(content) == entry['sha256'], 'MIGRATION_HASH_MISMATCH')
        record = strict_loads(content)
        require(record['version'] == entry['version'] and isinstance(record['statements'], list), 'MIGRATION_HISTORY_INVALID')
        result[entry['version']] = {**record, 'sha256': entry['sha256']}
    return result


class Database:
    def __init__(self, config: Config):
        require(config.database_url.startswith('postgresql+psycopg://'), 'DATABASE_CONFIG', status=503)
        connect_args = {}
        if os.environ.get('LIBRARY_TEST_MODE') == '1' and os.environ.get('TEST_DATABASE_SCHEMA'):
            schema = os.environ['TEST_DATABASE_SCHEMA']
            require(re.fullmatch(r'library_test_[a-f0-9]+', schema), 'TEST_SCHEMA_INVALID')
            connect_args = {'options': '-csearch_path=' + schema}
        self.engine = create_engine(config.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args=connect_args)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        from packages.jobs.history import track_lifecycle
        event.listen(self.session_factory, 'before_flush', track_lifecycle)

    @contextmanager
    def transaction(self):
        with self.session_factory() as session, session.begin():
            yield session

    def migrate(self, target=SCHEMA_VERSION):
        # Frozen DDL never changes merely because current ORM models gain fields.
        require(type(target) is int and 1 <= target <= SCHEMA_VERSION, 'MIGRATION_TARGET_INVALID')
        history = migration_history()
        with self.engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(798205423)'))
            conn.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())'))
            conn.execute(text('ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum varchar(64)'))
            installed = dict(conn.execute(text('SELECT version, checksum FROM schema_migrations')).all())
            require(not installed or max(installed) <= SCHEMA_VERSION, 'SCHEMA_TOO_NEW', status=503)
            require(not installed or set(installed) == set(range(1, max(installed) + 1)), 'MIGRATION_HISTORY_INCOMPLETE')
            require(not installed or target >= max(installed), 'MIGRATION_DOWNGRADE_FORBIDDEN')
            for version, checksum in installed.items():
                # Pre-release databases created before frozen DDL have no stored
                # checksum; retain that explicit unknown provenance as NULL.
                require(checksum is None or checksum == history[version]['sha256'], 'MIGRATION_HASH_MISMATCH')
            for version in range(1, target + 1):
                if version in installed:
                    continue
                for statement in history[version]['statements']:
                    conn.execute(text(statement))
                conn.execute(text('INSERT INTO schema_migrations (version, checksum) VALUES (:version, :checksum)'),
                    {'version': version, 'checksum': history[version]['sha256']})
            # Sealed snapshot indexes and history cannot be edited even by accidental ORM writes.
            conn.execute(text("""CREATE OR REPLACE FUNCTION immutable_history() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'immutable history may only be removed by maintenance'; END $$"""))
            for table in ('source_revisions', 'translation_revisions', 'segment_versions', 'publication_events', 'review_records', 'glossary_revisions'):
                if table not in ('review_records', 'glossary_revisions') or target >= 4:
                    conn.execute(text(f'DROP TRIGGER IF EXISTS forbid_history_update ON {table}'))
                    conn.execute(text(f'CREATE TRIGGER forbid_history_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION immutable_history()'))
        self.session_factory.configure(info={'nb_history_enabled': target >= 12})
        with self.transaction() as session:
            if session.get(Settings, 'singleton') is None:
                session.add(Settings(id='singleton', preferences={'locale': 'zh-Hans', 'publish_policy': 'auto_publish'}, dispatch_disabled=True))

    def ready(self):
        with self.engine.connect() as conn:
            require(conn.scalar(text('SELECT max(version) FROM schema_migrations')) == SCHEMA_VERSION, 'SCHEMA_MISMATCH', status=503)


def lock_singleton(session):
    value = session.scalar(select(Settings).where(Settings.id == 'singleton').with_for_update().execution_options(populate_existing=True))
    require(value is not None, 'DATABASE_NOT_INITIALIZED', status=503)
    return value


def writable(session):
    # All writes share a transaction advisory lock; maintenance takes exclusive.
    session.execute(text('SELECT pg_advisory_xact_lock_shared(798205424)'))
    settings = session.get(Settings, 'singleton')
    require(settings is not None and not settings.maintenance, 'MAINTENANCE', status=503)


def lock_lifecycle(session, *, allow_maintenance=False):
    """Order brief document/job commits before row locks and FK insertion.

    Provider transport and parser inference must stay outside this transaction.
    The single-instance boundary also protects file producers from cleanup.
    """
    if allow_maintenance:
        # Late accounting must classify already-dispatched money even when
        # maintenance has stopped new work. It still waits for backup's lock.
        session.execute(text('SELECT pg_advisory_xact_lock_shared(798205424)'))
        require(session.get(Settings, 'singleton') is not None, 'DATABASE_NOT_INITIALIZED', status=503)
    else:
        writable(session)
    session.execute(text('SELECT pg_advisory_xact_lock(798205425)'))


def get_document(session, document_id, lock=False):
    query = select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    doc = session.scalar(query)
    require(doc is not None, 'NOT_FOUND', status=404)
    require(doc.deleted_at is None, 'DOCUMENT_DELETED', status=410, resource_id=document_id)
    return doc


def get_entity(session, model, identifier, lock=False):
    # A previous unlocked lookup can populate the identity map. A later locking
    # SELECT must refresh it after waiting for the competing transaction.
    query = select(model).where(model.id == identifier).execution_options(populate_existing=True)
    entity = session.scalar(query.with_for_update() if lock else query)
    require(entity is not None, 'NOT_FOUND', status=404)
    if getattr(entity, 'document_id', None):
        get_document(session, entity.document_id)
    return entity
