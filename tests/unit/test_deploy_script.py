"""Exercise deployment selection/failure handling without running Docker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def deployment(tmp_path):
    root = tmp_path / 'checkout with spaces'
    root.mkdir()
    shutil.copyfile('deploy.sh', root / 'deploy.sh')
    executable = root / 'docker'
    executable.write_text(f'#!{sys.executable}\n' +
        'import json, os, sys\n'
        'with open(os.environ["CALL_LOG"], "a") as log:\n'
        '    log.write(json.dumps({"cwd": os.getcwd(), "args": sys.argv[1:]}) + "\\n")\n'
        'raise SystemExit(17 if os.environ.get("FAIL_BUILD") and "build" in sys.argv else 0)\n')
    executable.chmod(0o755)
    log = root / 'calls.jsonl'
    env = {'PATH': str(root) + os.pathsep + os.environ['PATH'], 'CALL_LOG': str(log)}
    return root, log, env


def test_missing_local_compose_cannot_deploy_a_different_default(deployment):
    root, log, env = deployment
    result = subprocess.run(['bash', str(root / 'deploy.sh')], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not log.exists()
    assert 'compose.example.yaml' in result.stderr and 'compose.yaml' in result.stderr


def test_deploy_preserves_local_selection_and_compose_options(deployment):
    root, log, env = deployment
    (root / 'compose.yaml').write_text('name: chosen-local-project\n')
    result = subprocess.run(['bash', str(root / 'deploy.sh'), '--project-name', 'chosen-local-project',
                             '--profile', 'local-translation'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    prefix = ['compose', '-f', 'compose.yaml', '--project-name', 'chosen-local-project', '--profile', 'local-translation']
    assert [call['args'] for call in calls] == [prefix + ['build', 'app', 'parser', 'db'],
        prefix + ['up', '-d', '--wait'], prefix + ['ps']]
    assert all(call['cwd'] == str(root) for call in calls)


def test_failed_build_stops_before_starting_services(deployment):
    root, log, env = deployment
    (root / 'compose.yaml').write_text('name: chosen-local-project\n')
    result = subprocess.run(['bash', str(root / 'deploy.sh')], env={**env, 'FAIL_BUILD': '1'}, capture_output=True)
    assert result.returncode == 17
    assert len(log.read_text().splitlines()) == 1
