"""Negative runtime probe: genuinely missing model assets must fail closed."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import os
from pathlib import Path
import time
from workers.parser.health import main as health
from workers.parser.main import ModelHealth

folder=Path('/tmp/missing-model-readiness')
folder.mkdir()
ModelHealth(folder, '/opt/docling/models').heartbeat()
os.environ['PARSER_OUTPUTS']=str(folder)
os.environ['DOCLING_ARTIFACTS_PATH']='/tmp/absent-models'
try:
    health()
except Exception as error:
    code=getattr(error,'code',type(error).__name__)
    assert 'MODEL' in code,code
    print(json.dumps({'status':'passed','scope':'real parser health with fresh heartbeat and absent required models','error':code,'network':'none','download_attempted':False}))
else:
    raise AssertionError('Readiness accepted absent required model assets')
