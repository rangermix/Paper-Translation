"""Repair only clear same-column inversions, keeping spanning resources as boundaries."""
from copy import deepcopy
import pytest

from packages.parsers.recovery import recover_items
from packages.parsers.layout_recovery import recover_layout
from tests.unit.test_academic_layout_recovery import row, pages_for


@pytest.mark.parametrize('later_label,earlier_label', [('text', 'text'), ('section_header', 'text'), ('text', 'section_header')])
def test_native_same_column_order_places_headings_and_prose_at_their_original_positions(later_label, earlier_label):
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('later', 'Later original content.', [310, 380, 550, 410], label=later_label),
             row('earlier', 'Earlier original content.', [310, 270, 550, 300], label=earlier_label)]
    result, audit = recover_items(items, pages_for(items)[:1])
    assert [item['self_ref'] for item in result] == ['title', 'earlier', 'later']
    assert [item['label'] for item in result] == ['title', earlier_label, later_label]
    record = next(item for item in audit if item['action'] == 'native_reading_order')
    assert record['before'] == ['Later original content.', 'Earlier original content.']
    assert record['after'] == list(reversed(record['before']))


def test_column_transition_and_spanning_figure_are_not_sorted_by_vertical_position():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'Left column ends.', [40, 600, 270, 630]),
             row('right', 'Right column begins.', [310, 100, 550, 130]),
             row('figure', '', [40, 250, 550, 400], label='picture'),
             row('next', 'Next original paragraph.', [310, 190, 550, 220])]
    result, audit = recover_items(items, pages_for(items)[:1])
    assert result == items
    assert not any(item['action'] == 'native_reading_order' for item in audit)


def test_overlapping_or_native_unsupported_items_are_not_reordered():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('first', 'First parser content.', [310, 380, 550, 430]),
             row('second', 'Second parser content.', [310, 370, 550, 410])]
    result, _ = recover_layout(deepcopy(items), pages_for(items)[:1])
    assert result == items
    items[2]['prov'][0]['bbox'].update(t=270, b=300)
    pages = pages_for(items)[:1]
    pages[0]['text_regions'] = pages[0]['text_regions'][:1]
    result, _ = recover_items(items, pages)
    assert result == items
