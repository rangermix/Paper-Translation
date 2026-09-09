"""Internal publication fixture only; never substitutes a real PDF parse/translation."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import argparse
from pathlib import Path
import sys


sys.path.insert(0,str(ROOT))
from packages.publisher import Publisher, export_bundle, export_single_html
from packages.templates.registry import get_template


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fixture',default='fixtures/sample-document-v3.json')
    parser.add_argument('--output',default='.agent/tmp/evidence/reader-review')
    args=parser.parse_args()
    destination=output_path(args.output)
    destination.mkdir(parents=True,exist_ok=True)
    for name in ('reader-v1','reader-v2'):
        document=json.loads(artifact_path(args.fixture).read_text('utf-8'))
        template=get_template(name)
        document['render']['template_id']=name
        document['render']['template_sha256']=template['css_sha256']
        artifact=destination/name
        Publisher().build(document,ROOT,artifact,include_source=True)
        export_bundle(artifact,destination/(name+'.zip'))
        export_single_html(artifact,destination/(name+'.html'))
        export_single_html(artifact,destination/(name+'-with-source.html'),include_source=True)
    print(json.dumps({'fixture':args.fixture,'fixture_kind':'internally authored PDF/IR publication fixture', 'directory':str(destination)}))


if __name__=='__main__':main()
