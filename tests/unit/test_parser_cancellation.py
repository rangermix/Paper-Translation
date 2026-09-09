from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time

from packages.ir import digest
from packages.parsers.spool import write_request
from workers.parser.main import run_once

ROOT = Path(__file__).resolve().parents[2]


def slow_child(request, source, output):
    (Path(output)/'private-text.txt').write_text('Synthetic private output', encoding='utf-8')
    time.sleep(20)


def test_active_child_is_killed_and_content_removed_on_tombstone(tmp_path, monkeypatch):
    inputs, outputs = tmp_path/'inputs', tmp_path/'outputs'
    request = {'task_id': 'task-private', 'fence': 1, 'source_sha256': digest((ROOT/'fixtures/sample.pdf').read_bytes()),
        'max_pages': 20, 'deadline': (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat(),
        'operation': 'inspect', 'parser_version': 'inspector-v1'}
    write_request(inputs, request, ROOT/'fixtures/sample.pdf')
    monkeypatch.setattr('workers.parser.main.process_request', slow_child)
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
