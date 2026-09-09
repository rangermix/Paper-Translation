"""No Docker or Provider call is made by these subprocess-boundary checks."""
import json
import subprocess

import pytest

from harness.live_provider_run import run_recorded_command


def test_timeout_retains_partial_evidence_without_retry_or_secret(tmp_path, monkeypatch):
    calls = []
    def timeout(argv, **kwargs):
        calls.append(argv)
        assert kwargs['encoding'] == 'utf-8' and kwargs['errors'] == 'replace'
        raise subprocess.TimeoutExpired(argv, kwargs['timeout'],
            output=b'Controlled source: 64 tokens.\nBearer TEST_ONLY_PRIVATE_VALUE\n',
            stderr=b'postgresql+psycopg://role:TEST_ONLY_DB_VALUE@db/library\napi_key=TEST_ONLY_KEY_VALUE\n'
                b'https://test-user:TEST_ONLY_HTTP_PASSWORD@example.invalid/endpoint?token=TEST_ONLY_QUERY_TOKEN')
    monkeypatch.setattr(subprocess, 'run', timeout)
    path = tmp_path / 'commands.json'
    commands = [{'status': 'completed', 'argv': ['prior-verified-step'], 'exit_code': 0}]
    with pytest.raises(RuntimeError, match='timed out') as caught:
        run_recorded_command(['docker', 'compose', 'exec', 'app'], env={}, commands=commands,
            evidence_path=path, timeout=0.01)
    stored = json.loads(path.read_text())
    assert len(calls) == 1 and len(stored) == 2
    assert stored[0]['argv'] == ['prior-verified-step']
    assert stored[1]['status'] == 'timed_out' and stored[1]['exit_code'] is None
    assert stored[1]['timeout_seconds'] == 0.01
    assert '64 tokens' in stored[1]['stdout']
    combined = path.read_text() + str(caught.value)
    assert '[REDACTED]' in combined
    for secret in ['TEST_ONLY_PRIVATE_VALUE', 'TEST_ONLY_DB_VALUE', 'TEST_ONLY_KEY_VALUE',
                   'TEST_ONLY_HTTP_PASSWORD', 'TEST_ONLY_QUERY_TOKEN']:
        assert secret not in combined


def test_nonzero_child_output_is_also_redacted_and_retained(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda argv, **kwargs:
        subprocess.CompletedProcess(argv, 7, 'Controlled result\n', 'secret=TEST_ONLY_VALUE'))
    path = tmp_path / 'commands.json'
    with pytest.raises(RuntimeError, match='stopped'):
        run_recorded_command(['docker', 'compose', 'exec', 'app'], env={}, commands=[], evidence_path=path)
    stored = json.loads(path.read_text())[0]
    assert stored['exit_code'] == 7 and stored['status'] == 'failed'
    assert stored['stdout'] == 'Controlled result\n'
    assert 'TEST_ONLY_VALUE' not in path.read_text()
