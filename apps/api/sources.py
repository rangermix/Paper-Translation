"""Creation and explicit confirmation of immutable PDF source revisions."""
import copy

from fastapi import APIRouter, Request
from pydantic import Field

from packages.domain.db import get_document, get_entity
from packages.domain.errors import DomainError, match_generation, require
from packages.domain.models import SourceAsset, SourceDraft, SourceRevision, new_id, now
from packages.ir import digest, validate_source
from packages.source_revisions import apply_corrections, apply_native_corrections, native_regions_for_block
from packages.source_revisions.math_crop import page_crop_factory,verify_page_image
from packages.storage import file_hash, read_snapshot, safe_path, write_snapshot
from .common import StrictModel, command, response
from .library import Session

router = APIRouter(prefix='/api/v1')


def draft_view(draft):
    return {'id': draft.id, 'source_draft_id': draft.id, 'document_id': draft.document_id,
        'generation': draft.generation, 'source_hash': digest(draft.source), 'source': draft.source,
        'coverage': draft.coverage, 'base_revision_id': draft.base_revision_id, 'evidence': draft.evidence}


class CorrectionBody(StrictModel):
    reason: str = Field(min_length=1, max_length=2000)
    evidence: dict
    operations: list[dict] = Field(min_length=1, max_length=100)


@router.get('/imports/{import_id}/native-regions')
def native_regions(import_id: str, request: Request, session=Session):
    draft = get_entity(session, SourceDraft, import_id)
    inspection = draft.evidence.get('inspection', {})
    pages=copy.deepcopy(inspection.get('pages', []))
    for page in pages:
        key=draft.evidence.get('page_images',{}).get(str(page['page']))
        if key:page['page_image_sha256']=file_hash(safe_path(request.app.state.config.data,key,must_exist=True))
    return response({'id': draft.id, 'generation': draft.generation, 'pages': pages,
        'blocks': [{'block_id': b['id'], 'native_text': '\n'.join(r['text'] for p, r in native_regions_for_block(inspection, b)),
            'native_regions': [{'page': p['page'], 'page_size': p['page_size'], **r} for p, r in native_regions_for_block(inspection, b)]}
            for b in (draft.source or {}).get('blocks', [])]})


@router.post('/imports/{import_id}/corrections', status_code=201)
def correct_preflight(import_id: str, body: CorrectionBody, request: Request, session=Session):
    def execute():
        base = get_entity(session, SourceDraft, import_id, lock=True)
        match_generation(base, request.headers.get('If-Match'))
        doc = get_document(session, base.document_id, lock=True)
        require(doc.source_asset_id == base.asset_id and not base.evidence.get('superseded_by') and not base.evidence.get('sealed_revision_id'), 'SOURCE_BASE_STALE')
        inspection = base.evidence.get('inspection')
        changed = apply_native_corrections(base.source, inspection, body.operations, body.evidence, body.reason, base.coverage.get('excluded', []),
            crop_asset=page_crop_factory(request.app.state.config.data,doc.id,base),
            page_image_verify=lambda page,sha:verify_page_image(request.app.state.config.data,base,page,sha))
        validate_source(changed['source'],asset_root=request.app.state.config.data)
        source = changed['source']
        source['id'] = new_id('source')
        source['created_at'] = now().isoformat()
        doc.generation += 1
        draft = SourceDraft(id=new_id('source_draft'), document_id=base.document_id, asset_id=base.asset_id,
            source=source, base_revision_id=base.base_revision_id, coverage=changed['coverage'],
            evidence={**copy.deepcopy(base.evidence), 'origin': 'manual_ui', 'reason': body.reason,
                'original_pdf': changed['evidence'], 'operations': body.operations, 'mapping': changed['mapping'],
                'native_restorations': changed['restorations'], 'parent_draft_id': base.id, 'document_generation': doc.generation})
        draft.evidence.pop('superseded_by', None)
        session.add(draft)
        base.generation += 1
        # Parser source and inspection remain unchanged; only the control tombstone advances.
        base.evidence = {**base.evidence, 'superseded_by': draft.id}
        session.flush()
        return draft_view(draft)
    return command(session, request, body.model_dump(), execute, 201)


