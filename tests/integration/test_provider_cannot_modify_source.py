"""M0-AT05B: hostile model response cannot mutate original source evidence."""
import copy

import pytest
from sqlalchemy import func, select

from packages.domain.models import Attempt, Job, Permit, SegmentVersion, SourceAsset, SourceRevision
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.storage import file_hash, read_snapshot
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import setup_library

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('source_field', ['source', 'source_inline', 'normalized_text'])
def test_model_source_rewrite_is_rejected_without_changing_original(database, source_field):
    db, cfg = database
    source = setup_library(db, cfg)
    with db.transaction() as session:
        asset = session.scalar(select(SourceAsset))
        revision = session.scalar(select(SourceRevision))
        original_path, revision_path = cfg.data / asset.storage_key, cfg.data / revision.storage_key
        before = (file_hash(original_path), file_hash(revision_path), copy.deepcopy(read_snapshot(cfg.data, revision)))
    def malicious(units):
        return {'results': [{'unit_id': unit['unit_id'], 'target_inline': unit['source_inline'],
            source_field: 'The model has rewritten the English original.'} for unit in units]}
    provider = FakeProvider([malicious])
    execute_translation(db, cfg, claim(db), provider)  # Internal planning, no model call.
    execute_translation(db, cfg, claim(db), provider)
    assert len(provider.calls) == 1
    with db.transaction() as session:
        revision = session.scalar(select(SourceRevision))
        after = (file_hash(original_path), file_hash(revision_path), read_snapshot(cfg.data, revision))
        assert before == after and after[2] == source
        assert session.scalar(select(func.count()).select_from(SourceRevision)) == 1
        assert session.scalar(select(func.count()).select_from(SegmentVersion)) == 0
        assert session.get(Job, 'job').error['code'] == 'PROVIDER_OUTPUT_SCHEMA'
        assert session.scalar(select(Permit)).state == 'settled'
        assert all(not attempt.output_hash for attempt in session.scalars(select(Attempt)))
