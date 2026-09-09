import json
import shutil
import zipfile
from pathlib import Path

from packages.ir import block_hash
from packages.editorial.drafts import render_input
from packages.publisher import Publisher, export_bundle, export_single_html


def fixture():
    ir = json.loads(Path('fixtures/sample-document-v3.json').read_text('utf-8'))
    source, tr = ir['source_revision'], ir['translation_revision']
    tr['content_policy'] = 'nonblocking-v1'
    result = next(r for r in tr['results'] if r['block_id'] == 'p2')
    result.update(status='fallback', target_inline=[], reason='translation_unavailable', fallback={'mode': 'source_text'},
        review_state='not_reviewed', review_record=None, warnings=['未得到可靠译文，保留原文。'])
    for block in source['blocks']:
        if block['kind'] in {'math', 'code'}:
            block['attributes']['comparison_asset_id'] = 'figure_1'
            block['attributes']['comparison_scope'] = 'page'
            block['source_hash'] = block_hash(block, source['protected_atoms'])
            next(r for r in tr['results'] if r['block_id'] == block['id'])['source_hash'] = block['source_hash']
    # Use the actual fixture's raster ID, independent of its friendly name.
    raster = next(a['id'] for a in source['assets'] if a['media_type'].startswith('image/'))
    for block in source['blocks']:
        if block['attributes'].get('comparison_asset_id'):
            block['attributes']['comparison_asset_id'] = raster
            block['source_hash'] = block_hash(block, source['protected_atoms'])
            next(r for r in tr['results'] if r['block_id'] == block['id'])['source_hash'] = block['source_hash']
    return render_input(ir['document']['id'], source, tr, 'reader-v3')


def test_fallback_and_original_comparisons_survive_offline_exports(tmp_path):
    ir = fixture()
    directory = tmp_path/'artifact'
    Publisher().build(ir, Path('.'), directory, include_source=True)
    html = (directory/'index.html').read_text('utf-8')
    assert '此段尚无译文，以下保留原文' in html
    assert 'data-issue-filter="page"' in html and 'data-issue-filter="category"' in html
    assert '显示整页' in html and '识别文字（仅供辅助对照）' in html
    assert (directory/'reader.css').read_bytes() != Path('reference/reader-v1.css').read_bytes()
    single = export_single_html(directory, tmp_path/'reading.html', include_source=True).read_text('utf-8')
    assert 'data:image/png;base64,' in single and 'data:application/pdf;base64,' in single
    assert '此段尚无译文' in single
    archive = export_bundle(directory, tmp_path/'reading.zip')
    with zipfile.ZipFile(archive) as content:
        assert any(name.startswith('assets/') for name in content.namelist())


def test_missing_crop_keeps_original_pdf_link_without_claiming_image_is_available(tmp_path):
    ir = fixture()
    (tmp_path/'fixtures').mkdir()
    shutil.copyfile('fixtures/sample.pdf', tmp_path/'fixtures/sample.pdf')
    Publisher().build(ir, tmp_path, tmp_path/'artifact', include_source=True)
    html = (tmp_path/'artifact/index.html').read_text('utf-8')
    assert '对照图暂不可用，打开原 PDF 查看' in html
    assert 'src="assets/' not in html
    without = export_single_html(tmp_path/'artifact', tmp_path/'without.html').read_text('utf-8')
    assert 'original.pdf' not in without and 'data:application/pdf' not in without
    assert '本次导出未包含原 PDF' in without
