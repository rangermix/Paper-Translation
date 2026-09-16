"""Run inside an immutable, network-none parser image; inventory real native linkage.

Mount a fresh run directory at /result, or pass a new --output file.
"""

if __package__:
    from ._project import ROOT
else:
    from _project import ROOT
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import tempfile

from packages.parsers.models import verify_models
from workers.parser.health import main as health
from workers.parser.main import ModelHealth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='/result/native-runtime.json',
        help='New evidence file in the mounted run directory; existing files are never replaced.')
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        raise ValueError('Output already exists; use a new run directory')

    opencv = {}
    for name in ('opencv-contrib-python', 'opencv-contrib-python-headless',
                 'opencv-python', 'opencv-python-headless'):
        try:
            opencv[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    assert len(opencv) == 1, 'Exactly one OpenCV distribution must provide the cv2 namespace'
    distribution = next(iter(opencv))
    try:
        importlib.metadata.version('pip')
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError('pip unexpectedly installed')

    import cv2
    import numpy as np
    converted = cv2.cvtColor(np.zeros((4, 4, 3), dtype=np.uint8), cv2.COLOR_BGR2GRAY)
    assert converted.shape == (4, 4)
    modules = list(Path(cv2.__file__).parent.glob('*.so'))
    assert len(modules) == 1
    linked = subprocess.check_output(['ldd', str(modules[0])], text=True)
    assert 'not found' not in linked.lower(), 'OpenCV has missing native dependencies'
    verify_models('/opt/docling/models')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='runtime-health-', dir=destination.parent) as temporary:
        output = Path(temporary)
        ModelHealth(output, '/opt/docling/models').heartbeat()
        previous = os.environ.get('PARSER_OUTPUTS')
        os.environ['PARSER_OUTPUTS'] = str(output)
        try:
            health()
        finally:
            if previous is None:
                os.environ.pop('PARSER_OUTPUTS', None)
            else:
                os.environ['PARSER_OUTPUTS'] = previous
    packages = {name: importlib.metadata.version(name)
        for name in ('docling', 'torch', 'torchvision', 'pypdfium2', 'pypdf')}
    packages.update(opencv)
    result = {'status': 'passed', 'uid': os.getuid(), 'versions': packages,
        'opencv_distribution': distribution, 'cv2_real_conversion': True,
        'native_linkage': linked,
        'opencv_gui_libraries_linked': any(name in linked.lower() for name in ('libqt', 'libgl.so', 'libglib')),
        'all_locked_model_hashes_verified': True, 'current_heartbeat_health': 'passed',
        'network': 'not_inspected; caller must enforce --network none', 'runtime_pip_present': False,
        'native_vulnerability_assessment': {'status': 'not_run',
            'reason': 'Observed native linkage is an inventory, not a vulnerability assessment.'}}
    with destination.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__=='__main__':main()
