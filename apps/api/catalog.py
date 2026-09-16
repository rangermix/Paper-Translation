from typing import Literal
import re

from fastapi import APIRouter, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import or_, select

from packages.billing.ledger import budget_totals
from packages.domain.config import provider_profile
from packages.domain.db import get_document, get_entity, writable
from packages.domain.errors import match_generation, require
from packages.domain.models import Artifact, Document, Edition, ReadingPosition, SearchEntry, Settings, SourceRevision, TranslationRevision, new_id
from packages.ir import digest, flatten_inline
from packages.storage import read_snapshot
from packages.templates import list_templates
from packages.translation.languages import canonical_locale
from packages.parsers.profiles import ParserProfile, selected_profile
from packages.parsers.timeouts import MIN_PARSE_TIMEOUT_SECONDS, MAX_PARSE_TIMEOUT_SECONDS, selected_timeout_seconds
from .common import StrictModel, command, page, response
from .library import Session, edition_view

router = APIRouter(prefix='/api/v1')


@router.get('/settings/provider')
def provider(session=Session):
    from packages.providers.settings import configuration_view
    return response(provider_view(session, configuration_view()))


def provider_view(session, profile):
    """All public aliases derive from one revision, including idempotent replay."""
    settings = session.get(Settings, 'singleton')
    from packages.providers.registry import privacy_notice
    from packages.providers.connection import has_unknown_test, latest_test, test_view
    connection = test_view(session, latest_test(session, profile.get('profile_hash', '')))
    return {**profile, 'configured': bool(profile.get('configured')), 'credentials_verified': bool(connection and connection['status'] == 'succeeded' and profile.get('auth_mode') != 'none'),
        'connection_test': connection,
        'connection_test_has_unknown': has_unknown_test(session, profile.get('profile_hash', '')),
        'language_policy': 'all',
        'price_revision': profile.get('price', {}).get('revision'), 'prices': profile.get('price'),
        'currency': profile.get('price', {}).get('currency', 'USD'), 'parser_profile_revision': selected_profile(settings.preferences),
        'privacy_note': privacy_notice(profile),
        'dispatch_disabled': settings.dispatch_disabled, 'instance_budget_micro': settings.instance_budget_micro,
        'costs': budget_totals(session), 'privacy_notice': privacy_notice(profile)}


@router.get('/settings/preferences')
def preferences(session=Session):
    settings = session.get(Settings, 'singleton')
    return response({'generation': settings.generation, 'theme': 'system', **settings.preferences,
        'parser_profile_revision': selected_profile(settings.preferences),
        'parser_timeout_seconds': selected_timeout_seconds(settings.preferences)})


@router.get('/settings/dispatch')
def dispatch_settings(session=Session):
    from packages.billing.dispatch import dispatch_view
    return response(dispatch_view(session))


class DispatchSettings(StrictModel):
    dispatch_disabled: bool
    accept_unknown_risk: bool = False
    reason: str | None = Field(None, max_length=2000)


@router.patch('/settings/dispatch')
def patch_dispatch_settings(body: DispatchSettings, request: Request, session=Session):
    from packages.billing.dispatch import update_dispatch
    from packages.domain.db import lock_singleton
    def execute():
        settings = lock_singleton(session)
        match_generation(settings, request.headers.get('If-Match'))
        return update_dispatch(session, body.dispatch_disabled, accept_unknown_risk=body.accept_unknown_risk,
            reason=body.reason, origin='manual_ui')
    return command(session, request, body.model_dump(), execute)


class Preferences(StrictModel):
    parser_profile_revision: ParserProfile | None = None
    parser_timeout_seconds: int | None = Field(None, strict=True,
        ge=MIN_PARSE_TIMEOUT_SECONDS, le=MAX_PARSE_TIMEOUT_SECONDS, multiple_of=60)
    locale: str | None = None
    publish_policy: Literal['manual_approval', 'auto_publish'] | None = None
    theme: Literal['light', 'dark', 'system', 'paper'] | None = None
    font_size: int | None = Field(None, ge=12, le=32)

    @field_validator('locale')
    @classmethod
    def normalize_locale(cls, value):
        return canonical_locale(value) if value is not None else None


@router.patch('/settings/preferences')
def patch_preferences(body: Preferences, request: Request, session=Session):
    writable(session)
    settings = session.scalar(select(Settings).where(Settings.id == 'singleton').with_for_update().execution_options(populate_existing=True))
    match_generation(settings, request.headers.get('If-Match'))
    settings.preferences = {**settings.preferences, **body.model_dump(exclude_none=True)}
    settings.generation += 1
    return response({'generation': settings.generation, 'theme': 'system', **settings.preferences,
        'parser_profile_revision': selected_profile(settings.preferences),
        'parser_timeout_seconds': selected_timeout_seconds(settings.preferences)})


@router.get('/templates')
def templates():
    return page(list_templates())


class CreateEdition(StrictModel):
    target_locale: str
    source_revision_id: str
    profile_hash: str = Field(pattern='^[0-9a-f]{64}$')

    @field_validator('target_locale')
    @classmethod
    def normalize_locale(cls, value):
        return canonical_locale(value)


@router.post('/documents/{document_id}/editions', status_code=201)
def create_edition(document_id: str, body: CreateEdition, request: Request, session=Session):
    def execute():
        doc = get_document(session, document_id, lock=True)
        match_generation(doc, request.headers.get('If-Match'))
        source = get_entity(session, SourceRevision, body.source_revision_id)
        require(source.document_id == doc.id, 'SOURCE_MISMATCH')
        profile = provider_profile()
        require(body.profile_hash == digest(profile), 'PROFILE_STALE')
        edition = session.scalar(select(Edition).where(Edition.document_id == doc.id, Edition.target_locale == body.target_locale))
        if edition is None:
            edition = Edition(id=new_id('edition'), document_id=doc.id, target_locale=body.target_locale)
            session.add(edition)
            session.flush()
            doc.generation += 1
        return {**edition_view(session, edition), 'source_revision_id': source.id,
            'notice': 'The existing source revision is reused. No parser or model call was made.'}
    return command(session, request, body.model_dump(), execute, 201)


