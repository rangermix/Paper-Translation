"""Fresh offline Compose matrix; defaults require explicit immutable image inputs."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
    from ._compose import provider_override
else:
    from _project import ROOT, artifact_path, output_path
    from _compose import provider_override
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import uuid

from live_provider_run import run_recorded_command




def main():
    images = {key: os.environ['ACCEPTANCE_' + key] for key in ('APP_IMAGE', 'PARSER_IMAGE', 'DATABASE_IMAGE')}
    suffix = uuid.uuid4().hex[:8]
    project = 'bilingual-no-provider-' + suffix
    output = ROOT / '.agent/tmp/evidence/no-provider-runtime' / suffix
    output.mkdir(parents=True)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 18088))
    profile_file = output / 'public-profile.json'
    profile_file.write_text('{}', encoding='utf-8')
    env = {**os.environ, "COMPOSE_PROFILES": "", **images, 'PORT': '18088'}
    override = output / 'override.json'
    injection = provider_override(profile_file)
    injection['services']['app']['volumes'] += [str(ROOT / '.agent/harness') + ':/harness:ro',
            str(ROOT / 'tests/fixtures/live-provider') + ':/no-provider-fixtures:ro',
            str(output) + ':/no-provider-evidence']
    injection['networks'] = {'http': {'internal': True}, 'provider_egress': {'internal': True}}
    override.write_text(json.dumps(injection, indent=2), encoding='utf-8')
    commands = []
    def call(argv, timeout=240):
        return run_recorded_command(argv, env=env, commands=commands, evidence_path=output / 'commands.json', timeout=timeout)
    def compose(*args):
        return call(['docker', 'compose', '-f', 'compose.example.yaml', '-f', str(override), '-p', project, *args])
    result = {'status': 'running', 'project': project, 'images': images,
        'scope': 'Actual offline HTTP/worker/parser; no Provider transport and no translation quality claim.',
        'started_at': datetime.now(timezone.utc).isoformat()}
    try:
        call(['docker', 'image', 'inspect', *images.values()])
        compose('up', '-d', '--wait', '--no-build', '--pull', 'never')
        networks = json.loads(call(['docker', 'network', 'inspect', project + '_http', project + '_backend', project + '_provider_egress']))
        if not all(network['Internal'] for network in networks):
            raise RuntimeError('All application networks must be internal')
        parser = json.loads(call(['docker', 'inspect', compose('ps', '-q', 'parser').strip()]))[0]
        if parser['HostConfig']['NetworkMode'] != 'none':
            raise RuntimeError('Parser requires network none')
        worker = json.loads(call(['docker', 'inspect', compose('ps', '-q', 'worker').strip()]))[0]
        if any(m['Destination'].startswith('/run/secrets/') for m in worker['Mounts']):
            raise RuntimeError('No Provider secret may be mounted in this offline probe')
        compose('exec', '-T', 'worker', 'python', '-c',
            "from pathlib import Path; assert not Path('/run/secrets/provider_key').exists(); assert not Path('/provider_config/current.json').exists()")
        compose('exec', '-T', 'app', 'python', '/harness/no_provider_product.py', 'no-price')
        profile = {'configured': True, 'provider': 'openai', 'model_id': 'offline-no-key-fixture',
            'profile_revision': 'offline-no-key-v1', 'prompt_version': 'translate-v1', 'privacy_revision': 'offline-v1',
            'enabled_pairs': [['en', 'zh-Hans']], 'max_input_tokens': 16384, 'max_output_tokens': 4096,
            'max_unit_characters': 2000, 'price': {'revision': 'offline-fixture', 'currency': 'USD',
                'input_micro_per_million': 1000000, 'cached_input_micro_per_million': 1000000,
                'output_micro_per_million': 1000000, 'output_includes_reasoning': True,
                'input_bound_rule': 'utf8-byte-ceiling-v1'}}
        profile_file.write_text(json.dumps(profile, indent=2), encoding='utf-8')
        compose('exec', '-T', 'app', 'python', '/harness/no_provider_product.py', 'no-key')
        result.update(status='passed', all_networks_internal=True, parser_network_none=True,
            provider_secret_absent=True, external_provider_requests=0,
            no_price=json.loads((output / 'no-price.json').read_text('utf-8')),
            no_key=json.loads((output / 'no-key.json').read_text('utf-8')))
    except BaseException as error:
        result.update(status='failed', error_type=type(error).__name__, error=str(error)[-2000:])
        raise
    finally:
        try:
            compose('logs', '--no-color', '--tail', '100', 'app', 'worker', 'parser')
        finally:
            compose('down', '--remove-orphans')
            remaining = call(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]).strip()
            result.update(remaining_containers=remaining.splitlines() if remaining else [], volumes_retained=True,
                finished_at=datetime.now(timezone.utc).isoformat())
            (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'status': result['status'], 'evidence': str(output), 'remaining': remaining}))
            if remaining:
                raise RuntimeError('Temporary project cleanup incomplete')


if __name__ == '__main__':
    main()
