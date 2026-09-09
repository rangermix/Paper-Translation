"""Scan an immutable saved image with actual Trivy; never infer release approval."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess




def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--role',choices=['app','parser','database'],required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--label',default='candidate')
    parser.add_argument('--archive',help='Existing previously saved archive filename under evidence/release')
    args=parser.parse_args()
    directory=ROOT/'.agent/tmp/evidence/release'
    assert args.label.replace('-','').isalnum()
    prefix=args.role+'-'+args.label
    commands=[]
    def run(argv):
        result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=900)
        commands.append({'argv':argv,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        (directory/(prefix+'-scan-commands.json')).write_text(json.dumps(commands,indent=2))
        assert result.returncode==0,result.stderr[-2000:]
        return result.stdout
    inspection=json.loads(run(['docker','image','inspect',args.image]))[0]
    archive=args.archive or prefix+'.tar'
    assert Path(archive).name==archive and archive.endswith('.tar')
    if args.archive:
        assert (directory/archive).is_file()
    else:
        run(['docker','image','save','--output',str(directory/archive),inspection['Id']])
    docker=['docker','run','--rm','--pull','never','--network','none',
            '--mount',f'type=bind,source={directory},target=/release',
            '--mount','type=volume,source=bilingual-acceptance-trivy-cache,target=/root/.cache/trivy',
            'aquasec/trivy:0.72.0']
    run(docker+['image','--timeout','10m','--skip-db-update','--skip-java-db-update','--scanners','vuln,license','--license-full',
        '--format','json','--output',f'/release/{prefix}-vulnerability-license.json','--input',f'/release/{archive}'])
    run(docker+['convert','--format','cyclonedx','--output',f'/release/{prefix}-sbom.cdx.json',
                f'/release/{prefix}-vulnerability-license.json'])
    scan=json.loads((directory/(prefix+'-vulnerability-license.json')).read_text())
    assert scan['Metadata']['DiffIDs']==inspection['RootFS']['Layers']
    (directory/(prefix+'-scan-binding.json')).write_text(json.dumps({'recorded_at':datetime.now(timezone.utc).isoformat(),
        'image_reference':args.image,'image_id':inspection['Id'],'rootfs_layers':inspection['RootFS']['Layers'],
        'scan_image_config_id':scan['Metadata']['ImageID'],'scan_created_at':scan['CreatedAt'],
        'scanned_layer_binding':'exact','release_approved':False},indent=2))
    print(json.dumps({'role':args.role,'image_id':inspection['Id'],'scan':'executed','release_approved':False}))


if __name__=='__main__':main()
