import copy
import pytest
from pathlib import Path

from packages.parsers.pdf_docling import DoclingParser
from packages.parsers import inspect_pdf

ROOT=Path(__file__).resolve().parents[2]


def item(ref,label,text,box,page=1,**extra):
    return {'self_ref':ref,'label':label,'orig':text,'text':text,
        'prov':[{'page_no':page,'bbox':dict(zip(['l','t','r','b'],box),coord_origin='TOPLEFT'),'charspan':[0,len(text)]}],**extra}


def test_native_graphic_bounds_remove_cross_page_plot_title():
    from packages.parsers.fidelity import reconcile_items
    items=[item('title','title','Paper',[10,10,90,20]),
        item('p','text','Body sentence Plot title',[10,80,90,95]),
        item('fig','picture','',[15,30,90,65],page=2)]
    items[1]['prov'][0]['charspan']=[0,13]
    items[1]['prov'].append(item('x','text','Plot title',[20,21,80,29],page=2)['prov'][0] | {'charspan':[14,24]})
    pages=[{'page':1,'page_size':[100,100],'text_regions':[]},
           {'page':2,'page_size':[100,100],'text_regions':[],'graphic_regions':[{'bbox':[10,20,95,70]}]}]
    fixed,audit=reconcile_items(items,pages)
    assert fixed[1]['orig']=='Body sentence'
    assert len(fixed[1]['prov'])==1
    assert fixed[2]['prov'][0]['bbox']['t']==20
    assert any(a['action']=='retain_text_in_graphic' for a in audit)


def test_figure_caption_reference_alias_and_geometry_group():
    from packages.parsers.fidelity import reconcile_items
    items=[item('a','picture','',[10,30,45,65]),item('b','picture','',[55,30,90,65],captions=[{'cref':'cap'}]),
           item('cap','caption','Figure 1: Two panels.',[10,72,90,82])]
    fixed,audit=reconcile_items(items,[{'page':1,'page_size':[100,100],'text_regions':[]}])
    figures=[i for i in fixed if i['label']=='picture']
    assert len(figures)==1
    assert figures[0]['captions']==[{'$ref':'cap'}]
    assert figures[0]['prov'][0]['bbox']['l']==10
    assert figures[0]['prov'][0]['bbox']['r']==90


def test_native_punctuation_restore_requires_identical_letter_digit_order():
    from packages.parsers.fidelity import recover_native_text
    assert recover_native_text('pages 30913099','pages 3091–3099')=='pages 3091–3099'
    assert recover_native_text('"quoted"','“quoted”')=='“quoted”'
    assert recover_native_text('different words','unrelated native text') is None
    assert recover_native_text('not safe','safe not') is None
    assert recover_native_text('attention and pages 30913099','at\x02 tention and pages 3091– 3099')=='attention and pages 3091–3099'
    assert recover_native_text('Arg - → Compute','Arg −→ Compute')=='Arg −→ Compute'
    assert recover_native_text('factor 0 . 5','factor 0.5')=='factor 0.5'
    assert recover_native_text('values 1 . 2','values 1 . 2')=='values 1 . 2'


def test_native_form_bbox_clips_invisible_content_and_records_url():
    result=inspect_pdf(ROOT/'reference/legacy/source/Efficiently-Scaling-Transformer-Inference.pdf')
    assert all(region['bbox'][3]<350 for region in result['pages'][4]['graphic_regions'])
    assert any(link['uri']=='https://github.com/google-research/t5x' for link in result['pages'][11]['links'])


def test_url_annotation_only_joins_wrapping_and_hyphen_loss():
    from packages.parsers.fidelity import annotation_url_span
    text='URL https://proceedings.neur ips.cc/paper/1457c0d6bfcb4 967.html .'
    uri='https://proceedings.neurips.cc/paper/1457c0d6bfcb4967.html'
    assert text[4:annotation_url_span(text,4,uri)].replace(' ','')==uri
    assert annotation_url_span('https://example.com/x',0,'https://example-com/x') is None
    assert annotation_url_span('https://example.com/xevil',0,'https://example.com/x') is None
    wrapped='https: //github.com/bytedance/effective trans former)'
    assert annotation_url_span(wrapped,0,'https://github.com/bytedance/effective_transformer')==len(wrapped)-1


