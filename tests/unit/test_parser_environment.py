import time
import pytest
from packages.ir import canonical_bytes
from packages.parsers.environment import detect_environment, read_environment, resolve_accelerator
from packages.parsers.profiles import PROFILE_IDS


def test_detection_never_contacts_inference_or_model_preparation(monkeypatch):
    monkeypatch.setattr('httpx.Client', lambda **kwargs: pytest.fail('Startup/read must not contact models'))
    report = detect_environment()
    assert report['default'] == 'dmr'
    assert report['options'] == [{'id': 'dmr', 'profiles': list(PROFILE_IDS), 'reason': None}]


def test_current_report_and_offline_jobs_both_freeze_dmr(tmp_path):
    report = detect_environment()
    body = {'timestamp': time.time(), 'service_ready': True, 'environment': report}
    path = tmp_path / 'heartbeat.json';path.write_bytes(canonical_bytes(body))
    assert read_environment(tmp_path)['online']
    assert resolve_accelerator(PROFILE_IDS[0], tmp_path) == 'dmr'
    body['timestamp'] -= 91;path.write_bytes(canonical_bytes(body))
    assert not read_environment(tmp_path)['online']
    assert resolve_accelerator(PROFILE_IDS[0], tmp_path) == 'dmr'


@pytest.mark.parametrize('options', [[{}], [None], [{'id': 'dmr', 'profiles': 'surya'}], [{'id': 'cpu', 'profiles': []}], [{'id': 'dmr', 'profiles': ['docling-v1']}]])
def test_untrusted_or_native_heartbeat_cannot_advertise_active_capabilities(tmp_path, options):
    body = {'timestamp': time.time(), 'service_ready': True, 'environment': {
        'detected_at': time.time(), 'default': 'dmr', 'options': options}}
    (tmp_path / 'heartbeat.json').write_bytes(canonical_bytes(body))
    assert read_environment(tmp_path)['online'] is False


def test_report_missing_active_profile_fails_closed(tmp_path):
    body = {'timestamp': time.time(), 'service_ready': True, 'environment': {
        'detected_at': time.time(), 'default': 'dmr', 'options': [{'id': 'dmr', 'profiles': []}]}}
    (tmp_path / 'heartbeat.json').write_bytes(canonical_bytes(body))
    with pytest.raises(ValueError, match='PARSER_ACCELERATOR_UNAVAILABLE'):
        resolve_accelerator(PROFILE_IDS[0], tmp_path)
