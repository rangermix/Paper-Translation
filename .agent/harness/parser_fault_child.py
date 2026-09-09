"""Acceptance-only real child failures; production parser files remain unchanged."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import resource
import time

import workers.parser.main as service


def resource_fault(request, source, output):
    limit = 64 * 1024 * 1024
    (Path(output) / 'fault-injection.json').write_text(json.dumps({
        'fault': 'real_RLIMIT_AS_allocation_failure', 'pid': os.getpid(),
        'address_space_limit_bytes': limit, 'attempted_allocation_bytes': 256 * 1024 * 1024}))
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    # An actual allocation is denied by the Linux process limit. Do not simulate
    # a successful PDF parse or label this an organically malicious-PDF OOM.
    bytearray(256 * 1024 * 1024)
    raise RuntimeError('Expected operating-system memory limit did not apply')


def timeout_fault(request, source, output):
    (Path(output) / 'fault-injection.json').write_text(json.dumps({
        'fault': 'actual_child_exceeds_natural_deadline', 'pid': os.getpid(), 'sleep_seconds': 30}))
    time.sleep(30)


def untrusted_payload(request, source, output):
    (Path(output) / 'payload.json').write_text('{}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=['resource', 'timeout', 'path', 'stale'], required=True)
    args = parser.parse_args()
    outputs = Path('/outputs')
    health = service.ModelHealth(outputs, '/opt/docling/models')
    health.heartbeat()
    original = service.validate_request
    def validate(value):
        checked = original(value)
        if checked.get('operation') != 'parse':
            raise ValueError('Fault harness only targets parse jobs')
        if args.case == 'timeout':
            checked = {**checked, 'deadline': (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()}
        return checked
    service.validate_request = validate
    service.process_request = {'resource': resource_fault, 'timeout': timeout_fault,
        'path': untrusted_payload, 'stale': untrusted_payload}[args.case]
    original_finish = service.finish
    def finish(path, request, status, error=None):
        original_finish(path, request, status, error)
        if args.case in ('path', 'stale'):
            result = json.loads(path.read_text())
            if args.case == 'path':
                result['files'][0]['path'] = '../../outside-parser-attempt.txt'
            else:
                result['fence'] += 1
            path.write_text(json.dumps(result))
    service.finish = finish
    limit = time.monotonic() + 20
    while time.monotonic() < limit:
        if service.run_once('/inputs', outputs, health.heartbeat):
            print(json.dumps({'fault_case': args.case, 'processed': True}))
            return
        health.heartbeat()
        time.sleep(.1)
    raise TimeoutError('No parse descriptor reached the isolated parser')


if __name__ == '__main__':
    main()
