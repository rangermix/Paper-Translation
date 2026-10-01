"""Real lease/permit settlement for received GGUF identity metadata; mocked wire."""
import httpx
import pytest
from sqlalchemy import select

from packages.domain.models import Attempt, Permit, SegmentVersion, Task
from packages.jobs.queue import claim
from packages.local_models.catalog import artifact, get_model
from packages.providers.local_translation import LocalTranslation
from packages.translation.execution import execute_translation
from tests.integration.test_local_translation_execution import prepare


@pytest.mark.parametrize('correct_bundle', [True, False])
def test_gguf_received_bundle_identity_is_settled_only_for_the_pinned_artifact(
        database, monkeypatch, tmp_path, correct_bundle):
    model = get_model('hy-mt2-7b-q4-k-m-gguf'); ident = artifact(model)['id']
    reported = '/models/bundles/sha256/' + (ident.split(':')[1] if correct_bundle else '0' * 64) + '/model/' + model['files'][0]['path']
    db, cfg = prepare(database, monkeypatch, tmp_path, model['id'])
    monkeypatch.setattr(LocalTranslation, 'prepare', lambda self, saved, check_current: check_current())
    original = LocalTranslation.__init__
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        'model': reported, 'choices': [{'text': '本地译文', 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 20, 'completion_tokens': 5}}))
    monkeypatch.setattr(LocalTranslation, '__init__', lambda self: original(self, transport=transport))
    lease = claim(db); execute_translation(db, cfg, lease)
    with db.transaction() as session:
        attempt = session.get(Attempt, lease.attempt_id)
        permit = session.scalar(select(Permit))
        task = session.get(Task, lease.task_id)
        if correct_bundle:
            assert permit.state == 'settled' and task.status == 'succeeded'
            assert attempt.actual_model['model_id'] == ident
            assert attempt.actual_model['reported_model_id'] == reported
            assert attempt.actual_model['engine'] == 'llama.cpp'
            assert attempt.usage == {'input_tokens': 20, 'output_tokens': 5}
            assert session.scalar(select(SegmentVersion)) is not None
        else:
            assert permit.state == 'unknown'
            assert task.status == 'outcome_unknown' and attempt.actual_model['model_id'] == reported
            assert session.scalar(select(SegmentVersion)) is None
    if not correct_bundle:
        assert claim(db) is None