def test_source_url_stays_link_and_heading_parent_follows_level(tmp_path):
    from packages.parsers.pdf_docling import _source_nodes
    assert _source_nodes('See https://example.com/a-1.', 'b', {}, 'paragraph')==[
        {'type':'text','text':'See '},{'type':'link','href':'https://example.com/a-1','text':'https://example.com/a-1'},{'type':'text','text':'.'}]
    pdf=ROOT/'fixtures/sample.pdf';inspection=inspect_pdf(pdf)
    items=[item('title','title','Paper',[20,20,200,40]),item('h','section_header','3. Section',[20,50,200,60]),
           item('hh','section_header','3.2.1 Deeper section',[20,70,200,80]),item('p','text','Body',[20,90,100,100])]
    # This is a heading/URL adapter fixture, not a deliberately incomplete
    # extraction of sample.pdf. Supply matching controlled native regions.
    inspection['pages'][0]['text_regions'] = [
        {'text': row['orig'], 'bbox': [row['prov'][0]['bbox'][k] for k in ('l', 't', 'r', 'b')]} for row in items]
    result=DoclingParser().adapt(items,inspection,pdf,'original',tmp_path)['source_revision']['blocks']
    assert result[2]['attributes']['level']==4
    assert result[2]['parent_id']==result[1]['id']
    assert result[3]['parent_id']==result[2]['id']


def test_small_caps_native_regions_do_not_repeat_neighbors():
    result=inspect_pdf(ROOT/'reference/legacy/source/Pathways.pdf')
    # PDFium bounded-word extraction returned PA + PATHWAYS for two adjacent
    # font-size rectangles; native character centers must return P + ATHWAYS.
    regions=result['pages'][1]['text_regions']
    selected=[r['text'] for r in regions if 208<r['bbox'][0]<255 and 297<r['bbox'][1]<300]
    assert ''.join(selected).replace(' ','')=='PATHWAYS'


def test_empty_native_marker_and_joint_table_cells_coverage():
    from packages.parsers.pdf_docling import coverage_report
    page={'page':1,'page_size':[100,100],'text_characters':4,'scan_suspected':False,
          'text_regions':[{'bbox':[10,20,90,30],'text':'A 12 B 34'},{'bbox':[1,1,2,2],'text':'\x02'}]}
    loc=lambda box:{'page':1,'bbox':box,'page_size':[100,100]}
    parent={'id':'t','kind':'table','raw_text':'','owner_id':None,'attributes':{'representation':'structured'},'provenance':[loc([10,20,90,30])],'warnings':[]}
    cells=[{'id':'a','kind':'table_cell','owner_id':'t','raw_text':'A 12','attributes':{},'provenance':[loc([10,20,49,30])],'warnings':[]},
           {'id':'b','kind':'table_cell','owner_id':'t','raw_text':'B 34','attributes':{},'provenance':[loc([50,20,90,30])],'warnings':[]}]
    assert coverage_report([page],[parent,*cells],[])['can_translate']
    cells[1]['raw_text']='B 35'
    assert not coverage_report([page],[parent,*cells],[])['can_translate']


def test_formula_always_retains_pdf_image(tmp_path):
    pdf=ROOT/'fixtures/sample.pdf';inspection=inspect_pdf(pdf)
    result=DoclingParser().adapt([item('title','title','Publication',[20,20,200,40]),
        item('m','formula','a b',[20,80,100,110])],inspection,pdf,'original',tmp_path)
    formula=next(b for b in result['source_revision']['blocks'] if b['kind']=='math')
    assert formula['attributes']['representation']=='image'
    assert formula['attributes']['asset_id']
    assert formula['warnings']


