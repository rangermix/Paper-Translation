"""Isolated Compose smoke: synthetic credentials and a local HTTP fixture only.

Run after .local-data/ai-settings/env.ps1. Never targets the ordinary 8080 app.
No real model, product translation, or certification is claimed by this probe.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx


PROJECT = 'bilingual-ai-settings-20260906'
COMPOSE = ['docker', 'compose', '-p', PROJECT, '-f', 'deployment/compose.production.yaml']
KEYS = ['synthetic-runtime-settings-A', 'synthetic-runtime-settings-B']
EVIDENCE = ROOT / '.agent/tmp/evidence/ai-service-settings'


def command(args, code=None):
    result = subprocess.run(args, cwd=ROOT, input=code, text=True, capture_output=True)
    assert result.returncode == 0, f'Command failed ({result.returncode}); output withheld'
    assert not any(key in result.stdout + result.stderr for key in KEYS), 'Synthetic credential leaked to command output'
    return result.stdout


def main():
    assert os.environ.get('COMPOSE_PROJECT_NAME') == PROJECT
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    calls = []

    class MockService(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert value['model'] == 'synthetic-local:latest'
            assert value['store'] is False and value['stream'] is False
            protocol = 'responses' if self.path.endswith('/responses') else 'chat_completions'
            expected = None if self.path.startswith('/none/') else 'Bearer ' + KEYS[0 if protocol == 'responses' else 1]
            assert self.headers.get('Authorization') == expected
            calls.append({'path': self.path, 'protocol': protocol, 'expected_auth_matched': True})
            output = json.dumps({'results': [{'unit_id': 'qa:0', 'target_inline': [{'type': 'text', 'text': 'Synthetic result'}]}]})
            if protocol == 'responses':
                assert value['text']['format']['strict'] is True
                result = {'id': 'qa-response', 'model': value['model'], 'status': 'completed',
                    'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}],
                    'usage': {'input_tokens': 10, 'output_tokens': 5}}
            else:
                assert value['response_format']['json_schema']['strict'] is True
                result = {'id': 'qa-chat', 'model': value['model'],
                    'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': output}}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('0.0.0.0', 18187), MockService)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    steps = []
    try:
        with httpx.Client(base_url='http://127.0.0.1:18086/api/v1', headers={'X-Library-Request': '1'}, trust_env=False) as http:
            def wait_ready():
                import time
                for _ in range(60):
                    try:
                        if http.get('http://127.0.0.1:18086/health/ready').status_code == 200:
                            return
                    except httpx.TransportError:
                        pass
                    time.sleep(1)
                raise AssertionError('Compose app did not become ready')

            wait_ready()
            def view():
                response = http.get('/settings/provider')
                assert response.status_code == 200 and not any(key in response.text for key in KEYS)
                return response

            def save(profile, key=None, clear=False, status=200):
                current = view()
                response = http.put('/settings/provider', headers={'If-Match': current.headers['etag'], 'Idempotency-Key': uuid4().hex},
                    json={'profile': profile, 'api_key': key, 'clear_api_key': clear})
                assert response.status_code == status, (response.status_code, response.text)
                assert not any(secret in response.text for secret in KEYS)
                assert calls == calls_before, 'Saving settings dispatched a request'
                return response.json()

            calls_before = list(calls)
            profile = {'endpoint': 'http://host.docker.internal:18187/qa/responses', 'api_protocol': 'responses',
                'auth_mode': 'bearer', 'model_id': 'synthetic-local:latest'}
            draft = save(profile, KEYS[0])
            assert draft['configured'] is False and draft['has_api_key'] is True
            assert view().json()['config_revision'] == draft['config_revision']
            steps.append('Incomplete configuration and key saved/reloaded without dispatch')
            profile |= {'enabled_pairs': [['en', 'zh-Hans']], 'max_input_tokens': 16384, 'max_output_tokens': 256,
                'price': {'currency': 'USD', 'input_micro_per_million': 0, 'cached_input_micro_per_million': 0,
                    'output_micro_per_million': 0, 'output_includes_reasoning': True, 'input_bound_rule': 'utf8-byte-ceiling-v1'}}
            full = save(profile)
            assert full['configured'] is True and full['has_api_key'] is True
            steps.append('Blank key retained while completing explicit free pricing')

            def worker_request():
                code = '''import json
from packages.domain.config import provider_profile
from packages.providers.settings import resolve_provider_credentials
from packages.providers.openai_responses import OpenAIResponses
from packages.providers.contract import validate_output
p=provider_profile(); endpoint, protocol, auth, path=resolve_provider_credentials(p)
unit={'unit_id':'qa:0','source_language':'en','target_locale':'zh-Hans','source_inline':[{'type':'text','text':'Synthetic controlled QA content'}],'protected_atoms':{},'context':{}}
result=OpenAIResponses(path,endpoint=endpoint,api_protocol=protocol,auth_mode=auth).translate([unit],p,[])
assert validate_output(result['output_text'],[unit])['qa:0'][0]['text']=='Synthetic result'
assert result['usage']=={'input_tokens':10,'output_tokens':5}
print(json.dumps({'protocol':protocol,'auth_mode':auth,'validated':True}))
'''
                return json.loads(command(COMPOSE + ['exec', '-T', 'worker', 'python', '-'], code))

            worker_request()
            calls_before = list(calls)
            profile |= {'endpoint': 'http://host.docker.internal:18187/qa/chat/completions', 'api_protocol': 'chat_completions'}
            rejected = save(profile, status=409)
            assert rejected['error']['code'] == 'PROVIDER_KEY_REBIND_REQUIRED'
            save(profile, KEYS[1])
            worker_request()
            calls_before = list(calls)
            profile |= {'endpoint': 'http://host.docker.internal:18187/none/chat/completions', 'auth_mode': 'none'}
            no_auth = save(profile, clear=True)
            assert no_auth['has_api_key'] is False
            worker_request()
            steps.append('Worker used exact custom HTTP routes with Responses/Bearer, Chat/Bearer and Chat/no Authorization')
            final_before_restart = view().json()
            command(COMPOSE + ['up', '-d', '--no-deps', '--force-recreate', 'app', 'worker'])
            # Bounded readiness polling, not an assumed startup delay.
            wait_ready()
            assert view().json()['config_revision'] == final_before_restart['config_revision']
            assert view().json()['has_api_key'] is False
            steps.append('Configuration persisted across app/worker container recreation')
            invalid = http.put('/settings/provider', json={'profile': {}, 'api_key': [KEYS[0]]})
            assert invalid.status_code == 422 and KEYS[0] not in invalid.text
            steps.append('Request validation did not echo a synthetic credential')

        backup = json.loads(command(COMPOSE + ['run', '--rm', '--no-deps', 'maintenance', 'python', '-m', 'packages.maintenance', 'backup']))
        backup_id = backup['backup_id']
        verified = json.loads(command(COMPOSE + ['run', '--rm', '--no-deps', 'maintenance', 'python', '-m', 'packages.maintenance', 'verify-backup', '--backup-id', backup_id]))
        assert verified['status'] == 'verified'
        scan = f'''import json,subprocess
from pathlib import Path
from sqlalchemy import select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Base,Job,Permit
keys={KEYS!r}
assert not Path('/provider_config').exists()
folder=Path('/backups')/{backup_id!r}
manifest=json.loads((folder/'manifest.json').read_text())
assert all('provider_config' not in row['path'] for row in manifest['files'])
dump=subprocess.run(['pg_restore','--file=-',str(folder/'database.dump')],capture_output=True,check=True).stdout
assert all(key.encode() not in dump for key in keys)
db=Database(Config.load())
with db.transaction() as session:
    rows=0
    for table in Base.metadata.sorted_tables:
        records=session.execute(select(table)).all(); rows+=len(records)
        assert not any(key in str(records) for key in keys)
    assert session.scalar(select(Job)) is None and session.scalar(select(Permit)) is None
print(json.dumps({{'backup_verified':True,'restored_sql_secret_free':True,'all_db_tables_secret_free':True,'rows_scanned':rows,'provider_mount_absent':True,'jobs_and_permits':0}}))
'''
        scan_result = json.loads(command(COMPOSE + ['run', '--rm', '--no-deps', '-T', 'maintenance', 'python', '-'], scan))
        command(COMPOSE + ['run', '--rm', '--no-deps', 'maintenance', 'python', '-m', 'packages.maintenance', 'maintenance-off'])
        steps.append('Real pg_dump/verify-backup and restored SQL contain no synthetic keys; maintenance has no secret volume')
        logs = command(COMPOSE + ['logs', '--no-color', 'app', 'worker', 'parser'])
        assert not any(key in logs for key in KEYS)
        result = {'status': 'passed', 'scope': 'isolated synthetic configuration/transport runtime smoke; no real model certification',
            'project': PROJECT, 'base_url': 'http://127.0.0.1:18086', 'steps': steps, 'mock_http_calls': calls,
            'backup_id': backup_id, 'backup_scan': scan_result, 'log_secret_scan': 'passed', 'mock_server_closed': True}
        (EVIDENCE / 'runtime-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
