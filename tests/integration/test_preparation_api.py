import pytest
from sqlalchemy import select

from packages.domain.models import Draft, Job, Task
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.translation.execution import execute_translation
from tests.integration.test_edition_translation import prepared

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('mode', ['off', 'extractive', 'provider', 'local'])
def test_new_edition_freezes_explicit_preparation_mode(client, database, monkeypatch, tmp_path, mode):
    body = prepared(client, database, monkeypatch, tmp_path) | {'preparation': {'mode': mode}}
    result = client.post('/api/v1/editions/new_edition/translate', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'preparation-' + mode})
    assert result.status_code == 202, result.text
    with database[0].transaction() as session:
        job = session.get(Job, result.json()['job_id'])
        assert job.payload['preparation_options']['mode'] == mode
        assert ('analysis_profile' in job.payload) == (mode == 'local')


def test_default_context_and_read_only_result_do_not_dispatch_model(client, database, monkeypatch, tmp_path):
    body = prepared(client, database, monkeypatch, tmp_path)
    p = client.get('/api/v1/editions/new_edition/preflight').json()
    assert p['preparation_estimates']['provider']['additional_requests'] == 1
    result = client.post('/api/v1/editions/new_edition/translate', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'default-context'}).json()
    db, cfg = database
    fake = FakeProvider()
    execute_translation(db, cfg, claim(db), fake)
    response = client.get('/api/v1/drafts/' + result['draft_id'] + '/preparation')
    assert response.status_code == 200, response.text
    assert response.json()['available'] is True
    assert response.json()['preparation']['analysis'] is None
    assert fake.calls == []
    with db.transaction() as session:
        assert len(list(session.scalars(select(Task).where(Task.status == 'leased')))) == 0


def test_unrecognized_preparation_mode_is_rejected_before_job_creation(client, database, monkeypatch, tmp_path):
    body = prepared(client, database, monkeypatch, tmp_path) | {'preparation': {'mode': 'random-free-cloud'}}
    result = client.post('/api/v1/editions/new_edition/translate', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'bad-preparation'})
    assert result.status_code == 422
    with database[0].transaction() as session:
        assert not list(session.scalars(select(Job)))


@pytest.mark.parametrize('prepared_candidate', [False, True])
def test_candidate_replacement_uses_its_own_preparation_lineage(client, database, prepared_candidate):
    from packages.domain.models import Candidate
    from packages.editorial.drafts import current_segments, edit_segment
    from tests.integration.test_candidates import candidate_fixture
    from packages.preparation.collection import collect
    from packages.preparation.context import freeze
    from packages.storage import read_snapshot
    from packages.domain.models import SourceRevision
    db, cfg = database
    candidate_fixture(db, cfg, client)
    with db.transaction() as session:
        draft = session.get(Draft, 'draft_fixture')
        old = current_segments(session, draft.id)['item']
        manual = edit_segment(session, cfg, draft, 'item', old.target_inline, 1, 'Fixture with existing preparation',
            provenance={'preparation_revision': 'old-pack', 'preparation_context_modes': ['background_and_terms']})
        edited = edit_segment(session, cfg, draft, 'item', manual.target_inline, 2, 'Human edit retains its basis')
        assert edited.provenance_json['preparation_revision'] == 'old-pack'
        candidate = session.get(Candidate, 'candidate_fixture')
        base = candidate.base
        base['segments']['item']['version'] = 3
        if prepared_candidate:
            pack = freeze(collect(read_snapshot(cfg.data, session.get(SourceRevision, draft.source_revision_id))),
                'zh-Hans', 'empty-v1', [], context_mode='terms_only')
            base['preparation'] = pack
            base['preparation_by_block'] = {'item': {'preparation_revision': pack['revision'],
                'preparation_context_modes': ['terms_only'], 'glossary_entries': []}}
        candidate.base = dict(base)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(candidate, 'base')
    accepted = client.post('/api/v1/candidates/candidate_fixture/accept', json={},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'replace-prepared-segment'})
    assert accepted.status_code == 200, accepted.text
    with db.transaction() as session:
        provenance = current_segments(session, 'draft_fixture')['item'].provenance_json
        if prepared_candidate:
            assert provenance['preparation_revision'] == pack['revision']
            assert provenance['preparation_context_modes'] == ['terms_only']
        else:
            assert 'preparation_revision' not in provenance and 'preparation_context_modes' not in provenance
    selected = client.get('/api/v1/drafts/draft_fixture/preparation?block_id=item').json()
    candidate_pack = client.get('/api/v1/drafts/draft_fixture/preparation?candidate_id=candidate_fixture').json()
    assert selected['available'] is prepared_candidate
    assert candidate_pack['available'] is prepared_candidate
    assert selected['scope'] == 'segment' and candidate_pack['scope'] == 'candidate'
    if prepared_candidate:
        assert selected['preparation']['revision'] == candidate_pack['preparation']['revision'] == pack['revision']
    assert client.get('/api/v1/drafts/draft_fixture/preparation').json()['available'] is False
