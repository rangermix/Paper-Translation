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
        return httpx.Response(200, json={'model': 'wrong', 'choices': [{'message': {'role': 'assistant', 'content': 'text'}}]})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(fetch), **kwargs))
    with Image.new('RGB', (10, 10)) as image:
        with pytest.raises(PDFError, match='MISMATCH'):
            DockerVision(model, None, runtime)(image, 'OCR')
    if wrong_at in ('metadata', 'configuration'):
        assert '/engines/vllm/v1/chat/completions' not in requests
