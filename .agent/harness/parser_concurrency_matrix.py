"""Observe real Linux parser children with three queued PDFs in an offline image.

This proves the serial process cap and progress for a bounded mixed queue. The
separate PostgreSQL queue-fairness test proves inter-job claim rotation; neither
result is replaced by the external Provider's unrelated two-permit limit.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid


def inside(research_paper=None, virtual_limit_gib=None):
    from packages.ir import digest, validate_source
    from packages.parsers.models import parser_version
    from packages.parsers.spool import verify_result, write_request
    from workers.parser.main import ModelHealth, run_once
    root = Path('/result')
    inputs, outputs = root / 'inputs', root / 'outputs'
    outputs.mkdir(parents=True)
    requests = []
    large_pdf = (Path('/papers') / {'efficient': 'Efficiently-Scaling-Transformer-Inference.pdf',
        'pathways': 'Pathways.pdf'}[research_paper]) if research_paper else Path('/fixtures/cross-page-resources/cross-page-resources.pdf')
    deadline_seconds = 300 if research_paper else 150
    for task, operation, pdf in [
        ('a-large-parse', 'parse', large_pdf),
        ('b-small-inspect', 'inspect', Path('/fixtures/live-provider/controlled-en.pdf')),
        ('c-small-inspect', 'inspect', Path('/fixtures/live-provider/controlled-zh.pdf')),
    ]:
        request = {'task_id': task, 'fence': 1, 'source_sha256': digest(pdf.read_bytes()),
            'max_pages': 200, 'deadline': (datetime.now(timezone.utc) + timedelta(seconds=deadline_seconds)).isoformat(),
            'parser_version': parser_version() if operation == 'parse' else 'inspector-v1',
            'operation': operation, 'asset_id': 'original-pdf', 'profile': {'language': 'en'}}
        write_request(inputs, request, pdf)
        requests.append(request)
    health = ModelHealth(outputs, os.environ.get('DOCLING_ARTIFACTS_PATH', '/opt/docling/models'))
    health.heartbeat()
    stopped = threading.Event()
    observations, observed_pids, memory_peaks, address_limits, largest_mappings = [], set(), {}, {}, {}
    parent = os.getpid()

    def observe():
        last = None
        while not stopped.is_set():
            pids = []
            for proc in Path('/proc').glob('[0-9]*'):
                try:
                    # stat's command field may contain spaces; split after its
                    # closing ')' to get state and ppid without misidentifying it.
                    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
                    command = (proc / 'cmdline').read_bytes()
                    if int(fields[1]) == parent and b'spawn_main' in command:
                        pids.append(int(proc.name))
                        values = {line.split(':', 1)[0]: line.split(':', 1)[1].strip()
                            for line in (proc / 'status').read_text().splitlines() if ':' in line}
                        peaks = memory_peaks.setdefault(proc.name, {})
                        previous_vm = peaks.get('VmSize', 0)
                        for name in ('VmPeak', 'VmSize', 'VmRSS', 'VmHWM', 'Threads'):
                            value = int(values.get(name, '0').split()[0])
                            peaks[name] = max(peaks.get(name, 0), value)
                        if int(values.get('VmSize', '0').split()[0]) > previous_vm:
                            mappings = []
                            for mapping in (proc / 'maps').read_text().splitlines():
                                parts = mapping.split()
                                low, high = (int(value, 16) for value in parts[0].split('-'))
                                mappings.append({'bytes': high-low, 'permissions': parts[1], 'path': ' '.join(parts[5:])})
                            largest_mappings[proc.name] = sorted(mappings, key=lambda row: row['bytes'], reverse=True)[:15]
                        for line in (proc / 'limits').read_text().splitlines():
                            if line.startswith('Max address space'):
                                address_limits.setdefault(proc.name, set()).add(line)
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
            current = tuple(sorted(pids))
            observed_pids.update(current)
            if current != last:
                observations.append({'monotonic': time.monotonic(), 'worker_child_pids': list(current)})
                last = current
            stopped.wait(.01)

    watcher = threading.Thread(target=observe)
    watcher.start()
    completed = []
    started = time.monotonic()
    try:
        for index, request in enumerate(requests):
            assert run_once(inputs, outputs, health.heartbeat)
            result = verify_result(outputs / request['task_id'] / '1', request)
            completed.append({'task_id': request['task_id'], 'operation': request['operation'],
                'elapsed_seconds': time.monotonic() - started, 'result': result})
            # Future tasks remain queued and must not have spawned prematurely.
            assert all(not (outputs / later['task_id'] / '1/started.json').exists() for later in requests[index+1:])
        assert run_once(inputs, outputs, health.heartbeat) is False
    finally:
        stopped.set()
        watcher.join(timeout=2)
        report = {'scope': 'actual production serial spool, local Docling plus native inspect; no Provider',
            'parent_pid': parent, 'queued_requests': requests, 'completed': completed,
            'process_transitions': observations, 'distinct_child_pids': sorted(observed_pids),
            'child_peak_status_kib_except_threads': memory_peaks,
            'observed_address_space_limits': {pid: sorted(values) for pid, values in address_limits.items()},
            'largest_mappings_at_peak_vm': largest_mappings,
            'allocator_arena_max': os.environ.get('MALLOC_ARENA_MAX'),
            'cgroup_memory': {name: (Path('/sys/fs/cgroup') / name).read_text()
                for name in ('memory.max', 'memory.current', 'memory.peak', 'memory.events') if (Path('/sys/fs/cgroup') / name).is_file()},
            'max_simultaneous_worker_children': max((len(o['worker_child_pids']) for o in observations), default=0)}
        (root / 'observations.json').write_text(json.dumps(report, indent=2))
    assert len(observed_pids) == 3 and report['max_simultaneous_worker_children'] == 1
    assert len(completed) == 3 and completed[-1]['elapsed_seconds'] < deadline_seconds
    assert all(item['result']['status'] == 'succeeded' for item in completed), completed
    assert int(report['cgroup_memory']['memory.max']) == 4 * 1024**3
    if virtual_limit_gib:
        assert all(any(str(virtual_limit_gib * 1024**3) in value for value in address_limits[str(pid)]) for pid in observed_pids)
    else:
        assert all(all('unlimited' in value for value in address_limits[str(pid)]) for pid in observed_pids)
    parsed_dir = outputs / requests[0]['task_id'] / '1'
    payload = json.loads((parsed_dir / 'payload.json').read_text())
    validate_source(payload['source_revision'], asset_root=parsed_dir)
    assert payload['source_revision']['sha256'] == requests[0]['source_sha256']
    report['parsed_source'] = {'source_sha256': digest(payload['source_revision']),
        'source_pdf_sha256': requests[0]['source_sha256'], 'research_paper': research_paper,
        'pages': payload['inspection']['page_count'], 'blocks': len(payload['source_revision']['blocks']),
        'can_translate': payload['coverage']['can_translate'], 'unresolved': payload['coverage']['unresolved'],
        'asset_hashes': {a['id']: a['sha256'] for a in payload['source_revision']['assets']},
        'scope': 'Actual raw parser output and verified assets; unresolved source review remains required, not corrected source gold'}
    report['status'] = 'passed'
    (root / 'observations.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'status': 'passed', 'children': 3, 'peak': 1, 'completed': 3}))


def outside(current_source_overlay=False, allocator_arenas=None, research_paper=None, virtual_limit_gib=None):
    root = ROOT
    sys.path.insert(0, str(root))
    from harness.live_provider_run import run_recorded_command
    from packages.ir import digest
    output = root / '.agent/tmp/evidence/parser-concurrency' / uuid.uuid4().hex[:8]
    output.mkdir(parents=True)
    commands = []
    def command(args):
        return run_recorded_command(args, env=dict(os.environ), commands=commands,
            evidence_path=output / 'commands.json', timeout=360 if research_paper else 210)
    image = command(['docker', 'image', 'inspect', '--format', '{{.Id}}', os.environ['ACCEPTANCE_PARSER_IMAGE']]).strip()
    args = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--memory', '4g', '--cpus', '2',
        '--pids-limit', '128', '--tmpfs', '/tmp:rw,nosuid,size=512m,mode=1777']
    if allocator_arenas is not None:
        args += ['-e', 'MALLOC_ARENA_MAX=' + str(allocator_arenas)]
    mounts = [(root / 'fixtures', '/fixtures', True), (root / '.agent/harness', '/harness', True), (output, '/result', False)]
    if research_paper:
        mounts.append((root / 'prototype/reader/source', '/papers', True))
    overlays = {}
    if current_source_overlay:
        for relative in ('packages/parsers/pdf_docling.py', 'workers/parser/main.py'):
            path = root / relative
            mounts.append((path, '/app/' + relative, True))
            overlays[relative] = digest(path.read_bytes())
    if virtual_limit_gib is not None:
        assert 8 < virtual_limit_gib <= 64, 'Diagnostic virtual ceiling must remain finite; actual cgroup stays4GiB'
        original = (root / 'workers/parser/main.py').read_text()
        needle = 'verify_memory_envelope()'
        assert original.count(needle) == 1
        probe = output / 'worker-limit-probe.py'
        probe.write_text(original.replace(needle, needle + f'\n            resource.setrlimit(resource.RLIMIT_AS,({virtual_limit_gib}*1024**3,{virtual_limit_gib}*1024**3))'))
        mounts = [mount for mount in mounts if mount[1] != '/app/workers/parser/main.py']
        mounts.append((probe, '/app/workers/parser/main.py', True))
        overlays['workers/parser/main.py'] = digest(probe.read_bytes())
    for host, target, readonly in mounts:
        args += ['--mount', f'type=bind,source={host},target={target}' + (',readonly' if readonly else '')]
    args += [image, 'python', '/harness/parser_concurrency_matrix.py', '--inside']
    if research_paper:
        args += ['--research-paper', research_paper]
    if virtual_limit_gib:
        args += ['--virtual-limit-gib', str(virtual_limit_gib)]
    report = {'parser_image': image, 'network': 'none', 'provider_calls': 0, 'source_overlays': overlays,
        'allocator_arenas_override': allocator_arenas,
        'research_paper': research_paper,
        'diagnostic_virtual_limit_gib_override': virtual_limit_gib,
        'harness_sha256': digest(Path(__file__).read_bytes()), 'scope': __doc__}
    try:
        command(args)
        actual = json.loads((output / 'observations.json').read_text())
        assert actual['status'] == 'passed'
        report.update(status='passed', peak_children=actual['max_simultaneous_worker_children'], completed=len(actual['completed']))
    finally:
        (output / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'status': report['status'], 'evidence': str(output.relative_to(root))}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('--current-source-overlay', action='store_true')
    parser.add_argument('--allocator-arenas', type=int)
    parser.add_argument('--research-paper', choices=['efficient', 'pathways'])
    parser.add_argument('--virtual-limit-gib', type=int)
    args = parser.parse_args()
    if args.inside:
        inside(args.research_paper, args.virtual_limit_gib)
    else:
        outside(args.current_source_overlay, args.allocator_arenas, args.research_paper, args.virtual_limit_gib)
