"""Exercise elapsed time beyond the old cap without waiting for model inference."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.ir import digest, strict_loads
from packages.parsers.models import parser_version
from packages.parsers.spool import validate_request, write_request
from packages.parsers.timeouts import request_timeout_seconds, selected_timeout_seconds
from workers.parser import main as parser

SOURCE = Path(__file__).resolve().parents[2] / 'fixtures/sample.pdf'


def request(timeout=None, deadline=10000):
    value = {'task_id': 'task-timeout', 'fence': 1, 'source_sha256': digest(SOURCE.read_bytes()),
        'max_pages': 20, 'deadline': (datetime.now(timezone.utc) + timedelta(seconds=deadline)).isoformat(),
        'operation': 'parse', 'parser_version': parser_version()}
    if timeout is not None:
        value['timeout_seconds'] = timeout
    return value


def test_new_preferences_and_legacy_requests_have_distinct_defaults():
    assert selected_timeout_seconds({}) == 7200
    assert request_timeout_seconds(request()) == 900
    assert request_timeout_seconds(request(10800)) == 10800
    assert request_timeout_seconds({'operation': 'inspect'}) == 900


@pytest.mark.parametrize('value', [0, 59, 61, 86460, True, '7200', 7200.0, None])
def test_spool_rejects_invalid_timeout(value):
    descriptor = request()
    descriptor['timeout_seconds'] = value
    with pytest.raises(ValueError, match='PARSER_REQUEST_INVALID'):
        validate_request(descriptor)


@pytest.mark.parametrize('timeout,duration,deadline,status', [
    (7200, 1000, 10000, 'succeeded'),
    (86400, 80000, 100000, 'succeeded'),
    (60, 90, 10000, 'failed'),
    (None, 1000, 10000, 'failed'),
    (7200, 90, 30, 'failed'),
])
def test_parser_uses_configured_limit_and_absolute_deadline(tmp_path, monkeypatch, timeout, duration, deadline, status):
    descriptor = request(timeout, deadline)
    inputs, outputs = tmp_path / 'inputs', tmp_path / 'outputs'
    write_request(inputs, descriptor, SOURCE)
    clock = SimpleNamespace(elapsed=0)
    child = SimpleNamespace(killed=False, exitcode=0)
    child.start = lambda: None
    child.is_alive = lambda: not child.killed and clock.elapsed < duration
    def join(timeout=None):
        clock.elapsed += timeout or 0
        if not child.is_alive() and not child.killed:
            (outputs / 'task-timeout/1/payload.json').write_text('{"synthetic":true}')
    child.join = join
    child.kill = lambda: setattr(child, 'killed', True)
    monkeypatch.setattr(parser, 'time', SimpleNamespace(monotonic=lambda: clock.elapsed))
    monkeypatch.setattr(parser, 'multiprocessing', SimpleNamespace(get_context=lambda _: SimpleNamespace(Process=lambda **_: child)))
    assert parser.run_once(inputs, outputs)
    result = strict_loads((outputs / 'task-timeout/1/result.json').read_bytes())
    assert result['status'] == status
    assert child.killed == (status == 'failed')
    if status == 'failed':
        assert result['error']['code'] == 'PARSER_TIMEOUT'
