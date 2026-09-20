"""Runtime imports and immutable resources must work outside the checkout cwd."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_source_imports_load_runtime_resources_from_an_unrelated_directory(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = '''
import json
from packages.ir import validate_ir
from packages.parsers.models import parser_version
from packages.seed.legacy import checked_release
from packages.templates.registry import list_templates
from workers.parser.process import ParserProcess
from tools.export_parser_model import export_model
print(json.dumps({"seeds": len(checked_release()["documents"]),
                  "templates": [row["id"] for row in list_templates()],
                  "parser_version": parser_version()}))
'''
    environment = dict(os.environ, PYTHONPATH=str(root / 'src'))
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
        env=environment, text=True, capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert data['seeds'] == 2
    assert data['templates'] == ['reader-v1', 'reader-v2', 'reader-v3', 'reader-v4', 'reader-v5', 'reader-v6']
    assert data['parser_version']
