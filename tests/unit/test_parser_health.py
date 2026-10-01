from pathlib import Path
import pytest

from packages.parsers.inspect import PDFError
from packages.ir import strict_loads


def test_probe_accepts_recent_legacy_heartbeat_without_reading_cache(tmp_path, monkeypatch):
    import time
    from packages.ir import canonical_bytes
    from workers.parser import health
    limit = 4 * 1024**3
    monkeypatch.setattr(health, 'verify_memory_envelope', lambda: limit)
    monkeypatch.setenv('PARSER_OUTPUTS', str(tmp_path))
    # Legacy receipts remain readable; selected weights are checked on parsing use.
    monkeypatch.setenv('DOCLING_ARTIFACTS_PATH', str(tmp_path / 'not-read-by-probe'))
    receipt = {'timestamp': time.time(), 'models_verified': True, 'memory_limit_bytes': limit}
    (tmp_path / 'heartbeat.json').write_bytes(canonical_bytes(receipt))
    health.main()
    receipt['timestamp'] -= 31
    (tmp_path / 'heartbeat.json').write_bytes(canonical_bytes(receipt))
    with pytest.raises(SystemExit, match='heartbeat stale'):
        health.main()


def test_empty_cache_creates_healthy_heartbeat_without_downloads(tmp_path, monkeypatch):
    from workers.parser.main import ModelHealth
    monkeypatch.setattr('workers.parser.main.verify_memory_envelope', lambda: 4 * 1024**3)
    ModelHealth(tmp_path, tmp_path/'absent').heartbeat()
    assert strict_loads((tmp_path/'heartbeat.json').read_bytes())['service_ready'] is True
    assert not (tmp_path / 'absent').exists()


def test_resource_and_environment_checks_revoke_health(tmp_path, monkeypatch):
    from workers.parser.main import ModelHealth
    checks = []
    def verify(path):
        checks.append(path)
        if len(checks) == 2:
            raise PDFError('PARSER_RESOURCE_LIMIT')
        return 4 * 1024**3
    clock = [0]
    monkeypatch.setattr('workers.parser.main.verify_memory_envelope', lambda: verify(tmp_path))
    monkeypatch.setattr('workers.parser.main.time.monotonic', lambda: clock[0])
    health = ModelHealth(tmp_path, tmp_path/'models')
    health.heartbeat('task')
    assert strict_loads((tmp_path/'heartbeat.json').read_bytes())['service_ready'] is True
    clock[0] = 59
    health.heartbeat('task')
    assert len(checks) == 1
    clock[0] = 60
    with pytest.raises(PDFError):
        health.heartbeat('task')
    assert len(checks) == 2 and not (tmp_path/'heartbeat.json').exists()
