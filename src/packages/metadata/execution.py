"""DOI metadata jobs retain snapshots and fence stale asynchronous results."""
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from packages.domain.db import get_document
from packages.domain.models import Document, Job, MetadataCache, SourceAsset, Task, Upload, now, new_id
from packages.domain.errors import require
from packages.ir import digest
from packages.jobs.queue import assert_current, finish, emit
from packages.jobs.history import record_log
from .client import lookup, LookupResult
from .mapping import VERSION, matches_paper


def cache_key(doi, service):
    return digest({'doi': doi, 'service': service, 'mapping_version': VERSION})


def enqueue_metadata(session, asset, *, parent_job_id=None, document_id=None, force=False):
    discovery = asset.doi_discovery or {}
    if not discovery.get('selected'):
        asset.metadata_status = discovery.get('status', 'no_doi')
        return None
    if not force:
        pending = session.scalar(select(Job).where(Job.stage == 'metadata_lookup',
            Job.payload['source_asset_id'].astext == asset.id, Job.status.in_(['pending', 'running'])).limit(1))
        if pending: return pending
    asset.metadata_generation = (asset.metadata_generation or 0) + 1
    asset.metadata_status = 'pending'
    job = Job(id=new_id('job'), document_id=document_id, parent_job_id=parent_job_id, stage='metadata_lookup',
        payload={'source_asset_id': asset.id, 'metadata_generation': asset.metadata_generation,
            'doi': discovery['selected'], 'force': force})
    session.add(job); session.flush()
    session.add(Task(id=new_id('task'), job_id=job.id, kind='metadata_lookup', payload=job.payload))
    return job


def apply_title(document, asset):
    value = asset.bibliography
    if value and asset.metadata_status == 'succeeded' and document.title_user_edited is False:
        document.title = value['title']
        document.title_origin = 'metadata'


def execute_metadata(db, cfg, lease, *, client=None):
    with db.transaction() as session:
        job, task = assert_current(session, lease)
        payload = job.payload
        asset = session.get(SourceAsset, payload['source_asset_id'])
        if not asset or (asset.metadata_generation or 0) != payload['metadata_generation']:
            finish(session, lease, {'superseded': True}, status='cancelled'); return
        if lease.document_id:
            doc = get_document(session, lease.document_id)
            require(doc.source_asset_id == asset.id, 'SOURCE_STALE')
        doi, generation = payload['doi'], payload['metadata_generation']
        discovery = asset.doi_discovery
        result = None
        if not payload.get('force'):
            for service in ('doi', 'crossref'):
                cached = session.get(MetadataCache, cache_key(doi, service))
                if cached and cached.expires_at > now():
                    if cached.status == 'succeeded':
                        result = LookupResult(cached.status, service, value=cached.value, response=cached.response_snapshot); break
                    if service == 'crossref' and cached.status == 'not_found':
                        result = LookupResult('not_found', service, code='METADATA_NOT_FOUND')
        record_log(session, job, event_key=f'lookup:{lease.attempt_id}', operation='metadata_lookup', task_id=task.id, attempt_id=lease.attempt_id)
    result = result or lookup(doi, client=client)
    with db.transaction() as session:
        # Same lifecycle lock order as import and last-reference cleanup.
        from packages.domain.db import lock_lifecycle
        lock_lifecycle(session)
        session.execute(text('SELECT pg_advisory_xact_lock(798205425)'))
        job, task = assert_current(session, lease)
        asset = session.scalar(select(SourceAsset).where(SourceAsset.id == payload['source_asset_id']).with_for_update())
        if not asset or asset.metadata_generation != generation:
            finish(session, lease, {'superseded': True}, status='cancelled'); return
        if lease.document_id:
            require(get_document(session, lease.document_id).source_asset_id == asset.id, 'SOURCE_STALE')
        if result.retry_after is not None and task.attempts < 3:
            from packages.domain.models import Attempt
            task.status = job.status = 'pending'
            task.available_at = now() + timedelta(seconds=max(1, min(result.retry_after, 365 * 86400)))
            attempt = session.get(Attempt, lease.attempt_id)
            attempt.state = 'failed'; attempt.finished_at = now()
            job.error = {'code': result.code}
            asset.metadata_status = 'retrying'
            emit(session, job); return
        if result.status in {'succeeded', 'not_found'}:
            at = now()
            values = dict(key=cache_key(doi, result.service), doi=doi, service=result.service, mapping_version=VERSION,
                status=result.status, fetched_at=at, expires_at=at+timedelta(days=30 if result.status=='succeeded' else 1),
                value=result.value, response_snapshot=result.response)
            session.execute(insert(MetadataCache).values(**values).on_conflict_do_update(index_elements=['key'], set_=values))
        if result.status == 'succeeded' and not matches_paper(result.value, discovery):
            result = LookupResult('unverified', result.service, code='METADATA_PAPER_MISMATCH')
        asset.metadata_status = result.status
        if result.status == 'succeeded':
            asset.bibliography = result.value | {'fetched_at': now().isoformat(), 'match': 'doi_and_document_evidence'}
            for document in session.scalars(select(Document).where(Document.source_asset_id == asset.id,
                    Document.deleted_at.is_(None)).with_for_update()):
                before = document.title
                apply_title(document, asset)
                if document.title != before: document.generation += 1
        job.error = {'code': result.code} if result.code else None
        finish(session, lease, {'metadata_status': result.status}, status='succeeded' if result.status == 'succeeded' else
            'completed_with_warnings' if result.status in {'not_found', 'unverified'} else 'failed')
