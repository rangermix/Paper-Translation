"""Orchestrate a fresh, wholly internal Compose matrix and preserve every command."""

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




def main():
    suffix = uuid.uuid4().hex[:8]
    project = 'bilingual-pdf-matrix-' + suffix
    output = ROOT / '.agent/tmp/evidence/pdf-security-matrix' / suffix
    output.mkdir(parents=True)
    offline_override = write_offline_override(output)
    override = output / 'override.yaml'
    override.write_text('services:\n  app:\n    volumes:\n      - ' + json.dumps(str(ROOT / 'tests/fixtures/security').replace('\\', '/') + ':/security-fixtures:ro') + '\n      - ' + json.dumps(str(output).replace('\\', '/') + ':/security-evidence') + '\n')
    env = {**os.environ, "COMPOSE_PROFILES": "", 'PORT': '18086', 'APP_IMAGE': os.environ.get('ACCEPTANCE_APP_IMAGE', 'bilingual-personal-pdf-app:acceptance-candidate'),
        'PARSER_IMAGE': os.environ.get('ACCEPTANCE_PARSER_IMAGE', 'bilingual-personal-pdf-parser:acceptance-candidate')}
    commands = []
    def call(arguments, timeout=240):
        completed = subprocess.run(arguments, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        commands.append({'argv': arguments, 'exit_code': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2))
        assert completed.returncode == 0, completed.stderr[-2000:] + completed.stdout[-2000:]
        return completed.stdout
    def compose(*arguments):
        return call(['docker', 'compose', '-f', 'compose.example.yaml', '-f', str(offline_override),
            '-f', str(override), '-p', project, *arguments])
    try:
        call(['docker', 'image', 'inspect', env['APP_IMAGE'], env['PARSER_IMAGE']])
        compose('up', '-d', '--wait', '--no-build', '--pull', 'never')
        parser_id = compose('ps', '-q', 'parser').strip()
        parser_config = json.loads(call(['docker', 'inspect', parser_id]))[0]
        assert parser_config['HostConfig']['NetworkMode'] == 'none'
        assert not any('SECRET' in item or 'PROVIDER_KEY' in item or 'DATABASE' in item for item in parser_config['Config']['Env'])
        networks = json.loads(call(['docker', 'network', 'inspect', project + '_backend', project + '_http', project + '_provider_egress']))
        assert all(network['Internal'] for network in networks)
        compose('exec', '-T', 'app', 'python', '/harness/pdf_security_product.py')
        compose('logs', '--no-color', '--tail', '100', 'worker', 'parser')
        print(json.dumps({'project': project, 'result': str(output / 'result.json'), 'status': 'passed', 'parser_network': 'none', 'all_networks_internal': True}))
    finally:
        try:
            compose('logs', '--no-color', '--tail', '100', 'app', 'worker', 'parser')
        except Exception:
            pass
        compose('down', '--remove-orphans')


if __name__ == '__main__':
    main()
