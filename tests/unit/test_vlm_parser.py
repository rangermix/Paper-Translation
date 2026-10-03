import io
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from packages.parsers.inspect import PDFError
from packages.parsers.vlm_output import html_items, json_items

PAGE = {'page': 1, 'page_size': [600, 800]}


def test_html_layout_maps_coordinates_preserves_table_spans_and_discards_image_descriptions():
    raw = '<div data-label="Text" data-bbox="0 0 500 100"><p>Source <b>words</b></p><script>hidden()</script></div><div data-label="Table" data-bbox="0 100 500 300"><table><tr><td colspan="2">Header</td></tr><tr><td>A</td><td>B</td></tr></table></div><div data-label="Image" data-bbox="500 0 1000 300">Generated description</div>'
    items = html_items(raw, PAGE)
    assert items[0]['text'] == 'Source words'
    assert items[0]['prov'][0]['bbox']['r'] == 300
    assert items[1]['data']['table_cells'][0]['col_span'] == 2
    assert items[2]['text'] == '' and items[2]['label'] == 'picture'


@pytest.mark.parametrize('bounds', ['nan 0 1000 1000', '0 0 1001 1000', '500 0 200 1000'])
def test_invalid_layout_does_not_fabricate_provenance(bounds):
    with pytest.raises((PDFError, ValueError)):
        html_items(f'<div data-label="Text" data-bbox="{bounds}">text</div>', PAGE)


def test_infinity_json_maps_formulas_and_table_data_in_reading_order():
    items = json_items('{"layout":[{"bbox":[0,0,1000,100],"category":"title","text":"Title"},{"bbox":[0,100,1000,200],"category":"formula","text":"E=mc^2"}]}', PAGE)
    assert [i['label'] for i in items] == ['title', 'formula']
    assert items[1]['text'] == 'E=mc^2'


@pytest.mark.parametrize('profile', ['surya-ocr-2-v1', 'chandra-ocr-2-v1', 'infinity-parser2-pro-v1',
    'infinity-parser2-flash-v1'])
def test_each_adapter_parses_real_fixture_pdf_into_valid_source_ir(profile, tmp_path, monkeypatch):
    from pathlib import Path
    from packages.parsers.pdf_vlm import VisionParser
    from packages.ir import validate_source
    monkeypatch.setenv('PARSER_ACCELERATOR', 'dmr')
    outputs = {
        'surya-ocr-2-v1': '<div data-label="Text" data-bbox="0 0 1000 1000">Synthetic OCR output</div>',
        'chandra-ocr-2-v1': '<div data-label="Text" data-bbox="0 0 1000 1000">Synthetic OCR output</div>',
        'infinity-parser2-pro-v1': '{"layout":[{"category":"text","bbox":[0,0,1000,1000],"text":"Synthetic OCR output"}]}',
        'infinity-parser2-flash-v1': '{"layout":[{"category":"text","bbox":[0,0,1000,1000],"text":"Synthetic OCR output"}]}',
    }
    def factory(*args):
        return lambda image, prompt: outputs[profile]
    result = VisionParser(inference_factory=factory).parse(Path('tests/fixtures/sample.pdf'), 'source_pdf', tmp_path,
        {'parser_profile_revision': profile})
    validate_source(result['source_revision'], asset_root=tmp_path)
    assert result['parser_profile_revision'] == profile
    assert result['source_revision']['blocks']
    assert (tmp_path / 'original.pdf').is_file() and list((tmp_path / 'pages').glob('*.png'))


@pytest.mark.parametrize('profile', ['surya-ocr-2-v1', 'chandra-ocr-2-v1',
    'infinity-parser2-pro-v1', 'infinity-parser2-flash-v1'])
def test_multi_page_evidence_index_can_advance_without_rewriting_page_receipts(profile, tmp_path):
    from pypdf import PdfReader, PdfWriter
    from packages.parsers.pdf_vlm import VisionParser
    from packages.ir import strict_loads, validate_source, digest
    original = PdfReader('tests/fixtures/sample.pdf')
    pdf = tmp_path / 'three-pages.pdf'
    writer = PdfWriter()
    for _ in range(3):
        writer.add_page(original.pages[0])
    writer.write(pdf)
    calls = []
    def factory(*args):
        def infer(*args):
            calls.append(len(calls) + 1)
            text = f'Synthetic page {calls[-1]}'
            return (f'<div data-label="Text" data-bbox="0 0 1000 1000">{text}</div>'
                    if profile.startswith(('surya', 'chandra')) else
                    '{"layout":[{"category":"text","bbox":[0,0,1000,1000],"text":"' + text + '"}]}')
        return infer
    output = tmp_path / 'output'
    result = VisionParser(inference_factory=factory).parse(pdf, 'source_pdf', output,
        {'parser_profile_revision': profile})
    validate_source(result['source_revision'], asset_root=output)
    index = strict_loads((output / 'vision-parser.json').read_bytes())
    assert calls == [1, 2, 3]
    assert [row['page'] for row in index['pages']] == calls
    for row in index['pages']:
        assert digest((output / row['response_path']).read_bytes()) == row['sha256']


