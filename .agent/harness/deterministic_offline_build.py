"""Repeat all publication/export bytes in a clean, network-none app container.

Bind the repository's tests/fixtures directory read-only at /app/fixtures and a
fresh output directory at /result. Product images do not contain test fixtures.
The /app/fixtures path also supports the historical pre-layout app images.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import copy
import hashlib
import json
from pathlib import Path
import tempfile

from packages.domain.config import provider_profile
from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact
from packages.templates.registry import get_template


def files(directory):
    return {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob('*')) if p.is_file()}


def main():
    assert not provider_profile()['configured']
    ir=json.loads(Path('/app/fixtures/complex-reader/document-ir.json').read_text())
    rows=[]
    with tempfile.TemporaryDirectory(dir='/tmp') as temporary:
        root=Path(temporary)
        for name in ('reader-v1','reader-v2'):
            template=get_template(name);document=copy.deepcopy(ir)
            document['render']['template_id']=name;document['render']['template_sha256']=template['css_sha256']
            runs=[]
            for index in range(2):
                target=root/f'{name}-{index}';target.mkdir()
                artifact=target/'artifact'
                Publisher().build(document,Path('/app'),artifact,include_source=True)
                for include in (False,True):
                    export_bundle(artifact,target/f'bundle-{include}.zip',include_source=include)
                    export_single_html(artifact,target/f'single-{include}.html',include_source=include)
                runs.append({'manifest':verify_artifact(artifact),'files':files(target)})
            assert runs[0]==runs[1]
            rows.append({'template':name,'all_artifact_and_export_bytes_identical':True,**runs[0]})
    result={'status':'passed','scope':'clean image-contained Python, network-none, unconfigured Provider',
            'templates':rows,'external_provider_calls':0,'model_configuration_present':False}
    Path('/result/deterministic-build.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'status':'passed','templates':2,'builds':4,'exports':8,'all_file_hashes_equal':True}))


if __name__=='__main__':main()
