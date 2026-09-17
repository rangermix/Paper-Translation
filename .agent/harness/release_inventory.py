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
from uuid import uuid4


DIRECTORY=ROOT/'.agent/tmp/evidence/release'


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', action='append', nargs=3, required=True, metavar=('ROLE', 'IMAGE', 'SCAN_PREFIX'),
        help='Repeat once for app, parser and database; use an explicit sha256 image ID and historical scan prefix.')
    parser.add_argument('--output-stem', default='verified-candidates')
    parser.add_argument('--output-dir', help='New repository-relative directory under .agent/tmp; defaults to a unique run directory.')
    parser.add_argument('--native-evidence', help='Optional repository-relative native-linkage JSON report; never inferred from historical runs.')
    parser.add_argument('--source-scope', default='Explicit candidate image IDs; checkout lock hashes below do not establish each image source binding.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.output_stem):
        raise ValueError('Output stem must be a single safe filename')
    images = {role: (image, prefix) for role, image, prefix in args.candidate}
    if len(args.candidate) != 3 or set(images) != {'app', 'parser', 'database'}:
        raise ValueError('Exactly app, parser and database candidate roles are required')
    for image, prefix in images.values():
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
            raise ValueError('Candidate images must be explicit immutable sha256 IDs')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', prefix):
            raise ValueError('Scan prefix must be a single safe filename')
    directory = output_path(args.output_dir or '.agent/tmp/release-inventory-' +
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:12], ROOT)
    if directory.exists():
        raise ValueError('Output directory already exists; use a new run directory')
    native = {'status': 'not_run', 'reason': 'No native-linkage evidence was supplied for this inventory.'}
    if args.native_evidence:
        evidence = artifact_path(args.native_evidence, ROOT)
        if not isinstance(json.loads(evidence.read_text()), dict):
            raise ValueError('Native-linkage evidence must be a JSON object')
        native = {'status': 'provided', 'path': evidence.relative_to(ROOT).as_posix(),
            'sha256': sha(evidence), 'candidate_binding': 'not_verified'}
    entries=[]
    notices=['# Third-party dependency evidence','',
        'Generated inventory for local candidate images, not a legal approval or a clean vulnerability attestation.',
        'Complete machine-readable package lists and detected license metadata are in the linked CycloneDX SBOM and Trivy JSON files.',
        'Dependency licenses can impose additional requirements not represented by a single metadata field. Model repository README/licenses are pinned with the model artifacts.','']
    for name,(image,prefix) in images.items():
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
            'lock_hashes':{name:sha(ROOT/name) for name in ('pyproject.toml','uv.lock','src/apps/web/package-lock.json','deployment/parser-models.lock.json')},
            'images':entries,
            'native_linkage_evidence':native,
            'source_scope':args.source_scope}
    directory.mkdir(parents=True)
    manifest = directory/(args.output_stem+'-manifest.json')
    notices_path = directory/(args.output_stem+'-NOTICES.md')
    manifest.write_text(json.dumps(report,indent=2)+'\n')
    notices_path.write_text('\n'.join(notices),encoding='utf-8')
    print(json.dumps({'images':[{k:r[k] for k in ('role','local_image_id','scan_status')} for r in entries],
        'manifest_path':manifest.relative_to(ROOT).as_posix(), 'notices_path':notices_path.relative_to(ROOT).as_posix(),
        'release_approved':False}))


if __name__=='__main__':main()
