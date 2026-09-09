"""Untrusted parser file protocol. No database, secrets, or caller-provided paths."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from packages.ir import canonical_bytes, digest, safe_path, strict_loads
from .models import parser_version
from .profiles import selected_profile
from .timeouts import request_timeout_seconds

REQUEST_KEYS = {'task_id','fence','source_sha256','max_pages','deadline','timeout_seconds','parser_version','operation','asset_id','profile'}


def validate_request(request):
    if not isinstance(request,dict) or set(request)-REQUEST_KEYS:
        raise ValueError('PARSER_REQUEST_INVALID: unknown fields')
    for field in ['task_id','fence','source_sha256','max_pages','deadline','parser_version']:
        if field not in request: raise ValueError('PARSER_REQUEST_INVALID: missing '+field)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}',request['task_id']): raise ValueError('PARSER_REQUEST_INVALID')
    if type(request['fence']) is not int or request['fence'] < 1: raise ValueError('PARSER_REQUEST_INVALID')
    if not re.fullmatch(r'[0-9a-f]{64}',request['source_sha256']): raise ValueError('PARSER_REQUEST_INVALID')
    if type(request['max_pages']) is not int or not 1 <= request['max_pages'] <= 200: raise ValueError('PARSER_REQUEST_INVALID')
    if request.get('operation','parse') not in {'inspect','parse'}: raise ValueError('PARSER_REQUEST_INVALID')
    request_timeout_seconds(request)
    if not isinstance(request.get('profile', {}), dict): raise ValueError('PARSER_REQUEST_INVALID: profile')
    selection = selected_profile(request.get('profile', {}))
    expected_version = 'inspector-v1' if request.get('operation','parse') == 'inspect' else parser_version(selection)
    if request['parser_version'] != expected_version: raise ValueError('PARSER_VERSION_MISMATCH')
    deadline = datetime.fromisoformat(request['deadline'].replace('Z','+00:00'))
    if deadline.tzinfo is None: raise ValueError('PARSER_REQUEST_INVALID: deadline must have timezone')
    if request.get('asset_id') and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,159}',request['asset_id']): raise ValueError('PARSER_REQUEST_INVALID')
    if not isinstance(request.get('profile', {}), dict) or set(request.get('profile',{}))-{'language','created_at','parser_profile_revision'}:
        raise ValueError('PARSER_REQUEST_INVALID: profile')
    selected_profile(request.get('profile', {}))
    return request


def write_request(input_root, request, source_pdf):
    import shutil
    validate_request(request)
    relative = request['task_id']+'/'+str(request['fence'])
    target = safe_path(input_root,relative+'/request.json',must_exist=False)
    target.parent.mkdir(parents=True,exist_ok=True)
    source = Path(source_pdf)
    if source.is_symlink() or digest(source.read_bytes()) != request['source_sha256']:
        raise ValueError('SOURCE_HASH_MISMATCH')
    original = target.parent/'original.pdf'
    if target.exists():
        if strict_loads(target.read_bytes()) != request:raise ValueError('PARSER_REQUEST_CONFLICT')
        return target
    shutil.copyfile(source,original)
    temporary = target.with_suffix('.tmp'); temporary.write_bytes(canonical_bytes(request)); temporary.replace(target)
    return target


def verify_result(output_dir, request, result=None):
    root = Path(output_dir)
    result = result or strict_loads(safe_path(root,'result.json').read_bytes())
    for field in ['task_id','fence','source_sha256']:
        if result.get(field) != request.get(field):raise ValueError('PARSER_STALE_RESULT')
    files = result.get('files',[])
    if len(files)>1000 or sum(f['byte_size'] for f in files)>300*1024*1024:raise ValueError('PARSER_OUTPUT_LIMIT')
    if len({f['path'] for f in files}) != len(files):raise ValueError('PARSER_DUPLICATE_OUTPUT')
    for entry in files:
        if entry['byte_size'] < 0:raise ValueError('PARSER_OUTPUT_LIMIT')
        file = safe_path(root,entry['path'])
        if file.stat().st_size != entry['byte_size'] or digest(file.read_bytes()) != entry['sha256']:
            raise ValueError('PARSER_OUTPUT_HASH_MISMATCH')
    if result.get('status') == 'succeeded' and result.get('operation') == 'parse' and 'payload.json' not in {f['path'] for f in files}:
        raise ValueError('PARSER_OUTPUT_MISSING_PAYLOAD')
    return result
