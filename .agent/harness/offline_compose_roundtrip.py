"""Fresh offline Compose library, backup, and restore to a second fresh instance."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
    from ._compose import write_offline_override
else:
    from _project import ROOT, artifact_path, output_path
    from _compose import write_offline_override
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import uuid


OUTPUT=ROOT/'.agent/tmp/evidence/offline-compose'


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    suffix=uuid.uuid4().hex[:8]
    archive=OUTPUT/'runs'/suffix
    archive.mkdir(parents=True)
    offline_override = write_offline_override(archive)
    fixture_override=archive/'fixtures.json'
    fixture_override.write_text(json.dumps({'services': {'app': {'volumes': [
        (ROOT/'tests/fixtures').as_posix()+':/app/fixtures:ro']}}}, indent=2))
    original='bilingual-offline-'+suffix
    restored='bilingual-restore-'+suffix
    env={**os.environ, "COMPOSE_PROFILES": "",'APP_IMAGE':os.environ.get('ACCEPTANCE_APP_IMAGE','bilingual-personal-pdf-app:acceptance-candidate'),
         'PARSER_IMAGE':os.environ.get('ACCEPTANCE_PARSER_IMAGE','bilingual-personal-pdf-parser:acceptance-candidate'),
         'DATABASE_IMAGE':os.environ.get('ACCEPTANCE_DATABASE_IMAGE','bilingual-personal-pdf-db:acceptance-candidate'),'PORT':'18084'}
    commands=[]
    def call(argv):
        run=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
        commands.append({'argv':argv,'exit_code':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
        (archive/'commands.json').write_text(json.dumps(commands,indent=2))
        assert run.returncode==0,run.stderr[-3000:]
        return run.stdout
    def compose(project,*args,restore_override=False):
        files=['-f','compose.example.yaml','-f',str(offline_override),'-f',str(fixture_override)]
        if restore_override:files+=['-f',str(archive/'restore-volume.yaml')]
        return call(['docker','compose',*files,'-p',project,*args])
    def maintenance(project,*args,restore_override=False):
        return compose(project,'run','--rm','--no-deps','maintenance','python','-m','packages.maintenance',*args,restore_override=restore_override)
    try:
        assert not call(['docker','ps','-aq','--filter','label=com.docker.compose.project='+original]).strip()
        compose(original,'up','-d','--wait','--no-build','--pull','never')
        compose(original,'exec','-T','app','python','/harness/offline_product.py')
        maintenance(original,'seed-legacy')
        compose(original,'exec','-T','app','python','/harness/offline_product.py','--export-legacy')
        compose(original,'exec','-T','app','python','/harness/readiness_corruption_probe.py')
        networks=json.loads(call(['docker','network','inspect',original+'_backend',original+'_http',original+'_provider_egress']))
        assert all(network['Internal'] for network in networks)
        backup=json.loads(maintenance(original,'backup'))
        maintenance(original,'verify-backup','--backup-id',backup['backup_id'])
        compose(original,'down','--remove-orphans')
        (archive/'restore-volume.yaml').write_text('volumes:\n  backups:\n    external: true\n    name: '+original+'_backups\n')
        env['PORT']='18085'
        assert not call(['docker','ps','-aq','--filter','label=com.docker.compose.project='+restored]).strip()
        compose(restored,'up','-d','--wait','--no-build','--pull','never',restore_override=True)
        result=json.loads(maintenance(restored,'restore','--backup-id',backup['backup_id'],restore_override=True))
        assert result['maintenance'] and result['dispatch_disabled']
        maintenance(restored,'verify',restore_override=True)
        compose(restored,'exec','-T','app','python','/harness/offline_product.py','--verify',restore_override=True)
        maintenance(restored,'maintenance-off',restore_override=True)
        report={'status':'passed','original_project':original,'restored_project':restored,'backup_id':backup['backup_id'],
            'recorded_at':datetime.now(timezone.utc).isoformat(),'all_networks_internal':True,'pull_policy':'never',
            'fresh_data_and_database_volumes':True,'provider_calls':0,'legacy_worker_exports':4,
            'host_runtime_commands':'Docker/Compose only; the test driver orchestrates commands but application operations use image-contained Python.',
            'verified':['PDF upload/native inspector','source bytes','metadata/star/tags','two seeded legacy current artifacts',
                        'four exact exports','real referenced PDF corruption produces readiness 503 and recovers',
                        'backup hashes','fresh-volume pg_restore','maintenance and dispatch flags']}
        (archive/'roundtrip.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report))
    finally:
        # Named volumes are retained as evidence/recovery material. Never --volumes.
        for project,override in ((original,False),(restored,True)):
            try:compose(project,'down','--remove-orphans',restore_override=override and (archive/'restore-volume.yaml').exists())
            except Exception:pass


if __name__=='__main__':main()