def test_coverage_requires_complete_ordered_text_even_for_short_omissions():
    from packages.parsers.pdf_docling import coverage_report
    prefix='The operation processes a substantial collection of independent requests with carefully documented conditions. '
    native=prefix+'It must not accept 64 invalid requests.'
    loc={'page':1,'bbox':[10,20,90,30],'page_size':[100,100]}
    page={'page':1,'page_size':[100,100],'text_characters':len(native),'scan_suspected':False,
          'text_regions':[{'bbox':loc['bbox'],'text':native}]}
    block={'id':'p','kind':'paragraph','raw_text':native,'owner_id':None,'attributes':{},'provenance':[loc],'warnings':[]}
    assert coverage_report([page],[block],[])['can_translate']
    for altered in [native.replace('not ',''),native.replace('64 ',''),native.replace('must not accept','must accept not')]:
        block['raw_text']=altered
        assert not coverage_report([page],[block],[])['can_translate'],altered


def test_appendix_heading_ancestry(tmp_path):
    pdf=ROOT/'fixtures/sample.pdf';inspection=inspect_pdf(pdf)
    items=[item('t','title','Paper',[20,20,200,40]),item('a','section_header','A Appendix',[20,50,200,60]),
        item('aa','section_header','A.2 Details',[20,70,200,80]),item('aaa','section_header','A.2.1 Nested',[20,90,200,100])]
    blocks=DoclingParser().adapt(items,inspection,pdf,'original',tmp_path)['source_revision']['blocks']
    headings=[b for b in blocks if b['kind']=='heading']
    assert [b['attributes']['level'] for b in headings[1:]]==[2,3,4]
    assert [b['parent_id'] for b in headings[1:]]==[headings[0]['id'],headings[1]['id'],headings[2]['id']]


def test_bibliography_misclassified_table_uses_native_columns_and_hanging_entries():
    from packages.parsers.fidelity import reconcile_items
    items=[item('refs','section_header','References',[10,5,90,10]),
        item('bad','table','',[10,20,90,90],data={'num_cols':2,'num_rows':4,'table_cells':[
            {'text':'Left author. 2020.'},{'text':'Right author. 2021.'},{'text':'Second left. 2022.'},{'text':'Second right. 2023.'}]})]
    regions=[{'bbox':b,'text':s} for b,s in [([10,20,43,25],'Left author. 2020.'),([13,28,43,33],'Left continuation.'),
        ([10,45,43,50],'Second left. 2022.'),([55,20,88,25],'Right author. 2021.'),
        ([58,28,88,33],'Right continuation.'),([55,45,88,50],'Second right. 2023.')]]
    page={'page':1,'page_size':[100,100],'text_regions':regions}
    fixed,audit=reconcile_items(items,[page])
    refs=[i for i in fixed if i['label']=='reference']
    assert len(refs)==4
    assert [i['orig'].splitlines()[0] for i in refs]==['Left author. 2020.','Second left. 2022.','Right author. 2021.','Second right. 2023.']
    assert 'Left continuation.' in refs[0]['orig']
    assert not any(i['label']=='table' for i in fixed)
    items[0]['orig']=items[0]['text']='Results'
    assert any(i['label']=='table' for i in reconcile_items(items,[page])[0])


@pytest.mark.parametrize('caption_label',['caption','text'])
def test_code_in_numbered_figure_retains_original_image_and_caption(tmp_path,caption_label):
    pdf=ROOT/'fixtures/sample.pdf';inspection=inspect_pdf(pdf)
    items=[item('title','title','Paper',[20,20,200,40]),item('code','code','def f(): return 1',[20,80,200,110]),
        item('caption',caption_label,'Figure 2. Code example.',[20,115,200,125])]
    source=DoclingParser().adapt(items,inspection,pdf,'original',tmp_path)['source_revision']
    owner=next(b for b in source['blocks'] if b['raw_text']=='def f(): return 1')
    caption=next(b for b in source['blocks'] if b['kind']=='caption')
    assert owner['kind']=='figure' and owner['attributes']['asset_id']
    assert caption['owner_id']==owner['id']


