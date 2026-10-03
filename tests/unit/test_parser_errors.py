import httpx

from packages.domain.errors import DomainError
from packages.parsers.errors import exception_failure, inference_failure, safe_failure


def test_unexpected_exception_never_exposes_credentials_paths_or_pdf_text():
    error = exception_failure(RuntimeError('Bearer private-token at /private/path with PDF source text'),
                              {'phase': 'model_inference', 'page': 2})
    assert error['code'] == 'PARSER_FAILED'
    assert error['details'] == {'phase': 'model_inference', 'page': 2, 'exception_type': 'RuntimeError'}
    assert 'private-token' not in str(error) and 'PDF source text' not in str(error)


def test_known_storage_error_preserves_code_and_execution_context():
    error = exception_failure(DomainError('IMMUTABLE_CONFLICT'), {'phase': 'model_inference', 'page': 2})
    assert error['code'] == 'IMMUTABLE_CONFLICT'
    assert 'overwrite immutable output' in error['message']
    assert error['details']['page'] == 2


def test_untrusted_failure_details_are_bounded_and_auth_material_is_removed():
    error = safe_failure({'code': 'PARSER_FAILED', 'message': 'token=private-token',
        'details': {'page': True, 'http_status': 500, 'pdf_text': 'private text', 'api_key': 'private-key'}})
    assert error['details'] == {'http_status': 500}
    assert 'private-token' not in str(error) and 'private-key' not in str(error)
    assert safe_failure({'code': 'bad\ncode'})['code'] == 'PARSER_FAILED'


def test_timeout_and_connection_failure_have_distinct_codes_without_request_urls():
    request = httpx.Request('POST', 'http://user:private-secret@runner/v1/chat/completions')
    for exception, code in [(httpx.ReadTimeout('private body', request=request), 'PARSER_DMR_REQUEST_TIMEOUT'),
                            (httpx.ConnectError('private body', request=request), 'PARSER_DMR_CONNECTION_FAILED')]:
        error = inference_failure(exception, 'vllm')
        assert error['code'] == code
        assert 'private-secret' not in str(error) and 'private body' not in str(error)
