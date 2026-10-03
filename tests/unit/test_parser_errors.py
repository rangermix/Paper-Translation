import httpx
import pytest

from packages.domain.errors import DomainError
from packages.ir import IRValidationError
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


def test_ir_failure_reports_fixed_reason_and_block_location():
    error = exception_failure(IRValidationError('prose cannot disable translation', '$.blocks.b385'),
                              {'phase': 'parser_result_validation'})
    assert error['code'] == 'PARSER_IR_INVALID'
    assert 'could not be saved' in error['message']
    assert error['details'] == {'phase': 'parser_result_validation', 'exception_type': 'IRValidationError',
        'validation_reason': 'prose cannot disable translation', 'validation_path': '$.blocks.b385'}
    assert safe_failure(error) == error


@pytest.mark.parametrize('path,expected', [('/private/token=secret', '$'),
    ('$.blocks.3.private_source_text.normalized_text', '$.blocks.3.*.normalized_text'),
    ('$.blocks.b12.attributes.cells.4', '$.blocks.b12.attributes.cells.4')])
def test_ir_failure_does_not_expose_dynamic_schema_messages_or_path_keys(path, expected):
    error = exception_failure(IRValidationError('Bearer private-secret: private PDF text is invalid', path))
    assert error['details']['validation_reason'] == 'schema or structure mismatch'
    assert error['details']['validation_path'] == expected
    assert 'private' not in str(error) and 'secret' not in str(error)


def test_untrusted_ir_spool_rejects_arbitrary_message_and_nonstring_reason():
    error = safe_failure({'code': 'PARSER_IR_INVALID', 'message': 'private PDF text',
        'details': {'validation_reason': ['private PDF text'], 'validation_path': '/private/file.pdf'}})
    assert error['details'] == {'validation_reason': 'schema or structure mismatch', 'validation_path': '$'}
    assert 'private' not in str(error)