@router.get('/search')
def search(q: str = Query(min_length=1, max_length=300), side: Literal['source', 'target', 'both'] = 'both', locale: str | None = None,
        cursor: str | None = None, limit: int = Query(30, ge=1, le=100), session=Session):
    query = select(SearchEntry, Document.title).join(Document, Document.id == SearchEntry.document_id).join(Edition, Edition.id == SearchEntry.edition_id).where(
        Document.deleted_at.is_(None), Edition.current_artifact_id == SearchEntry.artifact_id, Edition.generation == SearchEntry.generation)
    filters = []
    if side in ('source', 'both'):
        filters.append(SearchEntry.source_text.contains(q, autoescape=True))
    if side in ('target', 'both'):
        filters.append(SearchEntry.target_text.contains(q, autoescape=True))
    query = query.where(or_(*filters))
    if locale:
        query = query.where(SearchEntry.locale == locale)
    if cursor:
        query = query.where(SearchEntry.id > cursor)
    rows = list(session.execute(query.order_by(SearchEntry.id).limit(limit + 1)))
    items = [{'id': e.id, 'document_id': e.document_id, 'title': title, 'artifact_id': e.artifact_id, 'locale': e.locale,
        'block_id': e.block_id, 'source_text': e.source_text, 'target_text': e.target_text,
        'snippet': e.target_text if q in e.target_text else e.source_text, 'href': f'/artifacts/{e.artifact_id}/index.html#b-{e.block_id}'} for e, title in rows[:limit]]
    return page(items, rows[limit-1][0].id if len(rows) > limit else None)


class PositionBody(StrictModel):
    document_id: str
    locale: str
    artifact_id: str
    block_id: str
    offset: int = Field(ge=0)


@router.put('/reading-position')
def put_position(body: PositionBody, request: Request, session=Session):
    def execute():
        # Serialize first creation as well as updates; SELECT FOR UPDATE cannot
        # lock an absent composite-key position row in another browser yet.
        get_document(session, body.document_id, lock=True)
        artifact = get_entity(session, Artifact, body.artifact_id)
        edition = get_entity(session, Edition, artifact.edition_id)
        require(artifact.document_id == body.document_id and edition.target_locale == body.locale, 'ARTIFACT_MISMATCH')
        require(not artifact.legacy, 'LEGACY_PRECISE_POSITION_UNAVAILABLE')
        source = read_snapshot(request.app.state.config.data, get_entity(session, SourceRevision, artifact.source_revision_id))
        tr = read_snapshot(request.app.state.config.data, get_entity(session, TranslationRevision, artifact.translation_revision_id))
        block = next((b for b in source['blocks'] if b['id'] == body.block_id), None)
        require(block is not None, 'BOOKMARK_BLOCK_INVALID')
        target = next(r for r in tr['results'] if r['block_id'] == body.block_id)
        require(body.offset <= max(len(block['normalized_text']), len(flatten_inline(target['target_inline'], source['protected_atoms']))), 'BOOKMARK_OFFSET_INVALID')
        key = (body.document_id, body.locale, body.artifact_id)
        existing = session.get(ReadingPosition, key, with_for_update=True)
        if existing:
            match_generation(existing, request.headers.get('If-Match'))
            existing.block_id, existing.offset = body.block_id, body.offset
            existing.generation += 1
        else:
            require(request.headers.get('If-Match') == '"0"', 'PRECONDITION_REQUIRED', status=428)
            existing = ReadingPosition(**body.model_dump())
            session.add(existing)
            session.flush()
        return {**body.model_dump(), 'generation': existing.generation, 'current_artifact': edition.current_artifact_id == artifact.id}
    return command(session, request, body.model_dump(), execute)


@router.get('/reading-position')
def get_position(document_id: str, locale: str, artifact_id: str, session=Session):
    get_document(session, document_id)
    artifact = get_entity(session, Artifact, artifact_id)
    edition = get_entity(session, Edition, artifact.edition_id)
    require(artifact.document_id == document_id and edition.target_locale == locale, 'ARTIFACT_MISMATCH')
    position = session.get(ReadingPosition, (document_id, locale, artifact_id))
    previous = None
    if position is None:
        previous = session.scalar(select(ReadingPosition).join(Artifact, Artifact.id == ReadingPosition.artifact_id).where(
            ReadingPosition.document_id == document_id, ReadingPosition.locale == locale,
            ReadingPosition.artifact_id != artifact_id).order_by(Artifact.created_at.desc()).limit(1))
    return response({'generation': position.generation if position else 0, 'document_id': document_id, 'locale': locale,
        'artifact_id': artifact_id, 'block_id': position.block_id if position else None, 'offset': position.offset if position else 0,
        'current_artifact': edition.current_artifact_id == artifact_id, 'current_artifact_id': edition.current_artifact_id,
        'migration_required': edition.current_artifact_id != artifact_id or previous is not None,
        'migration_notice': 'This position belongs to another immutable version. Choose a block in the current version explicitly; no automatic jump was applied.' if previous or edition.current_artifact_id != artifact_id else None,
        'previous_position': {'artifact_id': previous.artifact_id, 'block_id': previous.block_id, 'offset': previous.offset} if previous else None})
