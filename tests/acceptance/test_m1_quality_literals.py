"""Mixed QA scenarios; actual PDF negation, explicit authored targets, no Provider."""
import copy
import json
from pathlib import Path
import shutil
import uuid

import pytest
from sqlalchemy import func, select

from packages.domain.models import Document, Draft, Edition, QA, ReviewRecord, SegmentVersion, SourceAsset, SourceRevision, TranslationRevision
from packages.editorial.drafts import context_hash, current_segments, quality_fingerprint, semantic_evidence
from packages.ir import digest
from packages.storage import file_hash, read_snapshot, write_snapshot
from tests.support import seed_editor

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]


def save_evidence(name, value):
    path = ROOT / '.agent/tmp/evidence/quality-literals' / uuid.uuid4().hex
    path.mkdir(parents=True)
    (path / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def qa(client, draft_id, generation=1, key='qa'):
    result = client.post(f'/api/v1/drafts/{draft_id}/validate', json={},
        headers={'If-Match': f'"{generation}"', 'Idempotency-Key': key})
    assert result.status_code == 200, result.text
    return result.json()


def seal(client, draft_id, quality, generation=1, key='seal'):
    return client.post(f'/api/v1/drafts/{draft_id}/seal', json={'qa_id': quality['id'],
        'qa_fingerprint': quality['fingerprint'], 'generation': generation},
        headers={'If-Match': f'"{generation}"', 'Idempotency-Key': key})


def test_correct_authored_targets_and_declared_original_figure_bind_qa_and_seal(client, database):
    db, cfg = database; ir = seed_editor(db, cfg); source = ir['source_revision']
    original_assets = {a['storage_key']: file_hash(cfg.data / a['storage_key']) for a in source['assets']}
    quality = qa(client, 'draft_fixture')
    assert quality['valid']
    with db.transaction() as session:
        draft = session.get(Draft, 'draft_fixture'); segments = current_segments(session, draft.id)
        assert quality['fingerprint'] == quality_fingerprint(draft, source, segments, semantic_evidence(session, draft, source, segments))
        assert session.get(QA, quality['id']).draft_generation == draft.generation
        assert session.scalar(select(func.count()).select_from(ReviewRecord)) == 0
    state = client.get('/api/v1/drafts/draft_fixture').json()
    assert all(s['review_status'] != 'human_reviewed' for s in state['segments'])
    sealed = seal(client, 'draft_fixture', quality)
    assert sealed.status_code == 201, sealed.text
    with db.transaction() as session:
        revision = session.get(TranslationRevision, sealed.json()['id']); translation = read_snapshot(cfg.data, revision)
        assert revision.qa_fingerprint == quality['fingerprint'] and revision.source_revision_id == 'src_fixture'
        figure = next(r for r in translation['results'] if r['block_id'] == 'fig')
        assert figure['status'] == 'retained' and figure['reason'] == 'original_figure' and figure['target_inline'] == []
    assert all(file_hash(cfg.data / key) == sha for key, sha in original_assets.items())
    # A new actual target revision invalidates the earlier bound QA approval.
    changed = client.patch('/api/v1/drafts/draft_fixture/segments/item', json={'base_segment_version': 1,
        'reason': 'Controlled subsequent wording revision', 'target_inline': [{'type': 'text', 'text': '请保留原件。'}]},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'new-wording'})
    assert changed.status_code == 200
    stale = seal(client, 'draft_fixture', quality, changed.json()['generation'], 'stale-quality')
    assert stale.status_code == 201
    save_evidence('correct-original-figure', {'scope': 'Hand-authored IR and targets, original sample PDF/image; not parser gold or Provider quality',
        'fixture': 'fixtures/sample-document.json', 'fixture_sha256': file_hash(ROOT / 'tests/fixtures/sample-document.json'),
        'source_hash': digest(source), 'qa': quality, 'figure_result': figure, 'assets_sha256': original_assets,
        'sealed_translation_sha256': digest(translation), 'later_target_edit_refreshes_old_qa': True, 'provider_requests': 0})


