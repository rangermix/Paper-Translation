"""Serial offline parser spool service, one resource-limited process per request."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from packages.ir import canonical_bytes, digest, safe_path, strict_loads
from packages.parsers import PDFError, inspect_pdf
from packages.parsers.pdf_docling import DoclingParser
from packages.parsers.spool import validate_request
from packages.parsers.models import verify_models
from packages.parsers.config import CPU_THREADS, MEMORY_LIMIT_BYTES
from packages.parsers.timeouts import request_timeout_seconds


class ModelHealth:
    """Only publish liveness while the locked local model set remains intact."""
    def __init__(self, outputs, artifacts_path):
        self.outputs, self.artifacts_path = Path(outputs), Path(artifacts_path)
        self.checked_at, self.version, self.memory_limit = None, None, None

    def heartbeat(self, active_task=None):
        if self.checked_at is None or time.monotonic() - self.checked_at >= 60:
            try:
                self.memory_limit = verify_memory_envelope()
                lock = verify_models(self.artifacts_path)
            except BaseException:
                (self.outputs/'heartbeat.json').unlink(missing_ok=True)
                raise
            self.checked_at, self.version = time.monotonic(), lock['docling_version']
        payload = {'timestamp': time.time(), 'models_verified': True, 'parser_version': self.version,
            'memory_limit_bytes': self.memory_limit}
        if active_task:
            payload['active_task'] = active_task
        temporary = self.outputs/'heartbeat.tmp'
        temporary.write_bytes(canonical_bytes(payload))
        temporary.replace(self.outputs/'heartbeat.json')


def is_cancelled(inputs, task_id):
    return safe_path(inputs, task_id+'/cancelled.json', must_exist=False).is_file()


def erase_cancelled_output(outputs, task_id):
    # A validated single task ID is the only recursive removal boundary. Both
    # traversal and symlink escape are rejected before touching its descendants.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', task_id):
        raise ValueError('PARSER_REQUEST_INVALID')
    directory = safe_path(outputs, task_id, must_exist=False)
    if directory.exists():
        if list(directory.iterdir()) == [directory/'cancelled.json'] and (directory/'cancelled.json').read_bytes() == canonical_bytes({'cancelled': True}):
            return
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'cancelled.json').write_bytes(canonical_bytes({'cancelled': True}))


def verify_memory_envelope(cgroup_root=Path('/sys/fs/cgroup')):
    """Require the Docker memory controller's finite bound before native decoding.

    RLIMIT_AS counts lazy virtual mappings: the controlled 18-page paper reserves
    about 26 GiB while resident use stays about 2 GiB. The cgroup controller caps
    actual charged memory, including native/mmap allocations, without confusing
    address reservations with RAM. Support the standard cgroup v2 and v1 mounts.
    """
    root = Path(cgroup_root)
    for path in (root/'memory.max', root/'memory/memory.limit_in_bytes'):
        if not path.is_file():
            continue
        try:
            limit = int(path.read_text().strip())
        except (ValueError, OSError) as exc:
            raise PDFError('PARSER_RESOURCE_LIMIT', 'Finite container memory limit is required') from exc
        if 0 < limit <= MEMORY_LIMIT_BYTES:
            return limit
        break
    raise PDFError('PARSER_RESOURCE_LIMIT', 'Container memory must be bounded to at most 16 GiB')


def process_request(request, source, output):
    """Child target. Limits protect native decoding and tensor allocation on Linux."""
    from packages.parsers.progress import configure_progress, report_progress, reset_progress
    progress_token = configure_progress(output, request)
    try:
        report_progress('started')
        if os.name == 'posix':
            import resource
            verify_memory_envelope()
            resource.setrlimit(resource.RLIMIT_CPU,(request_timeout_seconds(request)*CPU_THREADS,)*2)
            resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
            resource.setrlimit(resource.RLIMIT_FSIZE,(300*1024**2,300*1024**2))
        # Defense in depth; production Compose does not mount these secrets at all.
        for key in list(os.environ):
            if any(part in key.upper() for part in ('API_KEY','DATABASE','DB_PASSWORD','PGPASSWORD','PROVIDER_SECRET')):os.environ.pop(key,None)
        if digest(Path(source).read_bytes()) != request['source_sha256']:raise PDFError('SOURCE_HASH_MISMATCH')
        operation = request.get('operation','parse')
        if operation == 'inspect': payload = inspect_pdf(source,{'max_pages':request['max_pages']})
        else:
            profile = request.get('profile',{}) | {'limits':{'max_pages':request['max_pages']}}
            from packages.parsers.profiles import PADDLE_PROFILE, selected_profile
            if selected_profile(profile) == PADDLE_PROFILE:
                from packages.parsers.pdf_paddleocr import PaddleOCRParser
                parser = PaddleOCRParser()
            else:
                parser = DoclingParser()
            payload = parser.parse(source,request.get('asset_id','source_pdf'),output,profile)
        (Path(output)/'payload.json').write_bytes(canonical_bytes(payload))
        report_progress('finished')
    except BaseException as exc:
        code = exc.code if isinstance(exc,PDFError) else 'PARSER_FAILED'
        (Path(output)/'error.json').write_bytes(canonical_bytes({'code':code,'message':'PDF processing failed; original is preserved'}))
    finally:
        reset_progress(progress_token)


def run_once(input_root, output_root, heartbeat=None):
    inputs, outputs = Path(input_root),Path(output_root)
    outputs.mkdir(parents=True,exist_ok=True)
    for marker in inputs.glob('*/cancelled.json'):
        try:
            if is_cancelled(inputs, marker.parent.name):
                erase_cancelled_output(outputs, marker.parent.name)
        except (ValueError, OSError):
            continue
    for candidate in sorted(inputs.glob('*/*/request.json')):
        try:
            relative = candidate.relative_to(inputs).as_posix()
            request = validate_request(strict_loads(safe_path(inputs,relative).read_bytes()))
            if is_cancelled(inputs, request['task_id']):
                erase_cancelled_output(outputs, request['task_id'])
                continue
            expected = request['task_id']+'/'+str(request['fence'])
            if relative != expected+'/request.json':continue
            result_file = safe_path(outputs,expected+'/result.json',must_exist=False)
            if result_file.exists():continue
            result_file.parent.mkdir(parents=True,exist_ok=True)
            claim = result_file.parent/'started.json'
            if claim.exists():
                # A container restart never runs the same durable attempt indefinitely.
                finish(result_file,request,'failed',{'code':'PARSER_INTERRUPTED','message':'Prior parser process interrupted'})
                return True
            claim.write_bytes(canonical_bytes({'started_at':datetime.now(timezone.utc).isoformat()}))
            seconds = (datetime.fromisoformat(request['deadline'].replace('Z','+00:00'))-datetime.now(timezone.utc)).total_seconds()
            if seconds<=0:
                finish(result_file,request,'failed',{'code':'PARSER_TIMEOUT','message':'Request deadline expired'})
                return True
            source = safe_path(inputs,expected+'/original.pdf')
            process = multiprocessing.get_context('spawn').Process(target=process_request,args=(request,source,result_file.parent))
            until = time.monotonic() + min(seconds, request_timeout_seconds(request))
            process.start()
            while process.is_alive() and time.monotonic()<until:
                process.join(timeout=1)
                if is_cancelled(inputs, request['task_id']):
                    if process.is_alive():
                        process.kill()
                    process.join()
                    erase_cancelled_output(outputs, request['task_id'])
                    return True
                if heartbeat:
                    try:
                        heartbeat(request['task_id'])
                    except BaseException:
                        if process.is_alive():
                            process.kill()
                        process.join()
                        raise
            if is_cancelled(inputs, request['task_id']):
                if process.is_alive():
                    process.kill()
                process.join()
                erase_cancelled_output(outputs, request['task_id'])
            elif process.is_alive():
                process.kill();process.join()
                finish(result_file,request,'failed',{'code':'PARSER_TIMEOUT','message':'Parser time limit exceeded'})
            elif (result_file.parent/'error.json').exists():
                finish(result_file,request,'failed',strict_loads((result_file.parent/'error.json').read_bytes()))
            elif process.exitcode != 0:
                finish(result_file,request,'failed',{'code':'PARSER_RESOURCE_LIMIT','message':'Parser subprocess exited'})
            else:finish(result_file,request,'succeeded')
            if is_cancelled(inputs, request['task_id']):
                erase_cancelled_output(outputs, request['task_id'])
            return True
        except PDFError:
            raise
        except (ValueError,OSError):
            # Invalid descriptors are quarantined by omission; no arbitrary paths are touched.
            continue
    return False


def finish(result_file,request,status,error=None):
    files=[]
    for file in sorted(result_file.parent.rglob('*')):
        if file.is_file() and not file.is_symlink() and file.name not in {'result.json','result.tmp','started.json','error.json','progress.jsonl'}:
            content = file.read_bytes()
            files.append({'path':file.relative_to(result_file.parent).as_posix(),'byte_size':len(content),'sha256':digest(content)})
    result = {k:request[k] for k in ['task_id','fence','source_sha256']}
    result.update(status=status,operation=request.get('operation','parse'),files=files,error=error)
    temporary=result_file.with_suffix('.tmp');temporary.write_bytes(canonical_bytes(result));temporary.replace(result_file)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    inputs=Path(os.environ.get('PARSER_INPUTS','/inputs'));outputs=Path(os.environ.get('PARSER_OUTPUTS','/outputs'))
    outputs.mkdir(parents=True,exist_ok=True)
    health = ModelHealth(outputs, os.environ.get('DOCLING_ARTIFACTS_PATH','/opt/docling/models'))
    while True:
        health.heartbeat()
        worked=run_once(inputs,outputs,health.heartbeat)
        if args.once:break
        if not worked:time.sleep(1)


if __name__=='__main__':main()
