from pathlib import Path
import pytest

from packages.parsers.inspect import PDFError
from packages.ir import strict_loads


def test_missing_models_never_create_healthy_heartbeat(tmp_path, monkeypatch):
    from workers.parser.main import ModelHealth
    monkeypatch.setattr('workers.parser.main.verify_memory_envelope', lambda: 4 * 1024**3)
    with pytest.raises(PDFError):
        ModelHealth(tmp_path, tmp_path/'absent').heartbeat()
    assert not (tmp_path/'heartbeat.json').exists()


def test_models_are_reverified_after_sixty_seconds_and_revoke_health(tmp_path, monkeypatch):
    from workers.parser.main import ModelHealth
    checks = []
    def verify(path):
        checks.append(path)
        if len(checks) == 2:
            raise PDFError('PARSER_MODEL_HASH_MISMATCH')
        return {'docling_version': 'test-version'}
    clock = [0]
    monkeypatch.setattr('workers.parser.main.verify_models', verify)
    monkeypatch.setattr('workers.parser.main.verify_memory_envelope', lambda: 4 * 1024**3)
    monkeypatch.setattr('workers.parser.main.time.monotonic', lambda: clock[0])
    health = ModelHealth(tmp_path, tmp_path/'models')
    health.heartbeat('task')
    assert strict_loads((tmp_path/'heartbeat.json').read_bytes())['models_verified'] is True
    clock[0] = 59
    health.heartbeat('task')
    assert len(checks) == 1
    clock[0] = 60
    with pytest.raises(PDFError):
        health.heartbeat('task')
    assert len(checks) == 2 and not (tmp_path/'heartbeat.json').exists()
