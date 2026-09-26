"""Literal 100-block/98-locked workflow; FakeProvider proves isolation, not fluency."""
import copy
import json
from pathlib import Path
import shutil

import pytest
from sqlalchemy import select

from packages.domain.models import (Candidate, Document, Draft, Edition, ReviewRecord,
    SegmentVersion, Settings, SourceAsset, SourceRevision, Task, new_id)
from packages.editorial.drafts import context_hash, current_review, current_segments, segment_fingerprint
from packages.ir import digest, validate_source
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.storage import write_snapshot
from packages.translation.execution import execute_translation
from tests.integration.test_edition_translation import configure

pytestmark = pytest.mark.postgres


def test_candidate_api_worker_accept_preserves_98_locked_blocks(client, database, monkeypatch, tmp_path):
    db, cfg = database
    profile = configure(monkeypatch, tmp_path)
    fixture = json.loads(Path('tests/fixtures/sample-document.json').read_text('utf-8'))
    source = fixture['source_revision']
    paragraph = next(b for b in source['blocks'] if b['id'] == 'p1')
    blocks = [source['blocks'][0]]
    for index in range(99):
        block = copy.deepcopy(paragraph)
        block.update(id=f'para{index}', order=index + 1)
        blocks.append(block)
    source['blocks'] = blocks
    source['reading_order'] = [b['id'] for b in blocks]
    for asset in source['assets']:
        target = cfg.data / asset['storage_key']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path('tests') / asset['storage_key'], target)
    validate_source(source, asset_root=cfg.data)
    key = 'hundred-source.json'
    sha = write_snapshot(cfg.data, key, source)
    selected = {'para0', 'para1'}
    with db.transaction() as session:
        settings = session.get(Settings, 'singleton')
        settings.dispatch_disabled, settings.instance_budget_micro = False, 10_000_000
        original = next(a for a in source['assets'] if a['id'] == source['original_asset_id'])
        session.add(SourceAsset(id=original['id'], sha256=source['sha256'],
            byte_size=original['byte_size'], page_count=1, storage_key=original['storage_key']))
        session.flush()
        session.add(Document(id='hundred', title='Controlled hundred-block behavior test',
            source_asset_id=original['id'], current_source_id=source['id'], source_language='en'))
        session.flush()
        session.add(SourceRevision(id=source['id'], document_id='hundred', asset_id=original['id'],
            snapshot_hash=sha, storage_key=key))
        session.add(Edition(id='hundred_edition', document_id='hundred', target_locale='zh-Hans', current_draft_id='hundred_draft'))
        session.flush()
        draft = Draft(id='hundred_draft', document_id='hundred', edition_id='hundred_edition', source_revision_id=source['id'], profile=profile)
        session.add(draft)
        session.flush()
        for block in blocks:
            segment = SegmentVersion(id=new_id('seg'), draft_id=draft.id, block_id=block['id'], sequence=1,
                source_hash=block['source_hash'], context_hash=context_hash(source, block['id']),
                target_inline=copy.deepcopy(block['source_inline']), origin='manual_ui', reason='Authored test state')
            session.add(segment)
            session.flush()
            if block['id'] not in selected:
                session.add(ReviewRecord(id=new_id('review'), draft_id=draft.id, block_id=block['id'], segment_version=1,
                    fingerprint=segment_fingerprint(draft, segment), origin='manual_ui', reason='Authored test review marker, not source acceptance'))
        session.flush()
        before = {s.block_id: (s.id, digest(s.target_inline), s.sequence) for s in current_segments(session, draft.id).values()}
        reviews = {r.id: r.fingerprint for r in session.scalars(select(ReviewRecord))}
        assert len(before) == 100 and len(reviews) == 98
    created_glossary = client.post('/api/v1/glossaries/revisions', json={'scope': 'document', 'document_id': 'hundred',
        'source_language': 'en', 'target_language': 'zh-Hans',
        'entries': [{'source': 'tokens', 'target': '词元', 'mode': 'must', 'variants': []}]},
        headers={'Idempotency-Key': 'hundred-new-glossary'})
    assert created_glossary.status_code == 201, created_glossary.text
    preview = client.post('/api/v1/glossaries/' + created_glossary.json()['id'] + '/impact',
        json={'document_id': 'hundred'}, headers={'Idempotency-Key': 'hundred-impact'})
    assert preview.status_code == 200, preview.text
    assert preview.json()['provider_calls'] == 0
    impacted = {row['block_id']: row for row in preview.json()['items']}
    assert set(impacted) == set(before) - {'title'}
    assert {bid for bid, row in impacted.items() if row['locked']} == set(before) - selected - {'title'}
    assert all(row['matched_terms'] == ['tokens'] for row in impacted.values())
    # A new terminology revision only warns about existing reviewed text. Its
    # old review continues to describe the old terminology fingerprint.
    with db.transaction() as session:
        assert session.get(Draft, 'hundred_draft').glossary_revision == 'empty-v1'
        assert reviews == {r.id: r.fingerprint for r in session.scalars(select(ReviewRecord))}
        assert before == {s.block_id: (s.id, digest(s.target_inline), s.sequence)
                          for s in current_segments(session, 'hundred_draft').values()}
    terms = client.get('/api/v1/glossaries/effective', params={'document_id': 'hundred', 'source_language': 'en', 'target_language': 'zh-Hans'}).json()
    started = client.post('/api/v1/drafts/hundred_draft/candidates', json={'block_ids': sorted(selected),
        'profile_revision': profile['profile_revision'], 'profile_hash': digest(profile), 'glossary_revision': terms['revision'],
        'budget_micro': 10_000_000, 'external_processing_confirmed': True},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'hundred-two-only'})
    assert started.status_code == 202, started.text
    provider = FakeProvider()
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    with db.transaction() as session:
        assert before == {s.block_id: (s.id, digest(s.target_inline), s.sequence) for s in current_segments(session, 'hundred_draft').values()}
        candidate = session.get(Candidate, started.json()['id'])
        assert set(candidate.results) == selected and candidate.status == 'ready'
        candidate_etag = f'"{candidate.generation}"'
        tasks = list(session.scalars(select(Task).where(Task.job_id == candidate.job_id)))
        assert {t.payload['unit']['owner_block_id'] for t in tasks if 'unit' in t.payload} == selected
    # Identical source/context may reuse a validated cache entry. Neither a
    # real dispatch nor a cache hit may touch the other 98 locked paragraphs.
    sent = {u['owner_block_id'] for call in provider.calls for u in call}
    assert sent and sent <= selected
    accepted = client.post('/api/v1/candidates/' + started.json()['id'] + '/accept', json={'block_ids': sorted(selected)},
        headers={'If-Match': candidate_etag, 'Idempotency-Key': 'hundred-explicit-accept'})
    assert accepted.status_code == 200, accepted.text
    with db.transaction() as session:
        draft = session.get(Draft, 'hundred_draft')
        segments = current_segments(session, draft.id)
        assert len(segments) == 100
        assert {bid for bid, segment in segments.items() if current_review(session, draft, segment)} == before.keys() - selected
        assert reviews == {r.id: r.fingerprint for r in session.scalars(select(ReviewRecord))}
        for bid, segment in segments.items():
            if bid in selected:
                assert segment.sequence == 2 and segment.origin == 'candidate_accepted'
                assert segment.provenance_json['glossary_revision'] == terms['revision']
            else:
                assert (segment.id, digest(segment.target_inline), segment.sequence) == before[bid]
                assert segment.provenance_json.get('glossary_revision', draft.glossary_revision) == 'empty-v1'
