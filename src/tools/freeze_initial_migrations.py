"""One-time source generator. Refuses to overwrite an existing migration history."""
import json
from pathlib import Path

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from packages.domain.models import Base
from packages.ir import canonical_bytes, digest

from packages.paths import SOURCE_ROOT

destination = SOURCE_ROOT / 'packages/domain/migrations'
if destination.exists():
    raise SystemExit('Frozen migrations already exist; append a new migration instead.')
metadata = MetaData()
for table in Base.metadata.sorted_tables:
    table.to_metadata(metadata)
metadata.tables['documents'].c.source_asset_id.nullable = False
metadata.tables['exports'].c.artifact_id.nullable = False
for table, columns in {'exports': ['draft_snapshot_key', 'draft_snapshot_hash'],
        'translation_memory': ['generation'], 'idempotency_records': ['document_ids']}.items():
    for name in columns:
        metadata.tables[table]._columns.remove(metadata.tables[table].c[name])
groups = {
    1: {'source_assets', 'documents', 'uploads', 'source_drafts', 'source_revisions', 'editions', 'translation_drafts', 'segment_versions', 'translation_revisions', 'artifacts', 'publication_events', 'settings', 'idempotency_records'},
    2: {'jobs', 'tasks', 'attempts', 'job_events', 'heartbeats', 'exports'},
    3: {'dispatch_permits', 'translation_cache', 'quality_reports'},
    4: {'review_records', 'issue_resolutions', 'glossary_revisions', 'candidates', 'translation_memory', 'search_entries', 'reading_positions'},
}
records = {}
for version, names in groups.items():
    statements = []
    for table in metadata.sorted_tables:
        if table.name in names:
            statements.append(str(CreateTable(table).compile(dialect=postgresql.dialect())).strip())
            statements.extend(str(CreateIndex(index).compile(dialect=postgresql.dialect())).strip() for index in sorted(table.indexes, key=lambda x: x.name))
    records[version] = statements
records[5] = ['ALTER TABLE documents ALTER COLUMN source_asset_id DROP NOT NULL']
records[6] = ['ALTER TABLE translation_memory ADD COLUMN IF NOT EXISTS generation integer NOT NULL DEFAULT 1']
records[7] = ["ALTER TABLE idempotency_records ADD COLUMN IF NOT EXISTS document_ids jsonb NOT NULL DEFAULT '[]'::jsonb", 'DELETE FROM idempotency_records']
records[8] = ['ALTER TABLE exports ALTER COLUMN artifact_id DROP NOT NULL',
    'ALTER TABLE exports ADD COLUMN IF NOT EXISTS draft_snapshot_key text',
    'ALTER TABLE exports ADD COLUMN IF NOT EXISTS draft_snapshot_hash varchar(64)']
destination.mkdir()
index = []
for version, statements in records.items():
    content = canonical_bytes({'version': version, 'statements': statements})
    name = f'{version:03}.json'
    (destination / name).write_bytes(content)
    index.append({'version': version, 'file': name, 'sha256': digest(content)})
(destination / 'index.json').write_bytes(canonical_bytes(index))
print(json.dumps({'frozen_migrations': len(index)}))
