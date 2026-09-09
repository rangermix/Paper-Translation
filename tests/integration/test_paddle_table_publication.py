"""Paddle cells, including blanks, pass the real DB/QA/publisher/export path."""
import shutil

import pytest
from sqlalchemy import select

from packages.domain.models import SegmentVersion, SourceAsset
from tests.support import seed_editor
from tests.unit.test_paddle_tables import adapt_table, as_ir
from tests.integration.test_publication_lifecycle import drain, seal_and_publish

pytestmark = pytest.mark.postgres


def seed_table(database, tmp_path, damage=None):
    db, cfg = database
    source = adapt_table(tmp_path)['source_revision']
    source['id'] = 'src_fixture'
    for asset in source['assets']:
        dest = cfg.data / asset['storage_key']
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp_path / 'parsed' / asset['storage_key'], dest)
    ir = as_ir(source)
    if damage:
        cell = next(b for b in source['blocks'] if b['kind'] == 'table_cell' and b['raw_text'] == '64')
        target = next(r for r in ir['translation_revision']['results'] if r['block_id'] == cell['id'])
        if damage == 'missing': target['status'] = 'unresolved'
        else: target['target_inline'] = [{'type': 'text', 'text': '46'}]
    ir = seed_editor(db, cfg, document_ir=ir)
    with db.transaction() as session:
        original = session.get(SourceAsset, 'source_pdf')
        original.storage_key = 'original.pdf'
        original.byte_size = source['assets'][0]['byte_size']
    return ir


def test_cells_publish_and_export_with_spans_and_original_image(client, database, tmp_path):
    db, cfg = database
    ir = seed_table(database, tmp_path)
    artifact, path = seal_and_publish(client, db, cfg, 1, 1, 'paddle-table')
    html = path.read_text('utf-8')
    assert '状态组' in html and 'rowspan="2" colspan="1"' in html and 'rowspan="1" colspan="2"' in html
    assert '查看原 PDF 表格' in html
    cells = [b for b in ir['source_revision']['blocks'] if b['kind'] == 'table_cell']
    for cell in cells: assert html.count(f'id="b-{cell["id"]}"') == 1
    blank = next(b for b in cells if not b['raw_text'])
    with db.transaction() as session:
        assert session.scalar(select(SegmentVersion).where(SegmentVersion.block_id == blank['id'])) is None
    drain(db, cfg)
    queued = client.post(f'/api/v1/artifacts/{artifact}/exports', json={'format': 'single_html', 'include_source': False},
        headers={'Idempotency-Key': 'export-paddle-table'})
    assert queued.status_code == 202, queued.text
    drain(db, cfg)
    exported = client.get('/api/v1/exports/' + queued.json()['id'] + '/download')
    assert exported.status_code == 200 and '状态组' in exported.text
    assert 'data:image/png;base64,' in exported.text and '查看原 PDF 表格' in exported.text


@pytest.mark.parametrize('damage', ['missing', 'number'])
def test_nonempty_cell_still_requires_complete_correct_translation(client, database, tmp_path, damage):
    db, cfg = database
    source = seed_table(database, tmp_path, damage)['source_revision']
    cell = next(b for b in source['blocks'] if b['kind'] == 'table_cell' and b['raw_text'] == '64')
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'bad-table'}).json()
    assert not qa['valid']
    assert any(i['block_id'] == cell['id'] and i['severity'] == 'important' and i['blocking'] is False for i in qa['issues'])
