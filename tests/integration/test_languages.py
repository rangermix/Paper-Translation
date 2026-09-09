"""All-language flow uses real PostgreSQL/API/worker, never a live model."""
import json
import io
import zipfile

import pytest
from sqlalchemy import func, select

from packages.domain.models import Artifact, Draft, Edition, Job, SourceDraft, SourceRevision, Task, TranslationCache, TranslationRevision, Settings
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.storage import file_hash, read_snapshot
from packages.translation.execution import execute_translation
from packages.translation.languages import language_name
from tests.integration.test_edition_translation import configure
from tests.integration.test_publication_lifecycle import drain, seal_and_publish
from tests.support import seed_editor
from workers.main import execute

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('locale', ['ja', 'zh-Hant', 'ar', 'fr', 'pt-BR', 'fil'])
def test_all_languages_reuse_source_and_publish_without_language_consent(client, database, monkeypatch, tmp_path, locale, renamed_reuse=False):
    db, cfg = database
    seed_editor(db, cfg)
    old_artifact, old_path = seal_and_publish(client, db, cfg, 1, 1, 'experimental-old-zh')
    old_hash = file_hash(old_path)
    drain(db, cfg)
    document_etag = '"1"'
    if renamed_reuse:
        # Real chunk/finalize protocol plus the actual native inspector child.
        # Execute the serial spool locally; no authored inspection result or
        # Docling source output is substituted for its byte/page validation.
        import workers.main as worker
        from workers.parser.main import run_once
        original_write = worker.write_request
        def inspect_spool(input_root, request, pdf):
            written = original_write(input_root, request, pdf)
            assert request['operation'] == 'inspect'
            assert run_once(cfg.parser_inputs, cfg.parser_outputs)
            return written
        monkeypatch.setattr(worker, 'write_request', inspect_spool)
        content = (cfg.data / 'fixtures/sample.pdf').read_bytes()
        receipt = client.post('/api/v1/uploads', json={'filename': 'renamed-identical-paper.pdf',
            'media_type': 'application/pdf', 'byte_size': len(content)}, headers={'Idempotency-Key': 'renamed-receipt'})
        assert receipt.status_code == 201
        route = '/api/v1/uploads/' + receipt.json()['id']
        uploaded = client.put(route + '/chunks/0', content=content, headers={'If-Match': receipt.headers['etag'],
            'X-Chunk-SHA256': digest(content), 'Content-Range': f'bytes 0-{len(content)-1}/{len(content)}',
            'Content-Type': 'application/octet-stream'})
        assert uploaded.status_code == 200
        finalized = client.post(route + '/finalize', json={'expected_sha256': digest(content), 'total_bytes': len(content)},
            headers={'If-Match': uploaded.headers['etag'], 'Idempotency-Key': 'renamed-finalize'})
        assert finalized.status_code == 202
        worker.execute(db, cfg, claim(db))
        verified = client.get(route).json()
        assert verified['status'] == 'verified' and verified['source_asset_id'] == 'source_pdf'
        assert verified['duplicates'] == [{'id': 'doc_fixture', 'title': 'Publication fixture'}]
        unchanged = client.get('/api/v1/documents/doc_fixture')
        assert unchanged.headers['etag'] == document_etag
        reuse = {'source': {'kind': 'pdf_upload', 'upload_id': receipt.json()['id']}, 'document_id': 'doc_fixture', 'source_language': 'en'}
        denied = client.post('/api/v1/imports', json=reuse, headers={'Idempotency-Key': 'reuse-needs-choice'})
        assert denied.status_code == 428
        reused = client.post('/api/v1/imports', json=reuse,
            headers={'If-Match': unchanged.headers['etag'], 'Idempotency-Key': 'explicit-reuse'})
        assert reused.status_code == 201 and reused.json()['source_revision_id'] == 'src_fixture'
        assert reused.json()['editions'][0]['current_artifact_id'] == old_artifact
        document_etag = reused.headers['etag']
    profile = configure(monkeypatch, tmp_path)
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 1_000_000
        old_revision = session.get(Artifact, old_artifact).translation_revision_id
    copied_zh = client.post('/api/v1/editions/edition_fixture/drafts', json={'translation_revision_id': old_revision},
        headers={'If-Match': '"2"', 'Idempotency-Key': 'zh-comparison-draft'})
    assert copied_zh.status_code == 201, copied_zh.text
    from tests.integration.test_persistent_cache_jobs import candidate_job
    zh_provider = FakeProvider()
    zh_candidate = candidate_job(client, db, cfg, copied_zh.json()['id'], 'doc_fixture',
        profile, zh_provider, 'zh-comparison-cache')
    assert len(zh_provider.calls) == 1
    with db.transaction() as session:
        zh_cache = {row.key: row.value for row in session.scalars(select(TranslationCache))}
        assert len(zh_cache) == 1
    public = client.get('/api/v1/settings/provider').json()
    assert public['profile_hash'] == digest(profile) and public['language_policy'] == 'all' and 'experimental_locales' not in public
    body = {'target_locale': locale.upper(), 'source_revision_id': 'src_fixture', 'profile_hash': public['profile_hash']}
    created = client.post('/api/v1/documents/doc_fixture/editions', json=body,
        headers={'If-Match': document_etag, 'Idempotency-Key': 'language-create'})
    assert created.status_code == 201 and created.json()['target_locale'] == locale and 'experimental' not in created.json(), created.text
    eid = created.json()['id']
    preflight = client.get(f'/api/v1/editions/{eid}/preflight').json()
    assert preflight['can_translate'] and 'requires_experimental_confirmation' not in preflight
    translation = {'source_revision_id': 'src_fixture', 'source_hash': preflight['source_hash'],
        'profile_revision': profile['profile_revision'], 'profile_hash': preflight['profile_hash'], 'budget_micro': 1_000_000,
        'external_processing_confirmed': True, 'publish_policy': 'manual_approval'}
    for index, (change, error) in enumerate([({'external_processing_confirmed': False}, 'EXTERNAL_PROCESSING_UNCONFIRMED'),
            ({'profile_hash': '0' * 64}, 'PROFILE_STALE')]):
        refused = client.post(f'/api/v1/editions/{eid}/translate', json=translation | change,
            headers={'If-Match': '"1"', 'Idempotency-Key': f'experiment-denied-{index}'})
        assert refused.status_code == 409 and refused.json()['error']['code'] == error, refused.text
    with db.transaction() as session:
        assert not list(session.scalars(select(Job).where(Job.stage == 'translate')))
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 1_000_000
    started = client.post(f'/api/v1/editions/{eid}/translate', json=translation,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'experiment-translate'})
    assert started.status_code == 202 and 'experimental' not in started.json(), started.text
    did = started.json()['draft_id']
    provider = FakeProvider()
    key_file = tmp_path / 'test-key-never-sent'
    key_file.write_text('TEST_ONLY')
    monkeypatch.setenv('PROVIDER_KEY_FILE', str(key_file))
    monkeypatch.setattr('packages.translation.execution.OpenAIResponses', lambda key: provider)
    while lease := claim(db):
        execute_translation(db, cfg, lease)
    draft = client.get(f'/api/v1/drafts/{did}')
    assert draft.status_code == 200 and 'experimental' not in draft.json() and draft.json()['target_locale'] == locale
    with db.transaction() as session:
        saved = session.get(Draft, did)
        assert 'language_authorization' not in saved.profile
        assert saved.profile['enabled_pairs'] == profile['enabled_pairs'] == [['en', 'zh-Hans']]
        assert all(t.kind != 'parse' for t in session.scalars(select(Task)))
        assert session.scalar(select(func.count()).select_from(SourceRevision)) == 1
        assert session.scalar(select(func.count()).select_from(SourceDraft)) == 0
        assert session.get(Edition, 'edition_fixture').current_artifact_id == old_artifact
        other_locale_p1 = session.scalar(select(Task).where(Task.job_id == started.json()['job_id'],
            Task.payload['unit']['owner_block_id'].astext == 'p1'))
        assert other_locale_p1.result['cache_hit'] is False
        assert zh_cache == {key: session.get(TranslationCache, key).value for key in zh_cache}
        assert len(list(session.scalars(select(TranslationCache)))) > len(zh_cache)
    qa = client.post(f'/api/v1/drafts/{did}/validate', json={}, headers={'If-Match': draft.headers['etag'], 'Idempotency-Key': 'experiment-qa'})
    assert qa.json()['valid'], qa.text
    sealed = client.post(f'/api/v1/drafts/{did}/seal', json={'qa_id': qa.json()['id'], 'qa_fingerprint': qa.json()['fingerprint'],
        'generation': draft.json()['generation']}, headers={'If-Match': draft.headers['etag'], 'Idempotency-Key': 'experiment-seal'})
    assert sealed.status_code == 201, sealed.text
    published = client.post(f'/api/v1/editions/{eid}/publish', json={'translation_revision_id': sealed.json()['id'], 'expected_generation': 2},
        headers={'If-Match': '"2"', 'Idempotency-Key': 'experiment-publish'})
    assert published.status_code == 202, published.text
    assert 'experimental' not in client.get('/api/v1/jobs/' + published.json()['job_id']).json()
    execute(db, cfg, claim(db))
    with db.transaction() as session:
        revision = session.get(TranslationRevision, sealed.json()['id'])
        assert revision.language_authorization == {}
        frozen = read_snapshot(cfg.data, revision)
        assert not any('实验语言' in note for row in frozen['results'] for note in row['warnings'])
        artifact = session.get(Artifact, session.get(Edition, eid).current_artifact_id)
        html = (cfg.data / artifact.storage_key / 'index.html').read_text(encoding='utf-8')
        assert '实验语言' not in html and f'lang="{locale}"' in html
        assert f'English / {language_name(locale)}' in html
        assert artifact.id != old_artifact and session.get(Edition, 'edition_fixture').current_artifact_id == old_artifact
        assert session.get(Edition, 'edition_fixture').target_locale == 'zh-Hans'
        artifact_id = artifact.id
    for format in ('single_html', 'bundle'):
        queued = client.post(f'/api/v1/artifacts/{artifact_id}/exports', json={'format': format, 'include_source': False},
            headers={'Idempotency-Key': 'experiment-export-' + format})
        assert queued.status_code == 202, queued.text
        drain(db, cfg)
        exported = client.get('/api/v1/exports/' + queued.json()['id'] + '/download')
        assert exported.status_code == 200
        text = exported.text if format == 'single_html' else zipfile.ZipFile(io.BytesIO(exported.content)).read('index.html').decode('utf-8')
        assert '实验语言' not in text
    copied = client.post(f'/api/v1/editions/{eid}/drafts', json={'translation_revision_id': sealed.json()['id']},
        headers={'If-Match': '"3"', 'Idempotency-Key': 'experiment-new-draft'})
    assert copied.status_code == 201 and 'experimental' not in copied.json(), copied.text
    assert file_hash(old_path) == old_hash


