"""Source correction tests are written before implementation; DB cases need real PostgreSQL."""
import copy
import json
from pathlib import Path

import pytest

from packages.domain.errors import DomainError
from packages.ir import block_hash, digest, validate_source
from packages.source_revisions import apply_corrections, revision_mapping

ROOT = Path(__file__).resolve().parents[2]


def fixture_source():
    return json.loads((ROOT / 'tests/fixtures/sample-document.json').read_text('utf-8'))['source_revision']


def evidence(source, block_id='p1'):
    block = next(b for b in source['blocks'] if b['id'] == block_id)
    locator = block['provenance'][0]
    return {'page': locator['page'], 'bbox': locator['bbox'], 'quote': block['raw_text']}


def test_arbitrary_rewording_and_fabricated_evidence_are_rejected():
    source = fixture_source()
    block = next(b for b in source['blocks'] if b['id'] == 'p1')
    operation = {'kind': 'replace_text', 'block_id': 'p1', 'start': 0, 'end': len(block['normalized_text']), 'text': 'The job has 32 tokens.'}
    with pytest.raises(DomainError, match='mechanical'):
        apply_corrections(source, [operation], evidence(source), 'incorrect numeric replacement')
    bad = evidence(source)
    bad['quote'] = 'A claim absent from the PDF'
    with pytest.raises(DomainError):
        apply_corrections(source, [{'kind': 'reorder', 'block_ids': source['reading_order']}], bad, 'unproven quote')


def test_unicode_mechanical_correction_is_reproducible_and_old_snapshot_immutable():
    source = fixture_source()
    block = next(b for b in source['blocks'] if b['id'] == 'p2')
    block.update(raw_text='A😀  ﬁle.', normalized_text='A😀  ﬁle.', source_inline=[{'type': 'text', 'text': 'A😀  ﬁle.'}], normalization_edits=[])
    block['source_hash'] = block_hash(block, source['protected_atoms'])
    old_hash = digest(source)
    result = apply_corrections(source, [{'kind': 'replace_text', 'block_id': 'p2', 'start': 2, 'end': 4, 'text': ' '}], evidence(source, 'p2'), 'Collapse duplicate extracted whitespace')
    assert digest(source) == old_hash
    fixed = next(b for b in result['source']['blocks'] if b['id'] == 'p2')
    assert fixed['normalized_text'] == 'A😀 ﬁle.'
    assert fixed['raw_text'] == 'A😀  ﬁle.'
    assert fixed['normalization_edits'][0]['raw_end'] == len('A😀  ﬁle.')
    validate_source(result['source'])


def test_reorder_preserves_text_and_marks_neighbor_context_invalid():
    source = fixture_source()
    order = list(source['reading_order'])
    order[1], order[2] = order[2], order[1]
    result = apply_corrections(source, [{'kind': 'reorder', 'block_ids': order}], evidence(source), 'Compare PDF reading order')
    assert result['source']['reading_order'] == order
    before = {b['id']: b['normalized_text'] for b in source['blocks']}
    assert {b['id']: b['normalized_text'] for b in result['source']['blocks']} == before
    mapping = result['mapping']
    assert any(m['kind'] == 'moved' for m in mapping)
    assert any(not m['reusable'] and m['context_changed'] for m in mapping)


def test_split_does_not_bisect_protected_atom_and_merge_retains_provenance():
    source = fixture_source()
    with pytest.raises(DomainError, match='protected'):
        apply_corrections(source, [{'kind': 'split', 'block_id': 'p1', 'offset': 13}], evidence(source), 'Invalid atom cut')
    split = apply_corrections(source, [{'kind': 'split', 'block_id': 'p1', 'offset': 8}], evidence(source), 'Split at actual paragraph boundary')
    mapping = next(m for m in split['mapping'] if m['old_block_ids'] == ['p1'])
    assert mapping['kind'] == 'split' and not mapping['reusable']
    new_ids = mapping['new_block_ids']
    merged = apply_corrections(split['source'], [{'kind': 'merge', 'block_ids': new_ids}], evidence(split['source']), 'Rejoin adjacent paragraph parts')
    assert len(merged['source']['blocks']) == len(source['blocks'])
    assert next(b for b in merged['source']['blocks'] if b['id'] == 'p1')['provenance'] == next(b for b in source['blocks'] if b['id'] == 'p1')['provenance']


