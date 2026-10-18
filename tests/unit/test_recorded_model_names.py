from copy import deepcopy

from packages.jobs.model_names import model_identity_view
from packages.local_models.catalog import artifact, models
from packages.parsers.catalog import vlm_lock
from packages.parsers.profiles import PARSER_PROFILES


def test_locked_local_model_ids_have_readable_names_without_mutating_history():
    for model in models():
        for identifier in (model['id'], artifact(model)['id']):
            recorded = {'kind': 'local', 'model_id': identifier, 'revision': model['revision']}
            before = deepcopy(recorded)
            assert model_identity_view(recorded) == {**recorded, 'display_name': model['label']}
            assert recorded == before


def test_parser_names_require_recorded_exact_identity_not_a_current_or_recorded_profile_choice():
    labels = {row['id']: row['label'] for row in PARSER_PROFILES}
    for model in vlm_lock()['models']:
        if model['id'] not in labels:
            continue
        recorded = {'kind': 'local', 'model_id': model['repo'], 'revision': model['revision']}
        assert model_identity_view(recorded)['display_name'] == labels[model['id']]
        mismatch = {**recorded, 'revision': 'unknown-old-revision', 'parser_profile_revision': model['id']}
        assert model_identity_view(mismatch) == mismatch
    unknown = {'kind': 'local', 'model_id': 'unknown/repository', 'parser_profile_revision': 'surya-ocr-2-v1'}
    assert model_identity_view(unknown) == unknown


def test_unknown_api_missing_and_historical_identities_are_not_guessed():
    known = artifact(models()[0])['id']
    for recorded in [None, {}, {'kind': 'none'}, {'kind': 'historical_unknown'},
                     {'kind': 'local'}, {'kind': 'local', 'model_id': 'sha256:unknown'},
                     {'kind': 'api', 'model_id': known}, {'kind': 'api', 'model_id': 'custom-service-model'}]:
        assert model_identity_view(recorded) == recorded
