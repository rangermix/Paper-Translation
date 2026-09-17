"""Exercise number equivalence through persisted draft QA, without rewriting prose."""
import json
from pathlib import Path

import pytest

from packages.ir import block_hash
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('source,target,valid', [
    ('up to 11 billion parameters', '最高达 110 亿参数', True),
    ('3 billion parameters', '30 亿参数', True),
    ('S = 16 , M = 64 with 128 cores, 131 . 4 k tokens/sec',
     'S = 16、M = 64，128 个核心，131.4 k tokens/秒', True),
    ('3 billion parameters', '3 亿参数', False),
    ('64 and 64 cores at 50%', '64 个核心，50', False),
])
def test_numeric_formats_in_current_qa(client, database, source, target, valid):
    ir = json.loads(Path('tests/fixtures/sample-document.json').read_text(encoding='utf-8'))
    revision = ir['source_revision']
    block = next(b for b in revision['blocks'] if b['id'] == 'item')
    block['raw_text'] = block['normalized_text'] = source
    block['source_inline'] = [{'type': 'text', 'text': source}]
    block['source_hash'] = block_hash(block, revision['protected_atoms'])
    row = next(r for r in ir['translation_revision']['results'] if r['block_id'] == 'item')
    row['source_hash'] = block['source_hash']
    row['target_inline'] = [{'type': 'text', 'text': target}]
    seed_editor(*database, document_ir=ir)
    before = client.get('/api/v1/drafts/draft_fixture').json()
    response = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'numeric-qa'})
    assert response.status_code == 200, response.text
    qa = response.json()
    assert qa['valid'] is valid, qa['issues']
    issues = [i for i in qa['issues'] if i['code'] == 'NUMBER_MISMATCH']
    assert bool(issues) is not valid
    if issues:
        evidence = issues[0]['evidence']
        assert evidence['source'] == source and evidence['target'] == target
        assert evidence['missing_from_target'] and evidence['extra_in_target']
    after = client.get('/api/v1/drafts/draft_fixture').json()
    fields = ('block_id', 'version', 'source_text', 'raw_text', 'source_hash', 'target_inline')
    def contents(draft):
        return [{key: segment.get(key) for key in fields} for segment in draft['segments']]
    assert contents(after) == contents(before)
    assert after['generation'] == before['generation']
    sealed = client.post('/api/v1/drafts/draft_fixture/seal', json={
        'qa_id': qa['id'], 'qa_fingerprint': qa['fingerprint'], 'generation': 1},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'numeric-seal'})
    assert sealed.status_code == 201, sealed.text