def test_composite_arrow_is_protected_without_rewriting_native_operator():
    from packages.parsers.pdf_docling import _source_nodes
    atoms={};nodes=_source_nodes('Arg −→ Compute','b',atoms,'paragraph')
    assert [a for a in atoms.values()]==[{'kind':'math','value':'−→'}]
    assert nodes[1]['type']=='protected_ref'


def test_actual_pdf_native_accents_are_not_duplicated_or_detached():
    from packages.parsers.glyphs import region_text
    inspection=inspect_pdf(ROOT/'reference/legacy/source/Pathways.pdf')
    page=inspection['pages'][11]
    text=region_text([r for r in page['text_regions'] if 87<r['bbox'][1]<98 and r['bbox'][0]<300])
    assert 'Martín Abadi' in text
    assert '´' not in text
    assert any(r['replacement']=='í' for r in page['glyph_reconciliations'])
    indices=[i for r in page['text_regions'] for i in r.get('native_indices',[])]
    assert len(indices)==len(set(indices))
    from packages.parsers.fidelity import recover_native_text
    assert recover_native_text('Mart´ ın Abadi','Martín Abadi',proven_accents=True)=='Martín Abadi'
    assert recover_native_text('Mart´ ın Abadi','Martín Abadi') is None


def test_discontinuous_reference_exact_charspans_are_split_and_reordered():
    from packages.parsers.fidelity import reconcile_items
    first='Author A. URL prefix';second='Author C. Separate paper 2024.'
    bad=item('bad','text',first+' '+second,[55,680,290,720],page=1)
    bad['prov'][0]['charspan']=[0,len(first)]
    bad['prov'].append(item('rest','text',second,[55,70,290,100],page=3)['prov'][0] | {'charspan':[len(first)+1,len(first)+1+len(second)]})
    items=[item('h','section_header','References',[55,600,290,620]),bad,
        item('middle','text','Author B. Middle page 2023.',[55,100,290,150],page=2),
        item('later','text','Author D. Later paper 2025.',[55,200,290,240],page=3)]
    pages=[{'page':n,'page_size':[612,792],'text_regions':[]} for n in range(1,4)]
    fixed,audit=reconcile_items(items,pages)
    assert [i['orig'] for i in fixed[1:]]==[first,'Author B. Middle page 2023.',second,'Author D. Later paper 2025.']
    assert any(a['action']=='discontinuous_reference_split' for a in audit)


def test_reference_url_page_continuation_needs_exact_annotation_evidence():
    from packages.parsers.fidelity import reconcile_items
    uri='https://example.com/next-generation/'
    items=[item('h','section_header','References',[10,600,200,620]),item('a','text','Author. https://example.com/next-ge',[10,700,200,720]),
        item('b','reference','neration/, 2021.',[10,70,200,90],page=2)]
    pages=[{'page':1,'page_size':[612,792],'text_regions':[],'links':[{'uri':uri,'bbox':[10,700,200,720]}]},
        {'page':2,'page_size':[612,792],'text_regions':[]}]
    fixed,audit=reconcile_items(items,pages)
    assert len(fixed)==2 and fixed[1]['orig']=='Author. '+uri+', 2021.'
    assert len(fixed[1]['prov'])==2
    items[2]['orig']=items[2]['text']='New author. 2021.'
    assert len(reconcile_items(items,pages)[0])==3


def test_standalone_code_retains_original_layout_without_invented_line_breaks(tmp_path):
    pdf=ROOT/'fixtures/sample.pdf';inspection=inspect_pdf(pdf)
    source=DoclingParser().adapt([item('t','title','Paper',[20,20,200,40]),item('c','code','def f(): return 1',[20,80,200,110])],inspection,pdf,'original',tmp_path)['source_revision']
    code=next(b for b in source['blocks'] if b['kind']=='code')
    assert code['attributes']['representation']=='image' and code['attributes']['asset_id']
    assert code['warnings'] and code['raw_text']=='def f(): return 1'
