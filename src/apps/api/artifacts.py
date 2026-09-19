from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import Field
from sqlalchemy import select

from packages.domain.db import get_document, get_entity, writable
from packages.domain.errors import DomainError, match_generation, require
from packages.domain.models import Artifact, Draft, Edition, Export, Publication, SourceRevision, TranslationRevision, new_id
from packages.ir import digest, validate_ir
from packages.publisher import verify_artifact
from packages.publisher.history import checked_manifest, commit_publication
from packages.storage import file_hash, read_snapshot, safe_path, write_snapshot
from .common import StrictModel, command, page, response
from .library import Session, edition_view, enqueue

router = APIRouter()


def locked_edition(session, edition_id):
    info = get_entity(session, Edition, edition_id)
    get_document(session, info.document_id, lock=True)
    return get_entity(session, Edition, edition_id, lock=True)


def checked_artifact(session, config, artifact_id):
    artifact = get_entity(session, Artifact, artifact_id)
    directory = safe_path(config.data, artifact.storage_key)
    manifest = checked_manifest(config, artifact)
    return artifact, directory, manifest


@router.get('/read/{document_id}/{locale}')
def read_current(document_id: str, locale: str, session=Session):
    get_document(session, document_id)
    edition = session.scalar(select(Edition).where(Edition.document_id == document_id, Edition.target_locale == locale))
    require(edition and edition.current_artifact_id, 'NOT_PUBLISHED', status=404)
    return RedirectResponse(f'/artifacts/{edition.current_artifact_id}/index.html', status_code=307)


@router.get('/artifacts/{artifact_id}/{relative_path:path}')
@router.head('/artifacts/{artifact_id}/{relative_path:path}', include_in_schema=False)
def artifact_file(artifact_id: str, relative_path: str, request: Request, session=Session):
    _, directory, manifest = checked_artifact(session, request.app.state.config, artifact_id)
    entry = next((f for f in manifest['files'] if f['path'] == relative_path), None)
    require(entry is not None, 'NOT_FOUND', status=404)
    path = safe_path(directory, relative_path, must_exist=True)
    headers = {'ETag': f'"{entry["sha256"]}"', 'Cache-Control': 'private, no-cache'}
    if entry['media_type'] == 'text/html' and manifest.get('content_security_policy'):
        headers['Content-Security-Policy'] = manifest['content_security_policy']
    return FileResponse(path, media_type=entry['media_type'], headers=headers)


class ExportBody(StrictModel):
    format: Literal['single_html', 'bundle']
    include_source: bool


class DraftExportBody(ExportBody):
    confirm_draft: bool = False  # Retained for old clients; content confirmation is optional.


@router.post('/api/v1/drafts/{draft_id}/exports', status_code=202)
def create_draft_export(draft_id: str, body: DraftExportBody, request: Request, session=Session):
    def execute():
        from packages.editorial.drafts import render_input, translation_snapshot
        draft = get_entity(session, Draft, draft_id, lock=True)
        match_generation(draft, request.headers.get('If-Match'))
        source = read_snapshot(request.app.state.config.data, get_entity(session, SourceRevision, draft.source_revision_id))
        translation = translation_snapshot(session, request.app.state.config, draft, draft_mode=True)
        snapshot = render_input(draft.document_id, source, translation, template_id='reader-v4', mode='draft')
        validate_ir(snapshot, request.app.state.config.data)
        export_id = new_id('export')
        key = f'exports/{export_id}/draft.json'
        snapshot_hash = write_snapshot(request.app.state.config.data, key, snapshot)
        export = Export(id=export_id, document_id=draft.document_id, artifact_id=None,
            draft_snapshot_key=key, draft_snapshot_hash=snapshot_hash, format=body.format, include_source=body.include_source)
        session.add(export)
        job = enqueue(session, 'export', {'export_id': export.id}, draft.document_id)
        export.job_id = job.id
        return {'id': export.id, 'export_id': export.id, 'job_id': job.id, 'status': 'pending',
            'draft': True, 'draft_generation': draft.generation, 'missing_blocks': sum(r['status'] in {'unresolved','fallback'} for r in translation['results'])}
    return command(session, request, body.model_dump(), execute, 202)


