from copy import deepcopy

from packages.ir import digest
from packages.local_models.catalog import artifact, models
from packages.providers.presentation import profile_view


def test_exact_local_model_name_is_response_only_and_keeps_digest_inputs():
    for model in models():
        for identifier in (model['id'], artifact(model)['id']):
            profile = {'api_protocol': 'local_translation', 'model_id': identifier,
                       'endpoint': 'http://synthetic.invalid/v1/completions', 'profile_revision': 'recorded'}
            original = deepcopy(profile)
            view = profile_view(profile)
            assert view == {**original, 'model_display_name': model['label']}
            assert profile == original and digest(profile) == digest(original)


def test_api_unknown_and_missing_model_profiles_are_never_guessed():
    known = artifact(models()[0])['id']
    for profile in [{}, {'api_protocol': 'local_translation'},
                    {'api_protocol': 'local_translation', 'model_id': 'sha256:unknown'},
                    {'api_protocol': 'responses', 'model_id': known}, {'model_id': known}]:
        assert profile_view(profile) == profile


def test_display_name_is_derived_from_this_profile_not_a_supplied_hint():
    unknown = {'api_protocol': 'responses', 'model_id': 'unknown', 'model_display_name': 'Wrong name'}
    assert profile_view(unknown) == {'api_protocol': 'responses', 'model_id': 'unknown'}