def test_missing_original_figure_is_hard(client, database):
    db, cfg = database; ir = seed_editor(db, cfg); source = ir['source_revision']
    original_figure_hash = file_hash(ROOT / 'tests/fixtures/figure.png')
    assert qa(client, 'draft_fixture')['valid']
    (cfg.data / 'fixtures/figure.png').unlink()  # Only the copied per-test data volume.
    quality = qa(client, 'draft_fixture', key='qa-missing-figure')
    issue = next(i for i in quality['issues'] if i['code'] == 'IMAGE_UNAVAILABLE')
    assert issue['severity'] == 'general' and issue['blocking'] is False
    denied = seal(client, 'draft_fixture', quality)
    assert denied.status_code == 201
    assert file_hash(ROOT / 'tests/fixtures/figure.png') == original_figure_hash
    save_evidence('missing-image', {'scope': 'Missing local copy, original fixture unchanged', 'source_hash': digest(source),
        'original_figure_sha256': original_figure_hash, 'qa': quality, 'provider_requests': 0})


def test_actual_pdf_negation_risk_remains_visible_without_required_review_or_self_score_approval(client, database):
    corpus = ROOT / '.agent/tmp/evidence/live-provider-final-en'
    if not (corpus / 'result.json').is_file():pytest.skip('Requires actual controlled-English offline Docling output.')
    actual = json.loads((corpus / 'result.json').read_text(encoding='utf8')); source = actual['source_revision']
    assert actual['coverage']['can_translate'] and file_hash(corpus / 'original.pdf') == source['sha256']
    block = next(b for b in source['blocks'] if b['id'] == 'b2')
    assert block['normalized_text'] == 'Do not send a second request if the first result is unknown.'
    wrong = '若第一次结果未知，就发送第二次请求。'
    db, cfg = database; shutil.copy2(corpus / 'original.pdf', cfg.data / 'original.pdf')
    source_key = 'source.json'; source_hash = write_snapshot(cfg.data, source_key, source)
    with db.transaction() as session:
        asset = source['assets'][0]
        session.add(SourceAsset(id=asset['id'], sha256=asset['sha256'], byte_size=asset['byte_size'], page_count=1, storage_key='original.pdf')); session.flush()
        session.add(Document(id='negation-doc', title='Original negation check', source_asset_id=asset['id'], current_source_id=source['id'])); session.flush()
        session.add(SourceRevision(id=source['id'], document_id='negation-doc', asset_id=asset['id'], snapshot_hash=source_hash, storage_key=source_key))
        session.add(Edition(id='negation-edition', document_id='negation-doc', target_locale='zh-Hans', current_draft_id='negation-draft')); session.flush()
        session.add(Draft(id='negation-draft', document_id='negation-doc', edition_id='negation-edition', source_revision_id=source['id'])); session.flush()
        for b in source['blocks']:
            session.add(SegmentVersion(id='negation-segment-' + b['id'], draft_id='negation-draft', block_id=b['id'], sequence=1,
                target_inline=[{'type': 'text', 'text': wrong}] if b['id'] == 'b2' else copy.deepcopy(b['source_inline']),
                source_hash=b['source_hash'], context_hash=context_hash(source, b['id']), origin='model',
                provenance_json={'model_self_score': 1.0, 'claims_reviewed': True, 'kind': 'model'}, reason='Explicit authored adversarial QA fixture; no Provider request'))
    quality = qa(client, 'negation-draft')
    issue = next(i for i in quality['issues'] if i['block_id'] == 'b2' and i['code'] == 'SEMANTIC_RISK')
    assert issue['severity'] == 'important' and not issue['resolved'] and not issue['blocking']
    sealed = seal(client, 'negation-draft', quality)
    assert sealed.status_code == 201, sealed.text
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ReviewRecord)) == 0
        assert session.scalar(select(func.count()).select_from(TranslationRevision)) == 1
        revision = session.get(TranslationRevision, sealed.json()['id'])
        result = next(r for r in read_snapshot(cfg.data, revision)['results'] if r['block_id'] == 'b2')
        assert result['review_state'] == 'not_reviewed' and result['review_record'] is None
        assert any('条件、否定或数量关系' in note for note in result['warnings'])
    assert file_hash(cfg.data / source_key) == source_hash and file_hash(cfg.data / 'original.pdf') == source['sha256']
    save_evidence('actual-negation', {'scope': 'Actual original PDF/Docling text plus deliberately authored mistranslation, not a live Provider result',
        'original_pdf': 'fixtures/live-provider/controlled-en.pdf', 'original_pdf_sha256': source['sha256'],
        'actual_parser_result_sha256': file_hash(corpus / 'result.json'), 'source_hash': source_hash,
        'source_quote': block['normalized_text'], 'source_provenance': block['provenance'],
        'incorrect_target': wrong, 'correct_meaning': '如果第一次请求的结果未知，不要发送第二次请求。',
        'qa': quality, 'model_self_score': 1.0, 'review_records': 0, 'sealed_revisions': 1, 'provider_requests': 0})