def test_backend_execution_failure_is_recorded_once_and_stops_page_dispatch(tmp_path):
    from pypdf import PdfReader, PdfWriter
    from packages.parsers.pdf_vlm import VisionParser
    from packages.ir import strict_loads
    from packages.parsers.errors import MESSAGES
    writer = PdfWriter()
    original = PdfReader('tests/fixtures/sample.pdf')
    for _ in range(2):
        writer.add_page(original.pages[0])
    pdf = tmp_path / 'two-pages.pdf'
    writer.write(pdf)
    calls = []
    def factory(*args):
        def infer(*args):
            calls.append(1)
            return {'content': '', 'response': None, 'raw_response': None, 'finish_reason': None,
                    'usage': None, 'engine_version': None, 'inference_error': 'HTTPStatusError',
                    'inference_failure': {'code': 'PARSER_DMR_BACKEND_INIT_FAILED',
                        'message': MESSAGES['PARSER_DMR_BACKEND_INIT_FAILED'],
                        'details': {'backend': 'vllm', 'http_status': 500, 'phase': 'model_inference'}}}
        return infer
    with pytest.raises(PDFError, match='could not initialize') as error:
        VisionParser(inference_factory=factory).parse(pdf, 'source_pdf', tmp_path,
            {'parser_profile_revision': 'infinity-parser2-flash-v1'})
    assert calls == [1]
    assert error.value.details['page'] == 1
    receipt = strict_loads((tmp_path / 'evidence/page-0001.response.json').read_bytes())
    assert receipt['inference_failure']['details']['http_status'] == 500
    assert not (tmp_path / 'evidence/page-0002.response.json').exists()
    assert strict_loads((tmp_path / 'vision-parser.json').read_bytes())['pages'][0]['page'] == 1


def test_dmr_http_error_preserves_safe_backend_diagnostic_without_response_text(monkeypatch):
    from packages.parsers.pdf_vlm import DockerVision
    from packages.parsers.catalog import vlm_model
    from packages.parsers.runtime import runtime_config
    from packages.parsers.model_service import dmr_flags
    from packages.parsers.profiles import SURYA_PROFILE
    monkeypatch.setenv('PARSER_DMR_URL', 'http://runner')
    monkeypatch.setenv('PARSER_DMR_BACKEND', 'vllm')
    runtime, model = runtime_config(SURYA_PROFILE), vlm_model(SURYA_PROFILE)
    def fetch(request):
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm test'})
        if '/models/' in request.url.path:
            return httpx.Response(200, json={'id': runtime.model_id})
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': 'vllm', 'ModelID': runtime.model_id,
                'Config': {'context-size': model['context_size'], 'runtime-flags': dmr_flags(model, 'vllm')}}])
        return httpx.Response(500, content=b'unable to load runner: CUBLAS_STATUS_NOT_INITIALIZED; Bearer private-token; source content')
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(fetch), **kwargs))
    with Image.new('RGB', (10, 10)) as image:
        result = DockerVision(model, None, runtime)(image, 'OCR')
    failure = result['inference_failure']
    assert failure['code'] == 'PARSER_DMR_BACKEND_INIT_FAILED'
    assert failure['details']['http_status'] == 500
    assert failure['details']['backend_reason'] == 'CUBLAS_STATUS_NOT_INITIALIZED'
    assert 'private-token' not in str(result) and 'source content' not in str(result)


@pytest.mark.parametrize('wrong_at', ['metadata', 'configuration', 'response'])
def test_dmr_identity_mismatch_never_becomes_source_text(wrong_at, monkeypatch):
    from packages.parsers.pdf_vlm import DockerVision
    from packages.parsers.catalog import vlm_model
    from packages.parsers.runtime import runtime_config
    from packages.parsers.model_service import dmr_flags
    from packages.parsers.profiles import SURYA_PROFILE
    monkeypatch.setenv('PARSER_ACCELERATOR', 'dmr')
    monkeypatch.setenv('PARSER_DMR_BACKEND', 'vllm')
    monkeypatch.setenv('PARSER_DMR_URL', 'http://runner')
    runtime, model = runtime_config(SURYA_PROFILE), vlm_model(SURYA_PROFILE)
    requests = []
    def fetch(request):
        requests.append(request.url.path)
        if request.url.path == '/engines/status':
            return httpx.Response(200, json={'vllm': 'Running: vllm test'})
        if '/models/' in request.url.path:
            return httpx.Response(200, json={'id': 'wrong' if wrong_at == 'metadata' else runtime.model_id})
        if request.url.path == '/engines/_configure':
            return httpx.Response(200, json=[{'Backend': 'vllm', 'ModelID': runtime.model_id,
                'Config': {'context-size': 1 if wrong_at == 'configuration' else model['context_size'],
                           'runtime-flags': dmr_flags(model, 'vllm')}}])
        from packages.ir import strict_loads
        body = strict_loads(request.content)
        assert body['model'] == runtime.model_id
        assert body['chat_template_kwargs'] == {'enable_thinking': False}
        return httpx.Response(200, json={'model': 'wrong', 'choices': [{'message': {'role': 'assistant', 'content': 'text'}}]})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(fetch), **kwargs))
    with Image.new('RGB', (10, 10)) as image:
        with pytest.raises(PDFError, match='MISMATCH'):
            DockerVision(model, None, runtime)(image, 'OCR')
    if wrong_at in ('metadata', 'configuration'):
        assert '/engines/vllm/v1/chat/completions' not in requests
