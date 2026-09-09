"""Typed PostgreSQL entities. JSON fields hold immutable snapshots or bounded metadata."""
from datetime import datetime, timezone
import uuid

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def new_id(prefix):
    return prefix + '_' + uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Entity:
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Versioned:
    generation: Mapped[int] = mapped_column(Integer, default=1)


class Document(Entity, Versioned, Base):
    __tablename__ = 'documents'
    title: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    lifecycle: Mapped[str] = mapped_column(String(32), default='active')
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey('source_assets.id'))
    current_source_id: Mapped[str | None] = mapped_column(String(80))
    source_language: Mapped[str] = mapped_column(String(32), default='auto')
    status: Mapped[str] = mapped_column(String(40), default='source_only')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_filename: Mapped[str | None] = mapped_column(Text)
    title_user_edited: Mapped[bool | None] = mapped_column(Boolean)
    title_origin: Mapped[str | None] = mapped_column(String(40))


class SourceAsset(Entity, Base):
    __tablename__ = 'source_assets'
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(40), default='application/pdf')
    doi_discovery: Mapped[dict | None] = mapped_column(JSONB)
    bibliography: Mapped[dict | None] = mapped_column(JSONB)
    metadata_status: Mapped[str | None] = mapped_column(String(40))
    metadata_generation: Mapped[int | None] = mapped_column(Integer)


class Upload(Entity, Versioned, Base):
    __tablename__ = 'uploads'
    filename: Mapped[str] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    received_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    chunks: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(40), default='receiving')
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str | None] = mapped_column(String(64))
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey('source_assets.id'))
    job_id: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[dict | None] = mapped_column(JSONB)
    doi_discovery: Mapped[dict | None] = mapped_column(JSONB)


class SourceDraft(Entity, Versioned, Base):
    __tablename__ = 'source_drafts'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    asset_id: Mapped[str] = mapped_column(ForeignKey('source_assets.id'))
    source: Mapped[dict] = mapped_column(JSONB)
    coverage: Mapped[dict] = mapped_column(JSONB)
    base_revision_id: Mapped[str | None] = mapped_column(String(80))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceRevision(Entity, Base):
    __tablename__ = 'source_revisions'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    asset_id: Mapped[str] = mapped_column(ForeignKey('source_assets.id'))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class Edition(Entity, Versioned, Base):
    __tablename__ = 'editions'
    __table_args__ = (UniqueConstraint('document_id', 'target_locale'),)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    target_locale: Mapped[str] = mapped_column(String(32))
    current_artifact_id: Mapped[str | None] = mapped_column(String(80))
    current_draft_id: Mapped[str | None] = mapped_column(String(80))
    experimental: Mapped[bool] = mapped_column(Boolean, default=False)


class Draft(Entity, Versioned, Base):
    __tablename__ = 'translation_drafts'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    edition_id: Mapped[str] = mapped_column(ForeignKey('editions.id'))
    source_revision_id: Mapped[str] = mapped_column(ForeignKey('source_revisions.id'))
    base_revision_id: Mapped[str | None] = mapped_column(String(80))
    glossary_revision: Mapped[str] = mapped_column(String(80), default='empty-v1')
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    qa_id: Mapped[str | None] = mapped_column(String(80))


class SegmentVersion(Entity, Base):
    __tablename__ = 'segment_versions'
    __table_args__ = (UniqueConstraint('draft_id', 'block_id', 'sequence'),)
    draft_id: Mapped[str] = mapped_column(ForeignKey('translation_drafts.id'))
    block_id: Mapped[str] = mapped_column(String(160))
    sequence: Mapped[int] = mapped_column(Integer)
    target_inline: Mapped[list] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text, default='')
    context_hash: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    provenance_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class TranslationRevision(Entity, Base):
    __tablename__ = 'translation_revisions'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    edition_id: Mapped[str] = mapped_column(ForeignKey('editions.id'))
    source_revision_id: Mapped[str] = mapped_column(ForeignKey('source_revisions.id'))
    parent_id: Mapped[str | None] = mapped_column(String(80))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(Text)
    qa_fingerprint: Mapped[str] = mapped_column(String(64))
    language_authorization: Mapped[dict] = mapped_column(JSONB, default=dict)


