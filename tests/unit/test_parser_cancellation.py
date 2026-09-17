from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
import sys

import pytest

from packages.ir import digest
from packages.parsers.spool import write_request
from workers.parser.main import run_once
from workers.parser.process import ParserProcess

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('field,value', [
    ('task_id', 42), ('source_sha256', {}), ('deadline', 42),
    ('parser_version', None), ('operation', []), ('asset_id', 42), ('accelerator', []),
])
def test_malformed_descriptor_does_not_starve_later_work(tmp_path, field, value):
    inputs, outputs = tmp_path / 'inputs', tmp_path / 'outputs'
    valid = {'task_id': 'z-valid', 'fence': 1, 'source_sha256': 'a' * 64,
             'max_pages': 1, 'deadline': '2000-01-01T00:00:00+00:00',
             'operation': 'inspect', 'parser_version': 'inspector-v1'}
    invalid = valid | {'task_id': 'a-invalid', field: value}
    for task_id, descriptor in [('a-invalid', invalid), ('z-valid', valid)]:
        path = inputs / task_id / '1' / 'request.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(descriptor))

    assert run_once(inputs, outputs)
    assert not (outputs / 'a-invalid').exists()
    result = json.loads((outputs / 'z-valid/1/result.json').read_text())
    assert result['error']['code'] == 'PARSER_TIMEOUT'


def test_active_child_is_killed_and_content_removed_on_tombstone(tmp_path, monkeypatch):
    inputs, outputs = tmp_path/'inputs', tmp_path/'outputs'
    request = {'task_id': 'task-private', 'fence': 1, 'source_sha256': digest((ROOT/'tests/fixtures/sample.pdf').read_bytes()),
        'max_pages': 20, 'deadline': (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat(),
        'operation': 'inspect', 'parser_version': 'inspector-v1'}
    write_request(inputs, request, ROOT/'tests/fixtures/sample.pdf')
    # Exercise real subprocess termination, with a deterministic slow child.
    script = "from pathlib import Path; import sys, time; (Path(sys.argv[1])/'private-text.txt').write_text('Synthetic private output'); time.sleep(20)"
    monkeypatch.setattr('workers.parser.main.ParserProcess',
        lambda command: ParserProcess([sys.executable, '-c', script, command[-1]]))
    def cancel():
        for _ in range(300):
            if (outputs/'task-private/1/private-text.txt').exists():
                (inputs/'task-private/cancelled.json').write_text('{"cancelled":true}')
                return
            time.sleep(.01)
    thread = threading.Thread(target=cancel)
    thread.start()
    start = time.monotonic()
    assert run_once(inputs, outputs)
    thread.join(timeout=4)
    assert not thread.is_alive() and time.monotonic()-start < 8
    assert not (outputs/'task-private/1').exists()
    assert json.loads((outputs/'task-private/cancelled.json').read_text()) == {'cancelled': True}


def test_existing_tombstone_prevents_work_and_removes_prior_content(tmp_path):
    inputs, outputs = tmp_path/'inputs', tmp_path/'outputs'
    (inputs/'task-private').mkdir(parents=True)
    (outputs/'task-private/1').mkdir(parents=True)
    (inputs/'task-private/cancelled.json').write_text('{"cancelled":true}')
    (outputs/'task-private/1/source.txt').write_text('Old private source')
    assert run_once(inputs, outputs) is False
    assert not (outputs/'task-private/1').exists()