def test_mapping_never_reuses_changed_context_or_source_atoms():
    source = fixture_source()
    altered = copy.deepcopy(source)
    block = next(b for b in altered['blocks'] if b['id'] == 'p1')
    block['source_hash'] = '1' * 64
    mapping = revision_mapping(source, altered)
    assert next(m for m in mapping if m['old_block_ids'] == ['p1'])['reusable'] is False
    assert any(m['context_changed'] and not m['reusable'] for m in mapping)


def test_confirm_uses_cas_and_preserves_old_source_file(client, database):
    from packages.domain.models import Document, SourceAsset, SourceRevision
    from packages.storage import atomic_write, write_snapshot
    db, config = database
    source = fixture_source()
    atomic_write(config.data, 'sources/source_test.pdf', (ROOT / 'tests/fixtures/sample.pdf').read_bytes())
    with db.transaction() as session:
        asset = SourceAsset(id='asset_test_source', sha256=source['sha256'], byte_size=3822, page_count=2, storage_key='sources/source_test.pdf')
        session.add(asset)
        session.flush()
        doc = Document(id='doc_source_test', title='Source correction test', source_asset_id=asset.id, current_source_id=source['id'])
        session.add(doc)
        session.flush()
        key = 'documents/doc_source_test/sources/original.json'
        source_hash = write_snapshot(config.data, key, source)
        session.add(SourceRevision(id=source['id'], document_id=doc.id, asset_id=asset.id, snapshot_hash=source_hash, storage_key=key))
    body = {'reason': 'Compare original reading order', 'evidence': evidence(source), 'operations': [{'kind': 'reorder', 'block_ids': source['reading_order']}]}
    created = client.post(f'/api/v1/sources/{source["id"]}/corrections', json=body, headers={'Idempotency-Key': 'source-create', 'If-Match': '"1"'})
    assert created.status_code == 201, created.text
    draft = created.json()
    confirmed = client.post(f'/api/v1/sources/drafts/{draft["id"]}/confirm', json={'source_hash': draft['source_hash']}, headers={'Idempotency-Key': 'source-confirm', 'If-Match': created.headers['etag']})
    assert confirmed.status_code == 201, confirmed.text
    assert (config.data / key).read_bytes() == __import__('packages.ir', fromlist=['canonical_bytes']).canonical_bytes(source)
    again = client.post(f'/api/v1/sources/drafts/{draft["id"]}/confirm', json={'source_hash': draft['source_hash']}, headers={'Idempotency-Key': 'source-stale', 'If-Match': '"1"'})
    assert again.status_code in (409, 412)


def native_fixture():
    source = fixture_source()
    block = next(b for b in source['blocks'] if b['id'] == 'p2')
    block.update(raw_text="Say 'yes'.", normalized_text="Say 'yes'.", source_inline=[{'type': 'text', 'text': "Say 'yes'."}])
    block['source_hash'] = block_hash(block, source['protected_atoms'])
    regions = [{'bbox': b['provenance'][0]['bbox'], 'text': b['raw_text']} for b in source['blocks'] if b['raw_text']]
    next(r for r in regions if r['bbox'] == block['provenance'][0]['bbox'])['text'] = 'Say "yes".'
    pages = [{'page': 1, 'page_size': [612, 792], 'text_characters': 300, 'scan_suspected': False, 'text_regions': regions, 'image_regions': [], 'graphic_regions': []}]
    proof = {'page': 1, 'bbox': block['provenance'][0]['bbox'], 'quote': 'Say "yes".'}
    return source, {'sha256': source['sha256'], 'page_count': 1, 'pages': pages}, proof


