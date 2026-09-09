"""Terminology and explicit human memory contracts, written before implementation."""
import pytest
from sqlalchemy import select

from packages.domain.errors import DomainError
from packages.domain.models import Document, Glossary, TranslationMemory, now
from packages.glossaries import effective_glossary, merge_entries, term_matches
from tests.support import seed_editor


def entry(source, target, mode='must', **extra):
    return {'source': source, 'target': target, 'mode': mode, 'variants': [], **extra}


def test_english_boundaries_cjk_substrings_case_and_regex_literals():
    assert term_matches('The GPU is fast.', entry('GPU', '显卡'))
    assert not term_matches('The GPUs are fast.', entry('GPU', '显卡'))
    assert term_matches('the gpu is fast', entry('GPU', '显卡'))
    assert not term_matches('the gpu is fast', entry('GPU', '显卡', case_sensitive=True))
    assert term_matches('这是分布式计算系统', entry('分布式计算', 'distributed computing'))
    assert not term_matches('anything', entry('.*', 'unsafe'))
    assert term_matches('Literal .* text', entry('.*', 'literal'))


def test_document_override_and_same_level_conflicts():
    global_terms = [entry('token', '标记')]
    local_terms = [entry('token', '词元')]
    assert merge_entries(global_terms, local_terms)[0]['target'] == '词元'
    with pytest.raises(DomainError, match='conflict'):
        merge_entries([entry('token', '标记'), entry('TOKEN', '词元')], [])
    with pytest.raises(DomainError):
        merge_entries([entry('token', '标记', 'must'), entry('token', '标记', 'forbidden')], [])


