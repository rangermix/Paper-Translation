"""Run inside immutable, network-none parser image; verify real native linkage."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import time

import cv2
import pypdfium2
from packages.parsers.models import verify_models
from workers.parser.health import main as health
from workers.parser.main import ModelHealth


def main():
    import numpy as np
    converted=cv2.cvtColor(np.zeros((4,4,3),dtype=np.uint8),cv2.COLOR_BGR2GRAY)
    assert converted.shape==(4,4)
    modules=list(Path(cv2.__file__).parent.glob('*.so'))
    assert len(modules)==1
    linked=subprocess.check_output(['ldd',str(modules[0])],text=True)
    assert not any(name in linked.lower() for name in ('not found','libqt','libgl.so','libglib'))
    models=verify_models('/opt/docling/models')
    output=Path('/tmp/runtime-health');output.mkdir()
    ModelHealth(output, '/opt/docling/models').heartbeat()
    os.environ['PARSER_OUTPUTS']=str(output)
    health()
    for name in ('pip','opencv-python'):
        try:importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:pass
        else:raise AssertionError(name+' unexpectedly installed')
    packages={name:importlib.metadata.version(name) for name in ('docling','torch','torchvision','opencv-python-headless','pypdfium2','pypdf')}
    result={'status':'passed','uid':os.getuid(),'versions':packages,'cv2_real_conversion':True,
            'native_linkage':linked,'all_locked_model_hashes_verified':True,'current_heartbeat_health':'passed',
            'network':'none (docker invocation)','runtime_pip_present':False,'opencv_gui_present':False,
            'bundled_native_findings':['Headless OpenCV FFmpeg still links bundled OpenSSL 1.1.1k; this is not a clean native dependency attestation.']}
    Path('/result/native-runtime.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
