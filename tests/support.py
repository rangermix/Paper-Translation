"""Controlled internal fixture setup. Never imported by production API routes."""
import copy
import json
from pathlib import Path
import shutil
from sqlalchemy import text

from packages.domain.models import Document, Draft, Edition, SegmentVersion, SourceAsset, SourceRevision
from packages.editorial.drafts import context_hash
from packages.storage import write_snapshot


def legacy_insert(session, model, **values):
    """Insert against the literal historical schema, not today's added columns."""
    from sqlalchemy import MetaData, Table
    table = Table(model.__tablename__, MetaData(), autoload_with=session.connection())
    for column in model.__table__.columns:
        if column.name not in table.c or column.name in values or column.default is None:
            continue
        default = column.default
        values[column.name] = default.arg(None) if default.is_callable else copy.deepcopy(default.arg)
    session.execute(table.insert().values(**values))


def seed_editor(db, config, *, legacy_schema=False, document_ir=None):
    ir = copy.deepcopy(document_ir) if document_ir is not None else json.loads(Path('tests/fixtures/sample-document.json').read_text(encoding='utf-8'))
    source = ir['source_revision']
    (config.data / 'fixtures').mkdir(exist_ok=True)
    for name in ('sample.pdf', 'figure.png'):
        shutil.copyfile(Path('tests/fixtures') / name, config.data / 'fixtures' / name)
    source_key = 'documents/doc_fixture/sources/src_fixture/document.json'
    source_hash = write_snapshot(config.data, source_key, source)
    with db.transaction() as session:
        asset_values = dict(id='source_pdf', sha256=source['sha256'], byte_size=3822, page_count=1, storage_key='fixtures/sample.pdf')
        if legacy_schema:
            legacy_insert(session, SourceAsset, **asset_values)
        else:
            session.add(SourceAsset(**asset_values))
        session.flush()
        document_values = dict(id='doc_fixture', title='Publication fixture', source_asset_id='source_pdf', current_source_id='src_fixture', source_language='en')
        if legacy_schema:
            legacy_insert(session, Document, **document_values)
        else:
            session.add(Document(**document_values))
        session.flush()
        session.add(SourceRevision(id='src_fixture', document_id='doc_fixture', asset_id='source_pdf', snapshot_hash=source_hash, storage_key=source_key))
        if legacy_schema:
            # Historical upgrade fixtures must not use new ORM-column defaults
            # before the migration introducing those columns has run.
            session.execute(text("INSERT INTO editions (id, document_id, target_locale, current_draft_id, generation, created_at) VALUES ('edition_fixture', 'doc_fixture', 'zh-Hans', 'draft_fixture', 1, now())"))
        else:
            session.add(Edition(id='edition_fixture', document_id='doc_fixture', target_locale='zh-Hans', current_draft_id='draft_fixture'))
        session.flush()
        session.add(Draft(id='draft_fixture', document_id='doc_fixture', edition_id='edition_fixture', source_revision_id='src_fixture'))
        session.flush()
        for row in ir['translation_revision']['results']:
            if row['status'] == 'translated':
                session.add(SegmentVersion(id='seg_' + row['block_id'], draft_id='draft_fixture', block_id=row['block_id'], sequence=1,
                    target_inline=copy.deepcopy(row['target_inline']), source_hash=row['source_hash'], context_hash=context_hash(source, row['block_id']), origin='manual_ui', reason='Controlled internal fixture'))
    return ir
