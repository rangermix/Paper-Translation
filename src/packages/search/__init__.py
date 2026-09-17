from sqlalchemy import delete, select

from packages.domain.db import get_entity
from packages.domain.models import Artifact, Edition, SearchEntry, SourceRevision, TranslationRevision, new_id
from packages.ir import flatten_inline
from packages.jobs.queue import assert_current, finish
from packages.storage import read_snapshot


def update_index(db, cfg, lease):
    with db.transaction() as session:
        assert_current(session, lease)
        edition = get_entity(session, Edition, lease.payload['edition_id'], lock=True)
        if edition.generation != lease.payload['generation'] or not edition.current_artifact_id:
            finish(session, lease, {'stale': True})
            return
        artifact = get_entity(session, Artifact, edition.current_artifact_id)
        session.execute(delete(SearchEntry).where(SearchEntry.edition_id == edition.id))
        if artifact.legacy:
            # Legacy text was editorially reorganized; no fabricated exact block/source map.
            finish(session, lease, {'legacy_without_block_index': True})
            return
        source = read_snapshot(cfg.data, get_entity(session, SourceRevision, artifact.source_revision_id))
        translation = read_snapshot(cfg.data, get_entity(session, TranslationRevision, artifact.translation_revision_id))
        results = {r['block_id']: r for r in translation['results']}
        for block in source['blocks']:
            session.add(SearchEntry(id=new_id('search'), document_id=edition.document_id, edition_id=edition.id,
                artifact_id=artifact.id, generation=edition.generation, locale=edition.target_locale,
                block_id=block['id'], source_text=block['normalized_text'],
                target_text=(block['normalized_text'] if results[block['id']].get('reason') == 'same_language'
                    else flatten_inline(results[block['id']]['target_inline'], source['protected_atoms']))))
        finish(session, lease, {'indexed_blocks': len(source['blocks'])})