@router.post('/api/v1/artifacts/{artifact_id}/exports', status_code=202)
def create_export(artifact_id: str, body: ExportBody, request: Request, session=Session):
    def execute():
        artifact, _, _ = checked_artifact(session, request.app.state.config, artifact_id)
        export = Export(id=new_id('export'), document_id=artifact.document_id, artifact_id=artifact.id,
            format=body.format, include_source=body.include_source)
        session.add(export)
        job = enqueue(session, 'export', {'export_id': export.id}, artifact.document_id)
        export.job_id = job.id
        return {'id': export.id, 'export_id': export.id, 'job_id': job.id, 'status': 'pending'}
    return command(session, request, body.model_dump(), execute, 202)


@router.get('/api/v1/exports/{export_id}')
def get_export(export_id: str, session=Session):
    export = get_entity(session, Export, export_id)
    return {'id': export.id, 'status': export.status, 'job_id': export.job_id, 'format': export.format,
        'draft': bool(export.draft_snapshot_key),
        'sha256': export.sha256, 'download_url': f'/api/v1/exports/{export.id}/download' if export.status == 'succeeded' else None}


@router.get('/api/v1/exports/{export_id}/download')
def download_export(export_id: str, request: Request, session=Session):
    export = get_entity(session, Export, export_id)
    require(export.status == 'succeeded' and export.storage_key, 'EXPORT_NOT_READY')
    path = safe_path(request.app.state.config.data, export.storage_key, must_exist=True)
    require(file_hash(path) == export.sha256, 'EXPORT_CORRUPT')
    return FileResponse(path, media_type='text/html' if export.format == 'single_html' else 'application/zip', filename=path.name)


class PublishBody(StrictModel):
    translation_revision_id: str
    template_id: str = 'reader-v4'
    expected_generation: int = Field(ge=1)


@router.post('/api/v1/editions/{edition_id}/publish', status_code=202)
def publish(edition_id: str, body: PublishBody, request: Request, session=Session):
    def execute():
        edition = locked_edition(session, edition_id)
        match_generation(edition, request.headers.get('If-Match'))
        require(body.expected_generation == edition.generation, 'PRECONDITION_FAILED', status=412)
        revision = get_entity(session, TranslationRevision, body.translation_revision_id)
        require(revision.edition_id == edition.id, 'EDITION_MISMATCH')
        from packages.templates.registry import get_template
        get_template(body.template_id)
        from packages.editorial.drafts import render_input
        try:
            source = read_snapshot(request.app.state.config.data, get_entity(session, SourceRevision, revision.source_revision_id))
            translation = read_snapshot(request.app.state.config.data, revision)
            validate_ir(render_input(edition.document_id, source, translation, body.template_id), request.app.state.config.data)
        except (ValueError, OSError) as exc:
            raise DomainError('PUBLICATION_INPUT_INVALID', status=409) from exc
        job = enqueue(session, 'publish', {**body.model_dump(), 'edition_id': edition.id, 'artifact_id': new_id('artifact')}, edition.document_id)
        return {'id': job.id, 'job_id': job.id, 'status': job.status, 'generation': edition.generation}
    return command(session, request, body.model_dump(), execute, 202)


class RollbackBody(StrictModel):
    artifact_id: str
    expected_generation: int


@router.post('/api/v1/editions/{edition_id}/rollback')
def rollback(edition_id: str, body: RollbackBody, request: Request, session=Session):
    def execute():
        edition = locked_edition(session, edition_id)
        match_generation(edition, request.headers.get('If-Match'))
        artifact = get_entity(session, Artifact, body.artifact_id)
        commit_publication(session, request.app.state.config, edition, artifact, body.expected_generation, 'rollback')
        return edition_view(session, edition)
    return command(session, request, body.model_dump(), execute)


class GenerationBody(StrictModel):
    expected_generation: int


@router.post('/api/v1/editions/{edition_id}/unpublish')
def unpublish(edition_id: str, body: GenerationBody, request: Request, session=Session):
    def execute():
        edition = locked_edition(session, edition_id)
        match_generation(edition, request.headers.get('If-Match'))
        commit_publication(session, request.app.state.config, edition, None, body.expected_generation, 'unpublish')
        return edition_view(session, edition)
    return command(session, request, body.model_dump(), execute)


