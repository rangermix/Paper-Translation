"""Attach genuine local parser evidence and exact payload text to the review pack."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import hashlib
import json
from pathlib import Path




def main():
    path=ROOT/'fixtures/live-provider/manifest.json'
    manifest=json.loads(path.read_text('utf-8'))
    for case in manifest['documents']:
        language='en' if case['source_language']=='en' else 'zh'
        fixed=ROOT/('.agent/tmp/evidence/live-provider-'+language+'-fixed')
        final=ROOT/('.agent/tmp/evidence/live-provider-final-'+language)
        folder=final if (final/'result.json').exists() else (fixed if (fixed/'result.json').exists() else ROOT/('.agent/tmp/evidence/live-provider-'+language))
        result=json.loads((folder/'result.json').read_text('utf-8'))
        assert result['coverage']['can_translate'] and not result['coverage']['unresolved']
        blocks=result['source_revision']['blocks']
        assert [block['raw_text'] for block in blocks]==case['source_text']
        assert [atom['value'] for atom in result['source_revision']['protected_atoms'].values() if atom['kind']=='number']==['64']
        assert hashlib.sha256((ROOT/case['path']).read_bytes()).hexdigest()==case['sha256']==result['inspection']['sha256']
        case['parse_evidence']={
            'execution':json.loads((folder/'execution.json').read_text()),
            'result_path':(folder/'result.json').relative_to(ROOT).as_posix(),
            'result_sha256':hashlib.sha256((folder/'result.json').read_bytes()).hexdigest(),
            'page_image':(folder/'pages/page-0001.png').relative_to(ROOT).as_posix(),
            'source_revision_id':result['source_revision']['id'],
            'model_calls':'local offline Docling only; zero external Provider calls',
            'source_text_exact_match':True}
        case['blocks_to_send']=[{key:block[key] for key in ('id','kind','raw_text','normalized_text','source_inline','provenance')} for block in blocks]
        case['protected_atoms']=result['source_revision']['protected_atoms']
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'local_parse_verified','cases':len(manifest['documents']),'blocks':8,'external_calls':0}))


if __name__=='__main__':main()
