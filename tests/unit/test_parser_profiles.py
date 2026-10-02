"""Availability is distinct from immutable historical parser choices."""
import pytest
from pydantic import ValidationError
from apps.api.catalog import Preferences
from apps.api.library import ParseRequest
from packages.parsers.profiles import DEFAULT_PROFILE, PROFILE_IDS, RETIRED_PROFILES, recorded_profile, preferred_profile, selected_profile
from packages.parsers.spool import validate_request
from packages.parsers.models import parser_version


def test_new_default_and_missing_historical_snapshot_are_distinct():
    assert selected_profile({}) == preferred_profile({}) == DEFAULT_PROFILE == 'surya-ocr-2-v1'
    assert recorded_profile({}) == 'docling-v1'
    for profile in RETIRED_PROFILES:
        assert preferred_profile({'parser_profile_revision': profile}) == profile
        with pytest.raises(ValueError, match='PARSER_PROFILE_UNAVAILABLE'):
            selected_profile({'parser_profile_revision': profile})
        with pytest.raises(ValidationError):
            Preferences(parser_profile_revision=profile)
        with pytest.raises(ValidationError):
            ParseRequest(source_asset_id='asset', parser_profile_revision=profile)


@pytest.mark.parametrize('profile', PROFILE_IDS)
def test_new_inputs_and_spool_preserve_explicit_active_choice(profile):
    assert Preferences(parser_profile_revision=profile).parser_profile_revision == profile
    request = {'task_id': 'parse_test', 'fence': 1, 'source_sha256': 'a' * 64, 'max_pages': 20,
        'deadline': '2030-01-01T00:00:00Z', 'parser_version': parser_version(profile), 'operation': 'parse',
        'profile': {'parser_profile_revision': profile}, 'accelerator': 'dmr'}
    assert validate_request(request)['profile']['parser_profile_revision'] == profile
    with pytest.raises(ValueError, match='PARSER_VERSION_MISMATCH'):
        validate_request(request | {'parser_version': 'vlm-parser-v1'})


def test_retired_spool_is_structurally_valid_for_an_actionable_failure():
    request = {'task_id': 'legacy', 'fence': 1, 'source_sha256': 'a' * 64, 'max_pages': 20,
        'deadline': '2030-01-01T00:00:00Z', 'parser_version': '2.130.0', 'operation': 'parse'}
    assert validate_request(request) == request
    with pytest.raises(ValueError):
        validate_request(request | {'profile': {'parser_profile_revision': '../untrusted'}})
