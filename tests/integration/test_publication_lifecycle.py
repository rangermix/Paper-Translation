import pytest
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select

from packages.domain.models import Artifact, Document, Edition, Publication
from packages.jobs.queue import claim
from packages.storage import file_hash
from tests.support import seed_editor
from workers.main import execute

pytestmark = pytest.mark.postgres


def seal_and_publish(client, db, cfg, draft_generation, edition_generation, suffix):
    qa = client.post('/api/v1/drafts/draft_fixture/validate', json={},
        headers={'If-Match': f'"{draft_generation}"', 'Idempotency-Key': 'qa-' + suffix}).json()
    assert qa['quality']['state'] == 'completed' and not qa['quality']['blocking'], qa
    revision = client.post('/api/v1/drafts/draft_fixture/seal', json={'qa_id': qa['id'], 'qa_fingerprint': qa['fingerprint'], 'generation': draft_generation},
        headers={'If-Match': f'"{draft_generation}"', 'Idempotency-Key': 'seal-' + suffix}).json()
    queued = client.post('/api/v1/editions/edition_fixture/publish', json={'translation_revision_id': revision['id'], 'expected_generation': edition_generation},
        headers={'If-Match': f'"{edition_generation}"', 'Idempotency-Key': 'publish-' + suffix})
    assert queued.status_code == 202, queued.text
    execute(db, cfg, claim(db))
    with db.transaction() as session:
        edition = session.get(Edition, 'edition_fixture')
        artifact = session.get(Artifact, edition.current_artifact_id)
        return artifact.id, cfg.data / artifact.storage_key / 'index.html'


def drain(db, cfg):
    for _ in range(10):
        lease = claim(db)
        if lease is None:
            return
        execute(db, cfg, lease)
    raise AssertionError('Unexpected unbounded tasks')


