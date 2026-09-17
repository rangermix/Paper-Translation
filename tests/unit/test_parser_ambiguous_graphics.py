from pathlib import Path

from packages.parsers import inspect_pdf
from packages.parsers.pdf_docling import DoclingParser, coverage_report
from packages.parsers.fidelity import reconcile_items
from tests.unit.test_parser_fidelity import item

ROOT=Path(__file__).resolve().parents[2]


def test_complete_fallback_does_not_hide_partial_figure_grouping_ambiguity():
    page={'page':1,'page_size':[100,100],'text_characters':0,'scan_suspected':False,'text_regions':[],
        'image_regions':[{'bbox':[10,20,90,70]}]}
    def figure(bid,box):
        return {'id':bid,'kind':'figure','raw_text':'','attributes':{},'warnings':['Original image retained'],
            'provenance':[{'page':1,'bbox':box,'page_size':[100,100]}]}
    full=figure('complete',[10,20,90,70]);partial=figure('partial',[15,25,40,65])
    assert coverage_report([page],[full],[])['can_translate']
    coverage=coverage_report([page],[partial,full],[])
    assert not coverage['can_translate']
    issue=next(i for i in coverage['unresolved'] if i.get('reason')=='Original image overlaps separate incomplete layout graphics')
    assert set(issue['block_ids'])=={'complete','partial'} and issue['page']==1


def test_missed_full_image_and_partial_model_picture_keep_assets_and_visible_review(tmp_path):
    pdf=ROOT/'tests/fixtures/sample.pdf';inspection=inspect_pdf(pdf)
    native=inspection['pages'][0]['image_regions'][0]['bbox'];x0,y0,x1,y1=native
    partial=[x0,y0,x0+(x1-x0)/3,y1]
    result=DoclingParser().adapt([item('title','title','Controlled title',[15,15,200,30]),
        item('part','picture','',partial)],inspection,pdf,'original',tmp_path)
    figures=[b for b in result['source_revision']['blocks'] if b['kind']=='figure']
    assert len(figures)==2 and all((tmp_path/a['storage_key']).is_file() for a in result['source_revision']['assets'])
    assert all(any('分组与图注' in w for w in b['warnings']) for b in figures)
    assert any(i.get('reason')=='Original image overlaps separate incomplete layout graphics' for i in result['coverage']['unresolved'])


def test_explicit_continued_table_caption_above_next_page_grid_is_owned():
    caption=item('caption','text','Table 7 (continued). Remaining measurements.',[10,10,90,20],page=2)
    table=item('table','table','',[10,28,90,75],page=2)
    pages=[{'page':1,'page_size':[100,100],'text_regions':[]},{'page':2,'page_size':[100,100],'text_regions':[]}]
    fixed,audit=reconcile_items([caption,table],pages)
    assert fixed[0]['label']=='caption'
    assert fixed[1]['captions']==[{'$ref':'caption'}]
    assert any(a['action']=='caption_association' for a in audit)
