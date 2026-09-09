"""Long authored IR paragraph exercises real planner/worker boundaries, not parser gold."""
import copy
from collections import Counter

import pytest
from sqlalchemy import select

from packages.domain.models import Document, Draft, Job, SegmentVersion, SourceRevision, Task
from packages.ir import block_hash, digest, flatten_inline, validate_source
from packages.jobs.queue import claim
from packages.providers.fake import FakeProvider
from packages.storage import read_snapshot, write_snapshot
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import PROFILE, setup_library

pytestmark = pytest.mark.postgres


def test_long_paragraph_keeps_formula_whole_and_source_boundary_unchanged(database):
    db, cfg = database
    source = copy.deepcopy(setup_library(db, cfg))
    source['id'] = 'src_long_formula'
    paragraph = next(b for b in source['blocks'] if b['id'] == 'p1')
    formula = source['protected_atoms']['formula1']
    assert formula['kind'] == 'math'
    # Position the formula after enough prose to span multiple ordinary units,
    # near a boundary where splitting its characters would be incorrect.
    prefix = 'This controlled long paragraph preserves its mathematical expression. ' * 145
    suffix = ' The subsequent argument remains part of the same source paragraph.' * 100
    paragraph['source_inline'] = [{'type': 'text', 'text': prefix},
        {'type': 'protected_ref', 'ref': 'formula1'}, {'type': 'text', 'text': suffix}]
    paragraph['raw_text'] = paragraph['normalized_text'] = flatten_inline(paragraph['source_inline'], source['protected_atoms'])
    paragraph['normalization_edits'] = []
    paragraph['source_hash'] = block_hash(paragraph, source['protected_atoms'])
    assert len(paragraph['normalized_text']) > 5 * PROFILE['max_unit_characters']
    validate_source(source, asset_root=cfg.data)
    key = 'documents/doc/sources/src_long_formula/document.json'
    sha = write_snapshot(cfg.data, key, source)
    with db.transaction() as session:
        session.add(SourceRevision(id=source['id'], document_id='doc', asset_id=source['original_asset_id'],
            snapshot_hash=sha, storage_key=key))
        session.flush()
        session.get(Document, 'doc').current_source_id = source['id']
        session.get(Draft, 'draft').source_revision_id = source['id']
        job = session.get(Job, 'job')
        job.payload = job.payload | {'source_revision_id': source['id'], 'source_hash': sha, 'block_ids': ['p1']}
    original_snapshot = (cfg.data / key).read_bytes()
    original_assets = {a['storage_key']: digest((cfg.data / a['storage_key']).read_bytes()) for a in source['assets']}
    provider = FakeProvider()
    execute_translation(db, cfg, claim(db), provider)
    with db.transaction() as session:
        units = [t.payload['unit'] for t in session.scalars(select(Task)) if 'unit' in t.payload]
        assert len(units) > 5
        assert len({unit['unit_id'] for unit in units}) == len(units)
        assert {unit['owner_block_id'] for unit in units} == {'p1'}
        assert sorted(unit['unit_order'] for unit in units) == list(range(len(units)))
        atoms = [unit['protected_atoms'] for unit in units if unit['protected_atoms']]
        assert atoms == [{'formula1': formula}]
        assert ''.join(flatten_inline(u['source_inline'], u['protected_atoms'])
            for u in sorted(units, key=lambda u: u['unit_order'])) == paragraph['normalized_text']
    while lease := claim(db):
        execute_translation(db, cfg, lease, provider)
    with db.transaction() as session:
        segments = list(session.scalars(select(SegmentVersion)))
        assert len(segments) == 1 and segments[0].block_id == 'p1'
        assert Counter(n['ref'] for n in segments[0].target_inline if n['type'] == 'protected_ref') == {'formula1': 1}
        assert flatten_inline(segments[0].target_inline, source['protected_atoms']) == paragraph['normalized_text']
        assert read_snapshot(cfg.data, session.get(SourceRevision, source['id'])) == source
        progress = session.get(Job, 'job').progress
        assert progress['verified_blocks'] == 1 and progress['verified_units'] == len(units)
    # Repeated identical text can legitimately hit same-input unit cache, but
    # every original unit still completes once with exactly one final segment.
    assert 0 < len(provider.calls) <= len(units)
    assert (cfg.data / key).read_bytes() == original_snapshot
    assert original_assets == {a['storage_key']: digest((cfg.data / a['storage_key']).read_bytes()) for a in source['assets']}