def test_publication_aba_stale_index_and_bookmark_do_not_jump(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    first, first_path = seal_and_publish(client, db, cfg, 1, 1, 'a')
    old_hash = file_hash(first_path)
    drain(db, cfg)
    assert client.get('/api/v1/search', params={'q': 'The job has', 'side': 'source'}).json()['items']
    position = {'document_id': 'doc_fixture', 'locale': 'zh-Hans', 'artifact_id': first, 'block_id': 'item', 'offset': 2}
    assert client.put('/api/v1/reading-position', json=position, headers={'If-Match': '"0"', 'Idempotency-Key': 'position-a'}).status_code == 200
    edit = client.patch('/api/v1/drafts/draft_fixture/segments/item', json={'base_segment_version': 1, 'reason': 'New reviewed wording',
        'target_inline': [{'type': 'text', 'text': '新的中文连续词组'}]}, headers={'If-Match': '"1"', 'Idempotency-Key': 'new-target'})
    assert edit.status_code == 200
    second, second_path = seal_and_publish(client, db, cfg, 2, 2, 'b')
    # The old search rows still exist before the async index catches up. They
    # must not leak the previous current version even for a valid source query.
    assert not client.get('/api/v1/search', params={'q': 'The job has'}).json()['items']
    pos = client.get('/api/v1/reading-position', params={'document_id': 'doc_fixture', 'locale': 'zh-Hans', 'artifact_id': second}).json()
    assert pos['migration_required'] and pos['block_id'] is None and pos['offset'] == 0
    assert pos['previous_position']['artifact_id'] == first
    drain(db, cfg)
    found = client.get('/api/v1/search', params={'q': '中文连续', 'side': 'target'}).json()['items']
    assert len(found) == 1 and found[0]['href'] == f'/artifacts/{second}/index.html#b-item'
    rolled = client.post('/api/v1/editions/edition_fixture/rollback', json={'artifact_id': first, 'expected_generation': 3},
        headers={'If-Match': '"3"', 'Idempotency-Key': 'rollback-a'})
    assert rolled.status_code == 200 and rolled.json()['generation'] == 4
    stale = client.post('/api/v1/editions/edition_fixture/rollback', json={'artifact_id': second, 'expected_generation': 2},
        headers={'If-Match': '"2"', 'Idempotency-Key': 'aba-stale'})
    assert stale.status_code == 412
    assert file_hash(first_path) == old_hash
    assert client.get(f'/artifacts/{second}/index.html').status_code == 200
    assert not client.get('/api/v1/search', params={'q': '中文连续'}).json()['items']
    drain(db, cfg)
    unpublish = client.post('/api/v1/editions/edition_fixture/unpublish', json={'expected_generation': 4},
        headers={'If-Match': '"4"', 'Idempotency-Key': 'unpublish'})
    assert unpublish.status_code == 200
    assert not client.get('/api/v1/search', params={'q': 'The job has'}).json()['items']
    assert client.get('/read/doc_fixture/zh-Hans').status_code == 404
    assert client.get(f'/artifacts/{first}/index.html').status_code == 200
    with db.transaction() as session:
        assert [event.generation for event in session.scalars(select(Publication).order_by(Publication.created_at))] == [2, 3, 4, 5]


def test_two_browsers_first_bookmark_write_has_one_winner(client, database):
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    db, cfg = database
    seed_editor(db, cfg)
    artifact_id, _ = seal_and_publish(client, db, cfg, 1, 1, 'bookmark-race')
    body = {'document_id': 'doc_fixture', 'locale': 'zh-Hans', 'artifact_id': artifact_id, 'block_id': 'item', 'offset': 1}
    def write(index):
        with TestClient(create_app(cfg, db)) as browser:
            return browser.put('/api/v1/reading-position', json=body | {'offset': index}, headers={
                'X-Library-Request': '1', 'If-Match': '"0"', 'Idempotency-Key': f'bookmark-browser-{index}'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, [1, 2])) == [200, 412]


@pytest.mark.parametrize('other_document', [False, True])
def test_rollback_rejects_artifact_from_another_document_or_locale(client, database, other_document):
    db, cfg = database
    seed_editor(db, cfg)
    artifact_id, path = seal_and_publish(client, db, cfg, 1, 1, 'foreign-artifact')
    original_hash = file_hash(path)
    with db.transaction() as session:
        if other_document:
            session.add(Document(id='other_document', title='Other controlled document', source_asset_id='source_pdf'))
            session.flush()
        session.add(Edition(id='other_edition', document_id='other_document' if other_document else 'doc_fixture',
            target_locale='zh-Hans' if other_document else 'ja'))
    rejected = client.post('/api/v1/editions/other_edition/rollback', json={'artifact_id': artifact_id, 'expected_generation': 1},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'foreign-rollback'})
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'ARTIFACT_MISMATCH', rejected.text
    with db.transaction() as session:
        edition = session.get(Edition, 'other_edition')
        assert edition.current_artifact_id is None and edition.generation == 1
        assert not list(session.scalars(select(Publication).where(Publication.edition_id == edition.id)))
        assert session.get(Edition, 'edition_fixture').current_artifact_id == artifact_id
    assert file_hash(path) == original_hash


@pytest.mark.parametrize('deleted', [False, True])
def test_rollback_rejects_missing_artifact_asset_or_deleted_document(client, database, deleted):
    import json
    db, cfg = database
    seed_editor(db, cfg)
    first, first_path = seal_and_publish(client, db, cfg, 1, 1, 'rollback-original')
    drain(db, cfg)
    second, second_path = seal_and_publish(client, db, cfg, 1, 2, 'rollback-current')
    second_hash = file_hash(second_path)
    if deleted:
        doc = client.get('/api/v1/documents/doc_fixture')
        removed = client.request('DELETE', '/api/v1/documents/doc_fixture', json={'confirm': True},
            headers={'If-Match': doc.headers['etag']})
        assert removed.status_code == 202, removed.text
    else:
        manifest = json.loads((first_path.parent / 'manifest.json').read_text('utf-8'))
        image = next(item for item in manifest['files'] if item['media_type'].startswith('image/'))
        missing = first_path.parent / image['path']
        assert missing.resolve().is_relative_to(cfg.data.resolve())
        missing.unlink()
    rejected = client.post('/api/v1/editions/edition_fixture/rollback',
        json={'artifact_id': first, 'expected_generation': 3},
        headers={'If-Match': '"3"', 'Idempotency-Key': 'rollback-rejected'})
    assert rejected.status_code in (404, 409, 410, 422), rejected.text
    assert rejected.json()['error']['code'] == ('DOCUMENT_DELETED' if deleted else 'ARTIFACT_CORRUPT')
    with db.transaction() as session:
        edition = session.get(Edition, 'edition_fixture')
        assert edition.current_artifact_id == second and edition.generation == 3
        assert len(list(session.scalars(select(Publication)))) == 2
    assert file_hash(second_path) == second_hash
