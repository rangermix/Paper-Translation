"""Independent ambiguity guard for an exact mechanical normalization span."""
import pytest

from packages.domain.errors import DomainError
from packages.source_revisions import apply_native_corrections
from tests.integration.test_native_span_normalization import scenario


def test_native_spacing_from_one_occurrence_cannot_rewrite_another():
    source, inspection, proof, operation = scenario('alongside; alongside', 'restore_native_spacing')
    # Persisted native proof represents the FIRST printed occurrence, whose
    # whitespace differs. The requested span is the SECOND occurrence.
    proof['quote'] = 'along side;'
    inspection['pages'][0]['text_regions'][0].update(text=proof['quote'], native_indices=list(range(len(proof['quote']))))
    operation.update(start=11, end=20, page_image_sha256s={'1': 'a'*64})
    operation.pop('continuation_evidence')
    with pytest.raises(DomainError):
        apply_native_corrections(source, inspection, [operation], proof,
            'Controlled mismatched occurrence proof; must reject ambiguity.', [], page_image_verify=lambda page, sha: True)


def test_overlapping_literal_occurrences_are_not_mistaken_for_unique():
    source, inspection, proof, operation = scenario('aaaa', 'restore_native_spacing')
    proof['quote'] = 'a aa'
    inspection['pages'][0]['text_regions'][0].update(text=proof['quote'], native_indices=list(range(len(proof['quote']))))
    operation.update(start=1, end=4, page_image_sha256s={'1': 'a'*64})
    operation.pop('continuation_evidence')
    # "aaa" appears at offsets 0 and 1. Python str.count reports only one
    # non-overlapping hit; incomplete native order cannot choose an occurrence.
    with pytest.raises(DomainError):
        apply_native_corrections(source, inspection, [operation], proof,
            'Controlled overlapping occurrence proof; must reject ambiguity.', [], page_image_verify=lambda page, sha: True)


def test_complete_native_order_allows_the_exact_repeated_occurrence():
    from packages.ir import block_hash
    source, inspection, proof, operation = scenario('alongside; alongside', 'restore_native_spacing')
    proof['quote'] = 'along side;'
    first = inspection['pages'][0]['text_regions'][0]
    first.update(text=proof['quote'], native_indices=list(range(len(proof['quote']))))
    second = {'bbox': [20, 39, 230, 48], 'text': ' alongside', 'native_indices': list(range(11, 21))}
    inspection['pages'][0]['text_regions'].append(second)
    block = next(b for b in source['blocks'] if b['id'] == 'p2')
    block['provenance'] = [{**block['provenance'][0], 'bbox': [20, 20, 250, 50]}]
    block['source_hash'] = block_hash(block, source['protected_atoms'])
    operation.update(start=0, end=9, page_image_sha256s={'1': 'a'*64})
    operation.pop('continuation_evidence')
    result = apply_native_corrections(source, inspection, [operation], proof,
        'Complete original glyph ordering identifies the first occurrence.', [], page_image_verify=lambda page, sha: True)
    assert next(b for b in result['source']['blocks'] if b['id'] == 'p2')['normalized_text'] == 'along side; alongside'
    assert result['restorations'][0]['occurrence_binding']['basis'] == 'aligned_original_native_glyph_indices'
