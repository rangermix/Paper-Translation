"""Ignore page furniture only when the original PDF text and margins agree."""
from copy import deepcopy

from packages.parsers.recovery import recover_items
from tests.unit.test_native_page_recovery import item, region


def page(regions):
    return {'page': 1, 'page_size': [612, 792], 'text_regions': regions}


def test_mislabelled_arxiv_watermark_and_page_number_become_audited_furniture():
    watermark = 'arXiv:1806.03377v1 [cs.DC] 8 Jun 2018'
    items = [item('watermark', watermark, [14, 216, 36, 555], 1),
             item('title', 'A controlled paper', [70, 55, 540, 80], 1, 'title'),
             item('footer', '1', [302, 748, 310, 758], 1)]
    before = deepcopy(items)
    result, audit = recover_items(items, [page([
        region(watermark, [16, 218, 34, 553]),
        region('1', [303, 750, 309, 757])])])
    by_ref = {row['self_ref']: row for row in result}
    assert by_ref['watermark']['label'] == 'page_header'
    assert by_ref['footer']['label'] == 'page_footer'
    assert items == before
    records = [row for row in audit if row['action'] == 'native_page_furniture']
    assert {row['before'] for row in records} == {watermark, '1'}
    assert all(row['native_evidence'] and row['after'] == [] for row in records)


def test_missing_native_page_number_is_not_recovered_as_body_text():
    items = [item('title', 'A controlled paper', [70, 55, 540, 80], 1, 'title')]
    result, audit = recover_items(items, [page([region('1', [303, 750, 309, 757])])])
    footer = next(row for row in result if row.get('text') == '1')
    assert footer['label'] == 'page_footer'
    assert any(row['action'] == 'native_page_furniture' for row in audit)


def test_body_numbers_arxiv_citations_and_unsupported_model_footer_are_retained():
    citation = 'arXiv:1806.03377v1 [cs.DC] 8 Jun 2018'
    items = [item('title', 'A controlled paper', [70, 55, 540, 80], 1, 'title'),
             item('number', '16', [70, 300, 90, 312], 1),
             item('citation', citation, [70, 330, 300, 342], 1),
             item('unsupported', '1', [302, 748, 310, 758], 1)]
    result, _ = recover_items(items, [page([
        region('16', [70, 300, 90, 312]), region(citation, [70, 330, 300, 342])])])
    assert result == items


def test_native_number_inside_a_table_at_the_margin_is_not_furniture():
    items = [item('title', 'A controlled paper', [70, 55, 540, 80], 1, 'title'),
             item('table', '1', [70, 680, 540, 765], 1, 'table')]
    result, audit = recover_items(items, [page([region('1', [90, 745, 96, 755])])])
    assert result == items
    assert not any(row['action'] == 'native_page_furniture' for row in audit)
