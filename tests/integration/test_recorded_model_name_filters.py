"""Model display/filter names never come from mutable current configuration."""
from datetime import timedelta

import pytest

from packages.domain.models import Job, Settings, now
from packages.local_models.catalog import artifact, models
from packages.parsers.catalog import vlm_lock
from packages.parsers.profiles import PARSER_PROFILES

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('top_level', [False, True])
def test_model_names_filter_before_pagination_and_do_not_guess_identity(client, database, top_level):
    db, _ = database
    entry = models()[0]
    identifier = artifact(entry)['id']
    recorded = {'kind': 'local', 'model_id': identifier, 'revision': entry['revision']}
    with db.transaction() as session:
        session.get(Settings, 'singleton').preferences = {'local_analyst_model_id': identifier}
        session.add_all(Job(id=f'unrelated_{i}', stage='parse', status='succeeded') for i in range(101))
        session.add_all([
            Job(id='known', stage='translate', status='succeeded', actual_model=recorded, created_at=now() - timedelta(days=1)),
            Job(id='old_no_revision', stage='translate', status='succeeded', actual_model={'kind': 'local', 'model_id': identifier}, created_at=now() - timedelta(days=2)),
            Job(id='api_same_id', stage='translate', status='succeeded', actual_model={**recorded, 'kind': 'api'}),
            Job(id='wrong_revision', stage='translate', status='succeeded', actual_model={**recorded, 'revision': 'different-revision'}),
            Job(id='unknown', stage='translate', status='succeeded', actual_model={'kind': 'local', 'model_id': 'unknown/model'}),
            Job(id='configured_only', stage='translate', status='succeeded', payload={'profile': {'model_id': identifier}}),
        ])
    params = {'model': entry['label'].upper(), 'top_level_only': top_level, 'limit': 1}
    first = client.get('/api/v1/jobs', params=params).json()
    assert [row['id'] for row in first['items']] == ['known']
    assert first['items'][0]['actual_model'] == {**recorded, 'display_name': entry['label']}
    second = client.get('/api/v1/jobs', params={**params, 'cursor': first['next_cursor']}).json()
    assert [row['id'] for row in second['items']] == ['old_no_revision']
    assert second['next_cursor'] is None
    with db.transaction() as session:
        assert session.get(Job, 'known').actual_model == recorded
    # The existing exact/partial recorded-ID search remains available, including API IDs.
    ids = {row['id'] for row in client.get('/api/v1/jobs', params={'model': identifier}).json()['items']}
    assert ids == {'known', 'old_no_revision', 'api_same_id', 'wrong_revision'}


def test_internal_model_name_match_keeps_existing_main_task_family_boundaries(client, database):
    db, _ = database
    entry = models()[0]
    model = {'kind': 'local', 'model_id': artifact(entry)['id'], 'revision': entry['revision']}
    with db.transaction() as session:
        session.add(Job(id='parse_root', stage='parse', status='succeeded', actual_model={'kind': 'none'}))
        session.flush()
        session.add_all([
            Job(id='internal', parent_job_id='parse_root', stage='recovery', status='succeeded', actual_model=model),
            Job(id='independent_translation', parent_job_id='parse_root', stage='translate', status='succeeded', actual_model=model),
        ])
    params = {'model': entry['label'], 'top_level_only': True}
    assert {row['id'] for row in client.get('/api/v1/jobs', params=params).json()['items']} == {'parse_root', 'independent_translation'}
    params['top_level_only'] = False
    assert {row['id'] for row in client.get('/api/v1/jobs', params=params).json()['items']} == {'internal', 'independent_translation'}


def test_parser_label_search_matches_exact_repository_and_compatible_revision(client, database):
    db, _ = database
    entry = vlm_lock()['models'][0]
    label = next(row['label'] for row in PARSER_PROFILES if row['id'] == entry['id'])
    good = {'kind': 'local', 'model_id': entry['repo'], 'revision': entry['revision']}
    with db.transaction() as session:
        session.add_all([
            Job(id='parser', stage='parse', status='succeeded', actual_model=good),
            Job(id='old_parser_revision', stage='parse', status='succeeded', actual_model={**good, 'revision': 'old-revision'}),
            Job(id='api_repo', stage='translate', status='succeeded', actual_model={**good, 'kind': 'api'}),
        ])
    response = client.get('/api/v1/jobs', params={'model': label, 'top_level_only': True}).json()
    assert [row['id'] for row in response['items']] == ['parser']
    assert response['items'][0]['actual_model']['display_name'] == label
    assert 'display_name' not in client.get('/api/v1/jobs/old_parser_revision').json()['actual_model']
