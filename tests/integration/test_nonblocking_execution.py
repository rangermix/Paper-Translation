"""Partial completion uses real queue/accounting; the transport is controlled."""
from sqlalchemy import select

from packages.domain.models import Job, Task, Permit, Draft, TranslationRevision
from packages.editorial.drafts import seal
from packages.jobs.queue import claim
from packages.providers.contract import ProviderFailure
from packages.providers.fake import FakeProvider
from packages.storage import read_snapshot
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import setup_library


def test_refused_unit_does_not_stop_remaining_units_or_auto_publication(database):
    db, cfg = database
    setup_library(db, cfg)
    with db.transaction() as session:
        job = session.get(Job, 'job')
        job.payload = job.payload | {'publish_policy': 'auto_publish'}
    class RefuseFirst(FakeProvider):
        def translate(self, *args):
            response = super().translate(*args)
            response['refusal'] = len(self.calls) == 1
            return response
    provider = RefuseFirst()
    while lease := claim(db):
        if lease.kind == 'publish':
            from workers.main import publish
            publish(db, cfg, lease)
        elif lease.kind == 'index':
            from packages.search import update_index
            update_index(db, cfg, lease)
        else:
            execute_translation(db, cfg, lease, provider)
    with db.transaction() as session:
        job = session.get(Job, 'job')
        assert job.status == 'partially_completed'
        assert len(provider.calls) > 1
        assert job.actual_model['kind'] == 'api'
        children = session.scalars(select(Job).where(Job.parent_job_id == job.id)).all()
        assert {'quality_check', 'publish'} <= {child.stage for child in children}
        published = next(child for child in children if child.stage == 'publish')
        assert published.status == 'partially_completed'
        assert published.actual_model['kind'] == 'none'
        revision = session.get(TranslationRevision, job.progress['translation_revision_id'])
        snapshot = read_snapshot(cfg.data, revision)
        assert any(row['status'] == 'fallback' for row in snapshot['results'])
        assert any(row['status'] == 'translated' for row in snapshot['results'])
        assert all(p.state == 'settled' for p in session.scalars(select(Permit)))


def test_checker_failure_is_recorded_and_safe_result_still_seals(database, monkeypatch):
    import packages.editorial.drafts as editorial
    from tests.support import seed_editor
    db, cfg = database
    seed_editor(db, cfg)
    def unavailable(*args, **kwargs):
        raise RuntimeError('Controlled checker failure; never log raw message')
    monkeypatch.setattr(editorial, '_run_quality', unavailable)
    with db.transaction() as session:
        revision = seal(session, cfg, session.get(Draft, 'draft_fixture'))
        assert read_snapshot(cfg.data, revision)['content_policy'] == 'nonblocking-v1'
        receipt = session.scalar(select(Job).where(Job.stage == 'quality_check'))
        assert receipt.status == 'failed' and receipt.finished_at
        assert receipt.quality_summary['state'] == 'failed'
        assert 'Controlled' not in str(receipt.error)
