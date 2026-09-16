"""Relocated harness paths preserve historical bytes without granting host access."""
import hashlib
from pathlib import Path

import pytest

from harness._project import ROOT, artifact_path, output_path
from harness import acceptance


def test_root_is_product_root_and_legacy_record_hash_remains_valid(tmp_path):
    assert (ROOT / 'pyproject.toml').is_file() and (ROOT / 'packages').is_dir()
    target = tmp_path / '.agent/tmp/evidence/run/result.json'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"original":true}\n')
    original = {'path': 'evidence/run/result.json', 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    result = acceptance.safe_evidence(original['path'], tmp_path)
    assert result['sha256'] == original['sha256']
    assert result['path'] == '.agent/tmp/evidence/run/result.json'
    assert original['path'] == 'evidence/run/result.json'
    assert target.read_bytes() == b'{"original":true}\n'


@pytest.mark.parametrize('old,new', [
    ('harness/memory/current.md', '.agent/memory/current.md'),
    ('harness/gate-policy.json', '.agent/harness/gate-policy.json'),
    ('notes/handoff.md', '.agent/notes/handoff.md'),
    ('reports/check.xml', '.agent/tmp/reports/check.xml'),
    ('apps/web/evidence/review.json', '.agent/tmp/frontend/evidence/review.json'),
    ('.local-data/live-provider/used.json', '.agent/local-data/live-provider/used.json'),
    ('package-validation.json', '.agent/tmp/validation/package-validation.json'),
    ('html/package-review.html', '.agent/tmp/validation/package-review.html'),
    ('bilingual-library-personal-pdf-v3/evidence/run.json', '.agent/tmp/evidence/run.json'),
    ('fixtures/sample.pdf', 'fixtures/sample.pdf'),
])
def test_exact_legacy_prefixes_map_inside_repository(tmp_path, old, new):
    assert artifact_path(old, tmp_path) == tmp_path / new


def test_relocation_contract_matches_mapper():
    import json
    contract = json.loads((ROOT / '.agent/relocation.json').read_text(encoding='utf-8'))
    for old, new in contract['files'].items():
        assert artifact_path(old) == ROOT / new
    for old, new in contract['prefixes'].items():
        assert artifact_path(old + 'example') == ROOT / (new + 'example')
    assert artifact_path(contract['previous_project_prefix'] + 'fixtures/sample.pdf') == ROOT / 'fixtures/sample.pdf'


@pytest.mark.parametrize('bad', ['../outside', 'evidence/../../outside', '/etc/passwd',
    'C:/old/evidence/result.json', 'C:relative', '\\\\server\\share\\file', 'https://example.invalid/file'])
def test_artifact_resolution_never_opens_host_or_parent_paths(tmp_path, bad):
    with pytest.raises(ValueError):
        artifact_path(bad, tmp_path)


def test_outputs_are_temporary_and_authorization_receipts_are_not(tmp_path):
    assert output_path('evidence/new', tmp_path) == tmp_path / '.agent/tmp/evidence/new'
    with pytest.raises(ValueError):
        output_path('.local-data/live-provider/used.json', tmp_path)
    with pytest.raises(ValueError):
        output_path('packages/generated.py', tmp_path)


def test_evidence_symlink_to_outside_is_rejected(tmp_path):
    external = tmp_path / 'outside.json'
    external.write_text('outside')
    evidence = tmp_path / '.agent/tmp/evidence'
    evidence.mkdir(parents=True)
    try:
        (evidence / 'link.json').symlink_to(external)
    except OSError:
        pytest.skip('OS does not permit creating test symlinks')
    with pytest.raises(ValueError):
        acceptance.safe_evidence('evidence/link.json', tmp_path)


def test_fingerprint_tracks_harness_but_not_agent_state(tmp_path):
    code = tmp_path / '.agent/harness/check.py'
    code.parent.mkdir(parents=True)
    code.write_text('version = 1')
    baseline = acceptance.fingerprint(tmp_path)
    for name in ['tmp/evidence/result.json', 'memory/current.md', 'notes/handoff.md',
                 'local-data/live-provider/used.json', 'IMPLEMENTATION_STATUS.md']:
        file = tmp_path / '.agent' / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('state changed')
    assert acceptance.fingerprint(tmp_path) == baseline
    old_disk = tmp_path / 'bilingual-library-personal-pdf-v3/.local-data/host/ext4.vhdx'
    old_disk.parent.mkdir(parents=True)
    old_disk.write_text('locked legacy disk is outside the source fingerprint')
    assert acceptance.fingerprint(tmp_path) == baseline
    code.write_text('version = 2')
    assert acceptance.fingerprint(tmp_path) != baseline


@pytest.mark.parametrize('local_file', [
    'compose.yaml', '.vscode/settings.json', 'provider_config/profile.json',
    'deployment/provider_key.private',
])
def test_fingerprint_never_reads_local_configuration(tmp_path, monkeypatch, local_file):
    source = tmp_path / 'packages/example.py'
    source.parent.mkdir()
    source.write_text('version = 1')
    baseline = acceptance.fingerprint(tmp_path)
    local = tmp_path / local_file
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text('synthetic local configuration')
    original_digest = acceptance.digest

    def source_digest(path):
        assert Path(path) != local, 'Source fingerprint must not read private local configuration'
        return original_digest(path)

    monkeypatch.setattr(acceptance, 'digest', source_digest)
    assert acceptance.fingerprint(tmp_path) == baseline
    source.write_text('version = 2')
    assert acceptance.fingerprint(tmp_path) != baseline
