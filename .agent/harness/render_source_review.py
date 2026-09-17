"""Render an existing reviewed source as an explicitly untranslated DRAFT, offline."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import copy
import json
import shutil
import sys
import zipfile
from pathlib import Path


sys.path.insert(0,str(ROOT))
from packages.editorial.drafts import render_input
from packages.ir import digest,validate_ir
from packages.publisher import Publisher,export_bundle,export_single_html
from packages.storage import file_hash


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-evidence',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();base=artifact_path(args.source_evidence);out=output_path(args.output);out.mkdir(parents=True,exist_ok=False)
    response=json.loads((base/'response.json').read_text(encoding='utf8'));source=response['source']
    if 'source_hash' in response:assert digest(source)==response['source_hash']
    fixture=json.loads((ROOT/'tests/fixtures/sample-document.json').read_text(encoding='utf8'));example=fixture['translation_revision']['results'][1]
    translation=copy.deepcopy(fixture['translation_revision'])
    translation.update(source_revision_id=source['id'],title='DRAFT',results=[{**copy.deepcopy(example),'block_id':b['id'],'source_hash':b['source_hash'],
        'status':'unresolved','target_inline':[],'review_state':'not_reviewed','review_record':None} for b in source['blocks']])
    translation['results'][0]['target_inline']=[{'type':'text','text':'DRAFT'}]
    report={'source_hash':digest(source),'source_response_sha256':file_hash(base/'response.json'),'source_evidence':str(base.relative_to(ROOT)),
        'mode':'DRAFT source review only; no Provider request or translated content generated','artifacts':[]}
    for name in ['reader-v1','reader-v2']:
        destination=out/name;destination.mkdir()
        ir=render_input(response['document_id'],source,translation,template_id=name,mode='draft');validate_ir(ir,asset_root=base/'data')
        manifest=Publisher().build(ir,base/'data',destination/'artifact');export_single_html(destination/'artifact',destination/'single.html');export_bundle(destination/'artifact',destination/'bundle.zip')
        with zipfile.ZipFile(destination/'bundle.zip') as archive:archive.extractall(destination/'bundle')
        shutil.copyfile(base/'response.json',destination/'response.json')
        (destination/'reader-ir.json').write_text(json.dumps(ir,ensure_ascii=False,indent=2),encoding='utf8')
        report['artifacts'].append({'template':name,'manifest':manifest,'single_sha256':file_hash(destination/'single.html'),'bundle_sha256':file_hash(destination/'bundle.zip')})
    (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps({'directory':str(out.relative_to(ROOT)),'source_hash':digest(source)}))


if __name__=='__main__':main()
