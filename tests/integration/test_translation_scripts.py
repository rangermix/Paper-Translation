"""Language contamination is diagnosed without rewriting or blocking publication."""
import json
from pathlib import Path

import pytest

from packages.ir import block_hash
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_new_hangul_in_chinese_is_a_persisted_nonblocking_finding(client, database):
    ir = json.loads(Path('tests/fixtures/sample-document.json').read_text())
    source = ir['source_revision']
    block = next(b for b in source['blocks'] if b['id'] == 'item')
    block['raw_text'] = block['normalized_text'] = 'Only one minibatch is active.'
    block['source_inline'] = [{'type': 'text', 'text': block['normalized_text']}]
    block['source_hash'] = block_hash(block, source['protected_atoms'])
    result = next(r for r in ir['translation_revision']['results'] if r['block_id'] == 'item')
    result['source_hash'] = block['source_hash']
    result['target_inline'] = [{'type': 'text', 'text': '只有 하나의小批量处于活动状态。'}]
    seed_editor(*database, document_ir=ir)
    before = client.get('/api/v1/drafts/draft_fixture').json()
    response = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'script-qa'})
    assert response.status_code == 200, response.text
    qa = response.json()
    finding, = [i for i in qa['issues'] if i['code'] == 'UNEXPECTED_SCRIPT']
    assert finding['block_id'] == 'item'
    assert finding['blocking'] is False
    assert finding['severity'] == 'important'
    assert finding['evidence'] == {'target_locale': 'zh-Hans', 'scripts': [
        {'script': 'Hangul', 'unexpected': [{'text': '하나의', 'count': 1}]}]}
    after = client.get('/api/v1/drafts/draft_fixture').json()
    assert after['source'] == before['source']
    assert after['segments'] == before['segments']
    assert after['generation'] == before['generation']
    sealed = client.post('/api/v1/drafts/draft_fixture/seal', json={
        'qa_id': qa['id'], 'qa_fingerprint': qa['fingerprint'], 'generation': 1},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'script-seal'})
    assert sealed.status_code == 201, sealed.text
