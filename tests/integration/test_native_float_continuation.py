"""A native split word may span a floating figure without consuming the figure."""
import copy
import pytest

from packages.domain.errors import DomainError
from packages.ir import block_hash,digest
from packages.source_revisions import apply_native_corrections
from packages.source_revisions.corrections import _set_order
from tests.integration.test_source_continuations import continuation


def scenario(cross_page=True,retain=False):
    source,inspection,proof,_=continuation();by={b['id']:b for b in source['blocks']}
    first,second=by['p1'],by['p2'];first.update(kind='paragraph',attributes={})
    if retain:
        first.update(raw_text='Similar sizes. High',normalized_text='Similar sizes. High',source_inline=[{'type':'text','text':'Similar sizes. High'}])
        second.update(raw_text='throughput is useful.',normalized_text='throughput is useful.',source_inline=[{'type':'text','text':'throughput is useful.'}])
        proof['quote']='Similar sizes. High\x02';inspection['pages'][0]['text_regions'][0]['text']=proof['quote']
        inspection['pages'][0]['text_regions'][1]['text']='throughput is useful.'
    page=2 if cross_page else 1;second['provenance'][0]['page']=page
    following=inspection['pages'][0]['text_regions'].pop()
    if cross_page:inspection['pages'].append({'page':2,'page_size':[612,792],'text_characters':30,'scan_suspected':False,'text_regions':[following]})
    else:inspection['pages'][0]['text_regions'].append(following)
    for p in inspection['pages']:
        index=0
        for region in p['text_regions']:
            region['native_indices']=list(range(index,index+len(region['text'])));index+=len(region['text'])
    order=[bid for bid in source['reading_order'] if bid not in ['fig','p2']];at=order.index('p1');order[at+1:at+1]=['fig','p2'];_set_order(source,order)
    for b in source['blocks']:b['source_hash']=block_hash(b,source['protected_atoms'])
    op={'kind':'merge_native_continuation','block_ids':['p1','p2'],'rule':'retain_line_hyphen' if retain else 'remove_line_wrap',
        'continuation_evidence':{'page':page,'bbox':following['bbox'],'quote':following['text']},
        'page_image_sha256s':{str(p['page']):'a'*64 for p in inspection['pages']},'visual_review_confirmed':True}
    return source,inspection,proof,op


@pytest.mark.parametrize('cross_page,retain',[(True,False),(False,True)])
def test_float_continuation_keeps_original_images_raw_and_root_order(cross_page,retain):
    source,inspection,proof,op=scenario(cross_page,retain);before=digest(source)
    result=apply_native_corrections(source,inspection,[op],proof,'Independent agent viewed both original native endpoints and the floating image.',[],page_image_verify=lambda p,s:True)
    assert digest(source)==before
    by={b['id']:b for b in result['source']['blocks']};old={b['id']:b for b in source['blocks']}
    assert by['p1']['normalized_text']==('Similar sizes. High-throughput is useful.' if retain else 'Input types of input tensors are known.')
    assert by['p1']['raw_text']==old['p1']['raw_text']+'\n'+old['p2']['raw_text']
    assert by['p1']['provenance']==old['p1']['provenance']+old['p2']['provenance']
    assert result['source']['reading_order']==[bid for bid in source['reading_order'] if bid!='p2']
    for bid in ['fig','figcap']:
        assert {k:v for k,v in by[bid].items() if k not in {'order','source_hash'}}=={k:v for k,v in old[bid].items() if k not in {'order','source_hash'}}
    assert result['restorations'][0]['intervening_root_ids']==['fig']
    assert next(m for m in result['mapping'] if m['old_block_ids']==['p1','p2'])['reusable'] is False


@pytest.mark.parametrize('tamper',['prose_between','nonterminal','wrong_start','page_gap','foreign_hash','arbitrary_rule','missing_glyph_order'])
def test_float_continuation_rejects_unproven_merge(tamper):
    source,inspection,proof,op=scenario();by={b['id']:b for b in source['blocks']}
    if tamper=='prose_between':
        order=list(source['reading_order']);order.remove('ref1');order.insert(order.index('p2'),'ref1');_set_order(source,order)
    elif tamper=='nonterminal':
        proof['bbox']=[20,600,250,610];inspection['pages'][0]['text_regions'][0]['bbox']=proof['bbox']
    elif tamper=='wrong_start':op['continuation_evidence']['quote']='changed'
    elif tamper=='page_gap':
        op['continuation_evidence']['page']=3;inspection['pages'][1]['page']=3;by['p2']['provenance'][0]['page']=3
    elif tamper=='foreign_hash':op['page_image_sha256s']['99']='a'*64
    elif tamper=='arbitrary_rule':op['rule']='rewrite'
    else:inspection['pages'][1]['text_regions'][0].pop('native_indices')
    for b in source['blocks']:b['source_hash']=block_hash(b,source['protected_atoms'])
    with pytest.raises(DomainError):apply_native_corrections(source,inspection,[op],proof,'Review.',[],page_image_verify=lambda p,s:True)
