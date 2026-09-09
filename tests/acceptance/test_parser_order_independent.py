"""Independent geometric boundary checks; these controls are not PDF source gold."""
import copy
import pytest
from packages.parsers.pdf_docling import native_paragraph_order_conflicts

def fixture():
    regions=[{'bbox':[10,10,110,20],'text':'Upper original text.'},{'bbox':[10,40,110,50],'text':'Lower original text.'}]
    def block(i):
        return {'id':str(i),'kind':'paragraph','owner_id':None,'raw_text':regions[i]['text'],
                'provenance':[{'page':1,'bbox':regions[i]['bbox'][:]}]}
    return {'page':1,'text_regions':regions},[block(1),block(0)]

def test_order_conflict_preserves_all_inputs_and_requires_native_text_proof():
    page,blocks=fixture();before=copy.deepcopy((page,blocks))
    result=native_paragraph_order_conflicts(page,blocks)
    assert len(result)==1 and result[0]['block_ids']==['1','0']
    assert (page,blocks)==before
    page['text_regions'][0]['text']='Different native text at the same position.'
    assert native_paragraph_order_conflicts(page,blocks)==[]

@pytest.mark.parametrize('gap,expected',[(1.0,False),(1.001,True)])
def test_vertical_rounding_tolerance_is_inclusive(gap,expected):
    page,blocks=fixture()
    for item in (page['text_regions'][1],blocks[0]['provenance'][0]):item['bbox']=[10,20+gap,110,30+gap]
    assert bool(native_paragraph_order_conflicts(page,blocks)) is expected

@pytest.mark.parametrize('shift,expected',[(20.0,True),(20.001,False)])
def test_horizontal_threshold_uses_both_spans(shift,expected):
    page,blocks=fixture()
    for item in (page['text_regions'][1],blocks[0]['provenance'][0]):item['bbox']=[10+shift,40,110+shift,50]
    assert bool(native_paragraph_order_conflicts(page,blocks)) is expected
