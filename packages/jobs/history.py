"""Transactional execution receipts and bounded, content-free technical logs."""
import copy
import re
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import inspect, select
from sqlalchemy.dialects.postgresql import insert

from packages.domain.models import Attempt, Document, Job, Task, TaskLog, Upload, new_id, now
from packages.domain.workflow import ModelIdentity, TERMINAL_STATES

MODEL_TASKS = {'parse', 'recovery', 'translate', 'candidate', 'semantic_review', 'provider_test'}
MESSAGES = {
    'created': '任务已创建', 'started': '开始执行', 'finished': '执行结束',
    'state_changed': '任务状态已更新', 'lease_expired': '执行租约已到期',
    'model_loaded': '模型已加载', 'loading_model': '正在加载模型',
    'page_started': '正在解析页面', 'page_completed': '页面解析完成',
    'check_failed': '检查未完成', 'recovery_started': '开始恢复缺失内容',
    'recovery_completed': '内容恢复结束', 'metadata_lookup': '正在查询文献信息',
    'dispatch': '已派发 API 请求', 'response_received': '已收到 API 响应',
    'progress': '执行进度已更新',
    'history_backfill': '已从原有记录补全文档和任务信息',
}


def safe_details(details):
    """Allow technical values only; arbitrary keys/text are never copied."""
    result = {}
    for key in ('code', 'status', 'state', 'kind', 'result', 'quality_state'):
        value = (details or {}).get(key)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,99}', value):
            result[key] = value
    for key in ('fence', 'attempts', 'count', 'pages', 'blocks', 'elapsed_ms', 'timeout_seconds', 'sequence'):
        value = (details or {}).get(key)
        if type(value) in (int, float) and 0 <= value <= 10**12:
            result[key] = value
    return result


def _log_values(job, operation, *, event_key, level='info', task_id=None, attempt_id=None,
                page=None, unit_id=None, details=None, at=None):
    operation = operation if operation in MESSAGES else 'progress'
    return dict(job_id=job.id, event_key=event_key, at=at or now(), level=level if level in {'info', 'warning', 'error'} else 'info',
        stage=job.stage, operation=operation, task_id=task_id, attempt_id=attempt_id, page=page,
        unit_id=unit_id, message=MESSAGES[operation], details=safe_details(details))


def record_log(session, job, *, event_key, operation, **kwargs):
    values = _log_values(job, operation, event_key=event_key, **kwargs)
    # All callers hold the job/fence transaction. Spool replay is idempotent.
    session.flush()
    session.execute(insert(TaskLog).values(**values).on_conflict_do_nothing(index_elements=['job_id', 'event_key']))


def config_snapshot(stage, payload):
    payload = payload or {}
    workflow = payload.get('workflow') or {}
    profile = payload.get('profile') or workflow.get('profile') or {}
    result = {key: copy.deepcopy(profile[key]) for key in ('model_id', 'api_protocol', 'provider', 'config_revision',
        'profile_revision', 'prompt_version', 'privacy_revision', 'max_input_tokens', 'max_output_tokens',
        'max_unit_characters', 'cost_control_enabled') if key in profile}
    if profile.get('endpoint'):
        parsed = urlsplit(profile['endpoint'])
        if parsed.scheme in {'http', 'https'} and not parsed.username and not parsed.password:
            result['endpoint'] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
    for key in ('parser_profile_revision', 'parser_timeout_seconds', 'timeout_seconds', 'locale', 'source_language', 'publish_policy'):
        if key in payload:
            result[key] = copy.deepcopy(payload[key])
    result['task_kind'] = stage
    if workflow:
        result['target_locale'] = workflow.get('target_locale')
        result['translate'] = workflow.get('translate')
        result['publish_policy'] = workflow.get('publish_policy')
    return result


def set_actual_model(session, lease, identity):
    from packages.jobs.queue import assert_current
    job, task = assert_current(session, lease)
    model = ModelIdentity.model_validate(identity).model_dump(exclude_none=True)
    if model.get('endpoint'):
        parsed = urlsplit(model['endpoint'])
        model['endpoint'] = urlunsplit((parsed.scheme, parsed.netloc if not parsed.username and not parsed.password else parsed.hostname or '', parsed.path, '', ''))
    attempt = session.get(Attempt, lease.attempt_id)
    attempt.actual_model = copy.deepcopy(model)
    task.actual_model = copy.deepcopy(model)
    job.actual_model = copy.deepcopy(model)


