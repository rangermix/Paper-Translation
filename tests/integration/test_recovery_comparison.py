from datetime import timedelta

from packages.domain.models import Document, Job, SourceDraft, now
from packages.jobs.stages import record_recovery
from tests.support import seed_editor


def seed_recovery(database):
    db, cfg = database
    ir = seed_editor(db, cfg)
    at = now()
    audit = [{'page': 1, 'rule_version': 'native-page-recovery-v1', 'action': 'native_page_recovery',
        'started_at': at.isoformat(), 'finished_at': (at + timedelta(seconds=1)).isoformat(),
        'before': ['Original paragraph <script>unsafe()</script>'], 'after': ['Recovered first.', 'Recovered second.'],
        'elapsed_ms': 1000, 'model': None}]
    with db.transaction() as session:
        parent = Job(id='parse_parent', document_id='doc_fixture', stage='parse', payload={})
        source = SourceDraft(id='recovery_source', document_id='doc_fixture', asset_id='source_pdf',
            source=ir['source_revision'], coverage={}, evidence={'inspection': {'automatic_recovery': audit}})
        session.add_all([parent, source]); session.flush()
        job_id = record_recovery(session, parent, source, audit)[0]
    return job_id


def test_recovery_comparison_reads_historical_evidence_with_pagination(client, database):
    job_id = seed_recovery(database)
    result = client.get(f'/api/v1/jobs/{job_id}/recovery?limit=1')
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['available'] is True and data['page'] == 1
    assert data['before'] == ['Original paragraph <script>unsafe()</script>']
    assert data['after'] == ['Recovered first.']
    assert data['before_count'] == 1 and data['after_count'] == 2
    assert data['next_offset'] == 1
    second = client.get(f'/api/v1/jobs/{job_id}/recovery?limit=1&offset=1').json()
    assert second['before'] == [] and second['after'] == ['Recovered second.']
    assert second['next_offset'] is None
    assert 'Original paragraph' not in client.get(f'/api/v1/jobs/{job_id}/logs').text


def test_missing_recovery_evidence_is_explicit(client, database):
    job_id = seed_recovery(database)
    with database[0].transaction() as session:
        session.get(SourceDraft, 'recovery_source').evidence = {}
    result = client.get(f'/api/v1/jobs/{job_id}/recovery')
    assert result.status_code == 200
    assert result.json()['available'] is False


def test_deleted_document_recovery_content_is_not_exposed(client, database):
    job_id = seed_recovery(database)
    with database[0].transaction() as session:
        session.get(Document, 'doc_fixture').deleted_at = now()
    result = client.get(f'/api/v1/jobs/{job_id}/recovery')
    assert result.status_code == 404
    assert 'Original paragraph' not in result.text


def test_recovery_reference_cannot_read_another_document(client, database):
    job_id = seed_recovery(database)
    with database[0].transaction() as session:
        session.add(Document(id='other_document', title='Other', source_asset_id='source_pdf'))
        session.get(Job, job_id).document_id = 'other_document'
    result = client.get(f'/api/v1/jobs/{job_id}/recovery')
    assert result.status_code == 404
