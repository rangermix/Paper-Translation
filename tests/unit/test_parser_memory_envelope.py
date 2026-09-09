"""A real cgroup bound is required; virtual mappings are not resident memory."""
import pytest

from packages.parsers import PDFError
from workers.parser.main import verify_memory_envelope


@pytest.mark.parametrize('gib', [2, 4, 8, 16])
def test_bounded_cgroup_v2_is_accepted(tmp_path, gib):
    (tmp_path / 'memory.max').write_text(str(gib * 1024**3))
    assert verify_memory_envelope(tmp_path) == gib * 1024**3


def test_bounded_cgroup_v1_is_accepted(tmp_path):
    (tmp_path / 'memory').mkdir()
    (tmp_path / 'memory/memory.limit_in_bytes').write_text(str(4 * 1024**3))
    assert verify_memory_envelope(tmp_path) == 4 * 1024**3


@pytest.mark.parametrize('limit', ['max', '0', '-1', 'not-a-limit', str(16 * 1024**3 + 1)])
def test_unbounded_or_invalid_memory_envelope_fails_closed(tmp_path, limit):
    (tmp_path / 'memory.max').write_text(limit)
    with pytest.raises(PDFError) as rejected:
        verify_memory_envelope(tmp_path)
    assert rejected.value.code == 'PARSER_RESOURCE_LIMIT'


def test_missing_cgroup_cannot_silently_run_without_memory_protection(tmp_path):
    with pytest.raises(PDFError) as rejected:
        verify_memory_envelope(tmp_path)
    assert rejected.value.code == 'PARSER_RESOURCE_LIMIT'


def test_existing_unbounded_v2_is_not_masked_by_v1_shaped_file(tmp_path):
    (tmp_path / 'memory.max').write_text('max')
    (tmp_path / 'memory').mkdir()
    (tmp_path / 'memory/memory.limit_in_bytes').write_text(str(4 * 1024**3))
    with pytest.raises(PDFError):
        verify_memory_envelope(tmp_path)


def test_unbounded_service_cannot_advertise_model_health(tmp_path, monkeypatch):
    from workers.parser.main import ModelHealth
    (tmp_path / 'heartbeat.json').write_text('{"models_verified": true}')
    def unbounded():
        raise PDFError('PARSER_RESOURCE_LIMIT')
    monkeypatch.setattr('workers.parser.main.verify_memory_envelope', unbounded)
    monkeypatch.setattr('workers.parser.main.verify_models', lambda path: pytest.fail('Memory guard must precede model verification'))
    with pytest.raises(PDFError):
        ModelHealth(tmp_path, tmp_path / 'models').heartbeat()
    assert not (tmp_path / 'heartbeat.json').exists()
