"""Optional review status describes current selected text, never human certification."""
import copy
import json

import pytest
from sqlalchemy import select

from packages.domain.models import Job, Permit, ReviewRecord, SegmentVersion, Settings
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_edition_translation import configure
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def begin_review(client, db, cfg, monkeypatch, tmp_path, budget=True):
    seed_editor(db, cfg)
    profile = configure(monkeypatch, tmp_path) | {'semantic_review_enabled': True}
    (tmp_path / 'profile.json').write_text(json.dumps(profile), encoding='utf-8')
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, (1_000_000 if budget else 0)
        before = {s.id: digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
    started = client.post('/api/v1/drafts/draft_fixture/semantic-review', json={'block_ids': ['p1'],
        'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile),
        'glossary_revision': 'empty-v1', 'budget_micro': 1_000_000, 'external_processing_confirmed': True},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'semantic-status'})
    assert started.status_code == 202, started.text
    execute_translation(db, cfg, claim(db), FakeProvider())
    return started.json()['job_id'], before


@pytest.mark.parametrize('failure', ['missing_key', 'budget'])
def test_unavailable_optional_review_is_explicitly_incomplete(client, database, monkeypatch, tmp_path, failure):
    db, cfg = database
    job_id, before = begin_review(client, db, cfg, monkeypatch, tmp_path, budget=failure != 'budget')
    provider = FakeProvider()
    if failure == 'missing_key':
        key = tmp_path / 'empty-key'
        key.write_bytes(b'')
        monkeypatch.setenv('PROVIDER_KEY_FILE', str(key))
        def forbidden(*args, **kwargs):
            raise AssertionError('An empty key must never construct the transport')
        monkeypatch.setattr('packages.translation.execution.OpenAIResponses', forbidden)
        execute_translation(db, cfg, claim(db))
    else:
        execute_translation(db, cfg, claim(db), provider)
    assert not provider.calls and claim(db) is None
    draft = client.get('/api/v1/drafts/draft_fixture').json()
    assert draft.get('semantic_review_status') == 'incomplete'
    review = draft['semantic_reviews'][-1]
    assert review['job_id'] == job_id and review['completed'] is False
    assert review['block_ids'] == ['p1']
    assert review['status'] == ('waiting_config' if failure == 'missing_key' else 'waiting_budget')
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'semantic-incomplete-qa'})
    assert qa.status_code == 200
    assert any(i['code'] == 'OPTIONAL_REVIEW_INCOMPLETE' for i in qa.json()['issues'])
    with db.transaction() as session:
        assert before == {s.id: digest(s.target_inline) for s in session.scalars(select(SegmentVersion))}
        assert not list(session.scalars(select(ReviewRecord))) and not list(session.scalars(select(Permit)))
        assert not session.get(Job, job_id).progress.get('review_completed')


def test_zero_issue_review_becomes_stale_after_selected_target_changes(client, database, monkeypatch, tmp_path):
    db, cfg = database
    job_id, _ = begin_review(client, db, cfg, monkeypatch, tmp_path)
    provider = FakeProvider()
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    assert len(provider.calls) == 1
    draft = client.get('/api/v1/drafts/draft_fixture').json()
    # Even an issue-free review has an exact target snapshot and selected scope.
    assert draft.get('semantic_review_status') == 'completed'
    nodes = copy.deepcopy(next(s for s in draft['segments'] if s['block_id'] == 'p1')['target_inline'])
    next(n for n in nodes if n['type'] == 'text')['text'] += '（补充）'
    changed = client.patch('/api/v1/drafts/draft_fixture/segments/p1', json={'target_inline': nodes,
        'base_segment_version': 1, 'reason': 'Controlled target change after completed optional review'},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'semantic-target-change'})
    assert changed.status_code == 200, changed.text
    assert changed.json().get('semantic_review_status') == 'stale'
    review = changed.json()['semantic_reviews'][-1]
    assert review['job_id'] == job_id and review['completed'] is False and review['status'] == 'stale'
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': changed.headers['etag'], 'Idempotency-Key': 'semantic-stale-qa'})
    assert any(i['code'] == 'OPTIONAL_REVIEW_INCOMPLETE' and i['evidence']['status'] == 'stale'
               for i in qa.json()['issues'])
    with db.transaction() as session:
        assert session.get(Job, job_id).progress['review_completed'] is True, 'Retain historical completed report.'
        assert not list(session.scalars(select(ReviewRecord)))
