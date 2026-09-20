"""Correct one mistaken word only inside otherwise matching native prose."""
import pytest

from packages.parsers.recovery import recover_items
from tests.unit.test_native_page_recovery import item, region


def recover_paragraph(original, first, last):
    page = {'page': 1, 'page_size': [612, 792], 'text_regions': [
        region(first, [335, 597, 540, 606]), region(last, [335, 609, 510, 618])]}
    paragraph = item('prose', original, [319, 596, 542, 620], 1)
    items = [item('title', 'Paper', [40, 40, 550, 60], 1, 'title'), paragraph]
    return recover_items(items, [page])


def test_single_similar_wrong_word_is_replaced_from_complete_native_prose():
    original = '3. Ensuring that learning is effective in the face of asynchronous introduced by pipelining.'
    result, audit = recover_paragraph(original,
        '3. Ensuring that learning is effective in the face of asyn\x02',
        'chrony introduced by pipelining.')
    assert next(row for row in result if row['self_ref'] == 'prose')['text'] == original.replace('asynchronous', 'asynchrony')
    record = next(row for row in audit if row['action'] == 'native_prose_token')
    assert record['before'] == original
    assert record['after'] == original.replace('asynchronous', 'asynchrony')
    assert len(record['native_evidence']) == 2


def test_one_extra_character_in_an_otherwise_matching_long_paragraph_is_corrected():
    original = 'We combine model parallelism with aggressive pipelineing and data parallelism where this is appropriate.'
    result, _ = recover_paragraph(original, 'We combine model parallelism with aggressive pipelining',
                                  'and data parallelism where this is appropriate.')
    assert next(row for row in result if row['self_ref'] == 'prose')['text'] == original.replace('pipelineing', 'pipelining')


@pytest.mark.parametrize('original,first,last', [
    ('The model uses $x_1$ and asynchronous updates in each part of this pipeline.',
     'The model uses $x_1$ and asynchrony', 'updates in each part of this pipeline.'),
    ('3. Ensuring that learning is ineffective in the face of asynchronous introduced by pipelining.',
     '3. Ensuring that learning is effective in the face of asyn\x02', 'chrony introduced by pipelining.'),
    ('3. Ensuring that learning is effective in the face of independent changes introduced by pipelining.',
     '3. Ensuring that learning is effective in the face of unrelated', 'changes introduced by pipelining.'),
    ('Asynchronous changes happen.', 'Asynchrony changes', 'happen.'),
])
def test_math_multiple_changes_different_words_and_short_text_are_not_rewritten(original, first, last):
    result, audit = recover_paragraph(original, first, last)
    assert next(row for row in result if row['self_ref'] == 'prose')['text'] == original
    assert not any(row['action'] == 'native_prose_token' for row in audit)
