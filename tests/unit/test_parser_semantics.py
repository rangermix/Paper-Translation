"""Authored scientific/compound outputs exercise the independent audit gaps."""
from pathlib import Path
import json

import pytest

from packages.ir import block_hash, flatten_inline, validate_source
from packages.parsers.pdf_vlm import VisionParser
from packages.parsers.vlm_output import html_items, json_items

PAGE={'page':1,'page_size':[600,800]}
PDF=Path('tests/fixtures/sample.pdf')


def parse(raw,tmp_path,profile='chandra-ocr-2-v1'):
    return VisionParser(inference_factory=lambda *args:lambda image,prompt:raw).parse(PDF,'source_pdf',tmp_path,{'parser_profile_revision':profile})


def layout(role,text,bounds='0 100 1000 900'):
    return f'<div data-label="{role}" data-bbox="{bounds}">{text}</div>'


def document(text):return layout('Section-Header','<h1>Fixture title</h1>','0 0 1000 80')+text


def test_math_scripts_marks_links_controls_and_code_are_semantic(tmp_path):
    raw=document(layout('Text','<p><b>Bold</b> <u>under</u> <del>old</del> H<sub>2</sub>O x<sup>3</sup> <math>x<y</math> <a href="https://example.org/paper">article</a> <input type="checkbox" checked> <code> a  &lt; b </code></p>'))
    result=parse(raw,tmp_path);source=result['source_revision'];validate_source(source,asset_root=tmp_path)
    assert source['schema_version']=='4.0'
    prose=next(b for b in source['blocks'] if b['kind']=='paragraph' and 'Bold' in b['normalized_text'])
    runs=prose['source_inline'];atoms=source['protected_atoms']
    assert any(n.get('marks')==['strong'] and n.get('text')=='Bold' for n in runs)
    assert {'underline','deletion','subscript','superscript'} <= {m for n in runs for m in n.get('marks',[])}
    assert any(a['kind']=='math' and a['value']=='x<y' for a in atoms.values())
    assert any(a['kind']=='code' and a['value']==' a  < b ' for a in atoms.values())
    assert any(a['kind']=='control' and a['state']=='checked' for a in atoms.values())
    assert any(n['type']=='link' and n['text']=='article' and n['href']=='https://example.org/paper' for n in runs)
    assert flatten_inline(runs,atoms)==prose['normalized_text']


def test_compound_blocks_nested_lists_explicit_heading_and_inherited_geometry(tmp_path):
    raw=document(layout('Complex-Block','<h4>2.1 Explicit fourth heading</h4><p>First paragraph</p><p>Second paragraph</p><ol start="3"><li>First item<ul><li>Nested</li></ul><p>Continuation</p></li><li>Second item</li></ol><pre class="language-python">  x = 1\n\n  print(x)\n</pre>'))
    source=parse(raw,tmp_path)['source_revision'];validate_source(source,asset_root=tmp_path)
    assert next(b for b in source['blocks'] if b['normalized_text']=='2.1 Explicit fourth heading')['attributes']['level']==4
    assert any(b['kind']=='group' and b['attributes']['group_type']=='list' and b['attributes'].get('list_start')==3 for b in source['blocks'])
    code=next(b for b in source['blocks'] if b['kind']=='code')
    assert code['normalized_text']=='  x = 1\n\n  print(x)\n'
    assert code['attributes']['code_language']=='python'
    leaves=[b for b in source['blocks'] if b['normalized_text'] in {'First paragraph','Second paragraph','Nested'}]
    assert len(leaves)==3 and all(b['provenance'][0]['geometry']=='inherited' for b in leaves)
    assert all(b['provenance'][0]['bbox']==pytest.approx([0,b['provenance'][0]['page_size'][1]*.1,b['provenance'][0]['page_size'][0],b['provenance'][0]['page_size'][1]*.9]) for b in leaves)
    assert all(not b['normalized_text'] for b in source['blocks'] if b['kind']=='group')


@pytest.mark.parametrize('role', ['Footnote', 'Caption', 'Reference'])
@pytest.mark.parametrize('profile', ['surya-ocr-2-v1', 'infinity-parser2-flash-v1'])
def test_note_roles_preserve_horizontal_separators_as_nonprose(tmp_path, role, profile):
    if profile == 'surya-ocr-2-v1':
        raw = document(layout(role, '<hr/><p>Printed note content</p>'))
    else:
        raw = json.dumps([
            {'category': 'title', 'bbox': [0, 0, 1000, 80], 'text': 'Fixture title'},
            {'category': role.lower(), 'bbox': [0, 100, 1000, 900],
             'text': '---\n\nPrinted note content'},
        ])
    source = parse(raw, tmp_path, profile)['source_revision']
    validate_source(source, asset_root=tmp_path)
    separator = next(b for b in source['blocks'] if b['attributes'].get('separator') == 'horizontal')
    assert separator['kind'] == 'group' and not separator['normalized_text']
    assert not separator['translatable']
    prose = next(b for b in source['blocks'] if b['normalized_text'] == 'Printed note content')
    assert prose['kind'] == role.lower()
    assert separator['owner_id'] == prose['owner_id']
    assert separator['provenance'][0]['geometry'] == 'inherited'