def test_glossary_revision_and_impact_are_immutable_and_no_model(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    created = client.post('/api/v1/glossaries/revisions', json={'source_language': 'en', 'target_language': 'zh-Hans', 'scope': 'global', 'document_id': None, 'entries': [entry('tokens', '词元')]}, headers={'Idempotency-Key': 'glossary-one'})
    assert created.status_code == 201, created.text
    old = created.json()
    changed = client.post('/api/v1/glossaries/revisions', json={'source_language': 'en', 'target_language': 'zh-Hans', 'scope': 'document', 'document_id': 'doc_fixture', 'entries': [entry('tokens', 'token')]}, headers={'Idempotency-Key': 'glossary-local'})
    assert changed.status_code == 201, changed.text
    with db.transaction() as session:
        terms = effective_glossary(session, 'doc_fixture', 'en', 'zh-Hans')
        assert terms['entries'][0]['target'] == 'token'
        assert session.get(Glossary, old['id']).entries[0]['target'] == '词元'
    impact = client.post(f'/api/v1/glossaries/{changed.json()["id"]}/impact', json={'document_id': 'doc_fixture'}, headers={'Idempotency-Key': 'impact'})
    assert impact.status_code == 200, impact.text
    assert [x['block_id'] for x in impact.json()['items']] == ['p1']
    assert impact.json()['provider_calls'] == 0


def test_glossary_impact_does_not_transfer_old_review_to_reused_block_id(client, database):
    from packages.domain.models import Draft, ReviewRecord, SourceRevision
    from packages.editorial.drafts import current_segments, segment_fingerprint
    from packages.ir import block_hash, validate_source
    from packages.storage import write_snapshot

    db, cfg = database
    source = seed_editor(db, cfg)['source_revision']
    with db.transaction() as session:
        draft = session.get(Draft, 'draft_fixture')
        segment = current_segments(session, draft.id)['p1']
        fingerprint = segment_fingerprint(draft, segment)
        session.add(ReviewRecord(id='old_source_review', draft_id=draft.id, block_id='p1',
            segment_version=1, fingerprint=fingerprint, origin='manual_ui',
            reason='Authored marker bound to the previous source, not gold evidence'))
    terms = client.post('/api/v1/glossaries/revisions', json={'scope': 'document',
        'document_id': 'doc_fixture', 'source_language': 'en', 'target_language': 'zh-Hans',
        'entries': [entry('tokens', '词元')]}, headers={'Idempotency-Key': 'impact-source-terms'})
    assert terms.status_code == 201, terms.text
    url = '/api/v1/glossaries/' + terms.json()['id'] + '/impact'
    before = client.post(url, json={}, headers={'Idempotency-Key': 'impact-source-before'})
    assert before.status_code == 200 and before.json()['items'][0]['locked'] is True
    # A replacement source can reuse local block IDs. The previous edition
    # intentionally stays bound to its immutable old source until a new draft.
    source['id'] = 'src_replaced'
    paragraph = next(b for b in source['blocks'] if b['id'] == 'p1')
    paragraph.update(raw_text='A different sentence about tokens.',
        normalized_text='A different sentence about tokens.', normalization_edits=[],
        source_inline=[{'type': 'text', 'text': 'A different sentence about tokens.'}])
    paragraph['source_hash'] = block_hash(paragraph, source['protected_atoms'])
    validate_source(source, asset_root=cfg.data)
    key = 'documents/doc_fixture/sources/src_replaced/document.json'
    sha = write_snapshot(cfg.data, key, source)
    with db.transaction() as session:
        session.add(SourceRevision(id=source['id'], document_id='doc_fixture', asset_id='source_pdf',
            storage_key=key, snapshot_hash=sha))
        session.flush()
        session.get(Document, 'doc_fixture').current_source_id = source['id']
    after = client.post(url, json={}, headers={'Idempotency-Key': 'impact-source-after'})
    assert after.status_code == 200, after.text
    assert after.json()['items'][0]['source_text'] == paragraph['normalized_text']
    assert after.json()['items'][0]['locked'] is False
    with db.transaction() as session:
        assert session.get(ReviewRecord, 'old_source_review').fingerprint == fingerprint
        assert session.get(Draft, 'draft_fixture').source_revision_id == 'src_fixture'


def test_memory_requires_current_human_review_and_never_changes_draft(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    body = {'draft_id': 'draft_fixture', 'block_id': 'p1', 'segment_version': 1, 'independent': False}
    denied = client.post('/api/v1/translation-memory', json=body, headers={'Idempotency-Key': 'memory-denied'})
    assert denied.status_code == 409
    draft = client.get('/api/v1/drafts/draft_fixture').json()
    segment = next(s for s in draft['segments'] if s['block_id'] == 'p1')
    reviewed = client.post('/api/v1/drafts/draft_fixture/segments/p1/confirm-review', json={'source_hash': segment['source_hash'], 'base_segment_version': 1, 'context_hash': segment['context_hash'], 'glossary_revision': 'empty-v1', 'reason': 'Checked original page 1'}, headers={'Idempotency-Key': 'memory-review', 'If-Match': '"1"'})
    assert reviewed.status_code == 200
    saved = client.post('/api/v1/translation-memory', json=body, headers={'Idempotency-Key': 'memory-save'})
    assert saved.status_code == 201, saved.text
    memory = saved.json()
    before = client.get('/api/v1/drafts/draft_fixture').json()
    found = client.get('/api/v1/translation-memory?q=The%20job%20has%2032%20tokens.').json()
    assert found['items'][0]['exact_match'] is False
    assert found['items'][0]['difference']
    assert client.get('/api/v1/drafts/draft_fixture').json() == before
    with db.transaction() as session:
        session.get(Document, 'doc_fixture').deleted_at = now()
    assert not client.get('/api/v1/translation-memory').json()['items']
    assert client.get(f'/api/v1/translation-memory/{memory["id"]}').status_code == 410


def test_explicit_independent_memory_survives_source_deletion_but_stale_write_fails(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        session.add(TranslationMemory(id='memory_fixture', document_id='doc_fixture', independent=False, source_language='en', target_language='zh-Hans', source_text='Checked sentence', target_inline=[{'type': 'text', 'text': '已核对句子'}], context_hash='a' * 64, evidence={'origin': 'manual_ui', 'protected_atoms': {}}))
    fetched = client.get('/api/v1/translation-memory/memory_fixture')
    copied = client.patch('/api/v1/translation-memory/memory_fixture', json={'independent': True}, headers={'Idempotency-Key': 'preserve-memory', 'If-Match': fetched.headers['etag']})
    assert copied.status_code == 200, copied.text
    # A second explicit write must have a new monotonically increasing version,
    # even though the boolean state itself remains true. A derived 1/2 ETag fails.
    preserved_again = client.patch('/api/v1/translation-memory/memory_fixture', json={'independent': True}, headers={'Idempotency-Key': 'preserve-memory-again', 'If-Match': copied.headers['etag']})
    assert preserved_again.status_code == 200, preserved_again.text
    assert preserved_again.json()['generation'] == copied.json()['generation'] + 1
    previous = client.delete('/api/v1/translation-memory/memory_fixture', headers={'Idempotency-Key': 'previous-memory', 'If-Match': copied.headers['etag']})
    assert previous.status_code == 412
    stale = client.delete('/api/v1/translation-memory/memory_fixture', headers={'Idempotency-Key': 'stale-memory', 'If-Match': fetched.headers['etag']})
    assert stale.status_code == 412
    with db.transaction() as session:
        session.get(Document, 'doc_fixture').deleted_at = now()
    assert client.get('/api/v1/translation-memory').json()['items'][0]['id'] == 'memory_fixture'
    assert client.delete('/api/v1/translation-memory/memory_fixture', headers={'Idempotency-Key': 'delete-memory', 'If-Match': preserved_again.headers['etag']}).status_code == 200
    with db.transaction() as session:
        assert not list(session.scalars(select(TranslationMemory)))


def test_independent_memory_retains_only_atoms_referenced_by_selected_block(client, database):
    from packages.domain.models import Draft, SourceRevision
    from packages.storage import write_snapshot

    db, cfg = database
    source = seed_editor(db, cfg)['source_revision']
    # This source has a selected paragraph containing n64 and a separate formula
    # block containing formula1. Add a private unused source atom as well: neither
    # belongs to the selected sentence's independently retained evidence.
    source['protected_atoms']['privateAtom'] = {'kind': 'math', 'value': 'private-formula-884219'}
    source['id'] = 'src_privacy_fixture'
    key = 'documents/doc_fixture/sources/src_privacy_fixture/document.json'
    snapshot_hash = write_snapshot(cfg.data, key, source)
    with db.transaction() as session:
        session.add(SourceRevision(id=source['id'], document_id='doc_fixture', asset_id='source_pdf', storage_key=key, snapshot_hash=snapshot_hash))
        session.flush()
        session.get(Draft, 'draft_fixture').source_revision_id = source['id']
    draft = client.get('/api/v1/drafts/draft_fixture').json()
    segment = next(s for s in draft['segments'] if s['block_id'] == 'p1')
    reviewed = client.post('/api/v1/drafts/draft_fixture/segments/p1/confirm-review', json={
        'source_hash': segment['source_hash'], 'base_segment_version': 1,
        'context_hash': segment['context_hash'], 'glossary_revision': 'empty-v1',
        'reason': 'Independently checked only this source paragraph'},
        headers={'Idempotency-Key': 'private-memory-review', 'If-Match': '"1"'})
    assert reviewed.status_code == 200, reviewed.text
    saved = client.post('/api/v1/translation-memory', json={
        'draft_id': 'draft_fixture', 'block_id': 'p1', 'segment_version': 1, 'independent': True},
        headers={'Idempotency-Key': 'private-memory-save'})
    assert saved.status_code == 201, saved.text
    memory = saved.json()
    assert memory['evidence']['protected_atoms'] == {'n64': {'kind': 'number', 'value': '64'}}
    assert '64' in memory['target_text']
    with db.transaction() as session:
        stored = session.get(TranslationMemory, memory['id'])
        assert set(stored.evidence['protected_atoms']) == {'n64'}
        session.get(Document, 'doc_fixture').deleted_at = now()
    independent = client.get(f'/api/v1/translation-memory/{memory["id"]}')
    assert independent.status_code == 200
    assert 'private-formula-884219' not in independent.text and 'formula1' not in independent.text
    assert independent.json()['target_text'] == memory['target_text']