class Artifact(Entity, Base):
    __tablename__ = 'artifacts'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    edition_id: Mapped[str] = mapped_column(ForeignKey('editions.id'))
    source_revision_id: Mapped[str | None] = mapped_column(ForeignKey('source_revisions.id'))
    translation_revision_id: Mapped[str | None] = mapped_column(ForeignKey('translation_revisions.id'))
    template_id: Mapped[str] = mapped_column(String(80))
    storage_key: Mapped[str] = mapped_column(Text)
    manifest_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default='verified')
    legacy: Mapped[bool] = mapped_column(Boolean, default=False)


class Publication(Entity, Base):
    __tablename__ = 'publication_events'
    edition_id: Mapped[str] = mapped_column(ForeignKey('editions.id'))
    artifact_id: Mapped[str | None] = mapped_column(String(80))
    generation: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(32), default='manual_ui')
    __table_args__ = (UniqueConstraint('edition_id', 'generation'),)


class Job(Entity, Versioned, Base):
    __tablename__ = 'jobs'
    document_id: Mapped[str | None] = mapped_column(ForeignKey('documents.id'))
    stage: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default='pending')
    control_epoch: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[dict | None] = mapped_column(JSONB)
    budget_micro: Mapped[int | None] = mapped_column(BigInteger().evaluates_none(), default=0)
    parent_job_id: Mapped[str | None] = mapped_column(ForeignKey('jobs.id'))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    actual_model: Mapped[dict | None] = mapped_column(JSONB)
    title_snapshot: Mapped[str | None] = mapped_column(Text)
    quality_summary: Mapped[dict | None] = mapped_column(JSONB)


class Task(Entity, Base):
    __tablename__ = 'tasks'
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id'))
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default='pending')
    fence: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_model: Mapped[dict | None] = mapped_column(JSONB)


class Attempt(Entity, Base):
    __tablename__ = 'attempts'
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'))
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id'))
    fence: Mapped[int] = mapped_column(Integer)
    control_epoch: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(40), default='created')
    request_id: Mapped[str | None] = mapped_column(String(200))
    usage: Mapped[dict | None] = mapped_column(JSONB)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_model: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('task_id', 'fence'),)


class Permit(Entity, Base):
    __tablename__ = 'dispatch_permits'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'), unique=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id'))
    control_epoch: Mapped[int] = mapped_column(Integer)
    price_snapshot: Mapped[dict] = mapped_column(JSONB)
    reserved_micro: Mapped[int | None] = mapped_column(BigInteger)
    actual_micro: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(32), default='reserved')


class Event(Entity, Base):
    __tablename__ = 'job_events'
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id'), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)


class TaskLog(Base):
    """Durable technical events, independent of parser spool retention."""
    __tablename__ = 'task_logs'
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id'), index=True)
    event_key: Mapped[str] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    level: Mapped[str] = mapped_column(String(16))
    stage: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(80))
    task_id: Mapped[str | None] = mapped_column(String(80))
    attempt_id: Mapped[str | None] = mapped_column(String(80))
    page: Mapped[int | None] = mapped_column(Integer)
    unit_id: Mapped[str | None] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint('job_id', 'event_key'),)


class MetadataCache(Base):
    __tablename__ = 'metadata_cache'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    doi: Mapped[str] = mapped_column(Text)
    service: Mapped[str] = mapped_column(String(40))
    mapping_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value: Mapped[dict | None] = mapped_column(JSONB)
    response_snapshot: Mapped[dict | None] = mapped_column(JSONB)


