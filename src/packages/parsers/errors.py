"""Bounded parser diagnostics; never expose exception bodies or model content."""
import re

import httpx

from packages.domain.errors import DomainError
from packages.ir import IRValidationError
from .inspect import PDFError

MESSAGES = {
    'PARSER_FAILED': 'An unexpected parser error occurred. The original PDF is preserved.',
    'IMMUTABLE_CONFLICT': 'The parser tried to overwrite immutable output. The original PDF is preserved.',
    'PARSER_DMR_BACKEND_FAILED': 'Docker Model Runner failed while running the selected model. Check its backend logs; the original PDF is preserved.',
    'PARSER_DMR_BACKEND_INIT_FAILED': 'Docker Model Runner could not initialize the selected model. Check its backend logs; the original PDF is preserved.',
    'PARSER_DMR_CONNECTION_FAILED': 'The parser could not connect to Docker Model Runner. Check the inference service and network.',
    'PARSER_DMR_REQUEST_TIMEOUT': 'Docker Model Runner did not respond within the inference request timeout. No automatic retry was made.',
    'PARSER_DMR_CONFIGURATION_FAILED': 'Docker Model Runner rejected or could not apply the selected model configuration.',
    'PARSER_DMR_BACKEND_UNAVAILABLE': 'The selected Docker Model Runner inference backend is unavailable.',
    'PARSER_DMR_MODEL_MISMATCH': 'Docker Model Runner model identity or configuration differs from the saved parser selection.',
    'PARSER_IR_INVALID': 'The parsed document could not be saved because its structure failed validation. The original PDF is preserved; inspect the validation details.',
}

IR_REASONS = frozenset({
    'prose cannot disable translation', 'unknown schema version', 'not canonical JSON',
    'non-finite JSON number', 'source capacity exceeded', 'semantic inline capacity exceeded',
    'asset count exceeded', 'duplicate block IDs', 'duplicate asset IDs', 'duplicate block order',
    'invalid original PDF binding', 'asset bytes exceeded', 'duplicate parser evidence page',
    'parser evidence capacity exceeded', 'parser evidence hash mismatch', 'asset missing',
    'unsafe relative path', 'symlink forbidden', 'path escapes root', 'asset size mismatch',
    'asset hash mismatch', 'invalid raster image', 'root reading order mismatch',
    'reading order disagrees with block order', 'invalid title block', 'source title drift',
    'parent must be a heading', 'parent cycle', 'parent missing', 'invalid owner',
    'illegal owner kind', 'ownership cycle or missing owner', 'ownership depth exceeded',
    'table cell cannot be a root', 'normalization cannot be reproduced',
    'inline source differs from normalized text', 'source hash mismatch', 'bbox outside page',
    'missing raster asset', 'missing comparison raster', 'caption ownership mismatch',
    'child ownership mismatch', 'group duplicates leaf content', 'note ownership mismatch',
    'invalid table cell reference', 'cell out of bounds', 'overlapping table cells',
    'table coverage gap', 'schema or structure mismatch',
})
IR_PATH_FIELDS = frozenset({
    'blocks', 'assets', 'protected_atoms', 'parser', 'evidence', 'pages', 'path', 'page',
    'reading_order', 'schema_version', 'id', 'title_block_id', 'original_asset_id',
    'source_inline', 'normalized_text', 'raw_text', 'source_hash', 'sha256', 'byte_size',
    'storage_key', 'media_type', 'kind', 'type', 'owner_id', 'parent_id', 'order',
    'translatable', 'attributes', 'normalization_edits', 'provenance', 'bbox', 'page_size',
    'asset_id', 'comparison_asset_id', 'children_block_ids', 'caption_block_ids',
    'note_block_ids', 'cells', 'rows', 'columns', 'row', 'column', 'row_span', 'column_span',
    'row_groups', 'column_groups', 'warnings', 'text', 'ref', 'href', 'label',
})


def safe_ir_path(path):
    if not isinstance(path, str) or len(path) > 512 or not (path == '$' or path.startswith('$.')):
        return '$'
    parts = path.split('.')[1:]
    if len(parts) > 16:
        return '$'
    return '$' + ''.join('.' + (part if part in IR_PATH_FIELDS or re.fullmatch(r'(?:b)?[0-9]{1,6}', part) else '*')
                         for part in parts)