class RebuildBody(StrictModel):
    template_id: str
    preview_only: bool = True
    expected_generation: int


@router.post('/api/v1/artifacts/{artifact_id}/rebuild', status_code=202)
def rebuild(artifact_id: str, body: RebuildBody, request: Request, session=Session):
    def execute():
        artifact, _, _ = checked_artifact(session, request.app.state.config, artifact_id)
        require(not artifact.legacy and artifact.translation_revision_id, 'LEGACY_REBUILD_UNSUPPORTED')
        edition = locked_edition(session, artifact.edition_id)
        match_generation(edition, request.headers.get('If-Match'))
        require(edition.generation == body.expected_generation, 'PRECONDITION_FAILED', status=412)
        from packages.templates.registry import get_template
        get_template(body.template_id)
        job = enqueue(session, 'rebuild', {**body.model_dump(), 'edition_id': edition.id,
            'translation_revision_id': artifact.translation_revision_id, 'artifact_id': new_id('artifact')}, artifact.document_id)
        return {'id': job.id, 'job_id': job.id, 'status': job.status, 'generation': edition.generation}
    return command(session, request, body.model_dump(), execute, 202)


@router.get('/api/v1/documents/{document_id}/history')
def history(document_id: str, request: Request, session=Session):
    get_document(session, document_id)
    sources = list(session.scalars(select(SourceRevision).where(SourceRevision.document_id == document_id).order_by(SourceRevision.created_at)))
    translations = list(session.scalars(select(TranslationRevision).where(TranslationRevision.document_id == document_id).order_by(TranslationRevision.created_at)))
    artifacts = list(session.scalars(select(Artifact).where(Artifact.document_id == document_id).order_by(Artifact.created_at)))
    events = list(session.scalars(select(Publication).join(Edition).where(Edition.document_id == document_id).order_by(Publication.created_at)))
    editions = {e.id: e for e in session.scalars(select(Edition).where(Edition.document_id == document_id))}
    return {'sources': [{'id': s.id, 'parent_id': s.parent_id, 'snapshot_hash': s.snapshot_hash, 'created_at': s.created_at, 'changes': s.metadata_json.get('mapping', [])} for s in sources],
        'translations': [{'id': t.id, 'parent_id': t.parent_id, 'source_revision_id': t.source_revision_id, 'edition_id': t.edition_id,
            'snapshot_hash': t.snapshot_hash, 'created_at': t.created_at} for t in translations],
        'artifacts': [{'id': a.id, 'edition_id': a.edition_id, 'translation_revision_id': a.translation_revision_id, 'template_id': a.template_id,
            'source_revision_id': a.source_revision_id, 'locale': editions[a.edition_id].target_locale, 'state': a.state,
            'manifest_hash': a.manifest_hash, 'created_at': a.created_at, 'legacy': a.legacy,
            'read_url': f'/artifacts/{a.id}/index.html'} for a in artifacts],
        'publications': [{'id': e.id, 'edition_id': e.edition_id, 'artifact_id': e.artifact_id, 'generation': e.generation, 'operation': e.operation, 'created_at': e.created_at} for e in events]}


@router.get('/api/v1/documents/{document_id}/diff')
def diff(document_id: str, before: str, after: str, axis: Literal['source', 'target'], request: Request, session=Session):
    get_document(session, document_id)
    model = SourceRevision if axis == 'source' else TranslationRevision
    a, b = get_entity(session, model, before), get_entity(session, model, after)
    require(a.document_id == b.document_id == document_id, 'REVISION_MISMATCH')
    x, y = read_snapshot(request.app.state.config.data, a), read_snapshot(request.app.state.config.data, b)
    if axis == 'source':
        changes = _source_changes(x, y)
        fields = ('sha256', 'language', 'parser', 'normalization_version')
    else:
        require(a.edition_id == b.edition_id and x['target_language'] == y['target_language'], 'REVISION_LOCALE_MISMATCH',
            'Compare translation revisions from the same language edition.')
        edition = get_entity(session, Edition, a.edition_id)
        require(edition.document_id == document_id and edition.target_locale == x['target_language'], 'REVISION_LOCALE_MISMATCH')
        sa, sb = get_entity(session, SourceRevision, a.source_revision_id), get_entity(session, SourceRevision, b.source_revision_id)
        require(sa.document_id == sb.document_id == document_id, 'REVISION_MISMATCH')
        require(x['source_revision_id'] == sa.id and y['source_revision_id'] == sb.id, 'REVISION_MISMATCH')
        source_x, source_y = read_snapshot(request.app.state.config.data, sa), read_snapshot(request.app.state.config.data, sb)
        changes = _target_changes(x, y, source_x, source_y)
        fields = ('source_revision_id', 'target_language', 'title', 'profile_version', 'glossary_revision', 'engine')
    revision_changes = {key: {'before': x.get(key), 'after': y.get(key)} for key in fields if x.get(key) != y.get(key)}
    return {'axis': axis, 'before': before, 'after': after, 'changes': changes, 'revision_changes': revision_changes}