def test_renamed_duplicate_explicit_reuse_then_new_locale_preserves_old_publication(client, database, monkeypatch, tmp_path):
    test_all_languages_reuse_source_and_publish_without_language_consent(
        client, database, monkeypatch, tmp_path, 'ja', renamed_reuse=True)


def test_same_revision_changed_price_is_rejected_before_any_paid_task(client, database, monkeypatch, tmp_path):
    from tests.integration.test_edition_translation import prepared
    body = prepared(client, database, monkeypatch, tmp_path)
    path = tmp_path / 'profile.json'
    changed = json.loads(path.read_text())
    changed['price']['output_micro_per_million'] += 1
    path.write_text(json.dumps(changed))
    refused = client.post('/api/v1/editions/new_edition/translate', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'same-revision-price-change'})
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'PROFILE_STALE'
    with database[0].transaction() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize('source_language,target', [('ko', 'ar'), ('fr', 'pt-BR')])
def test_import_all_languages_can_auto_publish_and_review_with_no_pair_allowlist(client, database, monkeypatch, tmp_path, source_language, target):
    from packages.domain.models import Document
    from packages.ir import block_hash
    db, cfg = database
    seed_editor(db, cfg)
    profile = configure(monkeypatch, tmp_path, locales=()) | {'semantic_review_enabled': True}
    (tmp_path / 'profile.json').write_text(json.dumps(profile), encoding='utf-8')
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
        source = read_snapshot(cfg.data, session.get(SourceRevision, 'src_fixture'))
        source['language'] = 'und'
        for block in source['blocks']:
            block['language'] = 'und'
            block['source_hash'] = block_hash(block, source['protected_atoms'])
        session.add(SourceDraft(id='language_source', document_id='doc_fixture', asset_id='source_pdf',
            source=source, coverage={'can_translate': True, 'unresolved': []}, evidence={}))
    body = {'source_hash': digest(source), 'source_language': source_language, 'preflight_generation': 1,
        'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile), 'locale': target,
        'budget_micro': 1_000_000, 'external_processing_confirmed': True, 'publish_policy': 'auto_publish'}
    started = client.post('/api/v1/imports/language_source/confirm', json=body,
        headers={'If-Match': '"1"', 'Idempotency-Key': 'all-language-import'})
    assert started.status_code == 202, started.text
    provider = FakeProvider()
    while lease := claim(db):
        if lease.kind == 'translate':
            execute_translation(db, cfg, lease, provider)
        else:
            execute(db, cfg, lease)
    assert provider.calls and all(unit['source_language'] == source_language and unit['target_locale'] == target
        for units in provider.calls for unit in units)
    with db.transaction() as session:
        edition = session.get(Edition, started.json()['edition_id'])
        assert edition.current_artifact_id
        assert session.get(Job, started.json()['job_id']).status == 'succeeded'
        assert session.get(Document, 'doc_fixture').source_language == source_language
    draft = client.get('/api/v1/drafts/' + started.json()['draft_id'])
    request = {'block_ids': ['p1'], 'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile),
        'glossary_revision': 'empty-v1', 'budget_micro': 1_000_000, 'external_processing_confirmed': True}
    for operation in ('candidates', 'semantic-review'):
        result = client.post(f'/api/v1/drafts/{draft.json()["id"]}/{operation}', json=request,
            headers={'If-Match': draft.headers['etag'], 'Idempotency-Key': operation})
        assert result.status_code == 202, result.text
