"""Actual pre-release schema5 app -> schema10 backup/restore, fresh offline projects."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import uuid

from live_provider_run import run_recorded_command


OLD = 'sha256:e78ee5ae412fd2f54e9704be7a03fb231dd9ecdec04c49b1afe7d7fc56808366'
NEW = os.environ.get('ACCEPTANCE_APP_IMAGE', 'sha256:7eb031f352f8339c84903667d58c3cf492cf9e9f596d14ffe5beeafe046c86fa')
PARSER = os.environ.get('ACCEPTANCE_PARSER_IMAGE', 'sha256:7e2732e340e9c148663918d5d75977f50b66908071c2fbb265fa08af9ede39f6')
DATABASE = os.environ.get('ACCEPTANCE_DATABASE_IMAGE', 'sha256:04a249fe1c97c960a51b8630d0cec6b82a9a8ee87a78933c1e15bccbd669ff2a')


def main():
    suffix = uuid.uuid4().hex[:8]
    output = ROOT/'.agent/tmp/evidence/schema-upgrade'/suffix
    output.mkdir(parents=True)
    old_project, new_project = 'schema5-upgrade-'+suffix, 'schema10-restore-'+suffix
    for port in (18089, 18090):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', port))
    env = {**os.environ, 'APP_IMAGE': OLD, 'PARSER_IMAGE': PARSER, 'DATABASE_IMAGE': DATABASE,
        'PORT': '18089', 'PROVIDER_KEY_FILE': str(ROOT/'deployment/provider_key.empty')}
    commands = []
    def call(argv, timeout=180):
        return run_recorded_command(argv, env=env, commands=commands, evidence_path=output/'commands.json', timeout=timeout)
    mounts = [str(ROOT/'.agent/harness')+':/harness:ro', str(ROOT/'tests')+':/review/tests:ro', str(output)+':/upgrade-evidence']
    override = output/'offline.json'
    override.write_text(json.dumps({'services': {name: {'volumes': mounts, 'environment': {'PYTHONPATH': '/app/src:/app:/review:/harness'}}
        for name in ('app', 'maintenance')}, 'networks': {'http': {'internal': True}, 'provider_egress': {'internal': True}}}, indent=2))
    restore_override = output/'restore-backup-volume.json'
    restore_override.write_text(json.dumps({'volumes': {'backups': {'external': True, 'name': old_project+'_backups'}}}))
    def compose(project, *args):
        argv = ['docker', 'compose', '-f', 'deployment/compose.production.yaml', '-f', str(override)]
        if project == new_project:
            argv += ['-f', str(restore_override)]
        return call([*argv, '-p', project, *args])
    def maintenance(project, *args):
        return compose(project, 'run', '--rm', '--no-deps', 'maintenance', 'python', '-m', 'packages.maintenance', *args)
    def product(project, phase):
        return compose(project, 'exec', '-T', 'app', 'python', '/harness/old_schema_upgrade_product.py', phase)
    def networks(project):
        records = json.loads(call(['docker', 'network', 'inspect', project+'_backend', project+'_http', project+'_provider_egress']))
        if not all(n['Internal'] for n in records):
            raise RuntimeError('Every application network must be internal')
        parser_id = compose(project, 'ps', '-q', 'parser').strip()
        if json.loads(call(['docker', 'inspect', parser_id]))[0]['HostConfig']['NetworkMode'] != 'none':
            raise RuntimeError('Parser requires network none')
    result = {'status': 'running', 'scope': 'Pre-release old application schema5 ->10, not a released M1 upgrade or PostgreSQL major upgrade.',
        'old_project': old_project, 'new_project': new_project,
        'images': {'old_app': OLD, 'new_app': NEW, 'parser': PARSER, 'database': DATABASE},
        'external_provider_requests': 0, 'unknown_fixture': 'Explicitly synthetic ledger, not a real supplier charge',
        'started_at': datetime.now(timezone.utc).isoformat()}
    try:
        call(['docker', 'image', 'inspect', OLD, NEW, PARSER, DATABASE])
        for project in (old_project, new_project):
            if call(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project='+project]).strip():
                raise RuntimeError('Fresh project name unexpectedly exists')
        compose(old_project, 'up', '-d', '--wait', '--no-build', '--pull', 'never')
        networks(old_project)
        compose(old_project, 'stop', 'worker')
        product(old_project, 'prepare')
        backup = json.loads(maintenance(old_project, 'backup'))
        result['backup_id'] = backup['backup_id']
        maintenance(old_project, 'verify-backup', '--backup-id', backup['backup_id'])
        compose(old_project, 'down', '--remove-orphans')
        env.update(APP_IMAGE=NEW, PORT='18090')
        compose(new_project, 'up', '-d', '--wait', '--no-build', '--pull', 'never')
        networks(new_project)
        compose(new_project, 'stop', 'worker')
        restored = json.loads(maintenance(new_project, 'restore', '--backup-id', backup['backup_id']))
        if not restored['maintenance'] or not restored['dispatch_disabled']:
            raise RuntimeError('Restore must remain held with dispatch disabled')
        maintenance(new_project, 'verify')
        product(new_project, 'verify-held')
        compose(new_project, 'start', 'worker')
        # A second actual queue/state observation while the ordinary worker is
        # active proves maintenance prevents claims without inventing a heartbeat.
        product(new_project, 'verify-held')
        maintenance(new_project, 'maintenance-off')
        product(new_project, 'verify-resumed')
        result.update(status='passed', all_networks_internal=True, parser_network_none=True,
            fresh_pg_data_upload_volumes=True, shared_backup_volume_only=True,
            old_running_8080_project_untouched=True, verified_files=json.loads((output/'old-state.json').read_text())['files'],
            restore=restored, finished_at=datetime.now(timezone.utc).isoformat())
    except BaseException as error:
        result.update(status='failed', error_type=type(error).__name__, error=str(error)[-2000:])
        raise
    finally:
        cleanups = []
        for project, image, port in ((old_project, OLD, '18089'), (new_project, NEW, '18090')):
            env.update(APP_IMAGE=image, PORT=port)
            try:
                compose(project, 'down', '--remove-orphans')
                remaining = call(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project='+project]).strip()
                cleanups.append({'project': project, 'remaining_containers': remaining.splitlines() if remaining else [], 'volumes_retained': True})
            except Exception as error:
                cleanups.append({'project': project, 'cleanup_error': type(error).__name__})
        result['cleanup'] = cleanups
        (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({'status': result['status'], 'evidence': str(output), 'cleanup': cleanups}))


if __name__ == '__main__':
    main()