def test_native_region_restoration_requires_complete_original_region_and_rechecks_coverage():
    from packages.source_revisions import apply_native_corrections
    source, inspection, proof = native_fixture()
    original = digest(source)
    op = {'kind': 'replace_text', 'block_id': 'p2', 'start': 0, 'end': len("Say 'yes'."), 'text': 'Say "yes".'}
    restored = apply_native_corrections(source, inspection, [op], proof, 'Native PDF has double quotation marks', [])
    assert digest(source) == original
    assert restored['coverage']['can_translate']
    assert next(b for b in restored['source']['blocks'] if b['id'] == 'p2')['raw_text'] == 'Say "yes".'
    with pytest.raises(DomainError):
        apply_native_corrections(source, inspection, [{**op, 'text': 'Say "no".'}], proof, 'Unproven rewrite', [])
    with pytest.raises(DomainError):
        apply_native_corrections(source, inspection, [op], {**proof, 'quote': 'Invented native evidence'}, 'Bad quote', [])


def test_recovery_adds_only_unmapped_native_region_and_does_not_clear_graphics():
    from packages.source_revisions import apply_native_corrections
    source, inspection, _ = native_fixture()
    proof = {'page': 1, 'bbox': [50, 650, 300, 669], 'quote': 'A genuinely missing original sentence 42.'}
    inspection['pages'][0]['text_regions'].append({'bbox': proof['bbox'], 'text': proof['quote']})
    inspection['pages'][0]['graphic_regions'] = [{'bbox': [320, 640, 500, 740]}]
    op = {'kind': 'recover_region', **proof, 'after_block_id': 'ref1'}
    recovered = apply_native_corrections(source, inspection, [op], proof, 'Compare missing final sentence with PDF', [])
    added = next(b for b in recovered['source']['blocks'] if b['id'].startswith('recovered-'))
    assert added['raw_text'] == proof['quote']
    assert added['provenance'][0]['bbox'] == proof['bbox']
    assert any(n['type'] == 'protected_ref' for n in added['source_inline'])
    assert not recovered['coverage']['can_translate']
    assert any('graphic' in u['reason'] for u in recovered['coverage']['unresolved'])
    with pytest.raises(DomainError):
        apply_native_corrections(recovered['source'], inspection, [op], proof, 'Duplicate region', [])


def test_preflight_correction_creates_new_draft_keeps_parser_evidence_and_uses_cas(client, database):
    from packages.domain.models import Document, SourceAsset, SourceDraft
    from packages.parsers.pdf_docling import coverage_report
    db, cfg = database
    source, inspection, proof = native_fixture()
    from packages.storage import atomic_write
    for asset in source['assets']:
        atomic_write(cfg.data,asset['storage_key'],(ROOT/'tests'/asset['storage_key']).read_bytes())
    with db.transaction() as session:
        session.add(SourceAsset(id='asset_native', sha256=source['sha256'], byte_size=3822, page_count=1, storage_key='sources/native.pdf'))
        session.flush()
        session.add(Document(id='doc_native', title='Native restoration', source_asset_id='asset_native'))
        session.flush()
        session.add(SourceDraft(id='draft_native', document_id='doc_native', asset_id='asset_native', source=source,
            coverage=coverage_report(inspection['pages'], source['blocks'], []), evidence={'inspection': inspection, 'origin': 'parser'}))
    op = {'kind': 'replace_text', 'block_id': 'p2', 'start': 0, 'end': 10, 'text': 'Say "yes".'}
    body = {'reason': 'Compared double quotes in original PDF region', 'evidence': proof, 'operations': [op]}
    created = client.post('/api/v1/imports/draft_native/corrections', json=body, headers={'If-Match': '"1"', 'Idempotency-Key': 'native-fix'})
    assert created.status_code == 201, created.text
    changed = created.json()
    assert changed['id'] != 'draft_native' and changed['coverage']['can_translate']
    with db.transaction() as session:
        original = session.get(SourceDraft, 'draft_native')
        assert digest(original.source) == digest(source)
        assert original.evidence['inspection'] == inspection
    stale = client.post('/api/v1/imports/draft_native/corrections', json=body, headers={'If-Match': '"1"', 'Idempotency-Key': 'native-fix-stale'})
    assert stale.status_code == 412
