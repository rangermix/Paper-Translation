"""Three changed terms select exactly two blocks through actual API/worker flow."""
import pytest
from sqlalchemy import select

from packages.domain.models import Candidate, Draft, ReviewRecord, SegmentVersion, Settings
from packages.editorial.drafts import current_segments
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_edition_translation import configure
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_three_changed_terms_impact_and_explicitly_accept_only_two_blocks(client, database, monkeypatch, tmp_path):
    db, cfg = database
    seed_editor(db, cfg)
    profile = configure(monkeypatch, tmp_path)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
        before = {s.block_id: (s.id, s.sequence, digest(s.target_inline))
                  for s in current_segments(session, 'draft_fixture').values()}
    revisions = []
    for revision in range(2):
        entries = [{'source': term, 'target': target + str(revision), 'mode': 'preferred', 'variants': []}
                   for term, target in [('tokens', '词元'), ('original', '原件'), ('absentterm', '未匹配词')]]
        saved = client.post('/api/v1/glossaries/revisions', json={'scope': 'document',
            'document_id': 'doc_fixture', 'source_language': 'en', 'target_language': 'zh-Hans',
            'entries': entries}, headers={'Idempotency-Key': 'three-terms-' + str(revision)})
        assert saved.status_code == 201, saved.text
        revisions.append(saved.json())
    assert revisions[1]['parent_id'] == revisions[0]['id']
    assert all(a['target'] != b['target'] for a, b in zip(revisions[0]['entries'], revisions[1]['entries']))
    preview = client.post('/api/v1/glossaries/' + revisions[1]['id'] + '/impact', json={},
        headers={'Idempotency-Key': 'three-terms-preview'})
    assert preview.status_code == 200, preview.text
    selected = sorted(row['block_id'] for row in preview.json()['items'])
    assert selected == ['item', 'p1'] and preview.json()['provider_calls'] == 0
    terms = client.get('/api/v1/glossaries/effective', params={'document_id': 'doc_fixture',
        'source_language': 'en', 'target_language': 'zh-Hans'}).json()
    created = client.post('/api/v1/drafts/draft_fixture/candidates', json={'block_ids': selected,
        'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile),
        'glossary_revision': terms['revision'], 'budget_micro': 1_000_000, 'external_processing_confirmed': True},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'three-terms-candidate'})
    assert created.status_code == 202, created.text
    provider = FakeProvider()
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    assert {unit['owner_block_id'] for call in provider.calls for unit in call} == set(selected)
    with db.transaction() as session:
        assert before == {s.block_id: (s.id, s.sequence, digest(s.target_inline))
                          for s in current_segments(session, 'draft_fixture').values()}
        candidate = session.get(Candidate, created.json()['id'])
        assert set(candidate.results) == set(selected) and candidate.status == 'ready'
        assert candidate.base['requested_glossary_revision'] == terms['revision']
        assert candidate.base['glossary_entries'] == terms['entries']
        etag = f'"{candidate.generation}"'
    accepted = client.post('/api/v1/candidates/' + created.json()['id'] + '/accept',
        json={'block_ids': selected, 'glossary_revision': terms['revision']},
        headers={'If-Match': etag, 'Idempotency-Key': 'three-terms-accept'})
    assert accepted.status_code == 200, accepted.text
    with db.transaction() as session:
        assert session.get(Draft, 'draft_fixture').glossary_revision == 'empty-v1'
        assert not list(session.scalars(select(ReviewRecord)))
        for block_id, segment in current_segments(session, 'draft_fixture').items():
            if block_id in selected:
                assert segment.sequence == 2 and segment.origin == 'candidate_accepted'
                assert segment.provenance_json['glossary_revision'] == terms['revision']
                assert session.get(SegmentVersion, before[block_id][0]).sequence == 1
            else:
                assert (segment.id, segment.sequence, digest(segment.target_inline)) == before[block_id]
