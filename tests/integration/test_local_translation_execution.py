"""Real PostgreSQL dispatch, protected output and no-send cancellation; synthetic wire."""
import json
import httpx
import pytest
from sqlalchemy import select

from packages.domain.models import Attempt, Job, Permit, Task, SegmentVersion
from packages.jobs.queue import claim
from packages.providers.settings import save_configuration, managed_profile
from packages.providers.local_translation import LocalTranslation
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import setup_library
from tests.unit.test_local_translation_provider import profile


def prepare(database, monkeypatch, tmp_path, slug='hy-mt2-1.8b-q8', backend=None):
    db, cfg = database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR', str(tmp_path / 'settings'))
    save_configuration(profile(slug) | ({'local_backend': backend} if backend else {}), None, False, '"0"', 'local')
    setup_library(db, cfg)
    with db.transaction() as session:
        job = session.get(Job, 'job'); job.payload = job.payload | {'profile': managed_profile()}
    execute_translation(db, cfg, claim(db))
    return db, cfg


@pytest.mark.parametrize('slug,runtime', [
    ('hy-mt2-1.8b-q8', 'mlx'), ('hy-mt2-7b-q4-k-m-gguf', 'llama.cpp'),
    ('hy-mt2-1.8b-bf16-vllm', 'vllm'),
])
def test_local_prepare_precedes_permit_and_exact_model_is_recorded(database, monkeypatch, tmp_path, slug, runtime):
    db, cfg = prepare(database, monkeypatch, tmp_path, slug)
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
        assert identity['kind'] == 'local' and identity['model_id'] == profile(slug)['model_id']
        assert identity['engine'] == runtime and identity['revision']
    assert events == ['prepare', 'inference']


@pytest.mark.parametrize('request_id,expected_id', [
    ('r' * 201, None),
    ({'unexpected': 'local metadata'}, None),
    ('local-request-123', 'local-request-123'),
])
def test_local_tracking_metadata_does_not_prevent_known_usage_settlement(
        database, monkeypatch, tmp_path, request_id, expected_id):
    db, cfg = prepare(database, monkeypatch, tmp_path)
    calls = []
    def wire(request):
        calls.append(request)
        return httpx.Response(200, json={'id': request_id, 'model': profile()['model_id'],
            'choices': [{'text': '本地译文', 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 5}})
    monkeypatch.setattr(LocalTranslation, 'prepare', lambda self, saved, check_current: check_current())
    original = LocalTranslation.__init__
    monkeypatch.setattr(LocalTranslation, '__init__', lambda self: original(self, transport=httpx.MockTransport(wire)))
    lease = claim(db); execute_translation(db, cfg, lease)
    with db.transaction() as session:
        attempt = session.get(Attempt, lease.attempt_id)
        assert attempt.request_id == expected_id
        assert attempt.usage == {'input_tokens': 20, 'output_tokens': 5}
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.get(Task, lease.task_id).status == 'succeeded'
        assert session.scalar(select(SegmentVersion)) is not None
    assert len(calls) == 1


def test_local_profile_rotation_during_prepare_uses_frozen_model(database, monkeypatch, tmp_path):
    db, cfg = prepare(database, monkeypatch, tmp_path)
    frozen = managed_profile()
    def prepared(self, saved, check_current):
        check_current()
        save_configuration(profile('milmmt-46-4b-q4'), None, False, '"1"', 'rotate')
    monkeypatch.setattr(LocalTranslation, 'prepare', prepared)
    def wire(request):
        body = json.loads(request.content)
        assert body['model'] == frozen['model_id']
        return httpx.Response(200, json={'model': body['model'], 'choices': [{'text': '原设置译文', 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 5}})
    original = LocalTranslation.__init__
    monkeypatch.setattr(LocalTranslation, '__init__', lambda self: original(self, transport=httpx.MockTransport(wire)))
    execute_translation(db, cfg, claim(db))
    with db.transaction() as session:
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.get(Job, 'job').error is None
        assert session.scalar(select(SegmentVersion)) is not None
    assert managed_profile()['model_id'] != frozen['model_id']


def test_backend_rotation_during_prepare_keeps_task_dispatch_and_receipt_frozen(database, monkeypatch, tmp_path):
    import copy
    from packages.local_models import catalog
    # Future compatible adapter fixture; no model weights or real inference.
    model = copy.deepcopy(catalog.get_model('hy-mt2-1.8b-q4-k-m-gguf'))
    model['inference_backends'] = ['llama.cpp', 'vllm']
    monkeypatch.setattr(catalog, 'models', lambda: [model])
    from tests.integration import test_translation_execution
    monkeypatch.setattr(test_translation_execution, 'PROFILE', profile(model['id']) | {'local_backend': 'vllm'})
    db, cfg = prepare(database, monkeypatch, tmp_path, model['id'], backend='vllm')
    frozen = managed_profile()
    lease = claim(db)
    with db.transaction() as session:
        assert session.get(Job, 'job').config_snapshot['local_backend'] == 'vllm'
    def prepared(self, saved, check_current):
        check_current()
        assert saved['local_backend'] == 'vllm'
        save_configuration(profile(model['id']) | {'local_backend': 'llama.cpp'}, None, False, '"1"', 'rotate-backend')
    monkeypatch.setattr(LocalTranslation, 'prepare', prepared)
    def wire(request):
        body = json.loads(request.content)
        assert body['model'] == frozen['model_id'] and body['backend'] == 'vllm'
        return httpx.Response(200, json={'model': body['model'], 'choices': [{'text': '合成译文', 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 5}})
    original = LocalTranslation.__init__
    monkeypatch.setattr(LocalTranslation, '__init__', lambda self: original(self, transport=httpx.MockTransport(wire)))
    execute_translation(db, cfg, lease)
    with db.transaction() as session:
        assert session.get(Job, 'job').config_snapshot['local_backend'] == 'vllm'
        assert session.get(Attempt, lease.attempt_id).actual_model['engine'] == 'vllm'
        assert session.scalar(select(Permit)).state == 'settled'
        assert session.get(Job, 'job').error is None
    assert managed_profile()['local_backend'] == 'llama.cpp'
