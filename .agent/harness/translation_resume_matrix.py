"""One isolated real SIGKILL/restart run with an explicitly injected FakeProvider."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import uuid


sys.path.insert(0,str(ROOT))
from harness.live_provider_run import run_recorded_command

APP='sha256:cf026d80b2a9a337f9528e78238258508cf24119208e0ce99265dd16661ee52e'
PARSER='sha256:7e2732e340e9c148663918d5d75977f50b66908071c2fbb265fa08af9ede39f6'
DATABASE='sha256:04a249fe1c97c960a51b8630d0cec6b82a9a8ee87a78933c1e15bccbd669ff2a'

# Generated into each new evidence directory and run with the project's pinned
# Playwright and its disposable bundled Chromium. No personal browser/profile.
BROWSER_SCRIPT=r'''
import {pathToFileURL} from 'node:url';
import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const {chromium,expect}=await import(pathToFileURL(process.env.RESUME_PLAYWRIGHT_MODULE).href);
const base=process.env.RESUME_BROWSER_BASE,out=process.env.RESUME_EVIDENCE_DIR;
const report={base,scope:'Actual browser close at3/10, explicit FakeProvider only',requests:[],errors:[],external:[],browser_closed:false};
const browser=await chromium.launch();
try {
  const context=await browser.newContext({viewport:{width:1440,height:1060}}),page=await context.newPage();
  page.on('pageerror',error=>report.errors.push(error.message));
  page.on('request',request=>{report.requests.push(request.url());if(/^https?:/.test(request.url())&&!request.url().startsWith(base+'/'))report.external.push(request.url());});
  await context.route('**/*',route=>{
    const url=route.request().url();
    return /^https?:/.test(url)&&!url.startsWith(base+'/')?route.abort():route.continue();
  });
  await page.goto(base+'/#/jobs/resume_job');
  await expect(page.getByRole('heading',{name:'任务中心',exact:true})).toBeVisible();
  report.job=await(await context.request.get(base+'/api/v1/jobs/resume_job')).json();
  expect(report.job.verified_blocks).toBe(3);expect(report.job.total_blocks).toBe(10);
  await expect(page.locator('.task-layout > .panel')).toContainText('3 / 10');
  await page.screenshot({path:resolve(out,'browser-at-three.png')});
  expect(report.errors).toEqual([]);expect(report.external).toEqual([]);
  report.verified_blocks=3;report.total_blocks=10;report.snapshot_at=new Date().toISOString();
  await writeFile(resolve(out,'browser-open.json'),JSON.stringify(report,null,2));
} catch(error) {report.failure=String(error);throw error;}
finally {
  await browser.close();report.browser_closed=!browser.isConnected();report.closed_at=new Date().toISOString();
  await writeFile(resolve(out,report.failure?'browser-failed.json':'browser-closed.json'),JSON.stringify(report,null,2));
}
process.stdout.write(JSON.stringify({browser_closed:report.browser_closed,verified_blocks:report.verified_blocks,total_blocks:report.total_blocks}));
'''


def main():
    OUT=ROOT/'.agent/tmp/evidence/translation-resume'/uuid.uuid4().hex[:8]
    OUT.mkdir(parents=True,exist_ok=False)
    empty=ROOT/'deployment/provider_key.empty';assert empty.read_bytes()==b''
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    assert port!=8080
    project='biblio-resume30-'+uuid.uuid4().hex[:8]
    profile=OUT/'empty-public-profile.json';profile.write_text('{}',encoding='utf8')
    common=[OUT.as_posix()+':/evidence', (ROOT/'.agent/harness').as_posix()+':/harness:ro',profile.as_posix()+':/config/provider-profile.json:ro']
    override=OUT/'override.json'
    override.write_text(json.dumps({'services':{'app':{'volumes':common + [
        (ROOT/'tests/fixtures').as_posix()+':/app/tests/fixtures:ro']},'worker':{'volumes':common,
        'command':['python','/harness/translation_resume_worker.py'],'restart':'no'}},'networks':{'backend':{'internal':True},
        'http':{'internal':False},'provider_egress':{'internal':True}}},indent=2),encoding='utf8')
    images={key:os.environ.get('ACCEPTANCE_'+key,default) for key,default in [('APP_IMAGE',APP),('PARSER_IMAGE',PARSER),('DATABASE_IMAGE',DATABASE)]}
    env={**os.environ,**images,'PORT':str(port),
        'BIND_ADDRESS':'127.0.0.1','PROVIDER_KEY_FILE':str(empty),'READ_ONLY':'false','DISPATCH_DISABLED':'false',
        'ALLOWED_HOSTS':'localhost,127.0.0.1,app','APP_ORIGINS':f'http://127.0.0.1:{port},http://localhost:{port}'}
    commands=[]
    def command(argv,timeout=240):
        return run_recorded_command(argv,env=env,commands=commands,evidence_path=OUT/'commands.json',timeout=timeout)
    def call(*args,timeout=240):
        return command(['docker','compose','-f','deployment/compose.production.yaml','-f',str(override),'-p',project,*args],timeout)
    # Resolve any explicit caller aliases once, then use immutable local IDs for
    # every Compose service; never pull a changing image while running.
    images={key:command(['docker','image','inspect','--format','{{.Id}}',value]).strip() for key,value in images.items()}
    env.update(images)
    runtime={'project':project,'port':port,'images':images,
        'empty_key_confirmed':True,'external_provider_requests':0,'provider_kind':'explicit injected FakeProvider',
        'source_kind':'authored internal IR only; not parser or translation gold',
        'script_sha256':{n:hashlib.sha256((ROOT/'.agent/harness'/n).read_bytes()).hexdigest() for n in ('translation_resume_product.py','translation_resume_worker.py','translation_resume_matrix.py')}}
    (OUT/'runtime.json').write_text(json.dumps(runtime,indent=2),encoding='utf8')
    started=time.monotonic()
    try:
        call('up','-d','--wait','--no-build','--pull','never')
        inspect_images=json.loads(command(['docker','image','inspect',*images.values()]))
        assert {row['Id'] for row in inspect_images}==set(images.values())
        (OUT/'images.json').write_text(json.dumps(inspect_images,indent=2),encoding='utf8')
        network=json.loads(command(['docker','network','inspect',*[project+'_'+suffix for suffix in ('backend','http','provider_egress')]]))
        assert all(row['Internal'] for row in network if row['Name']!=project+'_http')
        assert next(row for row in network if row['Name']==project+'_http')['Internal'] is False
        (OUT/'networks.json').write_text(json.dumps(network,indent=2),encoding='utf8')
        parser_id=call('ps','-q','parser').strip();worker_id=call('ps','-q','worker').strip()
        containers=json.loads(command(['docker','inspect',parser_id,worker_id]))
        parser_info,worker_info=containers
        assert parser_info['HostConfig']['NetworkMode']=='none'
        assert set(worker_info['NetworkSettings']['Networks'])=={project+'_backend',project+'_provider_egress'}
        assert worker_info['HostConfig']['RestartPolicy']['Name']=='no'
        secret=next(m for m in worker_info['Mounts'] if m['Destination']=='/run/secrets/provider_key')
        assert secret['RW'] is False
        assert command(['docker','exec',worker_id,'python','-c',"from pathlib import Path; assert Path('/run/secrets/provider_key').read_bytes()==b''; print('empty key confirmed')"]).strip()=='empty key confirmed'
        (OUT/'containers-before.json').write_text(json.dumps(containers,indent=2),encoding='utf8')
        call('exec','-T','app','python','/harness/translation_resume_product.py','prepare')
        deadline=time.monotonic()+65
        while time.monotonic()<deadline and not (OUT/'kill-barrier.json').exists():time.sleep(.2)
        assert (OUT/'kill-barrier.json').exists(), 'The literal three-of-ten durable checkpoint was not reached.'
        call('exec','-T','app','python','/harness/translation_resume_product.py','barrier')
        (OUT/'browser-ready.json').write_text(json.dumps({'url':f'http://127.0.0.1:{port}/#/jobs/resume_job',
            'job_id':'resume_job','project':project,'verified_blocks':3,'total_blocks':10,
            'requires':'Actual disposable browser view of job progress followed by browser.close.'},indent=2),encoding='utf8')
        browser_script=OUT/'browser-close.mjs';browser_script.write_text(BROWSER_SCRIPT,encoding='utf8')
        env.update(RESUME_PLAYWRIGHT_MODULE=str(ROOT/'src/apps/web/node_modules/@playwright/test/index.mjs'),
            RESUME_BROWSER_BASE=f'http://127.0.0.1:{port}',RESUME_EVIDENCE_DIR=str(OUT))
        command([os.environ.get('ACCEPTANCE_NODE','node'),str(browser_script)],timeout=60)
        assert (OUT/'browser-closed.json').exists(), 'Independent browser-close evidence was not supplied; do not claim this scenario.'
        browser=json.loads((OUT/'browser-closed.json').read_text(encoding='utf8'))
        assert browser['browser_closed'] is True and browser['verified_blocks']==3 and browser['total_blocks']==10
        # Verify the browser's read-only visit/close left the exact durable boundary unchanged.
        call('exec','-T','app','python','/harness/translation_resume_product.py','barrier')
        command(['docker','kill','--signal','KILL',worker_id])
        killed=json.loads(command(['docker','inspect',worker_id]))[0]
        assert killed['State']['ExitCode']==137 and not killed['State']['Running']
        (OUT/'worker-killed.json').write_text(json.dumps(killed,indent=2),encoding='utf8')
        (OUT/'restart-authorized.json').write_text(json.dumps({'worker_id':worker_id,'signal':'SIGKILL','exit_code':137,'at':time.time()}),encoding='utf8')
        command(['docker','start',worker_id])
        call('exec','-T','app','python','/harness/translation_resume_product.py','final',timeout=190)
        result=json.loads((OUT/'result.json').read_text())
        runtime.update(status='passed',signal='SIGKILL',worker_exit_code=137,worker_container_id=worker_id,
            worker_only_internal_networks=True,app_loopback_http_bridge=True,parser_network_none=True,readonly_empty_key=True,
            browser_closed_at_three_of_ten=True,browser_evidence_sha256=hashlib.sha256((OUT/'browser-closed.json').read_bytes()).hexdigest(),
            elapsed_seconds=round(time.monotonic()-started,3),real_publication_count=result['real_publication_count'])
    except BaseException as error:
        runtime.update(status='failed',exception_type=type(error).__name__,message=str(error),elapsed_seconds=round(time.monotonic()-started,3))
        raise
    finally:
        try:
            logs=call('logs','--no-color','app','worker','parser',timeout=60)
            (OUT/'service.log').write_text(logs,encoding='utf8')
        finally:
            call('down','--remove-orphans',timeout=100)
            remaining=command(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project]).strip()
            assert not remaining
            runtime.update(remaining_project_containers=0,named_volumes_preserved=True)
            (OUT/'runtime.json').write_text(json.dumps(runtime,indent=2),encoding='utf8')
    print(json.dumps(runtime,indent=2))


if __name__=='__main__':main()
