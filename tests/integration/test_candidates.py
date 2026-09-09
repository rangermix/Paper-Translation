import pytest
from concurrent.futures import ThreadPoolExecutor

from packages.domain.models import Candidate, Draft
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def candidate_fixture(db, cfg, client):
    seed_editor(db, cfg)
    draft = client.get('/api/v1/drafts/draft_fixture').json()
    segment = next(s for s in draft['segments'] if s['block_id'] == 'item')
    with db.transaction() as session:
        session.add(Candidate(id='candidate_fixture', draft_id='draft_fixture', status='ready',
            base={'source_revision_id': draft['source_revision_id'], 'source_hash': draft['source_hash'],
                'glossary_revision': draft['glossary_revision'], 'requested_glossary_revision': draft['glossary_revision'],
                'segments': {'item': {'version': 1, 'source_hash': segment['source_hash'], 'context_hash': segment['context_hash'], 'reviewed': False}}},
            results={'item': [{'type': 'text', 'text': '保留这份原件。'}]}))
    return draft


def test_late_candidate_keeps_manual_edit(client, database):
    db, cfg = database
    candidate_fixture(db, cfg, client)
    changed = client.patch('/api/v1/drafts/draft_fixture/segments/item', json={'target_inline': [{'type': 'text', 'text': '这是我手工核对的译文。'}], 'base_segment_version': 1, 'reason': 'Manual change'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'manual'})
    assert changed.status_code == 200
    accepted = client.post('/api/v1/candidates/candidate_fixture/accept', json={}, headers={'If-Match': '"1"', 'Idempotency-Key': 'accept'})
    assert accepted.status_code == 409
    after = client.get('/api/v1/drafts/draft_fixture').json()
    assert next(s for s in after['segments'] if s['block_id'] == 'item')['target_inline'][0]['text'] == '这是我手工核对的译文。'


def test_accept_is_explicit_and_does_not_change_other_segments(client, database):
    db, cfg = database
    original = candidate_fixture(db, cfg, client)
    accepted = client.post('/api/v1/candidates/candidate_fixture/accept', json={}, headers={'If-Match': '"1"', 'Idempotency-Key': 'accept'})
    assert accepted.status_code == 200, accepted.text
    result = client.get('/api/v1/drafts/draft_fixture').json()
    assert [s for s in result['segments'] if s['block_id'] != 'item'] == [s for s in original['segments'] if s['block_id'] != 'item']
    replay = client.post('/api/v1/candidates/candidate_fixture/accept', json={}, headers={'If-Match': '"1"', 'Idempotency-Key': 'accept'})
    assert replay.json() == accepted.json()


def test_simultaneous_candidate_accept_has_one_winner(client, database):
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    db, cfg = database
    candidate_fixture(db, cfg, client)
    def accept(index):
        with TestClient(create_app(cfg, db)) as browser:
            return browser.post('/api/v1/candidates/candidate_fixture/accept', json={}, headers={
                'X-Library-Request': '1', 'If-Match': '"1"', 'Idempotency-Key': f'candidate-browser-{index}'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(accept, [1, 2])) == [200, 412]
    result = client.get('/api/v1/drafts/draft_fixture').json()
    assert next(s['version'] for s in result['segments'] if s['block_id'] == 'item') == 2
