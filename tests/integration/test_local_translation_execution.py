"""Real PostgreSQL dispatch, protected output and no-send cancellation; synthetic wire."""
import json
import httpx
from sqlalchemy import select

from packages.domain.models import Job, Permit, Task, SegmentVersion
from packages.jobs.queue import claim
from packages.providers.settings import save_configuration, managed_profile
from packages.providers.local_translation import LocalTranslation
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import setup_library
from tests.unit.test_local_translation_provider import profile


def prepare(database, monkeypatch, tmp_path):
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'settings'))
    save_configuration(profile(), None, False, '"0"', 'local')
    setup_library(db, cfg)
    with db.transaction() as session:
        job = session.get(Job, 'job'); job.payload = job.payload | {'profile': managed_profile()}
    execute_translation(db, cfg, claim(db))
    return db, cfg


def test_local_prepare_precedes_permit_and_exact_model_is_recorded(database, monkeypatch, tmp_path):
    db, cfg = prepare(database, monkeypatch, tmp_path)
    events = []
    def prepared(self, saved, check_current):
        check_current()
        with db.transaction() as session:
            assert session.scalar(select(Permit)) is None
        events.append('prepare')
    def wire(request):
        events.append('inference')
        assert 'authorization' not in request.headers
        body = json.loads(request.content)
        return httpx.Response(200, json={'model': body['model'], 'choices':[{'text':'本地译文', 'finish_reason':'stop'}],
                                       'usage':{'prompt_tokens':20,'completion_tokens':5}})
    monkeypatch.setattr(LocalTranslation, 'prepare', prepared)
    original = LocalTranslation.__init__
    monkeypatch.setattr(LocalTranslation, '__init__', lambda self: original(self, transport=httpx.MockTransport(wire)))
    lease = claim(db); execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.get(Task, lease.task_id).status == 'succeeded'
        assert session.scalar(select(SegmentVersion)) is not None
        identity = session.get(Job, 'job').actual_model
        assert identity['kind'] == 'local' and identity['model_id'] == profile()['model_id']
        assert identity['engine'] == 'mlx' and identity['revision']
    assert events == ['prepare', 'inference']


def test_local_profile_rotation_during_prepare_never_dispatches(database, monkeypatch, tmp_path):
    db, cfg = prepare(database, monkeypatch, tmp_path)
    def prepared(self, saved, check_current):
        check_current()
        save_configuration(profile('milmmt-46-4b-q4'), None, False, '"1"', 'rotate')
    monkeypatch.setattr(LocalTranslation, 'prepare', prepared)
    monkeypatch.setattr(LocalTranslation, 'translate', lambda *args: (_ for _ in ()).throw(AssertionError('sent stale model')))
    execute_translation(db, cfg, claim(db))
    with db.transaction() as session:
        assert session.scalar(select(Permit)) is None
        assert session.get(Job, 'job').error['code'] == 'PROVIDER_PROFILE_STALE'
