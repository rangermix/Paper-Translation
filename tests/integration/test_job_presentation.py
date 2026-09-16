"""M1-R17/M1-G08: readable job context and complete, stable task browsing."""
from datetime import timedelta

import pytest

from packages.domain.models import Document, Job, Upload, now

pytestmark = pytest.mark.postgres


def test_existing_jobs_resolve_document_and_upload_names(client, database):
    db, _ = database
    with db.transaction() as session:
        session.add(Document(id='doc_named', title='Attention Is All You Need'))
        session.add(Upload(id='upl_named', filename='论文检查.pdf', byte_size=100, expires_at=now()))
        session.flush()
        session.add_all([
            Job(id='job_translate', document_id='doc_named', stage='translate', payload={'locale': 'zh-Hans'}),
            Job(id='job_inspect', stage='inspect', payload={'upload_id': 'upl_named'}),
            Job(id='job_expired', stage='inspect', payload={'upload_id': 'missing'}),
        ])
    translated = client.get('/api/v1/jobs/job_translate').json()
    assert translated['title'] == 'Attention Is All You Need'
    assert translated['target_locale'] == 'zh-Hans'
    inspected = client.get('/api/v1/jobs/job_inspect').json()
    assert inspected['title'] == inspected['filename'] == '论文检查.pdf'
    assert client.get('/api/v1/jobs/job_expired').json()['title'] == '未命名 PDF'
    with db.transaction() as session:
        session.get(Document, 'doc_named').title = 'Updated paper title'
    items = {j['id']: j for j in client.get('/api/v1/jobs').json()['items']}
    assert items['job_translate']['title'] == 'Updated paper title'


def test_newest_first_cursor_has_no_gaps_even_with_equal_timestamps(client, database):
    db, _ = database
    timestamp = now()
    with db.transaction() as session:
        session.add_all(Job(id=f'job_{i:03}', stage='inspect', created_at=timestamp - timedelta(days=i // 2)) for i in range(105))
    ids, cursor = [], None
    while True:
        params = {'limit': 30, **({'cursor': cursor} if cursor else {})}
        response = client.get('/api/v1/jobs', params=params)
        assert response.status_code == 200
        data = response.json()
        ids.extend(j['id'] for j in data['items'])
        cursor = data['next_cursor']
        if not cursor:
            break
    expected = [f'job_{i:03}' for i in sorted(range(105), key=lambda i: (i // 2, -i))]
    assert ids == expected
    assert client.get('/api/v1/jobs?cursor=missing').status_code == 422


def test_search_and_status_filter_apply_before_pagination(client, database):
    db, _ = database
    with db.transaction() as session:
        session.add(Document(id='doc_search', title='100%_可靠翻译'))
        session.add(Upload(id='upl_search', filename='Uploaded systems.pdf', byte_size=100, expires_at=now()))
        session.flush()
        session.add_all(Job(id=f'job_recent_{i:03}', stage='export', status='succeeded') for i in range(101))
        session.add_all([
            Job(id='job_old', document_id='doc_search', stage='translate', status='outcome_unknown', created_at=now() - timedelta(days=7)),
            Job(id='job_upload', stage='inspect', status='failed', payload={'upload_id': 'upl_search'}),
        ])
    assert [j['id'] for j in client.get('/api/v1/jobs?q=100%25_&group=attention&limit=1').json()['items']] == ['job_old']
    assert [j['id'] for j in client.get('/api/v1/jobs?q=SYSTEMS&group=attention').json()['items']] == ['job_upload']
    assert client.get('/api/v1/jobs?q=100%25_&group=active').json()['items'] == []
    assert client.get('/api/v1/jobs?group=invalid').status_code == 422


def test_cleanup_does_not_expose_or_search_deleted_titles(client, database):
    db, _ = database
    with db.transaction() as session:
        session.add(Document(id='doc_deleted', title='Private deleted paper', deleted_at=now()))
        session.flush()
        session.add_all([
            Job(id='job_cleanup', document_id='doc_deleted', stage='cleanup'),
            Job(id='job_hidden', document_id='doc_deleted', stage='translate'),
        ])
    assert client.get('/api/v1/jobs?q=Private').json()['items'] == []
    items = client.get('/api/v1/jobs').json()['items']
    assert {j['id'] for j in items} == {'job_cleanup', 'job_hidden'}
    assert 'Private deleted paper' not in str(items)
    assert items[0]['title'] == '已删除文档'
    assert client.get('/api/v1/jobs/job_hidden').status_code == 200


@pytest.mark.parametrize('include_cleared', [False, True])
def test_top_level_tasks_filter_before_pagination_and_keep_children_readable(client, database, include_cleared):
    db, _ = database
    timestamp = now()
    with db.transaction() as session:
        session.add(Document(id='doc_family', title='Nested task paper'))
        session.flush()
        session.add_all([
            Job(id='root_new', document_id='doc_family', stage='parse', status='failed', created_at=timestamp),
            Job(id='root_old', document_id='doc_family', stage='parse', status='failed', created_at=timestamp - timedelta(days=1)),
            Job(id='root_cleared', document_id='doc_family', stage='parse', status='failed', generation=1,
                history_cleared_generation=1, created_at=timestamp - timedelta(days=2)),
        ])
        session.flush()
        session.add_all(Job(id=f'child_{i:03}', parent_job_id='root_new', document_id='doc_family',
            stage='parse', status='failed', created_at=timestamp + timedelta(seconds=i + 1)) for i in range(105))
        session.flush()
        session.add(Job(id='grandchild', parent_job_id='child_000', document_id='doc_family', stage='parse', status='failed'))
    params = {'top_level_only': True, 'include_cleared': include_cleared, 'limit': 1,
              'group': 'attention', 'stage': 'parse', 'q': 'Nested task paper', 'document_id': 'doc_family'}
    found = []
    while True:
        response = client.get('/api/v1/jobs', params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        assert all(item['parent_job_id'] is None for item in data['items'])
        found.extend(item['id'] for item in data['items'])
        if data['next_cursor'] is None:
            break
        params['cursor'] = data['next_cursor']
    assert found == ['root_new', 'root_old'] + (['root_cleared'] if include_cleared else [])
    parent = client.get('/api/v1/jobs/root_new').json()
    assert len(parent['child_jobs']) == 100
    child = client.get('/api/v1/jobs/child_000').json()
    assert child['parent_job_id'] == 'root_new'
    assert child['child_jobs'][0]['id'] == 'grandchild'
    assert client.get('/api/v1/jobs/child_000/logs').status_code == 200
    # The opt-in UI filter does not change existing API consumers or child queries.
    children = client.get('/api/v1/jobs', params={'parent_job_id': 'root_new', 'limit': 100}).json()
    assert len(children['items']) == 100
    remaining = client.get('/api/v1/jobs', params={'parent_job_id': 'root_new', 'limit': 100, 'cursor': children['next_cursor']}).json()
    assert len(remaining['items']) == 5 and remaining['next_cursor'] is None
    assert len({item['id'] for item in children['items'] + remaining['items']}) == 105
    assert any(item['parent_job_id'] for item in client.get('/api/v1/jobs').json()['items'])
