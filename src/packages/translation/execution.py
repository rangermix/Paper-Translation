"""Durable planning, one external attempt per task, validated checkpoints and safe merges."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from packages.domain.config import provider_profile
from packages.domain.db import get_entity,get_document,lock_lifecycle,lock_singleton
from packages.domain.errors import DomainError,require
from packages.domain.models import (Attempt,Candidate,Document,Draft,Edition,Job,Permit,SegmentVersion,
    SourceRevision,Task,TranslationCache,Settings,new_id,now)
from packages.editorial.drafts import context_hash,current_segments,run_quality,seal,translation_snapshot,quality_summary
from packages.ir import digest,flatten_inline
from packages.jobs.queue import assert_current,emit,finish
from packages.storage import read_snapshot
from packages.billing.price import reserve_cost,validate_profile
from packages.billing.ledger import authorize,budget_totals,mark_unknown,release_unsent,settle
from packages.providers.contract import ProviderFailure,validate_output,validate_review
from packages.providers.openai_responses import OpenAIResponses
from packages.providers.registry import request_body
from packages.providers.native import NativeProvider
from packages.providers.settings import resolve_provider_credentials
from .planner import plan_units,restore_inline,cache_key,cache_encode,cache_decode
from .languages import check_language_policy, public_profile


def snapshot(session,cfg,lease,*,allow_pending=False):
    job,task=assert_current(session,lease,allow_pending=allow_pending)
    payload=job.payload
    draft=get_entity(session,Draft,payload['draft_id'])
    source_entity=get_entity(session,SourceRevision,draft.source_revision_id)
    require(payload['source_revision_id']==draft.source_revision_id and payload['source_hash']==source_entity.snapshot_hash,'SOURCE_STALE')
    doc=get_document(session,draft.document_id)
    require(doc.current_source_id==source_entity.id and doc.source_asset_id==source_entity.asset_id,'SOURCE_STALE')
    source=read_snapshot(cfg.data,source_entity)
    require(digest(source)==payload['source_hash'],'SOURCE_STALE')
    return job,task,draft,source


def finalize_translation(session,cfg,job,draft,source,kind):
    rows=session.scalars(select(Task).where(Task.job_id==job.id)).all()
    if any(row.status in {'pending','leased','outcome_unknown'} for row in rows):return
    unknown=session.scalar(select(Permit.id).where(Permit.job_id==job.id,Permit.state=='unknown').limit(1))
    if unknown:
        job.status='outcome_unknown'
        job.error={'code':'OUTCOME_UNKNOWN'}
        return
    if kind=='candidate':
        candidate=get_entity(session,Candidate,job.payload['candidate_id'],lock=True)
        candidate.status='ready'
        job.status='partially_completed' if any(row.status=='failed' for row in rows) else 'succeeded'
        return
    qa=run_quality(session,cfg,draft,parent_job_id=job.id)
    job.quality_summary=quality_summary(qa)
    translated=translation_snapshot(session,cfg,draft)
    fallback=sum(row['status']=='fallback' for row in translated['results'])
    warnings=bool(qa.issues or any(block.get('warnings') for block in source['blocks']))
    job.status='partially_completed' if fallback else 'completed_with_warnings' if warnings else 'succeeded'
    job.progress=job.progress|{'fallback_blocks':fallback,'qa_id':qa.id}
    if not fallback and job.error:
        job.progress=job.progress|{'recovered_errors':[*job.progress.get('recovered_errors',[]),
            {'error':job.error,'at':now().isoformat(),'reason':'all_translation_units_succeeded'}]}
        job.error={}
    if job.payload.get('publish_policy')=='auto_publish':
        # Local artifact generation does not dispatch a model request. The
        # original job keeps its model identity and terminal translation result.
        revision=seal(session,cfg,draft,qa.id,qa.fingerprint)
        edition=get_entity(session,Edition,draft.edition_id,lock=True)
        child=Job(id=new_id('job'),document_id=job.document_id,parent_job_id=job.id,stage='publish',
            payload={'translation_revision_id':revision.id,'result_status':job.status},quality_summary=job.quality_summary)
        session.add(child);session.flush()
        session.add(Task(id=new_id('task'),job_id=child.id,kind='publish',payload={'translation_revision_id':revision.id,
            'edition_id':edition.id,'template_id':'reader-v3','artifact_id':new_id('artifact'),'expected_generation':edition.generation}))
        job.progress=job.progress|{'publication_job_id':child.id,'translation_revision_id':revision.id}


def finalize_semantic_review(session,job):
    """Finish only after every review unit settles, preserving incomplete scope."""
    units=[task for task in session.scalars(select(Task).where(Task.job_id==job.id))
        if 'unit' in task.payload]
    if not units or any(task.status in {'pending','leased','outcome_unknown'} for task in units):return
    completed=all(task.status=='succeeded' for task in units)
    job.progress=job.progress|{'review_completed':completed,'accuracy_certified':False}
    if completed:
        job.status='completed_with_warnings' if job.progress.get('semantic_issues') else 'succeeded'
    else:
        job.status='partially_completed' if any(task.status=='succeeded' for task in units) else 'failed'


def plan_tasks(db,cfg,lease):
    with db.transaction() as session:
        job,task,draft,source=snapshot(session,cfg,lease)
        require(job.payload.get('external_processing_confirmed') is True,'EXTERNAL_PROCESSING_UNCONFIRMED')
        profile=validate_profile(job.payload['profile'])
        segments=current_segments(session,draft.id)
        wanted=job.payload.get('block_ids')
        units=plan_units(source,job.payload['locale'],profile,wanted,nonblocking=lease.kind!='semantic_review')
        if lease.kind=='translate':units=[u for u in units if u['owner_block_id'] not in segments]
        if lease.kind=='semantic_review':
            # Separate issue-only task; never reuse translation output as a semantic verdict.
            require(profile.get('semantic_review_enabled') is True,'SEMANTIC_REVIEW_DISABLED')
            for unit in units:
                segment=segments.get(unit['owner_block_id']);require(segment is not None,'REVIEW_TARGET_MISSING')
                unit['review_target_text']=flatten_inline(segment.target_inline,source['protected_atoms'])
                unit['review_target_hash']=digest(segment.target_inline)
                unit['review_glossary_revision']=segment.provenance_json.get('glossary_revision',draft.glossary_revision)
                unit['review_glossary_entries']=segment.provenance_json.get('glossary_entries',draft.profile.get('glossary_entries',[]))
        versions={b['id']:(segments[b['id']].sequence if b['id'] in segments else 0) for b in source['blocks']}
        for unit in units:
            session.add(Task(id=new_id('task'),job_id=job.id,kind=lease.kind,payload={'unit':unit,'base_version':versions[unit['owner_block_id']],'repair_count':0}))
        job.progress={'total_units':len(units),'verified_units':0,'total_blocks':len({u['owner_block_id'] for u in units}),'verified_blocks':0,'requests':0,'cache_hits':0}
        session.flush();finish(session,lease,{'planned_units':len(units)})
        if not units:
            finalize_translation(session,cfg,job,draft,source,lease.kind)
            emit(session,job)


def retry_or_stop(db,lease,failure,cfg=None):
    with db.transaction() as session:
        lock_lifecycle(session, allow_maintenance=True)
        # Always classify money, even when pause/cancel invalidated content writes.
        permit=session.scalar(select(Permit).where(Permit.attempt_id==lease.attempt_id))
        if failure.outcome=='executed_invalid' and permit and permit.state=='reserved':
            # A transport exception is not a settled response. Without usage
            # evidence it must not permit another paid dispatch.
            failure=ProviderFailure(failure.code,'unknown')
        if failure.outcome in {'not_sent','not_executed'}:
            if permit:release_unsent(session,lease.attempt_id,failure.code)
        elif failure.outcome=='unknown':
            mark_unknown(session,lease.attempt_id,failure.code)
        attempt=get_entity(session,Attempt,lease.attempt_id,lock=True)
        attempt.evidence=attempt.evidence+[{'kind':'provider_failure','code':failure.code,'outcome':failure.outcome,'at':now().isoformat()}]
        # Financial evidence belongs to the dispatched attempt, including after
        # document deletion. Content-facing lookups reject tombstones and would
        # roll back that evidence. Read the retained control rows directly and
        # stop before any content/state update when their owner is no longer live.
        job=session.scalar(select(Job).where(Job.id==lease.job_id).with_for_update().execution_options(populate_existing=True))
        task=session.scalar(select(Task).where(Task.id==lease.task_id).with_for_update().execution_options(populate_existing=True))
        document=session.get(Document,lease.document_id) if lease.document_id else None
        if (job is None or task is None or (lease.document_id and (document is None or document.deleted_at is not None))
                or task.fence!=lease.fence or job.control_epoch!=lease.control_epoch):return
        if failure.outcome=='unknown':
            task.status=job.status='outcome_unknown'
        elif failure.code in {'PROVIDER_CONFIG','PROVIDER_UNSUPPORTED_RESPONSE'}:
            task.status='failed';job.status='waiting_config'
        elif failure.code in {'PROVIDER_REFUSAL', 'UNIT_TOO_LARGE'}:
            task.status='failed';job.status='pending'
        elif failure.outcome in {'not_sent','not_executed'} and task.attempts<3:
            task.status=job.status='pending';task.available_at=now()+timedelta(seconds=max(failure.retry_after,min(2**task.attempts,30)))
        elif failure.outcome=='executed_invalid' and task.payload.get('repair_count',0)<1 and task.attempts<3:
            task.payload=task.payload|{'repair_count':task.payload.get('repair_count',0)+1,'repair_reason':failure.code}
            task.status=job.status='pending';task.available_at=now()+timedelta(seconds=2)
        else:
            task.status='failed';job.status='pending'
        attempt.finished_at=now()
        if attempt.state=='created':attempt.state='failed'
        if cfg and task.status=='failed' and job.status=='pending' and lease.kind in {'translate','candidate'}:
            session.flush()
            draft=get_entity(session,Draft,job.payload['draft_id'],lock=True)
            source=read_snapshot(cfg.data,get_entity(session,SourceRevision,draft.source_revision_id))
            finalize_translation(session,cfg,job,draft,source,lease.kind)
        elif task.status=='failed' and job.status=='pending' and lease.kind=='semantic_review':
            session.flush()
            finalize_semantic_review(session,job)
        job.error={'code':failure.code,'retryable':task.status=='pending'};emit(session,job)


def wait_without_dispatch(db,lease,code):
    with db.transaction() as session:
        job,task=assert_current(session,lease)
        task.status='pending'
        task.available_at=now()+timedelta(seconds=2)
        # No actual transport attempt occurred; contention must not consume retry allowance.
        task.attempts=max(0,task.attempts-1)
        attempt=session.get(Attempt,lease.attempt_id)
        attempt.state='not_executed';attempt.finished_at=now()
        if code=='INSTANCE_CONCURRENCY_LIMIT':job.status='pending'
        elif code=='BUDGET_PAUSED':job.status='waiting_budget'
        else:job.status='waiting_config'
        job.error={'code':code};emit(session,job)


def commit_unit(db,cfg,lease,unit,nodes,key,profile,cache_hit=False,origin_attempt_id=None,cacheable=True):
    with db.transaction() as session:
        # A sibling's retry/capacity wait is a scheduling change, not a user
        # cancellation. The original lease and control epoch still fence writes.
        job,task,draft,source=snapshot(session,cfg,lease,allow_pending=True)
        draft=get_entity(session,Draft,draft.id,lock=True)
        expected_glossary=job.payload.get('base_glossary_revision',job.payload.get('glossary_revision','empty-v1')) if lease.kind=='candidate' else job.payload.get('glossary_revision','empty-v1')
        require(draft.glossary_revision==expected_glossary,'GLOSSARY_STALE')
        if not cache_hit and cacheable:
            session.execute(insert(TranslationCache).values(key=key,document_id=job.document_id,value={'target_inline':cache_encode(unit,nodes),'provider':profile['provider'],'model_id':profile['model_id']}).on_conflict_do_nothing(index_elements=['key']))
        progress=dict(job.progress);progress['verified_units']=progress.get('verified_units',0)+1
        progress['cache_hits']=progress.get('cache_hits',0)+int(cache_hit);job.progress=progress
        finish(session,lease,{'unit_id':unit['unit_id'],'target_inline':nodes,'cache_hit':cache_hit},status='needs_review')
        owner=unit['owner_block_id']
        rows=session.scalars(select(Task).where(Task.job_id==job.id)).all()
        siblings=[t for t in rows if t.payload.get('unit',{}).get('owner_block_id')==owner]
        if len(siblings)==unit['unit_count'] and all(t.status=='succeeded' and t.result and 'target_inline' in t.result for t in siblings):
            joined=[]
            for sibling in sorted(siblings,key=lambda t:t.payload['unit']['unit_order']):joined.extend(restore_inline(sibling.payload['unit'],sibling.result['target_inline']))
            if lease.kind=='candidate':
                candidate=get_entity(session,Candidate,job.payload['candidate_id'],lock=True)
                candidate.results=candidate.results|{owner:joined};candidate.generation+=1
            else:
                existing=current_segments(session,draft.id).get(owner)
                if (existing.sequence if existing else 0)==task.payload['base_version']:
                    block=next(b for b in source['blocks'] if b['id']==owner)
                    session.add(SegmentVersion(id=new_id('seg'),draft_id=draft.id,block_id=owner,sequence=task.payload['base_version']+1,
                        target_inline=joined,origin='cache' if cache_hit else 'model',reason='Validated translation task',source_hash=block['source_hash'],
                        context_hash=context_hash(source,owner),provenance_json={'attempt_id':origin_attempt_id or lease.attempt_id,'job_id':job.id,'profile_revision':profile['profile_revision'],'prompt_version':profile['prompt_version']}))
                    draft.generation+=1;draft.qa_id=None
                else:
                    task.result=task.result|{'merge_conflict':True};job.error={'code':'SEGMENT_CONFLICT','block_id':owner}
            job.progress=job.progress|{'verified_blocks':job.progress.get('verified_blocks',0)+1}
        session.flush()
        finalize_translation(session,cfg,job,draft,source,lease.kind)
        emit(session,job)


def execute_translation(db,cfg,lease,provider=None):
    if 'unit' not in lease.payload:
        plan_tasks(db,cfg,lease);return
    unit=lease.payload['unit'] | ({'repair_reason':lease.payload['repair_reason']} if lease.payload.get('repair_reason') else {})
    with db.transaction() as session:
        job,task,draft,source=snapshot(session,cfg,lease)
        profile=job.payload['profile'];glossary=unit.get('review_glossary_entries',job.payload.get('glossary',[]))
        try:check_language_policy(profile,source,unit['target_locale'])
        except ValueError as exc:raise DomainError(str(exc)) from exc
        key=cache_key(unit,profile,job.payload.get('glossary_revision','empty-v1'))
        cache=session.get(TranslationCache,key)
        cached_nodes=None
        checkpoint=None
        if lease.kind!='semantic_review':
            for old_attempt in session.scalars(select(Attempt).where(Attempt.task_id==lease.task_id,Attempt.state=='settled').order_by(Attempt.created_at.desc())):
                for evidence in old_attempt.evidence:
                    if evidence.get('kind')=='validated_unit' and evidence.get('unit_hash')==digest(unit):
                        candidate_nodes=evidence['target_inline']
                        validate_output({'results':[{'unit_id':unit['unit_id'],'target_inline':candidate_nodes}]},[unit],nonblocking=True)
                        checkpoint=(candidate_nodes,old_attempt.id,evidence.get('cache_key')==key)
                        break
                if checkpoint:break
        if cache and lease.kind!='semantic_review':
            origin=session.get(Document,cache.document_id)
            if origin and origin.deleted_at is None:
                try:
                    cached_nodes=cache_decode(unit,cache.value['target_inline'])
                    validate_output({'results':[{'unit_id':unit['unit_id'],'target_inline':cached_nodes}]},[unit],nonblocking=True)
                except (ValueError,KeyError):cached_nodes=None
    if cached_nodes is not None:
        commit_unit(db,cfg,lease,unit,cached_nodes,key,profile,cache_hit=True);return
    if checkpoint is not None:
        # Replay paid results even across adapter upgrades, but do not promote
        # legacy output into a cache for a different request format.
        commit_unit(db,cfg,lease,unit,checkpoint[0],key,profile,origin_attempt_id=checkpoint[1],cacheable=checkpoint[2]);return
    managed_provider = provider is None
    if provider is None:
        # Deployment changes invalidate the confirmed profile; a test double must be injected explicitly.
        if provider_profile()!=public_profile(profile):
            wait_without_dispatch(db,lease,'PROVIDER_PROFILE_STALE');return
        try:
            endpoint,protocol,auth_mode,key_file=resolve_provider_credentials(profile)
            if protocol == 'local_translation':
                from packages.providers.local_translation import LocalTranslation
                provider=LocalTranslation()
                def check_current():
                    with db.transaction() as session:
                        assert_current(session,lease)
                    if provider_profile()!=public_profile(profile):
                        raise ProviderFailure('PROVIDER_PROFILE_STALE','not_sent')
                provider.prepare(profile,check_current)
            elif protocol in ('gemini_interactions','claude_messages'):
                provider=NativeProvider(profile,key_file)
            elif not {'endpoint','api_protocol','auth_mode'} & profile.keys():
                # Preserve the explicitly configured legacy deployment contract.
                provider=OpenAIResponses(key_file)
            else:
                provider=OpenAIResponses(key_file,endpoint=endpoint,api_protocol=protocol,auth_mode=auth_mode)
        except ProviderFailure as failure:
            wait_without_dispatch(db,lease,failure.code);return
    try:
        request_body([unit],profile,glossary,review=lease.kind=='semantic_review')
        with db.transaction() as session:
            if managed_provider and profile.get('api_protocol')=='local_translation' and provider_profile()!=public_profile(profile):
                raise ProviderFailure('PROVIDER_PROFILE_STALE','not_sent')
            authorize(session,lease,reserve_cost(profile),profile.get('price'))
            job=session.get(Job,lease.job_id);job.progress=job.progress|{'requests':job.progress.get('requests',0)+1};emit(session,job)
    except DomainError as exc:
        if exc.code in {'BUDGET_PAUSED','INSTANCE_CONCURRENCY_LIMIT','DISPATCH_DISABLED'}:wait_without_dispatch(db,lease,exc.code);return
        raise
    except (ValueError,ProviderFailure) as exc:
        if profile.get('api_protocol')=='local_translation' and getattr(exc,'code',None)=='UNIT_TOO_LARGE':
            retry_or_stop(db,lease,exc,cfg);return
        wait_without_dispatch(db,lease,getattr(exc,'code','PROVIDER_CONFIG'));return
    try:
        from packages.jobs.history import record_api_model
        record_api_model(db, lease, profile)
        response=(provider.review if lease.kind=='semantic_review' else provider.translate)([unit],profile,glossary)
    except ProviderFailure as failure:
        retry_or_stop(db,lease,failure,cfg);return
    record_api_model(db, lease, profile, response)
    if response.get('failure_code') == 'PROVIDER_MODEL_MISMATCH':
        retry_or_stop(db,lease,ProviderFailure('PROVIDER_MODEL_MISMATCH','unknown'),cfg);return
    # Network has returned. Accounting accepts late evidence independently of the current fence.
    try:
        with db.transaction() as session:settle(session,lease.attempt_id,response.get('usage'),response.get('request_id'))
    except ValueError as exc:
        code = str(exc) if str(exc) in {'USAGE_BILLING_UNCONFIRMED','UNPRICED_USAGE_DIMENSION'} else 'USAGE_MISSING'
        if response.get('failure_code') == 'PROVIDER_MODEL_MISMATCH':
            code = 'PROVIDER_MODEL_MISMATCH'
        retry_or_stop(db,lease,ProviderFailure(code,'unknown'),cfg);return
    try:
        if response.get('failure_code'):raise ProviderFailure(response['failure_code'])
        if response.get('status')!='completed':raise ProviderFailure('PROVIDER_TRUNCATED')
        if response.get('refusal'):raise ProviderFailure('PROVIDER_REFUSAL')
        if lease.kind=='semantic_review':
            issues=validate_review(response['output_text'],[unit])
            with db.transaction() as session:
                job,task,draft,source=snapshot(session,cfg,lease)
                segment=current_segments(session,draft.id).get(unit['owner_block_id'])
                stale=(segment is None or digest(segment.target_inline)!=unit['review_target_hash']
                    or segment.provenance_json.get('glossary_revision',draft.glossary_revision)!=unit['review_glossary_revision'])
                localized=[issue|{'block_id':unit['owner_block_id'],'rule_version':'semantic-review-v1','source_hash':unit['source_hash'],'target_hash':unit['review_target_hash'],'context_hash':unit['context_hash'],'glossary_revision':unit['review_glossary_revision'],'stale':stale,'origin':'model'} for issue in issues]
                finish(session,lease,{'issues':localized,'stale':stale},status='needs_review')
                job.progress=job.progress|{'verified_units':job.progress.get('verified_units',0)+1,'semantic_issues':job.progress.get('semantic_issues',[])+localized}
                if not stale:
                    # A completed current review changes the QA evidence baseline,
                    # while target text and human review records remain untouched.
                    draft.qa_id=None
                finalize_semantic_review(session,job)
                emit(session,job)
            return
        nodes=validate_output(response['output_text'],[unit],nonblocking=True)[unit['unit_id']]
    except ProviderFailure as failure:
        retry_or_stop(db,lease,failure,cfg);return
    with db.transaction() as session:
        document=session.scalar(select(Document).where(Document.id==lease.document_id).with_for_update().execution_options(populate_existing=True))
        if document is None or document.deleted_at is not None:
            # Settlement is retained, but deletion must never be followed by a
            # late checkpoint that resurrects source or target content.
            return
        attempt=session.get(Attempt,lease.attempt_id);attempt.output_hash=digest(nodes)
        attempt.evidence=attempt.evidence+[{'kind':'validated_unit','unit_hash':digest(unit),'target_inline':nodes,'cache_key':key}]
    try:commit_unit(db,cfg,lease,unit,nodes,key,profile)
    except DomainError as exc:
        if exc.code not in {'CONTROL_CHANGED','FENCE_EXPIRED','DOCUMENT_DELETED','MAINTENANCE'}:raise
        # Accounting/checkpoint remains durable; a stale execution cannot write the current draft.
