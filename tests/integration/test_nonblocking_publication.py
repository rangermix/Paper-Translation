"""NB-AT09/10: quality findings and absent QA cannot prevent safe publication."""
from sqlalchemy import delete

from packages.domain.models import Draft, SegmentVersion
from packages.editorial.drafts import edit_segment, run_quality, seal
from packages.ir import validate_ir
from packages.storage import read_snapshot
from tests.support import seed_editor


def test_missing_and_numeric_differences_seal_as_explicit_partial_result(database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        draft = session.get(Draft, 'draft_fixture')
        session.execute(delete(SegmentVersion).where(SegmentVersion.draft_id == draft.id, SegmentVersion.block_id == 'p2'))
        edit_segment(session, cfg, draft, 'p1', [{'type': 'text', 'text': '数字 999，待对照原文。'}], 1, 'Controlled numeric mismatch')
        qa = run_quality(session, cfg, draft)
        assert any(issue['code'] == 'NUMBER_MISMATCH' for issue in qa.issues)
        revision = seal(session, cfg, draft, qa.id, qa.fingerprint)
        snapshot = read_snapshot(cfg.data, revision)
        assert snapshot['content_policy'] == 'nonblocking-v1'
        missing = next(row for row in snapshot['results'] if row['block_id'] == 'p2')
        assert missing['status'] == 'fallback' and missing['target_inline'] == []
        changed = next(row for row in snapshot['results'] if row['block_id'] == 'p1')
        assert changed['status'] == 'translated' and changed['warnings']


def test_missing_qa_and_stale_qa_are_refreshed_automatically(database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        draft = session.get(Draft, 'draft_fixture')
        first = seal(session, cfg, draft, None, None)
        assert first.qa_fingerprint
        old_qa = run_quality(session, cfg, draft)
        edit_segment(session, cfg, draft, 'p1', [{'type': 'text', 'text': '新版本数字 100。'}], 1, 'New content')
        second = seal(session, cfg, draft, old_qa.id, old_qa.fingerprint)
        assert second.qa_fingerprint != old_qa.fingerprint


def test_unsafe_legacy_target_becomes_fallback_not_raw_html(database):
    db, cfg = database
    seed_editor(db, cfg)
    with db.transaction() as session:
        draft = session.get(Draft, 'draft_fixture')
        session.add(SegmentVersion(id='unsafe_history', draft_id=draft.id, block_id='p1', sequence=2,
            target_inline=[{'type': 'html', 'html': '<script>unsafe</script>'}], source_hash='a' * 64,
            context_hash='b' * 64, origin='model', reason='Controlled corrupt historical target'))
        session.flush()
        result = seal(session, cfg, draft, None, None)
        snapshot = read_snapshot(cfg.data, result)
        row = next(row for row in snapshot['results'] if row['block_id'] == 'p1')
        assert row['status'] == 'fallback' and row['target_inline'] == []
        assert '<script>' not in str(snapshot)