class Settings(Versioned, Base):
    __tablename__ = 'settings'
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default='singleton')
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    instance_budget_micro: Mapped[int] = mapped_column(BigInteger, default=0)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    dispatch_disabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Idempotency(Base):
    __tablename__ = 'idempotency_records'
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    method: Mapped[str] = mapped_column(String(10), primary_key=True)
    path: Mapped[str] = mapped_column(String(400), primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    document_ids: Mapped[list] = mapped_column(JSONB, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QA(Entity, Base):
    __tablename__ = 'quality_reports'
    draft_id: Mapped[str] = mapped_column(ForeignKey('translation_drafts.id'))
    draft_generation: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    issues: Mapped[list] = mapped_column(JSONB)
    valid: Mapped[bool] = mapped_column(Boolean)


class ReviewRecord(Entity, Base):
    __tablename__ = 'review_records'
    draft_id: Mapped[str] = mapped_column(ForeignKey('translation_drafts.id'))
    block_id: Mapped[str] = mapped_column(String(160))
    segment_version: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(32), default='manual_ui')
    reason: Mapped[str] = mapped_column(Text)


class IssueResolution(Entity, Base):
    __tablename__ = 'issue_resolutions'
    draft_id: Mapped[str] = mapped_column(ForeignKey('translation_drafts.id'))
    issue_fingerprint: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(String(32), default='manual_ui')


class Glossary(Entity, Base):
    __tablename__ = 'glossary_revisions'
    document_id: Mapped[str | None] = mapped_column(ForeignKey('documents.id'))
    source_language: Mapped[str] = mapped_column(String(32))
    target_language: Mapped[str] = mapped_column(String(32))
    parent_id: Mapped[str | None] = mapped_column(String(80))
    entries: Mapped[list] = mapped_column(JSONB)
    snapshot_hash: Mapped[str] = mapped_column(String(64))


class Candidate(Entity, Versioned, Base):
    __tablename__ = 'candidates'
    draft_id: Mapped[str] = mapped_column(ForeignKey('translation_drafts.id'))
    job_id: Mapped[str | None] = mapped_column(ForeignKey('jobs.id'))
    base: Mapped[dict] = mapped_column(JSONB)
    results: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default='pending')


class TranslationCache(Base):
    __tablename__ = 'translation_cache'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    value: Mapped[dict] = mapped_column(JSONB)


class TranslationMemory(Entity, Versioned, Base):
    __tablename__ = 'translation_memory'
    document_id: Mapped[str | None] = mapped_column(ForeignKey('documents.id'))
    independent: Mapped[bool] = mapped_column(Boolean, default=False)
    source_language: Mapped[str] = mapped_column(String(32))
    target_language: Mapped[str] = mapped_column(String(32))
    source_text: Mapped[str] = mapped_column(Text)
    target_inline: Mapped[list] = mapped_column(JSONB)
    context_hash: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict] = mapped_column(JSONB)


class SearchEntry(Entity, Base):
    __tablename__ = 'search_entries'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    edition_id: Mapped[str] = mapped_column(ForeignKey('editions.id'))
    artifact_id: Mapped[str] = mapped_column(ForeignKey('artifacts.id'))
    generation: Mapped[int] = mapped_column(Integer)
    locale: Mapped[str] = mapped_column(String(32))
    block_id: Mapped[str] = mapped_column(String(160))
    source_text: Mapped[str] = mapped_column(Text)
    target_text: Mapped[str] = mapped_column(Text)


class ReadingPosition(Versioned, Base):
    __tablename__ = 'reading_positions'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), primary_key=True)
    locale: Mapped[str] = mapped_column(String(32), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey('artifacts.id'), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(160))
    offset: Mapped[int] = mapped_column(Integer)


class Export(Entity, Base):
    __tablename__ = 'exports'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey('artifacts.id'))
    draft_snapshot_key: Mapped[str | None] = mapped_column(Text)
    draft_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    job_id: Mapped[str | None] = mapped_column(ForeignKey('jobs.id'))
    status: Mapped[str] = mapped_column(String(32), default='pending')
    format: Mapped[str] = mapped_column(String(32))
    include_source: Mapped[bool] = mapped_column(Boolean)
    storage_key: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))


class Heartbeat(Base):
    __tablename__ = 'heartbeats'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
