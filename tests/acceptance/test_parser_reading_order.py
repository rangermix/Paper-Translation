"""Perturb genuine offline Docling output, retaining original text and locators."""
import copy
import json
import shutil
from pathlib import Path

import pytest

from packages.ir import digest, validate_source
from packages.parsers.pdf_docling import coverage_report
from packages.source_revisions.corrections import _set_order

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / '.agent/tmp/evidence/live-provider-final-en'


def actual():
    if not (CORPUS / 'result.json').is_file():
        pytest.skip('Requires the recorded genuine offline controlled-English Docling execution.')
    result = json.loads((CORPUS / 'result.json').read_text(encoding='utf8'))
    assert digest((CORPUS / 'original.pdf').read_bytes()) == result['source_revision']['sha256']
    assert result['coverage']['can_translate']
    return result


def report(result):
    return coverage_report(result['inspection']['pages'], result['source_revision']['blocks'], result['coverage']['excluded'])


def reverse_two_paragraphs(result):
    changed = copy.deepcopy(result)
    _set_order(changed['source_revision'], ['b0', 'b1', 'b3', 'b2'])
    validate_source(changed['source_revision'])
    return changed


def test_real_native_same_column_reversal_is_not_coverage_success():
    original = actual()
    changed = reverse_two_paragraphs(original)
    before = {b['id']: {k:v for k,v in b.items() if k != 'order'} for b in original['source_revision']['blocks']}
    assert before == {b['id']: {k:v for k,v in b.items() if k != 'order'} for b in changed['source_revision']['blocks']}
    assert report(original)['can_translate']
    coverage = report(changed)
    assert not coverage['can_translate']
    issue = next(i for i in coverage['unresolved'] if i['reason'] == 'Native same-column paragraph order conflicts with reading order')
    assert issue['code'] == 'SOURCE_PARSE_REVIEW' and issue['block_ids'] == ['b3', 'b2']
    assert issue['page'] == 1 and len(issue['native_regions']) == 2
    assert all(i['text'] in before[i['block_id']]['raw_text'] for i in issue['native_regions'])


@pytest.mark.parametrize('layout', ['separate_columns', 'multiple_regions', 'owned_caption', 'overlapping_regions'])
def test_geometry_guard_does_not_invent_order_for_ambiguous_layouts(layout):
    # Geometry-only negative controls are intentionally not claims about the PDF.
    changed = reverse_two_paragraphs(actual())
    block = next(b for b in changed['source_revision']['blocks'] if b['id'] == 'b3')
    if layout == 'separate_columns':
        block['provenance'][0]['bbox'] = [400, 218, 600, 230]
    elif layout == 'multiple_regions':
        block['provenance'].append(copy.deepcopy(block['provenance'][0]))
    elif layout == 'owned_caption':
        block.update(kind='caption', owner_id='a-figure')
    else:
        block['provenance'][0]['bbox'] = [54, 160, 376, 230]
    assert not any(i['reason'] == 'Native same-column paragraph order conflicts with reading order' for i in report(changed)['unresolved'])


@pytest.mark.parametrize('directory,source_sha', [
    ('efficient-native-final-1788660392870495400', 'b74b42997b7f55a28b0be54c510b39a322ddcf352d0ba489baa1659dc249f924'),
    ('reviewed-source-pathways-1788658073125877700', '293a7507712b85926b1397eb13d2ec0dad530a47b5309cea95283cc2506affd6'),
])
def test_reviewed_source_gold_order_remains_valid_without_rewriting_snapshot(directory, source_sha):
    path = ROOT / '.agent/tmp/evidence' / directory / 'response.json'
    if not path.is_file():pytest.skip('Requires the immutable independently reviewed original-page source gold.')
    original = path.read_bytes(); data = json.loads(original); source = data['source']
    assert digest(source) == source_sha
    coverage = coverage_report(data['evidence']['inspection']['pages'], source['blocks'], data['coverage']['excluded'])
    assert coverage['can_translate'] and not coverage['unresolved']
    assert path.read_bytes() == original and digest(source) == source_sha


@pytest.mark.postgres
def test_preflight_reversal_blocks_confirmation_and_reviewed_reorder_restores_it(client, database):
    from packages.domain.models import Document, SourceAsset, SourceDraft
    original = actual(); source = original['source_revision']; db, cfg = database
    shutil.copy2(CORPUS / 'original.pdf', cfg.data / 'original.pdf')
    asset = next(a for a in source['assets'] if a['id'] == source['original_asset_id'])
    with db.transaction() as session:
        session.add(SourceAsset(id=asset['id'], sha256=asset['sha256'], byte_size=asset['byte_size'], page_count=1, storage_key='original.pdf')); session.flush()
        session.add(Document(id='order-document', title='Native order review', source_asset_id=asset['id'])); session.flush()
        session.add(SourceDraft(id='order-original', document_id='order-document', asset_id=asset['id'], source=source,
            coverage=original['coverage'], evidence={'inspection': original['inspection']}))
    native = original['inspection']['pages'][0]['text_regions'][0]
    proof = {'page': 1, 'bbox': native['bbox'], 'quote': native['text']}
    def reorder(draft_id, generation, order, key, reason):
        return client.post(f'/api/v1/imports/{draft_id}/corrections',
            json={'reason': reason, 'evidence': proof, 'operations': [{'kind': 'reorder', 'block_ids': order}]},
            headers={'If-Match': f'"{generation}"', 'Idempotency-Key': key})
    bad = reorder('order-original', 1, ['b0', 'b1', 'b3', 'b2'], 'reverse-order', 'Controlled same-column reversal for verification.')
    assert bad.status_code == 201, bad.text
    bad = bad.json()
    assert not bad['coverage']['can_translate']
    blocked = client.post(f'/api/v1/sources/drafts/{bad["id"]}/confirm', json={'source_hash': bad['source_hash']},
        headers={'If-Match': f'"{bad["generation"]}"', 'Idempotency-Key': 'confirm-reversed'})
    assert blocked.status_code == 201  # A reading-order warning does not prevent saving.
    current = client.get('/api/v1/documents/order-document')
    good = client.post('/api/v1/sources/' + blocked.json()['source_revision_id'] + '/corrections',
        json={'reason': 'Restore original top-to-bottom order.', 'evidence': proof,
            'operations': [{'kind': 'reorder', 'block_ids': source['reading_order']}]},
        headers={'If-Match': current.headers['etag'], 'Idempotency-Key': 'restore-order'})
    assert good.status_code == 201, good.text
    good = good.json()
    assert good['source']['reading_order'] == source['reading_order']
    sealed = client.post(f'/api/v1/sources/drafts/{good["id"]}/confirm', json={'source_hash': good['source_hash']},
        headers={'If-Match': f'"{good["generation"]}"', 'Idempotency-Key': 'confirm-restored'})
    assert sealed.status_code == 201, sealed.text
    with db.transaction() as session:
        assert digest(session.get(SourceDraft, 'order-original').source) == digest(source)
        assert session.get(SourceDraft, bad['id']).source['reading_order'] == ['b0', 'b1', 'b3', 'b2']
    assert digest((cfg.data / 'original.pdf').read_bytes()) == source['sha256']
