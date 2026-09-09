"""A completed candidate remains outside the immutable publication until acceptance."""
import pytest
from sqlalchemy import select

from packages.domain.models import Candidate, Publication, SegmentVersion, Settings
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_edition_translation import configure
from tests.integration.test_publication_lifecycle import drain, seal_and_publish
from tests.support import seed_editor

pytestmark = pytest.mark.postgres


def test_unaccepted_candidate_does_not_enter_new_publication_or_its_audit(client, database, monkeypatch, tmp_path):
    db, cfg = database
    seed_editor(db, cfg)
    profile = configure(monkeypatch, tmp_path)
    first_id, first_file = seal_and_publish(client, db, cfg, 1, 1, 'before-candidate')
    old = first_file.read_bytes()
    drain(db, cfg)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
        versions = {v.id: digest(v.target_inline) for v in session.scalars(select(SegmentVersion))}
    body = {'block_ids': ['item'], 'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile),
        'glossary_revision': 'empty-v1', 'budget_micro': 10_000_000, 'external_processing_confirmed': True}
    created = client.post('/api/v1/drafts/draft_fixture/candidates', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'generate-only'})
    assert created.status_code == 202, created.text
    sentinel = 'UNACCEPTED-CANDIDATE-MUST-NOT-PUBLISH'
    provider = FakeProvider([lambda units: {'results': [{'unit_id': unit['unit_id'],
        'target_inline': [{'type': 'text', 'text': sentinel}]} for unit in units]}])
    for _ in range(4):
        lease = claim(db)
        if lease is None:
            break
        execute_translation(db, cfg, lease, provider)
    assert len(provider.calls) == 1
    with db.transaction() as session:
        candidate = session.get(Candidate, created.json()['id'])
        assert candidate.status == 'ready' and candidate.results['item'][0]['text'] == sentinel
        assert len(list(session.scalars(select(Publication)))) == 1
        assert versions == {v.id: digest(v.target_inline) for v in session.scalars(select(SegmentVersion))}
    second_id, second_file = seal_and_publish(client, db, cfg, 1, 2, 'while-candidate-unaccepted')
    assert second_id != first_id
    assert sentinel.encode() not in second_file.read_bytes()
    assert first_file.read_bytes() == old
    with db.transaction() as session:
        candidate = session.get(Candidate, created.json()['id'])
        assert candidate.status == 'ready'
        assert versions == {v.id: digest(v.target_inline) for v in session.scalars(select(SegmentVersion))}
        publications = list(session.scalars(select(Publication).order_by(Publication.created_at)))
        assert len(publications) == 2 and publications[-1].artifact_id == second_id
        assert publications[-1].created_at > candidate.created_at
        assert all(publication.origin == 'manual_ui' for publication in publications)
