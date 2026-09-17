"""Prepare an isolated real lost-response fault for independent agent UI review.

The prepare phase deliberately leaves its named project running; verify proves the
same unknown attempt was explicitly acknowledged and retried. Cleanup only removes
that recorded project's containers, retaining its new evidence volumes.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import uuid


sys.path.insert(0, str(ROOT))
from harness.live_provider_run import run_recorded_command

DEFAULTS = {
    'APP_IMAGE': 'sha256:cf026d80b2a9a337f9528e78238258508cf24119208e0ce99265dd16661ee52e',
    'PARSER_IMAGE': 'sha256:7e2732e340e9c148663918d5d75977f50b66908071c2fbb265fa08af9ede39f6',
    'DATABASE_IMAGE': 'sha256:04a249fe1c97c960a51b8630d0cec6b82a9a8ee87a78933c1e15bccbd669ff2a',
}

VERIFY = '''
import json
from pathlib import Path
from sqlalchemy import select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Attempt,Job,Permit,SegmentVersion,Task
from packages.billing.ledger import budget_totals
db=Database(Config.load());out=Path('/evidence')
with db.transaction() as s:
 job=s.get(Job,'fault_job')
 task=s.scalar(select(Task).where(Task.job_id==job.id,Task.id!='fault_planner'))
 attempts=list(s.scalars(select(Attempt).where(Attempt.task_id==task.id).order_by(Attempt.fence)))
 assert job.status in ('ready','needs_review') and task.status=='succeeded',(job.status,task.status)
 assert len(attempts)==2 and task.fence==2 and task.attempts==2
 old,new=attempts;permits={p.attempt_id:p for p in s.scalars(select(Permit))}
 assert old.state=='outcome_unknown' and old.usage is None
 assert permits[old.id].state=='unknown' and permits[old.id].actual_micro is None
 assert {e.get('kind') for e in old.evidence}>={'record_evidence','retry_accept_risk'}
 assert new.state=='settled' and permits[new.id].state=='settled' and permits[new.id].actual_micro==150
 assert len(list(s.scalars(select(SegmentVersion).where(SegmentVersion.draft_id=='draft_fixture',SegmentVersion.block_id=='item'))))==1
 calls=json.loads((out/'fake-provider-counter.json').read_text())['calls'];assert calls==2
 totals=budget_totals(s);assert totals['unknown_micro']==permits[old.id].reserved_micro and totals['actual_micro']==150
 facts={'status':'passed','same_task_id':task.id,'original_unknown_attempt':old.id,'retry_attempt':new.id,
  'old_unknown_usage':old.usage,'old_unknown_risk_retained_micro':permits[old.id].reserved_micro,
  'old_attempt_ui_evidence':old.evidence,'new_simulated_actual_micro':150,'budget_totals':totals,
  'fake_calls_total':calls,'automatic_second_call_before_ui':False,'live_provider_requests':0,
  'target_versions':1,'scope':'Actual SIGKILL/natural recovery and independent explicit UI actions; responses and costs are simulated.'}
(out/'verified-retry.json').write_text(json.dumps(facts,indent=2));print(json.dumps(facts))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'verify', 'cleanup'])
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    if args.phase == 'prepare':
        if args.run_dir is not None:
            raise ValueError('Prepare always creates a fresh unique evidence directory.')
        out = ROOT / '.agent/tmp/evidence/unknown-risk-ui' / uuid.uuid4().hex[:8]
        out.mkdir(parents=True, exist_ok=False)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        runtime = {'project': 'bilingual-unknown-ui-' + uuid.uuid4().hex[:8], 'port': port,
            'images': {k: os.environ.get('ACCEPTANCE_' + k, v) for k, v in DEFAULTS.items()},
            'status': 'preparing', 'provider_kind': 'explicit CountingFake', 'external_provider_requests': 0}
        override = {'services': {
            'app': {'environment': {'PYTHONPATH': '/app/src:/app:/harness'}, 'volumes': [
                (ROOT / '.agent/harness').as_posix() + ':/harness:ro',
                (ROOT / 'tests/support.py').as_posix() + ':/tests/support.py:ro',
                (ROOT / 'tests/fixtures').as_posix() + ':/app/tests/fixtures:ro', out.as_posix() + ':/evidence']},
            'worker': {'command': ['python', '/harness/unknown_retry_worker.py'], 'restart': 'no',
                'volumes': [(ROOT / '.agent/harness').as_posix() + ':/harness:ro', out.as_posix() + ':/evidence']}},
            'networks': {'http': {'internal': False}, 'backend': {'internal': True}, 'provider_egress': {'internal': True}}}
        (out / 'override.json').write_text(json.dumps(override, indent=2))
        (out / 'runtime.json').write_text(json.dumps(runtime, indent=2))
    else:
        if args.run_dir is None:
            raise ValueError('The recorded run directory is required.')
        out = args.run_dir.resolve()
        if not out.is_relative_to((ROOT / '.agent/tmp/evidence/unknown-risk-ui').resolve()):
            raise ValueError('Run directory is outside the controlled evidence area.')
        runtime = json.loads((out / 'runtime.json').read_text())
    if not re.fullmatch(r'bilingual-unknown-ui-[a-f0-9]{8}', runtime['project']):
        raise ValueError('Unexpected project name.')
    if not all(re.fullmatch(r'sha256:[a-f0-9]{64}', v) for v in runtime['images'].values()):
        raise ValueError('Only inspected immutable image IDs are supported.')
    empty = ROOT / 'deployment/provider_key.empty'
    if empty.read_bytes() != b'':
        raise ValueError('Only the fixed empty Provider key is allowed.')
    env = {**os.environ, **runtime['images'], 'PORT': str(runtime['port']), 'BIND_ADDRESS': '127.0.0.1',
        'PROVIDER_KEY_FILE': str(empty), 'APP_ORIGINS': 'http://127.0.0.1:' + str(runtime['port'])}
    commands = json.loads((out / 'commands.json').read_text()) if (out / 'commands.json').exists() else []
    base = ['docker', 'compose', '-f', 'deployment/compose.production.yaml', '-f', str(out / 'override.json'), '-p', runtime['project']]
    def command(argv, timeout=240):
        return run_recorded_command(argv, env=env, commands=commands, evidence_path=out / 'commands.json', timeout=timeout)
    def call(*args, timeout=240):
        return command(base + list(args), timeout)
    if args.phase == 'prepare':
        try:
            command(['docker', 'image', 'inspect', *runtime['images'].values()])
            call('up', '-d', '--wait', '--no-build', '--pull', 'never')
            networks = json.loads(command(['docker', 'network', 'inspect', *[runtime['project'] + '_' + n for n in ('backend', 'provider_egress')]]))
            if not all(n['Internal'] for n in networks):
                raise RuntimeError('Worker networks must be internal.')
            worker = call('ps', '-q', 'worker').strip()
            info = json.loads(command(['docker', 'inspect', worker, call('ps', '-q', 'parser').strip()]))
            if set(info[0]['NetworkSettings']['Networks']) != {runtime['project'] + '_' + n for n in ('backend', 'provider_egress')} or info[1]['HostConfig']['NetworkMode'] != 'none':
                raise RuntimeError('Unexpected worker/parser network exposure.')
            call('stop', 'worker')
            call('exec', '-T', 'app', 'python', '/harness/translation_kill_product.py', 'prepare')
            call('exec', '-T', 'app', 'python', '/harness/translation_kill_product.py', 'queue')
            call('start', 'worker')
            deadline = time.monotonic() + 60
            while not (out / 'translation-kill-barrier.json').exists() and time.monotonic() < deadline:
                time.sleep(.2)
            if not (out / 'translation-kill-barrier.json').exists():
                raise RuntimeError('No after-response barrier reached.')
            call('exec', '-T', 'app', 'python', '/harness/translation_kill_product.py', 'barrier')
            command(['docker', 'kill', '--signal', 'KILL', worker])
            killed = json.loads(command(['docker', 'inspect', worker]))[0]
            if killed['State']['ExitCode'] != 137:
                raise RuntimeError('The worker was not actually killed at the response barrier.')
            (out / 'worker-killed.json').write_text(json.dumps(killed, indent=2))
            command(['docker', 'start', worker])
            call('exec', '-T', 'app', 'python', '/harness/translation_kill_product.py', 'recovered', timeout=150)
            runtime.update(status='waiting_for_independent_ui', url='http://127.0.0.1:' + str(runtime['port']) + '/#/jobs/fault_job',
                actual_exit_code=137, natural_lease_recovery=True, cleanup_required=True)
        except BaseException as error:
            runtime.update(status='failed', error_type=type(error).__name__, cleanup_required=True)
            raise
        finally:
            (out / 'runtime.json').write_text(json.dumps(runtime, indent=2))
            print(json.dumps({'evidence': str(out), **runtime}))
    elif args.phase == 'verify':
        if runtime['status'] != 'waiting_for_independent_ui':
            raise RuntimeError('Inspect the recorded state before verification.')
        call('exec', '-T', 'app', 'python', '-c', VERIFY)
        runtime['status'] = 'verified_pending_cleanup'
        (out / 'runtime.json').write_text(json.dumps(runtime, indent=2))
    else:
        call('logs', '--no-color', '--tail', '100', 'app', 'worker', 'parser')
        call('down', '--remove-orphans')
        remaining = command(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + runtime['project']]).strip()
        if remaining:
            raise RuntimeError('Project containers remain.')
        runtime.update(cleanup_required=False, remaining_containers=[], volumes_retained=True)
        (out / 'runtime.json').write_text(json.dumps(runtime, indent=2))


if __name__ == '__main__':
    main()