@router.post('/sources/{revision_id}/corrections', status_code=201)
def corrections(revision_id: str, body: CorrectionBody, request: Request, session=Session):
    def execute():
        base = get_entity(session, SourceRevision, revision_id)
        doc = get_document(session, base.document_id, lock=True)
        match_generation(doc, request.headers.get('If-Match'))
        require(doc.current_source_id == base.id and doc.source_asset_id == base.asset_id, 'SOURCE_BASE_STALE')
        source = read_snapshot(request.app.state.config.data, base)
        inspection = base.metadata_json.get('inspection')
        native_proof = False
        if inspection:
            from packages.source_revisions.native import verified_native_region
            try:
                verified_native_region(inspection, body.evidence)
                native_proof = True
            except DomainError as exc:
                if exc.code != 'SOURCE_NATIVE_EVIDENCE_MISMATCH':
                    raise
        if native_proof:
            original = SourceDraft(id=new_id('source_draft'), document_id=doc.id, asset_id=base.asset_id,
                source=source, evidence=base.metadata_json)
            changed = apply_native_corrections(source, inspection, body.operations, body.evidence, body.reason,
                base.metadata_json.get('coverage', {}).get('excluded', []),
                crop_asset=page_crop_factory(request.app.state.config.data, doc.id, original),
                page_image_verify=lambda page, sha: verify_page_image(request.app.state.config.data, original, page, sha))
        else:
            # Older source editors submit the persisted parser block's exact
            # locator/quote. Preserve this separately verified evidence path.
            changed = apply_corrections(source, body.operations, body.evidence, body.reason)
            if inspection and inspection.get('pages'):
                from packages.parsers.pdf_docling import coverage_report
                changed['coverage'] = coverage_report(inspection['pages'], changed['source']['blocks'],
                    base.metadata_json.get('coverage', {}).get('excluded', []))
        new_source = changed['source']
        new_source['id'] = new_id('source')
        new_source['created_at'] = now().isoformat()
        doc.generation += 1
        draft = SourceDraft(id=new_id('source_draft'), document_id=doc.id, asset_id=base.asset_id,
            source=new_source, base_revision_id=base.id,
            coverage=copy.deepcopy(changed.get('coverage', base.metadata_json.get('coverage', {'status': 'ready', 'unresolved_blocks': 0}))),
            evidence={**{key:copy.deepcopy(base.metadata_json[key]) for key in ('inspection','page_images') if key in base.metadata_json},
                'origin': 'manual_ui', 'reason': body.reason, 'original_pdf': changed['evidence'],
                'operations': body.operations, 'mapping': changed['mapping'], 'document_generation': doc.generation})
        session.add(draft)
        session.flush()
        return draft_view(draft)
    return command(session, request, body.model_dump(), execute, 201)


@router.get('/sources/drafts/{draft_id}')
def get_source_draft(draft_id: str, session=Session):
    return response(draft_view(get_entity(session, SourceDraft, draft_id)))


class ConfirmBody(StrictModel):
    source_hash: str = Field(pattern='^[0-9a-f]{64}$')


@router.post('/sources/drafts/{draft_id}/confirm', status_code=201)
def confirm_source(draft_id: str, body: ConfirmBody, request: Request, session=Session):
    def execute():
        draft = get_entity(session, SourceDraft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        require(not draft.evidence.get('sealed_revision_id'), 'SOURCE_ALREADY_SEALED')
        doc = get_document(session, draft.document_id, lock=True)
        require(doc.current_source_id == draft.base_revision_id and doc.source_asset_id == draft.asset_id
            and not draft.evidence.get('superseded_by') and doc.generation == draft.evidence.get('document_generation'), 'SOURCE_BASE_STALE')
        require(digest(draft.source) == body.source_hash, 'SOURCE_DRAFT_STALE')
        require(draft.source and draft.source.get('blocks'), 'SOURCE_REQUIRED')
        require(draft.evidence.get('origin') == 'manual_ui' and draft.evidence.get('original_pdf'), 'SOURCE_EVIDENCE_REQUIRED')
        confirmed_source = copy.deepcopy(draft.source)
        for block in confirmed_source['blocks']:
            for edit in block['normalization_edits']:
                if edit['rule_id'] == 'manual-pdf-mechanical-v1':
                    edit['reviewed'] = True
        validate_source(confirmed_source)
        asset = get_entity(session, SourceAsset, draft.asset_id)
        require(file_hash(safe_path(request.app.state.config.data, asset.storage_key, must_exist=True)) == asset.sha256 == draft.source['sha256'], 'SOURCE_ASSET_CORRUPT')
        source_id = draft.source['id']
        key = f'documents/{doc.id}/sources/{source_id}/document.json'
        snapshot_hash = write_snapshot(request.app.state.config.data, key, confirmed_source)
        revision = SourceRevision(id=source_id, document_id=doc.id, asset_id=draft.asset_id,
            snapshot_hash=snapshot_hash, storage_key=key, parent_id=draft.base_revision_id,
            metadata_json={**{key:copy.deepcopy(draft.evidence[key]) for key in ('inspection','page_images','native_restorations','operations','parent_draft_id') if key in draft.evidence},
                'source_draft_id':draft.id,'mapping': draft.evidence['mapping'], 'evidence': draft.evidence['original_pdf'],
                'reason': draft.evidence['reason'], 'origin': 'manual_ui', 'coverage': draft.coverage})
        session.add(revision)
        draft.evidence = {**draft.evidence, 'sealed_revision_id': source_id}
        draft.generation += 1
        doc.current_source_id = source_id
        doc.generation += 1
        doc.status = 'preflight'
        session.flush()
        return {'id': source_id, 'source_revision_id': source_id, 'source_hash': snapshot_hash,
            'generation': draft.generation, 'document_generation': doc.generation, 'mapping': draft.evidence['mapping']}
    return command(session, request, body.model_dump(), execute, 201)
