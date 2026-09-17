"""Shared wall-time policy; queued jobs retain the timeout selected at enqueue."""

DEFAULT_PARSE_TIMEOUT_SECONDS = 7200
MIN_PARSE_TIMEOUT_SECONDS = 60
MAX_PARSE_TIMEOUT_SECONDS = 86400
LEGACY_PARSE_TIMEOUT_SECONDS = 900
INSPECT_TIMEOUT_SECONDS = 900
PARSER_RESULT_GRACE_SECONDS = 10


def validate_timeout_seconds(value):
    if type(value) is not int or not MIN_PARSE_TIMEOUT_SECONDS <= value <= MAX_PARSE_TIMEOUT_SECONDS or value % 60:
        raise ValueError('PARSER_REQUEST_INVALID: timeout must be whole minutes between 1 and 1440')
    return value


def selected_timeout_seconds(preferences):
    return validate_timeout_seconds(preferences.get('parser_timeout_seconds', DEFAULT_PARSE_TIMEOUT_SECONDS))


def task_timeout_seconds(payload, operation):
    if operation == 'inspect':
        return INSPECT_TIMEOUT_SECONDS
    return validate_timeout_seconds(payload.get('parser_timeout_seconds', LEGACY_PARSE_TIMEOUT_SECONDS))


def request_timeout_seconds(request):
    value = validate_timeout_seconds(request.get('timeout_seconds', LEGACY_PARSE_TIMEOUT_SECONDS))
    if request.get('operation', 'parse') == 'inspect':
        if value != INSPECT_TIMEOUT_SECONDS:
            raise ValueError('PARSER_REQUEST_INVALID: inspection timeout is fixed')
        return INSPECT_TIMEOUT_SECONDS
    return value
