"""Bibliography fixes use matching PDF text, never inferred reference sequence."""
from copy import deepcopy

import pytest

from packages.parsers.recovery import recover_items
from tests.unit.test_academic_layout_recovery import row, pages_for


REFERENCE = ('[26] A. Krizhevsky, I. Sutskever, and G. E. Hinton. Imagenet '
             'classification with deep convolutional neural networks. In Advances '
             'in neural information processing systems, pages 1097–1105, 2012.')


def reference_case(original=REFERENCE, native=REFERENCE):
    items = [row('title', 'References', [40, 40, 550, 60], label='title'),
             row('ref', original, [70, 218, 299, 264], label='reference')]
    chunks = native.split(' ')
    pieces = [' '.join(chunks[index * len(chunks) // 4:(index + 1) * len(chunks) // 4]) for index in range(4)]
    pages = pages_for(items)[:1]
    pages[0]['text_regions'][1:] = [dict(text=text, bbox=[72, 220 + 11 * index, 297, 229 + 11 * index])
                                   for index, text in enumerate(pieces)]
    return items, pages


def test_native_reference_number_and_author_typo_are_corrected_with_exact_citation_body():
    original = REFERENCE.replace('[26]', '[20]').replace('Krizhevsky', 'Kriznevsky')
    items, pages = reference_case(original)
    before = deepcopy(items)
    result, audit = recover_items(items, pages)
    assert next(item for item in result if item['self_ref'] == 'ref')['text'] == REFERENCE
    record = next(item for item in audit if item['action'] == 'native_reference_metadata')
    assert record['before'] == original and record['after'] == REFERENCE
    assert record['native_evidence'] and items == before


def test_native_author_initial_can_be_repaired_without_changing_the_citation_body():
    native = ('[27] S. Lee, J. K. Kim, X. Zheng, Q. Ho, G. A. Gibson, and E. P. Xing. '
              'On model parallelization and scheduling strategies for distributed '
              'machine learning. In NIPS, pages 2834–2842, 2014.')
    items, pages = reference_case(native.replace('X. Zheng', 'A. Zheng'), native)
    result, _ = recover_items(items, pages)
    assert next(item for item in result if item['self_ref'] == 'ref')['text'] == native


@pytest.mark.parametrize('native', [
    REFERENCE.replace('2012', '2013'),
    REFERENCE.replace('Hinton', 'Hintzz'),
])
def test_reference_body_changes_or_too_many_author_changes_are_not_guessed(native):
    original = REFERENCE.replace('[26]', '[20]').replace('Krizhevsky', 'Kriznevsky')
    items, pages = reference_case(original, native)
    result, audit = recover_items(items, pages)
    assert result == items
    assert not any(item['action'] == 'native_reference_metadata' for item in audit)


@pytest.mark.parametrize('across_page', [True, False])
def test_numbered_reference_joins_its_unnumbered_native_continuation(across_page):
    first = '[22] A. Karpathy and colleagues. In 2014 IEEE Confer' if across_page else '[36] K. Simonyan and A. Zisserman. Very deep convolutional'
    second = 'ence on Computer Vision and Pattern Recognition, pages 1725–1732, June 2014.' if across_page else 'networks for large-scale image recognition. arXiv preprint arXiv:1409.1556, 2014.'
    items = [row('title', 'References', [40, 40, 550, 60], label='title'),
             row('first', first, [310, 720, 550, 735] if across_page else [40, 720, 270, 735], label='reference'),
             row('second', second, [60, 80, 270, 110] if across_page else [330, 80, 550, 110],
                 2 if across_page else 1, 'reference')]
    pages = pages_for(items) if across_page else pages_for(items)[:1]
    if across_page:
        pages[0]['text_regions'][1]['text'] += '\x02'
    result, audit = recover_items(items, pages)
    expected = first + ('' if across_page else ' ') + second
    assert next(item for item in result if item['self_ref'] == 'first')['text'] == expected
    assert not any(item['self_ref'] == 'second' for item in result)
    assert any(item['action'] == 'native_reference_continuation' for item in audit)


def test_next_numbered_reference_is_never_joined():
    items = [row('title', 'References', [40, 40, 550, 60], label='title'),
             row('first', '[22] A citation ending without punctuation', [310, 720, 550, 735], label='reference'),
             row('second', '[23] a different numbered reference.', [40, 80, 270, 110], 2, 'reference')]
    result, _ = recover_items(items, pages_for(items))
    assert result == items
