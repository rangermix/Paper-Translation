"""Real PostgreSQL + worker publication, with network construction forbidden."""
import copy
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest
from sqlalchemy import event, func, select

from packages.domain.models import (Artifact, Document, Edition, Job, Permit, SourceAsset,
    SourceRevision, Task, TranslationCache, TranslationRevision)
from packages.editorial.drafts import render_input
from packages.ir import digest
from packages.jobs.queue import claim
from packages.publisher import Publisher, verify_artifact
from packages.storage import write_snapshot
from workers.main import execute

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]


def test_twenty_sealed_documents_rebuild_without_provider_or_cache_writes(database):
    db, cfg = database
    fixture = json.loads((ROOT/'fixtures/sample-document-v3.json').read_text('utf-8'))
    source_template, translation_template = fixture['source_revision'], fixture['translation_revision']
    for asset in source_template['assets']:
        destination = cfg.data/asset['storage_key']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/asset['storage_key'], destination)
    original = next(a for a in source_template['assets'] if a['id'] == source_template['original_asset_id'])
    previous_files = {}
    with db.transaction() as session:
        session.add(SourceAsset(id=original['id'], sha256=original['sha256'], byte_size=original['byte_size'],
            page_count=1, storage_key=original['storage_key']))
        session.flush()
        for i in range(20):
            doc_id, source_id, tr_id, edition_id = f'doc_{i}', f'source_{i}', f'translation_{i}', f'edition_{i}'
            source, translation = copy.deepcopy(source_template), copy.deepcopy(translation_template)
            source['id'] = source_id
            translation['id'], translation['source_revision_id'] = tr_id, source_id
            source_key, tr_key = f'documents/{doc_id}/source.json', f'documents/{doc_id}/translation.json'
            source_hash, tr_hash = write_snapshot(cfg.data, source_key, source), write_snapshot(cfg.data, tr_key, translation)
            session.add(Document(id=doc_id, title='Fixture '+str(i), current_source_id=source_id, source_asset_id=original['id']))
            session.flush()
            session.add(SourceRevision(id=source_id, document_id=doc_id, asset_id=original['id'], snapshot_hash=source_hash, storage_key=source_key))
            session.add(Edition(id=edition_id, document_id=doc_id, target_locale='zh-Hans', current_artifact_id=f'old_{i}'))
            session.flush()
            session.add(TranslationRevision(id=tr_id, document_id=doc_id, edition_id=edition_id, source_revision_id=source_id,
                snapshot_hash=tr_hash, storage_key=tr_key, qa_fingerprint=digest({'fixture_qa': i})))
            session.flush()
            key = f'documents/{doc_id}/artifacts/old_{i}'
            ir = render_input(doc_id, source, translation)
            manifest = Publisher().build(ir, cfg.data, cfg.data/key, include_source=True)
            session.add(Artifact(id=f'old_{i}', document_id=doc_id, edition_id=edition_id, source_revision_id=source_id,
                translation_revision_id=tr_id, template_id='reader-v1', storage_key=key, manifest_hash=digest(manifest)))
            for file in (cfg.data/key).rglob('*'):
                if file.is_file():
                    previous_files[file] = digest(file.read_bytes())
            payload = {'translation_revision_id': tr_id, 'template_id': 'reader-v2', 'artifact_id': f'new_{i}',
                'edition_id': edition_id, 'expected_generation': 1}
            session.add(Job(id=f'rebuild_{i}', document_id=doc_id, stage='rebuild', payload=payload))
            session.flush()
            session.add(Task(id=f'task_{i}', job_id=f'rebuild_{i}', kind='rebuild', payload=payload))

    cache_writes = []
    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        sql = statement.strip().lower()
        if sql.startswith(('insert ', 'update ', 'delete ')) and 'translation_cache' in sql:
            cache_writes.append(sql)
    event.listen(db.engine, 'before_cursor_execute', observe)
    try:
        with patch('packages.providers.openai_responses.OpenAIResponses.__init__', side_effect=AssertionError('Provider forbidden')) as provider:
            while lease := claim(db):
                execute(db, cfg, lease)
            assert provider.call_count == 0
    finally:
        event.remove(db.engine, 'before_cursor_execute', observe)
    assert cache_writes == []
    assert all(digest(file.read_bytes()) == sha for file, sha in previous_files.items())
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(TranslationCache)) == 0
        assert session.scalar(select(func.count()).select_from(Permit)) == 0
        assert session.scalar(select(func.count()).select_from(Artifact)) == 40
        for i in range(20):
            assert session.get(Job, f'rebuild_{i}').status == 'succeeded'
            edition = session.get(Edition, f'edition_{i}')
            assert edition.current_artifact_id == f'new_{i}' and edition.generation == 2
            artifact = session.get(Artifact, f'new_{i}')
            manifest = verify_artifact(cfg.data/artifact.storage_key)
            assert manifest['template_id'] == 'reader-v2'
            assert manifest['translation_snapshot_hash'] == session.get(TranslationRevision, f'translation_{i}').snapshot_hash
