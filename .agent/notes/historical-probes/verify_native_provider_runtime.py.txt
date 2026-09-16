"""Native adapter smoke in a NEW isolated Compose project, synthetic HTTP only.

No actual-model, product-job or billing certification is implied. Pair this
with PostgreSQL integration tests and independently delegated browser QA.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx


PROJECT = 'bilingual-native-20260906'
BASE = 'http://127.0.0.1:18088'
PORT = 18188
COMPOSE = ['docker','compose','-p',PROJECT,'-f','deployment/compose.production.yaml']
KEYS = ['synthetic-native-runtime-gemini','synthetic-native-runtime-claude']
EVIDENCE = ROOT/'.agent/tmp/evidence/gemini-claude'


def command(args, code=None):
    result = subprocess.run(args, cwd=ROOT, input=code, text=True, capture_output=True)
    assert result.returncode == 0, f'Command failed ({result.returncode}); output withheld'
    assert all(key not in result.stdout + result.stderr for key in KEYS), 'Synthetic key leaked'
    return result.stdout


def main():
    assert os.environ.get('COMPOSE_PROJECT_NAME') == PROJECT and os.environ.get('PORT') == '18088'
    assert os.environ.get('DISPATCH_DISABLED') == 'true'
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    calls = []; failures = []; steps = []

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            try:
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                gemini = self.path.endswith('/interactions')
                protocol = 'gemini_interactions' if gemini else 'claude_messages'
                own = 'x-goog-api-key' if gemini else 'x-api-key'
                other = 'x-api-key' if gemini else 'x-goog-api-key'
                expected = None if self.path.startswith('/none/') else KEYS[0 if gemini else 1]
                assert self.headers.get(own) == expected
                assert not self.headers.get(other) and not self.headers.get('Authorization')
                assert value['model'] == 'synthetic-native-exact' and value['stream'] is False
                if gemini:
                    assert value['store'] is False and value['background'] is False and value['tools'] == []
                    payload = json.loads(value['input']); schema = value['response_format']['schema']
                else:
                    assert 'store' not in value and 'tools' not in value
                    assert self.headers['anthropic-version'] == '2023-06-01'
                    payload = json.loads(value['messages'][0]['content']); schema = value['output_config']['format']['schema']
                review = 'issues' in schema['properties']
                assert payload['units'][0]['unit_id'] == 'qa:0'
                if review: assert payload['units'][0]['target_text'] == 'Synthetic existing target'
                output = json.dumps({'issues':[]} if review else {'results':[{'unit_id':'qa:0','target_inline':[{'type':'text','text':'Synthetic result'}]}]})
                if gemini:
                    result = {'id':'qa-interaction','model':value['model'],'status':'completed',
                        'steps':[{'type':'model_output','content':[{'type':'text','text':output}]}],
                        'usage':{'total_input_tokens':100,'total_cached_tokens':30,'total_output_tokens':20,
                            'total_thought_tokens':22,'total_tool_use_tokens':0,'total_tokens':142}}
                else:
                    result = {'id':'qa-message','type':'message','role':'assistant','model':value['model'],
                        'stop_reason':'end_turn','content':[{'type':'text','text':output}],
                        'usage':{'input_tokens':100,'cache_read_input_tokens':40,'cache_creation_input_tokens':0,
                            'output_tokens':30,'output_tokens_details':{'thinking_tokens':7}}}
                calls.append({'path':self.path,'protocol':protocol,'review':review,'expected_auth_matched':True})
                body = json.dumps(result).encode()
                self.send_response(200); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            except Exception as error:
                failures.append(type(error).__name__)
                self.send_error(500, 'Synthetic fixture assertion failed')

    server = ThreadingHTTPServer(('0.0.0.0', PORT), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with httpx.Client(base_url=BASE+'/api/v1', headers={'X-Library-Request':'1'}, trust_env=False) as http:
            def ready():
                for _ in range(60):
                    try:
                        if http.get(BASE+'/health/ready').status_code == 200: return
                    except httpx.TransportError: pass
                    time.sleep(1)
                raise AssertionError('Compose app readiness timeout')
            ready()

            def view():
                result = http.get('/settings/provider')
                assert result.status_code == 200 and all(key not in result.text for key in KEYS)
                return result

            def save(profile, key=None, clear=False, status=200):
                before = len(calls)
                result = http.put('/settings/provider', headers={'If-Match':view().headers['etag'],'Idempotency-Key':uuid4().hex},
                    json={'profile':profile,'api_key':key,'clear_api_key':clear})
                assert result.status_code == status, result.text
                assert len(calls) == before and all(key not in result.text for key in KEYS)
                return result.json()

            profile = {'api_protocol':'gemini_interactions','endpoint':f'http://host.docker.internal:{PORT}/qa/interactions',
                'auth_mode':'api_key','model_id':'synthetic-native-exact'}
            draft = save(profile, KEYS[0]); assert not draft['configured'] and draft['has_api_key']
            profile |= {'enabled_pairs':[['en','zh-Hans']],'semantic_review_enabled':True,'max_input_tokens':16384,'max_output_tokens':256,
                'price':{'currency':'USD','input_micro_per_million':1000000,'cached_input_micro_per_million':100000,
                    'output_micro_per_million':2000000,'output_includes_reasoning':True,'input_bound_rule':'utf8-byte-ceiling-v1'}}
            assert save(profile)['dispatch_configuration_ready']
            steps.append('Native draft/full configuration persists without dispatch; blank key retained')

            def worker_requests():
                code = '''import json
from packages.domain.config import provider_profile
from packages.providers.settings import resolve_provider_credentials
from packages.providers.native import NativeProvider
from packages.providers.contract import validate_output,validate_review
from packages.billing.price import actual_cost
p=provider_profile(); endpoint,protocol,auth,path=resolve_provider_credentials(p)
unit={'unit_id':'qa:0','source_language':'en','target_locale':'zh-Hans','source_inline':[{'type':'text','text':'Synthetic controlled QA content'}],'protected_atoms':{},'context':{},'review_target_text':'Synthetic existing target'}
adapter=NativeProvider(p,path)
for review in (False,True):
    result=(adapter.review if review else adapter.translate)([unit],p,[])
    if review: assert validate_review(result['output_text'],[unit])==[]
    else: assert validate_output(result['output_text'],[unit])['qa:0'][0]['text']=='Synthetic result'
    assert actual_cost(p['price'],result['usage'])==(157 if protocol=='gemini_interactions' else 164)
print(json.dumps({'protocol':protocol,'auth_mode':auth,'translation_and_review_validated':True}))
'''
                return json.loads(command(COMPOSE+['exec','-T','worker','python','-'],code))

            worker_results = [worker_requests()]
            profile |= {'api_protocol':'claude_messages','endpoint':f'http://host.docker.internal:{PORT}/qa/messages','api_version':'2023-06-01'}
            assert save(profile,status=409)['error']['code'] == 'PROVIDER_KEY_REBIND_REQUIRED'
            assert save(profile,KEYS[1])['api_version'] == '2023-06-01'
            worker_results.append(worker_requests())
            profile |= {'auth_mode':'none','endpoint':f'http://host.docker.internal:{PORT}/none/messages'}
            assert not save(profile,clear=True)['has_api_key']
            worker_results.append(worker_requests())
            steps.append('Six real local HTTP adapter requests: both native translation/review, API keys and explicit no-auth')
            previous = view().json()['config_revision']
            command(COMPOSE+['up','-d','--no-deps','--force-recreate','app','worker'])
            ready(); assert view().json()['config_revision'] == previous
            steps.append('Configuration persisted across actual app/worker recreation')

        backup = json.loads(command(COMPOSE+['run','--rm','--no-deps','maintenance','python','-m','packages.maintenance','backup']))
        backup_id = backup['backup_id']
        verified = json.loads(command(COMPOSE+['run','--rm','--no-deps','maintenance','python','-m','packages.maintenance','verify-backup','--backup-id',backup_id]))
        assert verified['status'] == 'verified'
        code = f'''import json,subprocess
from pathlib import Path
from sqlalchemy import select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Base,Job,Permit
assert not Path('/provider_config').exists()
folder=Path('/backups')/{backup_id!r}; keys={KEYS!r}
manifest=json.loads((folder/'manifest.json').read_text())
assert all('provider_config' not in row['path'] for row in manifest['files'])
dump=subprocess.run(['pg_restore','--file=-',str(folder/'database.dump')],capture_output=True,check=True).stdout
assert all(key.encode() not in dump for key in keys)
with Database(Config.load()).transaction() as session:
    rows=0
    for table in Base.metadata.sorted_tables:
        records=session.execute(select(table)).all(); rows+=len(records)
        assert all(key not in str(records) for key in keys)
    assert session.scalar(select(Job)) is None and session.scalar(select(Permit)) is None
print(json.dumps({{'backup_verified':True,'restored_sql_secret_free':True,'all_db_tables_secret_free':True,'rows_scanned':rows,'provider_mount_absent':True,'jobs_and_permits':0}}))
'''
        scan = json.loads(command(COMPOSE+['run','--rm','--no-deps','-T','maintenance','python','-'],code))
        command(COMPOSE+['run','--rm','--no-deps','maintenance','python','-m','packages.maintenance','maintenance-off'])
        command(COMPOSE+['logs','--no-color','app','worker','parser'])
        assert not failures and len(calls) == 6
        result = {'status':'passed','scope':__doc__,'project':PROJECT,'base_url':BASE,'steps':steps,
            'mock_http_calls':calls,'worker_results':worker_results,'backup_id':backup_id,'backup_scan':scan,'log_secret_scan':'passed'}
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1',PORT)) != 0
    result['mock_server_closed'] = True
    (EVIDENCE/'native-runtime-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__': main()
