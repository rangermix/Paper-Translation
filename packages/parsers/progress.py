"""Bounded one-writer progress spool; no text, credentials, database or network."""
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from packages.ir import canonical_bytes, safe_path, strict_loads

_writer = ContextVar('parser_progress', default=None)
MAX_EVENTS = 2048
MAX_BYTES = 2 * 1024 * 1024
OPERATIONS = {'started', 'loading_model', 'model_loaded', 'page_started', 'page_completed',
              'recovery_started', 'recovery_completed', 'check_failed', 'finished'}


def configure_progress(output, request):
    return _writer.set({'output': Path(output), 'request': request, 'sequence': 0, 'bytes': 0})


def reset_progress(token):
    _writer.reset(token)


def remaining_seconds():
    writer = _writer.get()
    if writer is None:
        return float('inf')
    deadline = datetime.fromisoformat(writer['request']['deadline'].replace('Z', '+00:00'))
    return max(0, (deadline - datetime.now(timezone.utc)).total_seconds())


def report_progress(operation, *, page=None, model=None, phase=None):
    writer = _writer.get()
    if writer is None or operation not in OPERATIONS or writer['sequence'] >= MAX_EVENTS:
        return
    request = writer['request']
    value = {k: request[k] for k in ('task_id', 'fence', 'source_sha256')}
    value.update(sequence=writer['sequence'] + 1, at=datetime.now(timezone.utc).isoformat(),
                 operation=operation, page=page, phase=phase)
    if model is not None:
        from packages.domain.workflow import ModelIdentity
        value['model'] = ModelIdentity.model_validate(model).model_dump(exclude_none=True)
    data = canonical_bytes(value) + b'\n'
    if writer['bytes'] + len(data) > MAX_BYTES:
        return
    path = safe_path(writer['output'], 'progress.jsonl', must_exist=False)
    with path.open('ab') as handle:
        handle.write(data)
    writer['sequence'] += 1
    writer['bytes'] += len(data)


def read_progress(output, request, cursor=0):
    path = safe_path(output, 'progress.jsonl', must_exist=False)
    if not path.exists():
        return []
    with path.open('rb') as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('PARSER_PROGRESS_LIMIT')
    lines = data.split(b'\n')[:-1]  # A concurrent incomplete line is read next time.
    if len(lines) > MAX_EVENTS:
        raise ValueError('PARSER_PROGRESS_LIMIT')
    result = []
    for expected, line in enumerate(lines, 1):
        event = strict_loads(line)
        if event.get('sequence') != expected or any(event.get(k) != request[k] for k in ('task_id', 'fence', 'source_sha256')):
            raise ValueError('PARSER_PROGRESS_BINDING')
        if event.get('operation') not in OPERATIONS:
            raise ValueError('PARSER_PROGRESS_INVALID')
        page = event.get('page')
        if page is not None and (type(page) is not int or not 1 <= page <= request['max_pages']):
            raise ValueError('PARSER_PROGRESS_INVALID')
        when = datetime.fromisoformat(event['at'])
        if when.tzinfo is None:
            raise ValueError('PARSER_PROGRESS_INVALID')
        if expected > cursor:
            result.append(event)
    return result


def local_identity(selection, lock):
    from packages.parsers.config import CPU_THREADS
    from packages.parsers.profiles import GRANITE_MODEL, GRANITE_PROFILE, PADDLE_MODEL, PADDLE_PROFILE
    from .runtime import runtime_config
    runtime = runtime_config(selection)
    ids = ({PADDLE_MODEL, 'PaddlePaddle/PP-DocLayoutV3'} if selection == PADDLE_PROFILE else
           {GRANITE_MODEL} if selection == GRANITE_PROFILE else
           {'docling-project/docling-layout-old', 'docling-project/docling-models', 'docling-project/CodeFormulaV2', 'RapidAI/RapidOCR'})
    models = [{'model_id': row['repo_id'], 'revision': row['revision']} for row in lock['repositories'] if row['repo_id'] in ids]
    writer = _writer.get()
    from packages.parsers.timeouts import request_timeout_seconds
    return {'kind': 'local', 'model_id': PADDLE_MODEL if selection == PADDLE_PROFILE else GRANITE_MODEL if selection == GRANITE_PROFILE else 'docling-standard',
        'models': models, 'parser_profile_revision': selection, **runtime.identity(), 'threads': CPU_THREADS,
        'engine': 'paddleocr' if selection == PADDLE_PROFILE else 'docling',
        'engine_version': lock['paddleocr_version' if selection == PADDLE_PROFILE else 'docling_version'],
        'timeout_seconds': request_timeout_seconds(writer['request']) if writer else None,
        'evidence_source': 'parser_execution'}
