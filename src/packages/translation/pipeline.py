"""Frozen upload/parse choices advance without a content approval checkpoint."""
import copy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from packages.billing.price import cost_control_enabled, validate_profile
from packages.domain.config import provider_profile
from packages.domain.errors import require
from packages.domain.models import Document, Edition, Job, Settings, Task, new_id, now
from packages.editorial.drafts import create_draft, run_quality, seal, quality_summary
from packages.editorial.source_sealing import seal_source
from packages.ir import digest
from packages.translation.languages import canonical_locale, translation_profile


class PipelineOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    translate: bool = True
    target_locale: str = 'zh-Hans'
    publish_policy: Literal['auto_publish', 'manual_approval'] = 'auto_publish'
    external_processing_confirmed: bool = False
    profile_hash: str | None = Field(None, pattern='^[0-9a-f]{64}$')
    budget_micro: int | None = Field(None, gt=0)

    @field_validator('target_locale')
    @classmethod
    def normalize_locale(cls, value):
        return canonical_locale(value)


def freeze_pipeline(options, asset_id):
    profile = provider_profile()
    if options.translate and options.external_processing_confirmed:
        require(options.profile_hash == digest(profile), 'PROFILE_STALE')
    return {**options.model_dump(), 'profile': copy.deepcopy(profile), 'source_asset_id': asset_id,
        'confirmed_at': now().isoformat() if options.external_processing_confirmed else None,
        'origin': 'upload_workflow'}


def advance_parse(session, cfg, source_draft, parent):
    """Caller holds the live parse fence and the document row lock."""
    options = parent.payload.get('workflow')
    if not options:
        return
    require(options['source_asset_id'] == source_draft.asset_id, 'SOURCE_STALE')
    revision, source = seal_source(session, cfg, source_draft, origin='automatic_workflow')
    locale = options['target_locale']
    edition = session.scalar(select(Edition).where(Edition.document_id == revision.document_id,
        Edition.target_locale == locale).with_for_update())
    if edition is None:
        edition = Edition(id=new_id('edition'), document_id=revision.document_id, target_locale=locale)
        session.add(edition); session.flush()
    profile = options['profile']
    failure = None
    try:
        validate_profile(profile)
        profile = translation_profile(profile, source, locale)
    except ValueError:
        failure = 'PROVIDER_CONFIG'
    if options['translate'] and not options['external_processing_confirmed']:
        failure = failure or 'EXTERNAL_PROCESSING_UNCONFIRMED'
    if options['translate'] and not failure and cost_control_enabled(profile) and not options.get('budget_micro'):
        failure = 'BUDGET_REQUIRED'
    if options['translate'] and session.get(Settings, 'singleton').dispatch_disabled:
        failure = failure or 'DISPATCH_DISABLED'
    from packages.glossaries import effective_glossary
    glossary = effective_glossary(session, revision.document_id, source['language'], locale)
    draft_profile = profile if not failure or failure == 'DISPATCH_DISABLED' else {}
    draft_profile = {**draft_profile, 'glossary_revision': glossary['revision'], 'glossary_entries': glossary['entries']}
    draft = create_draft(session, cfg, edition, revision, draft_profile)
    parent.progress = parent.progress | {'draft_id': draft.id, 'source_revision_id': revision.id}
    if options['translate']:
        payload = {**options, 'draft_id': draft.id, 'source_revision_id': revision.id, 'source_hash': digest(source),
            'profile': profile, 'locale': locale, 'glossary_revision': glossary['revision'], 'glossary': glossary['entries']}
        job = Job(id=new_id('job'), document_id=revision.document_id, parent_job_id=parent.id, stage='translate',
            payload=payload, budget_micro=options.get('budget_micro'),
            status='waiting_budget' if failure == 'BUDGET_REQUIRED' else 'waiting_config' if failure else 'pending',
            error={'code': failure} if failure else None)
        session.add(job); session.flush()
        session.add(Task(id=new_id('task'), job_id=job.id, kind='translate'))
        parent.progress = parent.progress | {'translation_job_id': job.id}
    if not options['translate'] or failure:
        # A source-only artifact remains available while external execution
        # waits. Its missing translations are explicitly labelled as originals.
        qa = run_quality(session, cfg, draft, parent_job_id=parent.id)
        revision_tr = seal(session, cfg, draft, qa.id, qa.fingerprint)
        payload = {'source_only': True, 'translation_revision_id': revision_tr.id, 'result_status': 'completed_with_warnings'}
        local = Job(id=new_id('job'), document_id=revision.document_id, parent_job_id=parent.id,
            stage='publish', payload=payload, quality_summary=quality_summary(qa))
        session.add(local); session.flush()
        session.add(Task(id=new_id('task'), job_id=local.id, kind='publish', payload={
            'translation_revision_id': revision_tr.id, 'edition_id': edition.id, 'template_id': 'reader-v4',
            'artifact_id': new_id('artifact'), 'expected_generation': edition.generation,
            'preview_only': options['publish_policy'] == 'manual_approval'}))
        parent.progress = parent.progress | {'publication_job_id': local.id}
    session.get(Document, revision.document_id).status = 'ready'
    session.flush()
