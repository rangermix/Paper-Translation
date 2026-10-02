"""Authored raw/PDF contracts and failure boundaries, independent of model quality."""
from copy import deepcopy
from pathlib import Path
import json

import pytest
from PIL import Image, ImageDraw

from packages.ir import digest, validate_source
from packages.parsers.pdf_vlm import decode_response, VisionParser
from packages.parsers.semantic import HTMLSemantics, node
from packages.parsers.vlm_output import html_items, json_items
from tests.unit.test_parser_semantics import PAGE, document, layout, parse


@pytest.mark.parametrize('rotation',[0,90])
def test_original_crop_alignment_on_authored_rotated_pdf(tmp_path,rotation):
    import pypdfium2 as pdfium
    pdf=tmp_path/'authored.pdf'
    with Image.new('RGB',(600,800),'white') as image:
        ImageDraw.Draw(image).rectangle((50,150,350,350),fill='red')
        image.save(pdf,'PDF',resolution=72)
    if rotation:
        rotated=tmp_path/'rotated.pdf'
        with pdfium.PdfDocument(pdf) as doc:
            page=doc[0];page.set_rotation(rotation);page.close();doc.save(rotated)
        pdf=rotated
    width,height=(800,600) if rotation else (600,800)
    box=[450,50,650,350] if rotation else [50,150,350,350]
    norm=' '.join(str(v/(width if i%2==0 else height)*1000) for i,v in enumerate(box))
    raw=document(layout('Figure','Derived description',norm))
    out=tmp_path/'output'
    result=VisionParser(inference_factory=lambda *args:lambda *args:raw).parse(pdf,'original',out,{'parser_profile_revision':'surya-ocr-2-v1'})
    src=result['source_revision'];validate_source(src,asset_root=out)
    figure=next(b for b in src['blocks'] if b['kind']=='figure' and b['attributes'].get('model_role')=='figure')
    assert figure['provenance'][0]['page_size']==[width,height]
    assert figure['provenance'][0]['bbox']==pytest.approx(box)
    asset=next(a for a in src['assets'] if a['id']==figure['attributes']['asset_id'])
    with Image.open(out/asset['storage_key']) as crop:
        r,g,b=crop.convert('RGB').getpixel((crop.width//2,crop.height//2))
        assert r>200 and g<40 and b<40
    assert all('confidence' not in b['attributes'] and 'polygon' not in loc for b in src['blocks'] for loc in b['provenance'])


def test_internal_note_links_bibliography_entries_and_unsafe_links(tmp_path):
    raw=document(layout('Text','<p>שלום <a href="#note"><sup>1</sup></a> <a href="javascript:alert(1)">label</a></p>')+layout('Footnote','<p id="note">Printed note.</p>','0 910 1000 940')+layout('Bibliography','<p>First <i>entry</i>.</p><p>Second entry.</p>','0 810 1000 890'))
    src=parse(raw,tmp_path)['source_revision'];validate_source(src,asset_root=tmp_path)
    notes=[b for b in src['blocks'] if b['kind']=='footnote']
    links=[n for b in src['blocks'] for n in b['source_inline'] if n['type']=='xref']
    assert len(notes)==1 and any(n['target_block_id']==notes[0]['id'] and n.get('marks')==['superscript'] for n in links)
    assert len([b for b in src['blocks'] if b['kind']=='reference'])==2
    assert any('label' in b['normalized_text'] for b in src['blocks'])
    assert not any(n.get('href','').startswith('javascript') for b in src['blocks'] for n in b['source_inline'])


def test_unclosed_math_keeps_good_neighbors_and_original_region(tmp_path):
    raw=document(layout('Text','<p>good first</p>','0 100 1000 200')+layout('Text','<math>x<y','0 220 1000 300')+layout('Text','<p>good last</p>','0 320 1000 400'))
    result=parse(raw,tmp_path);src=result['source_revision'];validate_source(src,asset_root=tmp_path)
    assert {'good first','good last'}<={b['normalized_text'] for b in src['blocks']}
    assert any(b['kind']=='figure' and any(a['kind']=='incomplete_literal' for a in b['attributes'].get('annotations',[])) for b in src['blocks'])
    assert any(d['code']=='LITERAL_UNCLOSED' for d in result['inspection']['pages'][0]['decoder_diagnostics'])


def test_static_controls_separators_nested_code_and_column_groups(tmp_path):
    raw=document(layout('Form','<p>Options <select><option value="a">Alpha</option><option value="b" selected>Beta</option></select></p><p><input type="text" value=""></p><hr><pre><code class="language-python">  x = 1\n</code></pre>')+layout('Table','<table><colgroup span="2"></colgroup><tr><th scope="colgroup" colspan="2">Group</th></tr><tr><td>a</td><td>b</td></tr></table>'))
    src=parse(raw,tmp_path)['source_revision'];validate_source(src,asset_root=tmp_path)
    control=next(a for a in src['protected_atoms'].values() if a.get('control_type')=='select')
    assert control['value']=='Beta' and control['state']=='selected'
    assert control['options']==[{'label':'Alpha','value':'a','selected':False},{'label':'Beta','value':'b','selected':True}]
    assert any(a.get('control_type')=='text' and a['value']=='' for a in src['protected_atoms'].values())
    assert any(b['attributes'].get('separator')=='horizontal' for b in src['blocks'])
    assert next(b for b in src['blocks'] if b['kind']=='code')['normalized_text']=='  x = 1\n'
    assert next(b for b in src['blocks'] if b['kind']=='table')['attributes']['column_groups']==[{'start_column':0,'end_column':2}]


@pytest.mark.parametrize('label,owner', [('formula_caption','math'),('table_footnote','table'),('figure_footnote','figure')])
def test_scoped_relations_require_one_same_page_owner(label,owner,tmp_path):
    content='<math>x^2</math>' if owner=='math' else '<table><tr><td>A</td></tr></table>' if owner=='table' else 'derived description'
    src=parse(document(layout({'math':'Equation-Block','table':'Table','figure':'Figure'}[owner],content,'100 200 900 400')+layout(label,'Printed note','100 410 900 440')),tmp_path)['source_revision']
    validate_source(src,asset_root=tmp_path)
    relation=next(b for b in src['blocks'] if b['normalized_text']=='Printed note')
    parent=next(b for b in src['blocks'] if b['id']==relation['owner_id'])
    assert parent['kind']==owner
    assert relation['id'] in parent['attributes']['caption_block_ids' if 'caption' in label else 'note_block_ids']


def test_decoder_loops_have_explicit_bounded_prefix_and_evidence():
    diagnostics=[]
    items=json_items(json.dumps([{'category':'text','bbox':[0,0,1000,1000],'text':'repeat'}]*1001),PAGE,diagnostics)
    assert len(items)==1000 and any(d['code']=='LAYOUT_CAPACITY' for d in diagnostics)
    diagnostics=[]
    parser=HTMLSemantics('<div>'*40+'visible'+'</div>'*40,diagnostics)
    assert parser.contents(parser.tree)==[] or any(d['code']=='SEMANTIC_LIMIT' for d in diagnostics)
    from packages.parsers.rich_ir import limit_semantic_items
    large=html_items(layout('Text','large '*100),PAGE)
    large[0]['_semantic']=node('paragraph',[{'type':'text','text':'a'*750001,'path':'/huge'}],path='/huge')
    inspection={};bounded=limit_semantic_items(large,inspection)
    assert bounded[0]['_semantic']['kind']=='figure' and inspection['warnings'][0]['code']=='SEMANTIC_CAPACITY'


def test_repetition_is_a_warning_and_preserves_source():
    text=('An unusually repeated complete sentence.\n')*12
    diagnostics=[];items=html_items(layout('Text',text),PAGE,diagnostics)
    assert len(items)==1 and items[0]['text'].count('An unusually repeated complete sentence')==12
    assert any(d['code']=='REPETITIVE_OUTPUT' for d in diagnostics)


def test_markdown_diagnostics_and_inline_nodes_are_bounded():
    from packages.parsers.semantic import markdown_semantics
    diagnostics=[];tree=markdown_semantics(' '.join(['[label](ftp://example.org)']*150),diagnostics)
    assert len(diagnostics)==100 and tree['text'].count('label')==150
    raw=json.dumps([{'category':'text','bbox':[0,0,1000,500],'text':' '.join(['**word**']*4000)},
        {'category':'text','bbox':[0,500,1000,1000],'text':'Good neighbor'}])
    diagnostics=[];items=json_items(raw,PAGE,diagnostics)
    assert [i['text'] for i in items]==['Good neighbor']
    assert diagnostics[0]['code']=='LAYOUT_ELEMENT_INVALID'


@pytest.mark.parametrize('message',[None,{'role':'assistant','content':None},{'role':'assistant','content':'unsafe','tool_calls':[{}]},{'role':'assistant','content':'unsafe','refusal':'no'}])
def test_refusal_and_unusable_completion_are_exact_evidence_not_source(message):
    from types import SimpleNamespace
    runtime=SimpleNamespace(model_id='exact-artifact',backend='vllm')
    raw=json.dumps({'model':'exact-artifact','usage':None,'choices':[{'finish_reason':'stop','message':message}]})
    response=decode_response(raw,runtime)
    assert response['content']=='' and response['raw_response']==raw and response['inference_error']


def test_raw_receipt_is_linked_and_corruption_rejected(tmp_path):
    src=parse(document(layout('Text','body')),tmp_path)['source_revision']
    receipt=src['parser']['evidence']['pages'][0]
    assert receipt['sha256']==digest((tmp_path/receipt['path']).read_bytes())
    assert src['parser']['evidence']['contract_revision']=='d4f7467435aa4137d9539f000ddf0b7ced3eb43f'
    (tmp_path/receipt['path']).write_text('{}')
    with pytest.raises(ValueError,match='evidence hash mismatch'):validate_source(src,asset_root=tmp_path)


def test_reference_slicing_preserves_only_corresponding_runs():
    from packages.parsers.rich_ir import carry_reference_semantics
    tree=node('reference',[{'type':'text','text':'First entry','marks':['strong'],'path':'/first'},{'type':'text','text':' Second entry','marks':['emphasis'],'path':'/second'}],path='/refs')
    original={'_semantic':tree,'orig':tree['text']};first={'orig':'First entry'};second={'orig':' Second entry'}
    carry_reference_semantics(original,first,0,11);carry_reference_semantics(original,second,11,len(tree['text']))
    assert first['_semantic']['text']=='First entry' and first['_semantic']['runs'][0]['marks']==['strong']
    assert second['_semantic']['text']==' Second entry' and second['_semantic']['runs'][0]['marks']==['emphasis']
    assert 'First entry' not in second['_semantic']['text']


def test_nested_figure_and_equation_captions_remain_source(tmp_path):
    raw=document(layout('Figure','<div>A derived description<div><figcaption>Printed figure caption</figcaption></div></div>','0 100 1000 400')+layout('Equation-Block','<div><math>x&lt;y</math><div data-label="formula_caption"><p>Printed equation caption</p></div></div>','0 500 1000 800'))
    src=parse(raw,tmp_path)['source_revision'];validate_source(src,asset_root=tmp_path)
    by={b['id']:b for b in src['blocks']}
    for label,kind in [('Printed figure caption','figure'),('Printed equation caption','math')]:
        caption=next(b for b in src['blocks'] if b['normalized_text']==label)
        assert caption['kind']=='caption' and by[caption['owner_id']]['kind']==kind
    formula=next(b for b in src['blocks'] if b['kind']=='math')
    assert formula['normalized_text']=='x<y'
    assert all('Printed figure caption' not in a['value'] for b in src['blocks'] for a in b['attributes'].get('annotations',[]))


def test_graphic_transcription_retains_nested_printed_caption(tmp_path):
    raw=document(layout('Figure','Derived diagram description')+layout('Equation-Block','<math>x&lt;y</math><div data-label="formula_caption">Printed annotation</div>'))
    src=parse(raw,tmp_path)['source_revision'];validate_source(src,asset_root=tmp_path)
    figure=next(b for b in src['blocks'] if b['kind']=='figure')
    caption=next(b for b in src['blocks'] if b['normalized_text']=='Printed annotation')
    assert caption['owner_id']==figure['id']
    assert any(a['kind']=='graphic_text_transcription' and a['value']=='x<y' for a in figure['attributes']['annotations'])


def test_code_recovered_as_figure_keeps_exact_auxiliary_transcription(tmp_path):
    code='  x = 1\n\n  print(x)\n'
    raw=document(layout('Code','<pre>'+code+'</pre>','100 200 900 400')+layout('Caption','Figure 1: A printed listing.','100 410 900 440'))
    src=parse(raw,tmp_path)['source_revision'];validate_source(src,asset_root=tmp_path)
    figure=next(b for b in src['blocks'] if b['kind']=='figure' and any(a['kind']=='code_transcription' for a in b['attributes'].get('annotations',[])))
    assert next(a['value'] for a in figure['attributes']['annotations'] if a['kind']=='code_transcription')==code
    assert figure['attributes']['caption_block_ids'] and not figure['translatable']


def test_long_role_and_finish_metadata_are_bounded_with_exact_receipt(tmp_path):
    role='unknown-role-'*20
    response={'content':document(layout(role,'Kept source')), 'finish_reason':'unknown-reason-'*20}
    result=parse(response,tmp_path);src=result['source_revision'];validate_source(src,asset_root=tmp_path)
    assert any(b['normalized_text']=='Kept source' for b in src['blocks'])
    assert all(len(b['attributes'].get('model_role',''))<=100 for b in src['blocks'])
    entry=src['parser']['evidence']['pages'][0]
    assert len(entry['finish_reason'])==40
    receipt=json.loads((tmp_path/entry['path']).read_text())
    assert receipt['finish_reason']==response['finish_reason'] and role in receipt['content']


def test_bare_code_and_nested_code_caption_preserve_whitespace(tmp_path):
    code='  x = 1\n\n  print(x)\n'
    raw=document(layout('Code',code,'0 100 1000 400')+layout('Code-Block','<pre>'+code+'</pre><div data-label="code_caption">Listing explanation</div>','0 500 1000 900'))
    src=parse(raw,tmp_path)['source_revision'];validate_source(src,asset_root=tmp_path)
    codes=[b for b in src['blocks'] if b['kind']=='code'];assert len(codes)==2
    assert all(b['normalized_text']==code for b in codes)
    caption=next(b for b in src['blocks'] if b['normalized_text']=='Listing explanation')
    assert caption['owner_id'] in [b['id'] for b in codes] and caption['kind']=='caption'


def test_non_margin_decoration_is_retained_in_new_source(tmp_path):
    src=parse(document(layout('Header','Printed body mislabeled as header','100 300 900 400')+layout('Footer','Printed body mislabeled as footer','100 600 900 700')),tmp_path)['source_revision']
    assert {'Printed body mislabeled as header','Printed body mislabeled as footer'}<={b['normalized_text'] for b in src['blocks']}


def test_empty_math_region_does_not_discard_good_neighbors(tmp_path):
    result=parse(document(layout('Text','Good before','0 100 1000 200')+layout('Equation-Block','<math></math>','0 300 1000 400')+layout('Text','Good after','0 500 1000 600')),tmp_path)
    src=result['source_revision'];validate_source(src,asset_root=tmp_path)
    assert {'Good before','Good after'}<={b['normalized_text'] for b in src['blocks']}
    assert any(a['kind']=='empty_literal' for b in src['blocks'] for a in b['attributes'].get('annotations',[]))
    assert any(d['code']=='EMPTY_LITERAL' for d in result['inspection']['pages'][0]['decoder_diagnostics'])


def test_list_values_reversed_order_and_markdown_marker_are_preserved(tmp_path):
    src=parse(document(layout('List-Group','<ol start="-2" reversed type="A"><li>First</li><li value="7">Second</li><li>Third</li></ol>')),tmp_path)['source_revision'];validate_source(src,asset_root=tmp_path)
    listing=next(b for b in src['blocks'] if b['attributes'].get('group_type')=='list')
    assert listing['attributes']['list_start']==-2 and listing['attributes']['list_reversed'] is True and listing['attributes']['list_marker']=='A'
    assert [b['attributes']['list_index'] for b in src['blocks'] if b['kind']=='list_item']==[-2,7,6]
    item=json_items(json.dumps([{'category':'text','bbox':[0,0,1000,1000],'text':'3) First\n4) Second'}]),PAGE)[0]
    assert item['_semantic']['attrs']['list_marker']==')' and item['_semantic']['attrs']['list_start']==3


def test_nested_table_and_rowspan_zero_preserve_exact_row_group_grid(tmp_path):
    table='<table><thead><tr><th rowspan="0" scope="rowgroup">A</th><th>B</th></tr><tr><td>C</td></tr></thead><tbody><tr><td><p>Before</p><table><tr><td>Nested one</td><td>Nested two</td></tr></table></td><td>End</td></tr></tbody></table>'
    src=parse(document(layout('Table',table)),tmp_path)['source_revision'];validate_source(src,asset_root=tmp_path)
    tables=[b for b in src['blocks'] if b['kind']=='table'];assert len(tables)==2
    outer=next(b for b in tables if b['owner_id'] is None)
    assert outer['attributes']['cells'][0]['row_span']==2
    assert outer['attributes']['row_groups']==[{'kind':'head','start_row':0,'end_row':2},{'kind':'body','start_row':2,'end_row':3}]
    assert {'Before','Nested one','Nested two'}<={b['normalized_text'] for b in src['blocks']}


def test_bad_duplicate_key_sibling_does_not_drop_later_valid_json():
    value='[{"category":"text","bbox":[0,0,1000,100],"text":"first"},{"category":"text","category":"figure","bbox":[0,100,1000,200],"text":"bad"},{"category":"text","bbox":[0,200,1000,300],"text":"last"}]'
    diagnostics=[];items=json_items(value,PAGE,diagnostics)
    assert [i['text'] for i in items]==['first','last']
    assert any(d['code']=='LAYOUT_ELEMENT_INVALID' for d in diagnostics)


def test_json_table_paths_identify_the_decoded_text_field():
    table='<table><tr><td><math>x&lt;y</math></td></tr></table>'
    raw=json.dumps({'layout':[{'category':'table','bbox':[0,0,1000,500],'text':table},{'category':'table','bbox':[0,500,1000,1000],'text':table}]})
    items=json_items(raw,PAGE)
    paths=[i['_semantic']['data']['table_cells'][0]['_semantic']['runs'][0]['path'] for i in items]
    assert paths[0].startswith('/layout/0/text/chars/') and paths[1].startswith('/layout/1/text/chars/')


def test_appendix_equation_labels_need_exact_native_baseline_evidence():
    from packages.parsers.layout_recovery import recover_layout
    from tests.unit.test_academic_layout_recovery import row,pages_for
    items=[row('equation','x^2',[80,200,220,220],label='formula'),row('label','(A.1)',[270,201,290,218],_semantic_version='4.0')]
    result,audit=recover_layout(deepcopy(items),pages_for(items))
    assert result[0]['_equation_number']=='(A.1)' and len(result)==1
    assert any(r['action']=='native_equation_number' for r in audit)
    pages=pages_for(items);pages[0]['text_regions'][-1]['text']='(A.2)'
    result,_=recover_layout(deepcopy(items),pages)
    assert len(result)==2 and '_equation_number' not in result[0]
