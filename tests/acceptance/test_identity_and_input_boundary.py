"""Real migrated PostgreSQL and HTTP boundaries supplement independent browser evidence."""
import pytest
from sqlalchemy import inspect

pytestmark = pytest.mark.postgres


def test_migrated_schema_and_api_require_no_virtual_identity(database, client):
    db, _ = database
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    assert tables and 'documents' in tables
    forbidden_tables = {'users', 'workspaces', 'tenants', 'roles', 'sessions', 'owners'}
    forbidden_columns = {'user_id', 'workspace_id', 'tenant_id', 'role_id', 'session_id', 'owner_id'}
    assert not forbidden_tables.intersection(tables)
    assert not [(table, column['name']) for table in tables for column in inspector.get_columns(table)
        if column['name'] in forbidden_columns]
    schema = client.get('/openapi.json').json()
    assert not schema.get('components', {}).get('securitySchemes')
    assert client.get('/api/v1/documents').status_code == 200
    for path in ('login', 'users', 'workspaces', 'tenants', 'roles', 'sessions'):
        assert client.post('/api/v1/' + path, json={}).status_code == 404


@pytest.mark.parametrize('source', [
    {'kind': 'url', 'url': 'https://example.invalid/paper.pdf'},
    {'kind': 'text', 'text': 'Text cannot be imported'},
    {'kind': 'bilingual', 'source': 'Source', 'target': 'Target'},
    {'kind': 'html', 'html': '<p>Untrusted source</p>'},
    {'kind': 'docx', 'filename': 'paper.docx'},
    {'kind': 'json', 'blocks': []},
    {'kind': 'pdf_upload', 'upload_id': 'absent', 'attachments': []},
    [{'filename': 'attachment.pdf', 'media_type': 'application/pdf'}],
])
def test_direct_import_rejects_every_non_pdf_shape(client, source):
    response = client.post('/api/v1/imports', json={'source': source},
        headers={'Idempotency-Key': 'boundary-direct-import'})
    assert response.status_code in (415, 422), response.text
    for path in ('imports/html', 'imports/ir', 'imports/text', 'imports/docx', 'imports/url'):
        assert client.post('/api/v1/' + path, json=source).status_code == 404


@pytest.mark.parametrize('mime,filename', [
    ('text/html', 'renamed.pdf'),
    ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'paper.docx'),
    ('application/json', 'paper.json'),
])
def test_upload_media_type_cannot_open_a_non_pdf_entry(client, mime, filename):
    response = client.post('/api/v1/uploads', json={'filename': filename, 'media_type': mime, 'byte_size': 20},
        headers={'Idempotency-Key': 'mime-' + filename})
    assert response.status_code in (415, 422), response.text
