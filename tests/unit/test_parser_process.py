"""Verify separate parser environments with real interpreter imports."""
import json
import subprocess
import venv
from pathlib import Path


def test_child_imports_its_own_environment(tmp_path):
    root = Path(__file__).resolve().parents[2]
    interpreters = []
    for name in ('parent', 'child'):
        directory = tmp_path / name
        venv.EnvBuilder(with_pip=False, symlinks=True).create(directory)
        interpreter = directory / 'bin/python'
        site = subprocess.check_output([str(interpreter), '-c',
            'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip()
        (Path(site) / 'environment_marker.py').write_text(f'VALUE = {name!r}')
        interpreters.append(str(interpreter))
    output = tmp_path / 'imported.json'
    command = [interpreters[1], '-c',
        f'import environment_marker, json; from pathlib import Path; Path({str(output)!r}).write_text(json.dumps(environment_marker.VALUE))']
    parent_script = f'''
import sys
sys.path.insert(0, {str(root)!r})
import environment_marker
assert environment_marker.VALUE == 'parent'
from workers.parser.process import ParserProcess
process = ParserProcess({command!r})
process.start()
process.join(timeout=10)
assert not process.is_alive()
assert process.exitcode == 0
'''
    subprocess.run([interpreters[0], '-c', parent_script], check=True, timeout=20)
    assert json.loads(output.read_text()) == 'child'