def _change(left, right, aspects):
    if left is None:
        kind = 'added'
    elif right is None:
        kind = 'deleted'
    elif not aspects:
        return None
    elif 'content' in aspects:
        kind = 'changed'
    elif 'order' in aspects:
        kind = 'moved'
    else:
        kind = aspects[0] + '_changed' if len(aspects) == 1 else 'metadata_changed'
    return {'block_id': (right or left).get('id', (right or left).get('block_id')), 'kind': kind,
        'before': left, 'after': right, 'aspects': aspects}


def _source_changes(x, y):
    from packages.source_revisions import revision_mapping
    left, right = {r['id']: r for r in x['blocks']}, {r['id']: r for r in y['blocks']}
    changes = []
    for match in revision_mapping(x, y):
        a = left[match['old_block_ids'][0]] if match['old_block_ids'] else None
        b = right[match['new_block_ids'][0]] if match['new_block_ids'] else None
        aspects = []
        if a is not None and b is not None:
            if match['kind'] == 'changed': aspects.append('content')
            if a['order'] != b['order']: aspects.append('order')
            if match['context_changed']: aspects.append('context')
            if a['provenance'] != b['provenance']: aspects.append('provenance')
            if (a['raw_text'] != b['raw_text'] and 'content' not in aspects) or a['normalization_edits'] != b['normalization_edits']: aspects.append('normalization')
            if a['warnings'] != b['warnings']: aspects.append('quality')
        change = _change(a, b, aspects)
        if change: changes.append(change)
    return changes


def _target_changes(x, y, source_x, source_y):
    from packages.source_revisions import revision_mapping
    mapping = revision_mapping(source_x, source_y)
    correspondence = {row['old_block_ids'][0]: row['new_block_ids'][0] for row in mapping if len(row['old_block_ids']) == len(row['new_block_ids']) == 1}
    left, right = {r['block_id']: r for r in x['results']}, {r['block_id']: r for r in y['results']}

    def resolved(value, source, remap):
        if isinstance(value, list): return [resolved(item, source, remap) for item in value]
        if not isinstance(value, dict): return value
        if value.get('type') == 'protected_ref':
            require(value['ref'] in source['protected_atoms'], 'REVISION_CORRUPT')
            return {'type': 'protected_ref', 'atom': source['protected_atoms'][value['ref']]}
        return {key: remap.get(item, item) if key == 'target_block_id' else resolved(item, source, remap) for key, item in value.items()}

    groups = {'source': ('source_hash', 'context_hash'), 'review': ('review_state', 'review_record'),
        'generation': ('generation',), 'status': ('status',), 'quality': ('warnings',), 'decision': ('reason',)}
    changes, consumed = [], set()
    for bid, a in left.items():
        new_id = correspondence.get(bid)
        b = right.get(new_id) if new_id is not None else None
        aspects = []
        if b is not None:
            consumed.add(new_id)
            if resolved(a['target_inline'], source_x, correspondence) != resolved(b['target_inline'], source_y, {}): aspects.append('content')
            for aspect, keys in groups.items():
                if any(a.get(key) != b.get(key) for key in keys): aspects.append(aspect)
        change = _change(a, b, aspects)
        if change: changes.append(change)
    for bid, b in right.items():
        if bid not in consumed: changes.append(_change(None, b, []))
    return changes