def record_api_model(db, lease, profile, response=None):
    """Technical response receipt may arrive after cancellation, like usage."""
    from packages.domain.db import lock_lifecycle
    reported = (response or {}).get('response_model')
    if not isinstance(reported, str) or not 0 < len(reported) <= 256 or any(ord(c) < 32 for c in reported):
        reported = None
    fields = {k: profile[k] for k in ('provider', 'api_protocol', 'config_revision', 'endpoint') if k in profile}
    local = profile.get('api_protocol') == 'local_translation'
    if local:
        from packages.local_models.catalog import get_model
        entry = get_model(profile['model_id'])
        fields.update(engine='mlx', revision=entry['revision'], models=[{'name': entry['label'], 'bits': entry['bits']}])
    model = ModelIdentity(kind='local' if local else 'api', model_id=reported,
        evidence_source=('local_response' if local else 'api_response') if response is not None else ('local_dispatch' if local else 'api_dispatch'),
        **fields).model_dump(exclude_none=True)
    with db.transaction() as session:
        lock_lifecycle(session, allow_maintenance=True)
        attempt = session.get(Attempt, lease.attempt_id)
        job = session.scalar(select(Job).where(Job.id == lease.job_id).with_for_update())
        task = session.get(Task, lease.task_id)
        if not attempt or not job:
            return
        attempt.actual_model = copy.deepcopy(model)
        if task and task.fence == lease.fence:
            task.actual_model = copy.deepcopy(model)
            job.actual_model = copy.deepcopy(model)
        record_log(session, job, event_key=f'api:{lease.attempt_id}:{"response" if response is not None else "dispatch"}',
            operation='response_received' if response is not None else 'dispatch',
            attempt_id=lease.attempt_id, task_id=lease.task_id, details={'fence': lease.fence})


def track_lifecycle(session, flush_context, instances):
    """Capture ORM exits, including failures/cancellation outside queue.finish."""
    if not session.info.get('nb_history_enabled', True):
        return
    at = now()
    for entity in list(session.new) + list(session.dirty):
        if not isinstance(entity, (Job, Task, Attempt)):
            continue
        state = inspect(entity)
        fresh = entity in session.new
        field = 'state' if isinstance(entity, Attempt) else 'status'
        changed = state.attrs[field].history.has_changes()
        if not fresh and not changed:
            continue
        value = getattr(entity, field) or ('created' if isinstance(entity, Attempt) else 'pending')
        setattr(entity, field, value)
        if isinstance(entity, Job):
            job = entity
            if fresh:
                entity.queued_at = entity.queued_at or at
                entity.config_snapshot = config_snapshot(entity.stage, entity.payload)
                document = session.get(Document, entity.document_id) if entity.document_id else None
                if document and not document.deleted_at:
                    entity.title_snapshot = document.title
                elif (entity.payload or {}).get('upload_id'):
                    upload = session.get(Upload, entity.payload['upload_id'])
                    entity.title_snapshot = upload.filename if upload else None
            if value == 'running' and entity.started_at is None:
                entity.started_at = at
            if value in TERMINAL_STATES:
                entity.finished_at = entity.finished_at or at
            elif changed and value in {'pending', 'running'}:
                entity.finished_at = None
        else:
            job = session.get(Job, entity.job_id)
            if isinstance(entity, Attempt) and fresh or value == 'leased':
                entity.started_at = entity.started_at or at
            if value in TERMINAL_STATES | {'outcome_unknown', 'committed', 'known_failed', 'received', 'superseded', 'settled'}:
                entity.finished_at = entity.finished_at or at
        if job:
            operation = 'created' if fresh and not isinstance(entity, Attempt) else ('started' if value in {'running', 'leased', 'created'} else 'finished' if getattr(entity, 'finished_at', None) else 'state_changed')
            session.add(TaskLog(**_log_values(job, operation, event_key=new_id('lifecycle'), at=at,
                task_id=entity.task_id if isinstance(entity, Attempt) else entity.id if isinstance(entity, Task) else None,
                attempt_id=entity.id if isinstance(entity, Attempt) else None,
                details={'status': value, 'kind': type(entity).__name__, 'code': (job.error or {}).get('code')})))


def time_view(entity):
    at = now()
    started, ended = entity.started_at, entity.finished_at
    queued = getattr(entity, 'queued_at', None)
    return {'queued_at': queued, 'started_at': started, 'finished_at': ended,
        'queue_ms': max(0, int(((started or ended or at) - queued).total_seconds() * 1000)) if queued else None,
        'execution_ms': max(0, int(((ended or at) - started).total_seconds() * 1000)) if started else None}


def log_view(entry, *, content_deleted=False):
    view = {key: getattr(entry, key) for key in ('sequence', 'at', 'level', 'stage', 'operation',
        'task_id', 'attempt_id', 'page', 'unit_id', 'message', 'details')}
    if content_deleted:
        view['unit_id'] = None
    return view
