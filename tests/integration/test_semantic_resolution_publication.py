"""Actual source-reviewed negation risk resolution; no model is constructed."""
import copy
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select

from packages.domain.models import Artifact, Document, Draft, Edition, IssueResolution, ReviewRecord, SegmentVersion, SourceAsset, SourceRevision
from packages.editorial.drafts import context_hash
from packages.ir import digest, flatten_inline, validate_source
from packages.jobs.queue import claim
from packages.storage import atomic_write, file_hash, write_snapshot
from workers.main import execute

pytestmark = pytest.mark.postgres


def test_reviewed_negation_and_condition_resolution_allows_publication_without_changing_text(client, database):
    corpus = Path('.agent/tmp/evidence/live-provider-final-en')
    review_path = corpus / 'independent-manual-target-review.json'
    review = json.loads(review_path.read_text(encoding='utf-8'))
    assert review['reviewer'] == '/root/web_ui' and review['actual_page_viewed']
    assert file_hash(corpus / 'result.json') == review['result_sha256']
    assert file_hash(corpus / 'pages/page-0001.png') == review['page_image_sha256']
    result = json.loads((corpus / 'result.json').read_text(encoding='utf-8'))
    source = copy.deepcopy(result['source_revision'])
    assert source['sha256'] == review['original_pdf_sha256']
    db, cfg = database
    for asset in source['assets']:
        atomic_write(cfg.data, asset['storage_key'], (corpus / asset['storage_key']).read_bytes())
    validate_source(source, asset_root=cfg.data)
    targets = {b['block_id']: [{'type': 'text', 'text': b['target_text']}] for b in review['blocks']}
    targets['b1'] = [{'type': 'text', 'text': '该批次包含'}, {'type': 'protected_ref', 'ref': 'b1-n0'}, {'type': 'text', 'text': '个token。'}]
    for checked in review['blocks']:
        block = next(b for b in source['blocks'] if b['id'] == checked['block_id'])
        assert checked['accuracy'] and checked['quantity_condition_negation_preserved']
        assert block['source_hash'] == checked['source_hash'] and block['normalized_text'] == checked['source_quote']
        assert flatten_inline(targets[block['id']], source['protected_atoms']) == checked['target_text']
    snapshot = write_snapshot(cfg.data, 'controlled/source.json', source)
    with db.transaction() as session:
        asset = source['assets'][0]
        session.add(SourceAsset(id=source['original_asset_id'], sha256=source['sha256'],
            byte_size=asset['byte_size'], page_count=1, storage_key=asset['storage_key']))
        session.flush()
        session.add(Document(id='review_doc', title='Controlled source-reviewed risk resolution',
            source_asset_id=source['original_asset_id'], current_source_id=source['id'], source_language='en'))
        session.flush()
        session.add(SourceRevision(id=source['id'], document_id='review_doc', asset_id=source['original_asset_id'],
            snapshot_hash=snapshot, storage_key='controlled/source.json'))
        session.add(Edition(id='review_edition', document_id='review_doc', target_locale='zh-Hans', current_draft_id='review_draft'))
        session.flush()
        session.add(Draft(id='review_draft', document_id='review_doc', edition_id='review_edition', source_revision_id=source['id']))
        session.flush()
        for block in source['blocks']:
            session.add(SegmentVersion(id='review_seg_' + block['id'], draft_id='review_draft', block_id=block['id'],
                sequence=1, target_inline=targets[block['id']], origin='manual_ui', reason='Internal manual target independently reviewed by /root/web_ui.',
                source_hash=block['source_hash'], context_hash=context_hash(source, block['id'])))
    generation = 1
    resolutions = []
    for bid in ('b2', 'b3'):
        qa = client.post('/api/v1/drafts/review_draft/validate', json={},
            headers={'If-Match': f'"{generation}"', 'Idempotency-Key': 'risk-qa-' + bid})
        assert qa.status_code == 200 and qa.json()['quality']['state'] == 'completed', qa.text
        issue = next(i for i in qa.json()['issues'] if i['block_id'] == bid and i['code'] == 'SEMANTIC_RISK')
        checked = next(b for b in review['blocks'] if b['block_id'] == bid)
        url = f'/api/v1/drafts/review_draft/issues/{issue["fingerprint"]}/resolve'
        reason = ('Independent /root/web_ui original-page comparison preserves the unknown-result condition and prohibition on sending a second request.'
            if bid == 'b2' else 'Independent /root/web_ui original-page comparison preserves the limit on what this test proves; it does not assert all documents unsafe.')
        wrong = client.post(url, json={'reason': reason, 'evidence': {'quote': 'Invented quotation', 'page': 1}},
            headers={'If-Match': f'"{generation}"', 'Idempotency-Key': 'risk-unproven-' + bid})
        assert wrong.status_code == 409 and wrong.json()['error']['code'] == 'SOURCE_EVIDENCE_REQUIRED'
        resolved = client.post(url, json={'reason': reason, 'evidence': {'quote': checked['source_quote'], 'page': 1,
            'independent_review_sha256': file_hash(review_path), 'target_hash': digest(targets[bid])}},
            headers={'If-Match': f'"{generation}"', 'Idempotency-Key': 'risk-confirm-' + bid})
        assert resolved.status_code == 200, resolved.text
        generation = resolved.json()['generation']
        resolutions.append({'issue': issue, 'reason': reason, 'generation': generation})
    qa = client.post('/api/v1/drafts/review_draft/validate', json={},
        headers={'If-Match': f'"{generation}"', 'Idempotency-Key': 'risk-final-qa'})
    assert qa.status_code == 200 and qa.json()['quality']['state'] == 'completed', qa.text
    assert all(i['resolved'] for i in qa.json()['issues'] if i['code'] == 'SEMANTIC_RISK')
    sealed = client.post('/api/v1/drafts/review_draft/seal', json={'qa_id': qa.json()['id'],
        'qa_fingerprint': qa.json()['fingerprint'], 'generation': generation},
        headers={'If-Match': f'"{generation}"', 'Idempotency-Key': 'risk-seal'})
    assert sealed.status_code == 201, sealed.text
    published = client.post('/api/v1/editions/review_edition/publish', json={'translation_revision_id': sealed.json()['id'], 'expected_generation': 1},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'risk-publish'})
    assert published.status_code == 202, published.text
    execute(db, cfg, claim(db))
    with db.transaction() as session:
        assert {s.block_id: s.target_inline for s in session.scalars(select(SegmentVersion))} == targets
        assert len(list(session.scalars(select(ReviewRecord)))) == 0
        records = list(session.scalars(select(IssueResolution)))
        assert len(records) == 2 and all(r.origin == 'manual_ui' and r.evidence['page'] == 1 for r in records)
        artifact = session.get(Artifact, session.get(Edition, 'review_edition').current_artifact_id)
        html = (cfg.data / artifact.storage_key / 'index.html').read_text(encoding='utf-8')
        assert '已记录核对说明' in html
    output = Path('.agent/tmp/evidence/semantic-resolution') / uuid.uuid4().hex
    output.mkdir(parents=True)
    (output / 'index.html').write_text(html, encoding='utf-8')
    (output / 'verification.json').write_text(json.dumps({'scope': 'Actual offline parse plus independently reviewed internal manual targets; no live Provider.',
        'review_file': str(review_path), 'review_sha256': file_hash(review_path), 'source_sha256': source['sha256'],
        'resolutions': resolutions, 'final_qa': qa.json(), 'targets_unchanged': True, 'provider_calls': 0,
        'publication_revision': sealed.json()['id']}, ensure_ascii=False, indent=2), encoding='utf-8')
