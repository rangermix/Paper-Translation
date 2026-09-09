"""Authorization regressions never construct a Provider or run Docker."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness.live_provider_run import MANIFEST, authorization, sha
from tests.integration.test_translation_execution import PROFILE


def request_file(tmp_path):
    profile = {**PROFILE, 'enabled_pairs': [['en', 'zh-Hans'], ['zh-Hans', 'en']], 'semantic_review_enabled': True}
    profile_file = tmp_path / 'profile.json'
    profile_file.write_text(json.dumps(profile))
    key_file = tmp_path / 'key-never-read'
    key_file.write_text('TEST_ONLY_NOT_A_REAL_SECRET')
    approval = {'approved': True, 'approval_id': 'test-approval-only',
        'scope': 'controlled_eight_blocks_translation_candidate_semantic_review', 'manifest_sha256': sha(MANIFEST),
        'profile_file': str(profile_file), 'profile_sha256': sha(profile_file), 'secret_file': str(key_file), 'total_budget_micro': 1000000}
    path = tmp_path / 'approval.json'
    path.write_text(json.dumps(approval))
    return path, approval, key_file


@pytest.mark.parametrize('change', [{'approved': False}, {'total_budget_micro': 0}, {'total_budget_micro': True},
    {'manifest_sha256': '0' * 64}, {'profile_sha256': '0' * 64}, {'scope': 'all_documents'}, {'approval_id': '../escape'}])
def test_guard_rejects_missing_or_changed_authorization(tmp_path, change):
    path, approval, _ = request_file(tmp_path)
    path.write_text(json.dumps({**approval, **change}))
    with pytest.raises(ValueError):
        authorization(path)


def test_validating_authorization_never_reads_secret(tmp_path, monkeypatch):
    path, approval, key = request_file(tmp_path)
    original = Path.read_bytes
    def guarded(self):
        if self.resolve() == key.resolve():
            raise AssertionError('Validation tried to read the secret.')
        return original(self)
    monkeypatch.setattr(Path, 'read_bytes', guarded)
    assert authorization(path)[0]['approval_id'] == approval['approval_id']


def test_optimized_python_cannot_bypass_external_confirmation(tmp_path):
    path = tmp_path / 'unapproved.json'
    path.write_text('{"approved": false}')
    result = subprocess.run([sys.executable, '-O', '.agent/harness/live_provider_run.py', '--approval', str(path), '--execute'], capture_output=True, text=True)
    assert result.returncode != 0 and 'Explicit external-processing approval is missing' in result.stderr


@pytest.mark.parametrize('nested', [False, True])
def test_public_profile_rejects_secret_fields_before_any_execution(tmp_path, nested):
    path, approval, _ = request_file(tmp_path)
    profile_file = Path(approval['profile_file'])
    profile = json.loads(profile_file.read_text())
    if nested:
        profile['price']['secret'] = 'TEST_ONLY_MUST_NOT_APPEAR'
    else:
        profile['api_key'] = 'TEST_ONLY_MUST_NOT_APPEAR'
    profile_file.write_text(json.dumps(profile))
    approval['profile_sha256'] = sha(profile_file)
    path.write_text(json.dumps(approval))
    with pytest.raises(ValueError, match='PROVIDER_PUBLIC_FIELDS'):
        authorization(path)
    result = subprocess.run([sys.executable, '-O', '.agent/harness/live_provider_run.py', '--approval', str(path), '--execute'], capture_output=True, text=True)
    assert result.returncode != 0 and 'PROVIDER_PUBLIC_FIELDS' in result.stderr
    assert 'TEST_ONLY_MUST_NOT_APPEAR' not in result.stdout + result.stderr