def safe_failure(value):
    value = value if isinstance(value, dict) else {}
    code = value.get('code')
    if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', code):
        code = 'PARSER_FAILED'
    message = value.get('message')
    if not isinstance(message, str) or not message.strip():
        message = MESSAGES.get(code, code.replace('_', ' ').capitalize())
    # Messages originate in parser code, not arbitrary exception/HTTP bodies.
    # Defense in depth for an untrusted spool record containing auth material.
    if re.search(r'(?i)bearer\s|api[_-]?key\s*[:=]|password\s*[:=]|secret\s*[:=]|token\s*[:=]|data:image/', message):
        message = MESSAGES.get(code, code.replace('_', ' ').capitalize())
    details = {}
    source = value.get('details') if isinstance(value.get('details'), dict) else {}
    for key in ('phase', 'exception_type', 'backend', 'backend_reason'):
        entry = source.get(key)
        if isinstance(entry, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}', entry):
            details[key] = entry
    for key, low, high in [('page', 1, 200), ('http_status', 100, 599)]:
        entry = source.get(key)
        if type(entry) is int and low <= entry <= high:
            details[key] = entry
    if code == 'PARSER_IR_INVALID':
        # JSON-schema messages may interpolate source text; only fixed validator
        # reasons and structural path components are suitable for task history.
        message = MESSAGES[code]
        reason = source.get('validation_reason')
        details['validation_reason'] = reason if isinstance(reason, str) and reason in IR_REASONS else 'schema or structure mismatch'
        details['validation_path'] = safe_ir_path(source.get('validation_path'))
    return {'code': code, 'message': message.strip()[:1000], **({'details': details} if details else {})}


def exception_failure(exc, context=None):
    if isinstance(exc, IRValidationError):
        prefix = f'{exc.path}: '
        reason = str(exc).removeprefix(prefix)
        return safe_failure({'code': 'PARSER_IR_INVALID', 'message': MESSAGES['PARSER_IR_INVALID'],
            'details': {**(context or {}), 'exception_type': 'IRValidationError',
                        'validation_reason': reason, 'validation_path': exc.path}})
    code = exc.code if isinstance(exc, (PDFError, DomainError)) else (
        str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'PARSER_[A-Z0-9_]{1,80}', str(exc)) else 'PARSER_FAILED')
    extra = getattr(exc, 'details', {})
    details = {**(context or {}), **(extra if isinstance(extra, dict) else {}), 'exception_type': type(exc).__name__}
    # Only our classified errors carry a user-facing custom message. Unexpected
    # exceptions may contain PDF text, URLs, credentials or absolute paths.
    message = MESSAGES.get(code, code.replace('_', ' ').capitalize())
    if isinstance(exc, PDFError) and code.startswith('PARSER_DMR_'):
        message = str(exc) if str(exc) != code else message
    return safe_failure({'code': code, 'message': message, 'details': details})


def inference_failure(exc, backend):
    code = 'PARSER_DMR_BACKEND_FAILED'
    details = {'backend': backend, 'phase': 'model_inference', 'exception_type': type(exc).__name__}
    if isinstance(exc, httpx.TimeoutException):
        code = 'PARSER_DMR_REQUEST_TIMEOUT'
    elif isinstance(exc, httpx.RequestError):
        code = 'PARSER_DMR_CONNECTION_FAILED'
    elif isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        details['http_status'] = response.status_code
        # Read a bounded error while the response stream is open. Only recognized
        # technical categories survive; backend tracebacks/request text do not.
        body = bytearray()
        try:
            for chunk in response.iter_bytes(1024):
                body.extend(chunk[:8192 - len(body)])
                if len(body) >= 8192:
                    break
        except (httpx.HTTPError, httpx.StreamError):
            pass
        if any(marker in body for marker in (b'unable to load runner', b'Engine core initialization failed', b'terminated unexpectedly')):
            code = 'PARSER_DMR_BACKEND_INIT_FAILED'
            details['backend_reason'] = 'engine_initialization_failed'
        if b'CUBLAS_STATUS_NOT_INITIALIZED' in body:
            code = 'PARSER_DMR_BACKEND_INIT_FAILED'
            details['backend_reason'] = 'CUBLAS_STATUS_NOT_INITIALIZED'
    return safe_failure({'code': code, 'message': MESSAGES[code], 'details': details})
