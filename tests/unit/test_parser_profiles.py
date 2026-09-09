"""Parser selection must be explicit, reproducible, and independent of providers."""
import pytest
from pydantic import ValidationError

from apps.api.catalog import Preferences
from apps.api.library import ParseRequest
from packages.parsers.config import pipeline_fingerprint
from packages.parsers.profiles import DEFAULT_PROFILE, GRANITE_PROFILE, PADDLE_PROFILE, selected_profile
from packages.parsers.spool import validate_request
from packages.parsers.models import parser_version


def test_profile_validation_and_legacy_default():
    assert selected_profile({}) == DEFAULT_PROFILE == 'docling-v1'
    assert selected_profile({'parser_profile_revision': GRANITE_PROFILE}) == GRANITE_PROFILE
    assert selected_profile({'parser_profile_revision': PADDLE_PROFILE}) == PADDLE_PROFILE
    for value in ('paddle', '', None, '../model'):
        with pytest.raises(ValueError):
            selected_profile({'parser_profile_revision': value})
        with pytest.raises(ValidationError):
            ParseRequest(source_asset_id='asset', parser_profile_revision=value) if value is not None else Preferences(parser_profile_revision='invalid')


def test_selected_pipeline_changes_fingerprint():
    lock = {'repositories': [], 'pipeline_revision': 'test'}
    assert pipeline_fingerprint(lock, DEFAULT_PROFILE) != pipeline_fingerprint(lock, GRANITE_PROFILE)


def test_spool_accepts_only_supported_profiles():
    request = {'task_id': 'parse_test', 'fence': 1, 'source_sha256': 'a' * 64, 'max_pages': 20,
        'deadline': '2030-01-01T00:00:00Z', 'parser_version': parser_version(), 'operation': 'parse'}
    for profile in (DEFAULT_PROFILE, GRANITE_PROFILE, PADDLE_PROFILE):
        assert validate_request(request | {'profile': {'parser_profile_revision': profile}, 'parser_version': parser_version(profile)})
    with pytest.raises(ValueError):
        validate_request(request | {'profile': {'parser_profile_revision': 'invalid'}})
