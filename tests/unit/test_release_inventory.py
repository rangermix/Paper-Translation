"""Release evidence collection never infers a current candidate or native scan."""
import json
import sys

import pytest

from harness import release_inventory


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(release_inventory, 'ROOT', tmp_path)
    scans = tmp_path / '.agent/tmp/evidence/release'
    scans.mkdir(parents=True)
    monkeypatch.setattr(release_inventory, 'DIRECTORY', scans)
    for name in ('pyproject.toml', 'uv.lock', 'src/apps/web/package-lock.json', 'deployment/parser-models.lock.json'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic locked input')
    candidates = []
    images = {}
    for role, symbol in [('app', 'a'), ('parser', 'b'), ('database', 'c')]:
        image = 'sha256:' + symbol * 64
        candidates += ['--candidate', role, image, role + '-historic-scan']
        images[image] = {'Id': image, 'Os': 'linux', 'Architecture': 'amd64', 'Created': '2026-09-16T00:00:00Z',
            'Config': {'Labels': {}}, 'RootFS': {'Layers': ['sha256:' + symbol * 64]}}
    calls = []
    def inspect(command, **kwargs):
        assert command[:3] == ['docker', 'image', 'inspect']
        calls.append(command[-1])
        return json.dumps([images[command[-1]]])
    monkeypatch.setattr(release_inventory.subprocess, 'check_output', inspect)
    return tmp_path, scans, candidates, calls


def invoke(monkeypatch, args):
    monkeypatch.setattr(sys, 'argv', ['release_inventory.py', *args])
    release_inventory.main()


def test_candidates_are_required_before_any_docker_access(inventory, monkeypatch):
    _, _, _, calls = inventory
    with pytest.raises(SystemExit) as failure:
        invoke(monkeypatch, [])
    assert failure.value.code == 2
    assert not calls


def test_absent_native_evidence_is_not_run_and_each_run_preserves_prior_outputs(inventory, monkeypatch, capsys):
    root, scans, candidates, _ = inventory
    scan = scans / 'app-historic-scan-vulnerability-license.json'
    scan.write_text(json.dumps({'Metadata': {'ImageID': 'sha256:' + 'a' * 64,
        'DiffIDs': ['sha256:' + 'a' * 64]}, 'Results': []}))
    original = scan.read_bytes()
    # A historical artifact must not become an implicit current assessment.
    stale = root / '.agent/tmp/evidence/parser-final-runtime/native-runtime.json'
    stale.parent.mkdir(parents=True)
    stale.write_text('{"finding":"stale historical finding"}')
    manifests = []
    for _ in range(2):
        invoke(monkeypatch, candidates)
        result = json.loads(capsys.readouterr().out)
        manifest = root / result['manifest_path']
        report = json.loads(manifest.read_text())
        assert report['native_linkage_evidence']['status'] == 'not_run'
        assert 'finding' not in report['native_linkage_evidence']
        app = next(row for row in report['images'] if row['role'] == 'app')
        assert app['scan_matches_current_image_layers'] is True
        assert app['scan_path'] == scan.relative_to(root).as_posix()
        manifests.append((manifest, manifest.read_bytes()))
    assert manifests[0][0].parent != manifests[1][0].parent
    assert manifests[0][0].read_bytes() == manifests[0][1]
    assert scan.read_bytes() == original


def test_explicit_native_evidence_is_linked_without_inventing_a_finding(inventory, monkeypatch, capsys):
    root, _, candidates, _ = inventory
    evidence = root / '.agent/tmp/current-native.json'
    evidence.write_text(json.dumps({'native_linkage': 'synthetic inspected linkage'}))
    invoke(monkeypatch, [*candidates, '--native-evidence', evidence.relative_to(root).as_posix()])
    result = json.loads(capsys.readouterr().out)
    report = json.loads((root / result['manifest_path']).read_text())
    assert report['native_linkage_evidence'] == {
        'status': 'provided', 'path': evidence.relative_to(root).as_posix(),
        'sha256': release_inventory.sha(evidence), 'candidate_binding': 'not_verified'}
    assert report['release_approved'] is False


@pytest.mark.parametrize('extra', [
    ['--candidate', 'app', 'sha256:' + 'a' * 64, 'duplicate'],
    ['--output-dir', '.agent/local-data/preserved'],
])
def test_ambiguous_candidates_and_persistent_output_locations_are_rejected(inventory, monkeypatch, extra):
    _, _, candidates, calls = inventory
    with pytest.raises((SystemExit, ValueError)):
        invoke(monkeypatch, [*candidates, *extra])
    assert not calls


def test_mutable_image_tags_are_rejected_before_docker_access(inventory, monkeypatch):
    _, _, candidates, calls = inventory
    candidates[2] = 'parser:latest'
    with pytest.raises(ValueError, match='immutable sha256'):
        invoke(monkeypatch, candidates)
    assert not calls
