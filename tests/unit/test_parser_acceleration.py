"""The portable client delegates inference without silently retargeting old jobs."""
import sys
import pytest
from packages.parsers.catalog import vlm_model
from packages.local_models.catalog import artifact
from packages.parsers.profiles import PROFILE_IDS, RETIRED_PROFILES
from packages.parsers.runtime import runtime_config, child_executable
from packages.parsers.progress import local_identity
from packages.domain.workflow import ModelIdentity


@pytest.mark.parametrize('backend', ['vllm', 'mlx'])
@pytest.mark.parametrize('profile', PROFILE_IDS)
def test_all_active_parsers_use_exact_dmr_artifact_on_either_declared_backend(monkeypatch, profile, backend):
    monkeypatch.setenv('PARSER_DMR_BACKEND', backend)
    monkeypatch.setenv('PARSER_DMR_URL', 'http://runner')
    runtime = runtime_config(profile, 'dmr')
    assert runtime.model_id == artifact(vlm_model(profile))['id']
    assert runtime.server_url == 'http://runner/engines/vllm/v1'
    identity = ModelIdentity.model_validate(local_identity(profile, {}))
    assert identity.device == 'dmr' and identity.model_id == vlm_model(profile)['repo']
    assert identity.engine_version is None  # Client metadata is not package-version proof.
    assert child_executable(profile, 'dmr') == sys.executable


@pytest.mark.parametrize('device', ['cpu', 'cuda', 'mlx'])
def test_native_snapshot_is_rejected_instead_of_silently_moved_to_dmr(device):
    with pytest.raises(ValueError, match='PARSER_NATIVE_RUNTIME_RETIRED'):
        runtime_config(PROFILE_IDS[0], device)


@pytest.mark.parametrize('profile', RETIRED_PROFILES)
def test_retired_model_cannot_reenter_through_runtime_configuration(profile):
    with pytest.raises(ValueError, match='PARSER_PROFILE_UNAVAILABLE'):
        runtime_config(profile, 'dmr')


def test_backend_change_cannot_redirect_a_frozen_job(monkeypatch):
    monkeypatch.setenv('PARSER_DMR_BACKEND', 'mlx')
    with pytest.raises(ValueError, match='PARSER_BACKEND_CHANGED'):
        runtime_config('surya-ocr-2-v1', 'dmr', 'vllm')
