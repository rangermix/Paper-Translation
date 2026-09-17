"""Recovery produces safe, renderable source facts and actual local image assets."""
from pathlib import Path

from pypdf import PdfWriter

from packages.ir import validate_source
from packages.parsers import inspect_pdf
from packages.parsers.pdf_docling import DoclingParser


def test_image_only_source_has_page_fallback_and_does_not_invent_text(tmp_path):
    path = tmp_path / 'blank.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open('wb') as handle:
        writer.write(handle)
    output = tmp_path / 'output'
    result = DoclingParser().adapt([], inspect_pdf(path), path, 'original', output)
    source = result['source_revision']
    validate_source(source, asset_root=output)
    assert not any(b['normalized_text'] for b in source['blocks'])
    figures = [b for b in source['blocks'] if b['kind'] == 'figure']
    assert len(figures) == 1 and figures[0]['provenance'][0]['page'] == 1
    assert '未翻译' in ''.join(figures[0]['warnings'])


def test_native_recovery_retains_original_and_all_numeric_comparison_assets(tmp_path):
    path = Path('tests/fixtures/sample.pdf')
    before = path.read_bytes()
    output = tmp_path / 'output'
    result = DoclingParser().adapt([], inspect_pdf(path), path, 'original', output)
    source = result['source_revision']
    validate_source(source, asset_root=output)
    assert path.read_bytes() == before
    assert result['inspection']['automatic_recovery']
    for block in source['blocks']:
        numeric = any(node['type'] == 'protected_ref' and source['protected_atoms'][node['ref']]['kind'] == 'number' for node in block['source_inline'])
        if numeric:
            aid = block['attributes']['comparison_asset_id']
            asset = next(asset for asset in source['assets'] if asset['id'] == aid)
            assert (output / asset['storage_key']).is_file()