def test_rich_tables_preserve_header_roles_groups_math_and_nested_cell_content(tmp_path):
    table='<table><caption>Results</caption><thead><tr><th id="c" scope="col">Name</th><th scope="col">Value</th></tr></thead><tbody><tr><td headers="c"><p><b>Method</b></p><ul><li>Nested <math>n^2</math></li></ul></td><td>H<sub>2</sub>O</td></tr></tbody></table>'
    source=parse(document(layout('Table',table)),tmp_path)['source_revision'];validate_source(source,asset_root=tmp_path)
    t=next(b for b in source['blocks'] if b['kind']=='table' and b['attributes']['representation']=='structured');cells=t['attributes']['cells'];by={b['id']:b for b in source['blocks']}
    assert (t['attributes']['rows'],t['attributes']['columns'])==(2,2)
    assert cells[0]['role']=='header' and cells[0]['scope']=='col'
    assert cells[2]['header_block_ids']==[cells[0]['content_block_id']]
    assert t['attributes']['row_groups']==[{'kind':'head','start_row':0,'end_row':1},{'kind':'body','start_row':1,'end_row':2}]
    compound=by[cells[2]['content_block_id']]
    assert not compound['normalized_text'] and compound['attributes']['children_block_ids']
    assert any(n.get('marks')==['strong'] for b in source['blocks'] for n in b['source_inline'])
    assert any(a['kind']=='math' and a['value']=='n^2' for a in source['protected_atoms'].values())
    assert len(t['attributes']['caption_block_ids'])==1


def test_infinity_markdown_and_partial_json_salvage_independent_siblings():
    raw='[{"category":"title","bbox":[0,0,1000,80],"text":"## Methods"},{"category":"text","bbox":[0,100,1000,200],"text":"A **bold** word and `code`."},17,{"category":"text","bbox":[0,200,1000,300],"text":"Good neighbor"},{"category":"text"'
    warnings=[];items=json_items(raw,PAGE,warnings)
    assert len(items)==3
    assert items[0]['_semantic']['text']=='Methods' and items[0]['level']==2
    assert any(r.get('marks')==['strong'] for r in items[1]['_semantic']['runs'])
    assert {'JSON_INCOMPLETE','LAYOUT_ELEMENT_INVALID'} <= {d['code'] for d in warnings}
    assert items[2]['text']=='Good neighbor'


def test_blank_and_bad_sibling_and_unknown_role_are_not_silent():
    assert html_items(layout('Blank-Page',''),PAGE)==[]
    diagnostics=[]
    items=html_items(layout('Text','good')+layout('Text','bad','nan 0 20 30')+layout('Mystery-Role','kept'),PAGE,diagnostics)
    assert [i['text'] for i in items]==['good','kept']
    assert {'LAYOUT_ELEMENT_INVALID','UNKNOWN_MODEL_ROLE'} <= {d['code'] for d in diagnostics}


def test_generated_visual_and_chemistry_are_inert_auxiliary_with_source_captions(tmp_path):
    source=parse(document(layout('Figure','A generated interpretation<img alt="chart description"><figcaption>Printed caption</figcaption>')+layout('Chemical-Block','<chem>CC(=O)O</chem>')),tmp_path)['source_revision']
    validate_source(source,asset_root=tmp_path)
    figures=[b for b in source['blocks'] if b['kind']=='figure']
    assert any(a['kind']=='derived_visual' and 'generated interpretation' in a['value'] for f in figures for a in f['attributes'].get('annotations',[]))
    assert any(a['kind']=='derived_chemical' and a['value']=='CC(=O)O' for f in figures for a in f['attributes'].get('annotations',[]))
    assert all(not f['normalized_text'] for f in figures)
    assert any(b['kind']=='caption' and b['normalized_text']=='Printed caption' for b in source['blocks'])


def test_response_is_durable_before_decode_failure_and_truncation_is_recorded(tmp_path):
    response={'content':' malformed {', 'response':{'choices':[]},'raw_response':' literal response ', 'finish_reason':'length','usage':{'completion_tokens':8192},'model_artifact_id':'authored-fixture','backend':'vllm','engine_version':None}
    result=parse(response,tmp_path)
    raw= json.loads((tmp_path/'evidence/page-0001.response.json').read_text())
    assert raw['content']==response['content'] and raw['raw_response']==response['raw_response']
    assert raw['finish_reason']=='length' and raw['usage']==response['usage']
    assert any(d['code']=='PARSER_OUTPUT_INCOMPLETE' for d in result['inspection']['pages'][0]['decoder_diagnostics'])
    assert result['source_revision']['parser']['evidence']['pages'][0]['finish_reason']=='length'


def test_repaired_text_keeps_marks_and_protected_math_cannot_be_rewritten():
    from packages.parsers.rich_ir import reconcile_runs,merge_semantics
    from packages.parsers.semantic import node
    runs=[{'type':'text','text':'recognized wrd','marks':['strong'],'path':'/p/b'}]
    fixed,ambiguous=reconcile_runs(runs,'recognized word')
    assert not ambiguous and ''.join(n['text'] for n in fixed)=='recognized word' and all(n['marks']==['strong'] for n in fixed)
    math=[{'type':'math','text':'x<y','path':'/math'}]
    fixed,ambiguous=reconcile_runs(math,'x>y');assert ambiguous and fixed==math
    first={'_semantic':node('paragraph',runs),'orig':'recognized wrd'}
    second={'_semantic':node('paragraph',[{'type':'text','text':'tail','marks':['emphasis'],'path':'/tail'}]),'orig':'tail'}
    merge_semantics(first,second)
    assert first['_semantic']['text']=='recognized wrd tail' and first['_semantic']['runs'][-1]['marks']==['emphasis']
