"""Versioned source sealing, independent of optional content diagnostics."""
import copy
from packages.domain.db import get_document, get_entity
from packages.domain.errors import require
from packages.domain.models import SourceRevision, new_id, now
from packages.ir import block_hash, validate_source
from packages.storage import read_snapshot, write_snapshot


def seal_source(session, cfg, draft, language=None, *, origin='manual_ui'):
    require(not draft.evidence.get('sealed_revision_id'), 'SOURCE_ALREADY_SEALED')
    require(not draft.evidence.get('superseded_by'), 'SOURCE_BASE_STALE')
    require(draft.source and draft.source.get('blocks'), 'SOURCE_REQUIRED')
    doc = get_document(session, draft.document_id, lock=True)
    require(doc.source_asset_id == draft.asset_id, 'SOURCE_STALE')
    if 'document_generation' in draft.evidence:
        require(doc.generation == draft.evidence['document_generation'], 'SOURCE_BASE_STALE')
    if draft.base_revision_id is not None:
        require(doc.current_source_id == draft.base_revision_id, 'SOURCE_BASE_STALE')
    source = copy.deepcopy(draft.source)
    if language:
        source['language'] = language
        for block in source['blocks']:
            if block['language'] in ('und', 'auto'):
                block['language'] = language
                block['source_hash'] = block_hash(block, source['protected_atoms'])
    source['id'] = new_id('src')
    validate_source(source, asset_root=cfg.data)
    key = f'documents/{doc.id}/sources/{source["id"]}/document.json'
    h = write_snapshot(cfg.data, key, source)
    mapping = None
    if doc.current_source_id:
        from packages.source_revisions import revision_mapping
        previous = read_snapshot(cfg.data, get_entity(session, SourceRevision, doc.current_source_id))
        mapping = revision_mapping(previous, source)
    revision = SourceRevision(id=source['id'], document_id=doc.id, asset_id=draft.asset_id,
        snapshot_hash=h, storage_key=key, parent_id=doc.current_source_id,
        metadata_json={**draft.evidence, **({'mapping': mapping} if mapping is not None else {}),
            'coverage': draft.coverage, 'sealed_at': now().isoformat(), 'origin': origin})
    session.add(revision)
    doc.current_source_id = revision.id
    doc.source_language = source['language']
    doc.generation += 1
    draft.generation += 1
    draft.evidence = {**draft.evidence, 'sealed_revision_id': revision.id}
    session.flush()
    return revision, source


