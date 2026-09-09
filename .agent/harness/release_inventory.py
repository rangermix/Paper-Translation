"""Collect actual image/SBOM/scan evidence; does not promote a source build to release."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
from collections import Counter
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import re


DIRECTORY=ROOT/'.agent/tmp/evidence/release'
IMAGES={
 'app':('sha256:50e6ff5b3ccc115a046834cfd5c2f2d22a3f47eea631e155a7c6649ab5fe2d5e','app-schema9-ready'),
 'parser':('sha256:b77fbe0e0a68ea5508754ba8473c5ca984a2746b65a415539ffa1aeaf4defedd','parser-fidelity-retry'),
 'database':('sha256:c4edcff9ad90a498a19735265eaa28c9303cdaf83658568fdc1f4220edcefca4','database-hardened-candidate')}


def sha(path):
    return hashlib.file_digest(path.open('rb'),'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', action='append', nargs=3, metavar=('ROLE', 'IMAGE', 'SCAN_PREFIX'))
    parser.add_argument('--output-stem', default='verified-candidates')
    parser.add_argument('--source-scope', default='Immutable image IDs above; current working tree may have additional corrections requiring a separate build.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.output_stem):
        raise ValueError('Output stem must be a single safe filename')
    images = {role: (image, prefix) for role, image, prefix in args.candidate} if args.candidate else IMAGES
    if set(images) != {'app', 'parser', 'database'}:
        raise ValueError('Exactly app, parser and database candidate roles are required')
    entries=[]
    notices=['# Third-party dependency evidence','',
        'Generated inventory for local candidate images, not a legal approval or a clean vulnerability attestation.',
        'Complete machine-readable package lists and detected license metadata are in the linked CycloneDX SBOM and Trivy JSON files.',
        'Dependency licenses can impose additional requirements not represented by a single metadata field. Model repository README/licenses are pinned with the model artifacts.','']
    for name,(image,prefix) in images.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', prefix):
            raise ValueError('Scan prefix must be a single safe filename')
        inspection=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
        row={'role':name,'image_reference':image,'local_image_id':inspection['Id'],
             'os':inspection['Os'],'architecture':inspection['Architecture'],
             'created':inspection['Created'],'registry_digests':inspection.get('RepoDigests',[]),
             'labels':inspection['Config'].get('Labels',{}),'scan_status':'not_run'}
        scan_path=DIRECTORY/(prefix+'-vulnerability-license.json')
        if scan_path.exists():
            scan=json.loads(scan_path.read_text())
            findings=[v for result in scan.get('Results',[]) for v in result.get('Vulnerabilities',[])]
            licenses=[v for result in scan.get('Results',[]) for v in result.get('Licenses',[])]
            summary=dict(Counter(v['Severity'] for v in findings))
            row.update({'scan_status':'executed_findings_require_triage','scan_created':scan.get('CreatedAt'),
                'scanned_image_config_id':scan['Metadata'].get('ImageID'),
                'scan_matches_current_image_layers':scan['Metadata'].get('DiffIDs')==inspection['RootFS']['Layers'],
                'vulnerability_counts':summary,'detected_license_count':len(licenses),
                'scan_path':scan_path.relative_to(ROOT).as_posix(),'scan_sha256':sha(scan_path)})
            fixes=[{'package':v['PkgName'],'installed':v['InstalledVersion'],'fixed':v.get('FixedVersion'),
                    'id':v['VulnerabilityID'],'severity':v['Severity'],'status':v.get('Status'),'primary_url':v.get('PrimaryURL')}
                   for result in scan.get('Results',[]) if result.get('Class')=='lang-pkgs' for v in result.get('Vulnerabilities',[])]
            row['application_dependency_findings']=fixes
            notices += [f'## {name}', '',f'Image: `{inspection["Id"]}`. Scanner findings: `{summary}`. Findings are not a count of proven reachable exploits.','',
                '| Dependency | Detected license |','|---|---|']
            notices += [f'| {license["PkgName"]} | {license["Name"]} |' for license in licenses]
            notices += ['']
        sbom=DIRECTORY/(prefix+'-sbom.cdx.json')
        if sbom.exists():row.update({'sbom_path':sbom.relative_to(ROOT).as_posix(),'sbom_sha256':sha(sbom)})
        entries.append(row)
    report={'format':'local-image-evidence-v1','recorded_at':datetime.now(timezone.utc).isoformat(),
            'release_approved':False,'reason':'Source candidates; dependency findings and full milestone acceptance remain under review.',
            'lock_hashes':{name:sha(ROOT/name) for name in ('pyproject.toml','uv.lock','apps/web/package-lock.json','deployment/parser-models.lock.json')},
            'images':entries,
            'native_linkage_evidence':{'path':'.agent/tmp/evidence/parser-final-runtime/native-runtime.json',
                'sha256':sha(ROOT/'.agent/tmp/evidence/parser-final-runtime/native-runtime.json'),
                'finding':'Headless OpenCV FFmpeg links bundled OpenSSL1.1.1k. Zero Python scanner findings is not an assertion of zero native CVEs.'},
            'source_scope':args.source_scope}
    (DIRECTORY/(args.output_stem+'-manifest.json')).write_text(json.dumps(report,indent=2)+'\n')
    (DIRECTORY/(args.output_stem+'-NOTICES.md')).write_text('\n'.join(notices),encoding='utf-8')
    print(json.dumps({'images':[{k:r[k] for k in ('role','local_image_id','scan_status')} for r in entries],'release_approved':False}))


if __name__=='__main__':main()
