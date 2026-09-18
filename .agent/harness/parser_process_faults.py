"""Fresh offline Compose; injected real child faults leave API and DB usable."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
    from ._compose import write_offline_override
else:
    from _project import ROOT, artifact_path, output_path
    from _compose import write_offline_override
import json
import os
from pathlib import Path
import subprocess
import uuid

from acceptance import redact




def main():
    suffix = uuid.uuid4().hex[:8]
    project = 'bilingual-parser-fault-' + suffix
    output = ROOT / '.agent/tmp/evidence/parser-process-faults' / suffix
    output.mkdir(parents=True)
    mounts = [str(ROOT / '.agent/harness').replace('\\', '/') + ':/harness:ro',
        str(output).replace('\\', '/') + ':/fault-evidence']
    offline_override = write_offline_override(output)
    override = output / 'override.json'
    override.write_text(json.dumps({'services': {'app': {'volumes': mounts + [
        (ROOT / 'tests/fixtures').as_posix() + ':/app/fixtures:ro']}, 'parser': {'volumes': mounts}}}))
    env = {**os.environ, "COMPOSE_PROFILES": "", 'PORT': '18093',
        'APP_IMAGE': os.environ.get('ACCEPTANCE_APP_IMAGE', 'bilingual-personal-pdf-app:final-review'),
        'PARSER_IMAGE': os.environ.get('ACCEPTANCE_PARSER_IMAGE', 'bilingual-personal-pdf-parser:final-review'),
        'DATABASE_IMAGE': os.environ.get('ACCEPTANCE_DATABASE_IMAGE', 'bilingual-personal-pdf-db:final-review')}
    commands = []
    def call(argv):
        result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
        commands.append({'argv': argv, 'exit_code': result.returncode, 'stdout': redact(result.stdout), 'stderr': redact(result.stderr)})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2))
        assert result.returncode == 0, redact(result.stderr[-2000:] + result.stdout[-2000:])
        return result.stdout
    def compose(*args):
        return call(['docker', 'compose', '-f', 'compose.example.yaml', '-f', str(offline_override),
            '-f', str(override), '-p', project, *args])
    try:
        call(['docker', 'image', 'inspect', env['APP_IMAGE'], env['PARSER_IMAGE'], env['DATABASE_IMAGE']])
        compose('up', '-d', '--wait', '--no-build', '--pull', 'never')
        compose('exec', '-T', 'app', 'python', '/harness/parser_fault_product.py', 'prepare')
        compose('stop', 'parser')
        for case in ('resource', 'timeout', 'path', 'stale'):
            compose('exec', '-T', 'app', 'python', '/harness/parser_fault_product.py', 'queue', '--case', case)
            compose('run', '--rm', '--no-deps', '--entrypoint', 'python', 'parser', '/harness/parser_fault_child.py', '--case', case)
            compose('exec', '-T', 'app', 'python', '/harness/parser_fault_product.py', 'verify', '--case', case)
        captured = compose('run', '--rm', '--no-deps', '--entrypoint', 'python', 'parser', '-c',
            'import json; from pathlib import Path; r=Path("/outputs"); print(json.dumps({str(p.relative_to(r)):json.loads(p.read_text()) for p in r.glob("*/*/*.json") if p.name in ("result.json","fault-injection.json")}))')
        (output / 'spool-protocol.json').write_text(captured)
        compose('start', 'parser')
        compose('exec', '-T', 'app', 'python', '-c', 'from urllib.request import urlopen; print(urlopen("http://127.0.0.1:8080/health/ready").status)')
        result = {'status': 'passed', 'project': project, 'cases': ['resource', 'timeout', 'path', 'stale'], 'provider_calls': 0,
            'scope': 'Real OS-limited child failure and natural deadline kill, injected in harness only; normal API/worker/DB and original bytes survive.'}
        (output / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        try:
            compose('logs', '--no-color', '--tail', '100', 'app', 'worker', 'parser')
        finally:
            compose('down', '--remove-orphans')


if __name__ == '__main__':
    main()
