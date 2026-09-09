"""NB content findings remain advisory; unsafe assets are still rejected."""
import io
import json
from pathlib import Path
import zipfile

import pytest
from sqlalchemy import func, select

from packages.domain.models import Draft, IssueResolution, ReviewRecord, TranslationRevision
from packages.editorial import drafts
from packages.ir import block_hash
from packages.storage import read_snapshot
from tests.integration.test_publication_lifecycle import drain, seal_and_publish
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def seed_risk(db, cfg, damage=None):
    ir = json.loads(Path('fixtures/sample-document-v3.json').read_text(encoding='utf-8'))
    source = ir['source_revision']
    block = next(b for b in source['blocks'] if b['id'] == 'item')
    block['raw_text'] = block['normalized_text'] = 'Only keep the original.'
    block['source_inline'] = [{'type': 'text', 'text': block['normalized_text']}]
    block['source_hash'] = block_hash(block, source['protected_atoms'])
    for row in ir['translation_revision']['results']:
        if row['block_id'] == 'item':
            row['source_hash'] = block['source_hash']
        if row['block_id'] == 'p1' and damage == 'missing':
            row['status'] = 'unresolved'
        elif row['block_id'] == 'p1' and damage == 'number':
            row['target_inline'] = [{'type': 'text', 'text': '32'}]
    seed_editor(db, cfg, document_ir=ir)
    return source


def validate(client, key='qa'):
    result = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': key})
    assert result.status_code == 200, result.text
    return result.json()


def test_unreviewed_risk_can_publish_and_export_with_warning_and_no_fabricated_confirmation(client, database):
    db, cfg = database
    seed_risk(db, cfg)
    quality = validate(client)
    risk = next(i for i in quality['issues'] if i['code'] == 'SEMANTIC_RISK')
    assert quality['quality']['state'] == 'completed' and risk['severity'] == 'important' and not risk['resolved']
    assert all(s['review_status'] != 'human_reviewed' for s in client.get('/api/v1/drafts/draft_fixture').json()['segments'])
    artifact, path = seal_and_publish(client, db, cfg, 1, 1, 'unreviewed')
    assert '条件、否定或数量关系' in path.read_text(encoding='utf-8')
    drain(db, cfg)
    for format in ('single_html', 'bundle'):
        queued = client.post(f'/api/v1/artifacts/{artifact}/exports', json={'format': format, 'include_source': False},
            headers={'Idempotency-Key': 'unreviewed-export-' + format})
        assert queued.status_code == 202, queued.text
        drain(db, cfg)
        exported = client.get('/api/v1/exports/' + queued.json()['id'] + '/download')
        assert exported.status_code == 200
        html = exported.text if format == 'single_html' else zipfile.ZipFile(io.BytesIO(exported.content)).read('index.html').decode('utf-8')
        assert '条件、否定或数量关系' in html
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ReviewRecord)) == 0
        assert session.scalar(select(func.count()).select_from(IssueResolution)) == 0
        revision = session.scalar(select(TranslationRevision))
        assert all(row['review_state'] != 'human_reviewed' and row['review_record'] is None
            for row in read_snapshot(cfg.data, revision)['results'])


@pytest.mark.parametrize('damage', ['missing', 'number', 'asset'])
def test_optional_review_never_bypasses_hard_integrity(client, database, damage):
    db, cfg = database
    seed_risk(db, cfg, damage)
    if damage == 'asset':
        (cfg.data / 'fixtures/figure.png').write_bytes(b'Broken test image')
    quality = validate(client)
    assert not quality['valid'] and any(i['severity'] == 'important' and i['blocking'] is False for i in quality['issues'])
    denied = client.post('/api/v1/drafts/draft_fixture/seal', json={'qa_id': quality['id'],
        'qa_fingerprint': quality['fingerprint'], 'generation': 1},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'hard-seal'})
    assert denied.status_code == (409 if damage == 'asset' else 201), denied.text


def test_previous_review_policy_qa_is_stale_until_revalidated_without_retranslation(client, database, monkeypatch):
    seed_risk(*database)
    with monkeypatch.context() as legacy:
        legacy.setattr(drafts, 'RULE_VERSION', 'quality-v1')
        old = validate(client, 'old-rules')
    current = client.get('/api/v1/drafts/draft_fixture').json()
    assert current['qa']['stale'] is True
    denied = client.post('/api/v1/drafts/draft_fixture/seal', json={'qa_id': old['id'],
        'qa_fingerprint': old['fingerprint'], 'generation': 1},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'stale-rules-seal'})
    assert denied.status_code == 201, denied.text
    fresh = validate(client, 'new-rules')
    assert fresh['quality']['state'] == 'completed' and fresh['fingerprint'] != old['fingerprint']
    assert client.get('/api/v1/drafts/draft_fixture').json()['qa']['stale'] is False
    with database[0].transaction() as session:
        assert all(segment.sequence == 1 for segment in drafts.current_segments(session, 'draft_fixture').values())


@pytest.mark.parametrize('mode,target', [('must', '缺失的术语'), ('forbidden', '原件')])
def test_terminology_risks_are_advisory_without_requiring_manual_resolution(client, database, mode, target):
    seed_risk(*database)
    with database[0].transaction() as session:
        session.get(Draft, 'draft_fixture').profile = {'glossary_entries': [
            {'source': 'original', 'target': target, 'mode': mode, 'variants': []}]}
    quality = validate(client)
    assert quality['quality']['blocking'] is False
    assert any(i['code'] == ('TERM_REQUIRED' if mode == 'must' else 'TERM_FORBIDDEN') and not i['resolved'] for i in quality['issues'])
