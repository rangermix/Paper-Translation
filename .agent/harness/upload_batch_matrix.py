"""Fresh isolated Compose execution of the literal three-valid/one-invalid batch."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import os
from pathlib import Path
import subprocess
import uuid




def main():
    suffix = uuid.uuid4().hex[:8]
    project = 'bilingual-upload-batch-' + suffix
    output = ROOT / '.agent/tmp/evidence/upload-batch' / suffix
    output.mkdir(parents=True)
    override = output / 'override.json'
    override.write_text(json.dumps({'services': {'app': {'volumes': [
        str(ROOT / 'fixtures').replace('\\', '/') + ':/batch-fixtures:ro',
        str(output).replace('\\', '/') + ':/batch-evidence']}}}), encoding='utf-8')
    env = {**os.environ, 'PORT': '18087',
        'APP_IMAGE': os.environ.get('ACCEPTANCE_APP_IMAGE', 'bilingual-personal-pdf-app:acceptance-candidate'),
        'PARSER_IMAGE': os.environ.get('ACCEPTANCE_PARSER_IMAGE', 'bilingual-personal-pdf-parser:acceptance-candidate'),
        'DATABASE_IMAGE': os.environ.get('ACCEPTANCE_DATABASE_IMAGE', 'bilingual-personal-pdf-db:acceptance-candidate')}
    commands = []
    def call(argv):
        try:
            completed = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=240)
            record = {'argv': argv, 'exit_code': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr}
        except subprocess.TimeoutExpired as error:
            record = {'argv': argv, 'status': 'timeout', 'stdout': str(error.stdout or ''), 'stderr': str(error.stderr or '')}
        commands.append(record)
        (output / 'commands.json').write_text(json.dumps(commands, indent=2), encoding='utf-8')
        assert record.get('exit_code') == 0, str(record)[-3000:]
        return record['stdout']
    def compose(*args):
        return call(['docker', 'compose', '-f', 'deployment/compose.production.yaml', '-f', 'deployment/compose.acceptance-offline.yaml',
            '-f', str(override), '-p', project, *args])
    try:
        call(['docker', 'image', 'inspect', env['APP_IMAGE'], env['PARSER_IMAGE'], env['DATABASE_IMAGE']])
        compose('up', '-d', '--wait', '--no-build', '--pull', 'never')
        networks = json.loads(call(['docker', 'network', 'inspect', project+'_backend', project+'_http', project+'_provider_egress']))
        assert all(network['Internal'] for network in networks)
        parser_config = json.loads(call(['docker', 'inspect', compose('ps', '-q', 'parser').strip()]))[0]
        assert parser_config['HostConfig']['NetworkMode'] == 'none'
        compose('exec', '-T', 'app', 'python', '/harness/upload_batch_product.py')
        print(json.dumps({'status': 'passed', 'project': project, 'result': str(output / 'result.json')}))
    finally:
        try:
            compose('logs', '--no-color', '--tail', '100', 'app', 'worker', 'parser')
        finally:
            compose('down', '--remove-orphans')
        assert not call(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project='+project]).strip()


if __name__ == '__main__':
    main()
