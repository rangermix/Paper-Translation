"""Native evidence must describe observed packages/linkage, not historical findings."""
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    cv2 = ModuleType('cv2')
    package = tmp_path / 'cv2'
    package.mkdir()
    (package / 'cv2.abi3.so').write_bytes(b'synthetic native library')
    cv2.__file__ = str(package / '__init__.py')
    cv2.COLOR_BGR2GRAY = 1
    cv2.cvtColor = lambda *args: SimpleNamespace(shape=(4, 4))
    monkeypatch.setitem(sys.modules, 'cv2', cv2)
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace(zeros=lambda *args, **kwargs: None, uint8='uint8'))
    module = importlib.import_module('harness.parser_runtime_dependencies')
    report = tmp_path / 'native-runtime.json'
    monkeypatch.setattr(sys, 'argv', ['parser_runtime_dependencies.py', '--output', str(report)])
    monkeypatch.setattr(module, 'verify_models', lambda _: {})
    monkeypatch.setattr(module, 'ModelHealth', lambda *args: SimpleNamespace(heartbeat=lambda: None))
    monkeypatch.setattr(module, 'health', lambda: None)
    monkeypatch.setattr(module.os, 'getuid', lambda: 10001, raising=False)
    monkeypatch.setenv('PARSER_OUTPUTS', str(tmp_path / 'previous-output'))
    versions = {name: 'synthetic-version' for name in ('docling', 'torch', 'torchvision', 'pypdfium2', 'pypdf')}
    def version(name):
        if name not in versions:
            raise importlib.metadata.PackageNotFoundError(name)
        return versions[name]
    monkeypatch.setattr(module.importlib.metadata, 'version', version)
    return module, report, versions


@pytest.mark.parametrize('distribution,linkage,gui_linked', [
    ('opencv-contrib-python', 'libGL.so.1 => /lib/libGL.so.1\nlibglib-2.0.so.0 => /lib/libglib-2.0.so.0', True),
    ('opencv-python-headless', 'libcrypto.so.3 => /usr/lib/libcrypto.so.3', False),
])
def test_native_report_uses_actual_distribution_and_linkage(runtime, monkeypatch, distribution, linkage, gui_linked):
    module, path, versions = runtime
    versions[distribution] = '4.10.0.84'
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *args, **kwargs: linkage)
    module.main()
    report = json.loads(path.read_text())
    assert report['versions'][distribution] == '4.10.0.84'
    assert report['opencv_distribution'] == distribution
    assert report['native_linkage'] == linkage
    assert report['opencv_gui_libraries_linked'] is gui_linked
    assert report['native_vulnerability_assessment']['status'] == 'not_run'
    assert 'bundled_native_findings' not in report
    assert 'OpenSSL 1.1.1k' not in path.read_text()
    assert module.os.environ['PARSER_OUTPUTS'] == str(path.parent / 'previous-output')


def test_missing_native_library_cannot_produce_a_passing_report(runtime, monkeypatch):
    module, path, versions = runtime
    versions['opencv-contrib-python'] = '4.10.0.84'
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *args, **kwargs: 'librequired.so => not found')
    with pytest.raises(AssertionError):
        module.main()
    assert not path.exists()


def test_overlapping_opencv_distributions_are_rejected(runtime, monkeypatch):
    module, path, versions = runtime
    versions.update({'opencv-contrib-python': '4.10.0.84', 'opencv-python-headless': '4.10.0.84'})
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *args, **kwargs: 'libc.so.6 => /lib/libc.so.6')
    with pytest.raises(AssertionError):
        module.main()
    assert not path.exists()


def test_existing_native_report_is_preserved_before_running_the_probe(runtime):
    module, path, _ = runtime
    path.write_text('historical native evidence')
    with pytest.raises(ValueError, match='Output already exists'):
        module.main()
    assert path.read_text() == 'historical native evidence'
