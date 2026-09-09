"""Explicit native-glyph mechanical spans never accept arbitrary replacement text."""
import copy
import pytest

from packages.domain.errors import DomainError
from packages.ir import block_hash,digest,flatten_inline
from packages.source_revisions import apply_native_corrections
from tests.integration.test_source_revisions import fixture_source


def scenario(text='A discus sion ends.',rule='remove_line_wrap'):
    source=fixture_source();block=next(b for b in source['blocks'] if b['id']=='p2')
    block.update(raw_text=text,normalized_text=text,normalization_edits=[],source_inline=[{'type':'text','text':text}])
    old=block['provenance'][0];block['provenance']=[{**old,'page':1,'bbox':[20,20,250,40]},{**old,'page':2,'bbox':[20,20,250,40]}]
    block['source_hash']=block_hash(block,source['protected_atoms'])
    a={'page':1,'bbox':[20,22,230,38],'quote':'A discus\x02'};b={'page':2,'bbox':[20,22,230,38],'quote':'sion ends.'}
    inspection={'sha256':source['sha256'],'pages':[{'page':p['page'],'page_size':[612,792],'text_characters':len(p['quote']),'scan_suspected':False,
        'text_regions':[{'bbox':p['bbox'],'text':p['quote'],'native_indices':list(range(len(p['quote'])))}]} for p in [a,b]]}
    operation={'kind':'normalize_native_span','block_id':'p2','start':2,'end':13,'rule':rule,
        'page_image_sha256s':{'1':'a'*64,'2':'b'*64},'visual_review_confirmed':True,'continuation_evidence':b}
    return source,inspection,a,operation


def test_native_crosspage_word_join_preserves_original_raw_and_maps_exact_span():
    source,inspection,proof,op=scenario();before=digest(source)
    result=apply_native_corrections(source,inspection,[op],proof,'Agent views the original printed discus- / sion.',[],page_image_verify=lambda p,s:True)
    assert digest(source)==before
    block=next(b for b in result['source']['blocks'] if b['id']=='p2')
    assert block['raw_text']=='A discus sion ends.' and block['normalized_text']=='A discussion ends.'
    assert flatten_inline(block['source_inline'],result['source']['protected_atoms'])==block['normalized_text']
    assert result['restorations'][0]['native_evidence']==[proof,op['continuation_evidence']]


def test_native_spacing_restoration_uses_only_unique_original_char_sequence():
    source,inspection,proof,op=scenario('A MPMDprograms example.','restore_native_spacing')
    proof['quote']='A MPMD programs example.';inspection['pages'][0]['text_regions'][0].update(text=proof['quote'],native_indices=list(range(len(proof['quote']))))
    op.update(start=2,end=14,page_image_sha256s={'1':'a'*64});op.pop('continuation_evidence')
    result=apply_native_corrections(source,inspection,[op],proof,'Original native space was lost.',[],page_image_verify=lambda p,s:True)
    assert next(b for b in result['source']['blocks'] if b['id']=='p2')['normalized_text']=='A MPMD programs example.'


@pytest.mark.parametrize('change',[{'text':'Invented new text'},{'start':0},{'visual_review_confirmed':False},{'rule':'rewrite'},{'rule':[]}])
def test_native_normalization_rejects_arbitrary_replacement_or_unbound_span(change):
    source,inspection,proof,op=scenario();op.update(change)
    with pytest.raises(DomainError):apply_native_corrections(source,inspection,[op],proof,'Review.',[],page_image_verify=lambda p,s:True)


def test_native_word_join_rejects_nonterminal_hyphen_or_missing_second_page_hash():
    for tamper in ['proof','hash']:
        source,inspection,proof,op=scenario()
        if tamper=='proof':
            proof['quote']='A discus';inspection['pages'][0]['text_regions'][0].update(text=proof['quote'],native_indices=list(range(len(proof['quote']))))
        else:op['page_image_sha256s'].pop('2')
        with pytest.raises(DomainError):apply_native_corrections(source,inspection,[op],proof,'Review.',[],page_image_verify=lambda p,s:True)


def test_split_paragraph_binds_repeated_span_within_exact_native_parent_sequence():
    text='A MPMDprograms and MPMDprograms.'
    source,inspection,proof,op=scenario(text,'restore_native_spacing')
    proof['quote']='A MPMD programs and MPMDprograms. Original suffix.'
    inspection['pages'][0]['text_regions'][0].update(text=proof['quote'],native_indices=list(range(len(proof['quote']))))
    # Use two native regions so that the declared first occurrence is unique inside its proof.
    proof['quote']='A MPMD programs and '
    inspection['pages'][0]['text_regions'][0].update(text=proof['quote'],native_indices=list(range(len(proof['quote']))))
    suffix='MPMDprograms. Original suffix.'
    inspection['pages'][0]['text_regions'].append({'bbox':[20,30,230,39],'text':suffix,'native_indices':list(range(len(proof['quote']),len(proof['quote'])+len(suffix)))})
    inspection['pages']=inspection['pages'][:1];next(b for b in source['blocks'] if b['id']=='p2')['provenance']=next(b for b in source['blocks'] if b['id']=='p2')['provenance'][:1]
    op.update(start=2,end=14,page_image_sha256s={'1':'a'*64});op.pop('continuation_evidence')
    block=next(b for b in source['blocks'] if b['id']=='p2');block['source_hash']=block_hash(block,source['protected_atoms'])
    result=apply_native_corrections(source,inspection,[op],proof,'Source paragraph is an exact original prefix after a math split.',[],page_image_verify=lambda p,s:True)
    assert next(b for b in result['source']['blocks'] if b['id']=='p2')['normalized_text']=='A MPMD programs and MPMDprograms.'


def test_native_hyphen_suffix_does_not_consume_an_existing_compound_prefix():
    source,inspection,proof,op=scenario('A XY-weightgathered ends.','retain_line_hyphen')
    proof['quote']='A XY-weight\x02';inspection['pages'][0]['text_regions'][0].update(text=proof['quote'],native_indices=list(range(len(proof['quote']))))
    next_proof=op['continuation_evidence'];next_proof['quote']='gathered ends.'
    inspection['pages'][1]['text_regions'][0].update(text=next_proof['quote'],native_indices=list(range(len(next_proof['quote']))))
    op.update(start=5,end=19)
    result=apply_native_corrections(source,inspection,[op],proof,'Original XY- prefix is already present; restore its terminal weight-/gathered seam only.',[],page_image_verify=lambda p,s:True)
    assert next(b for b in result['source']['blocks'] if b['id']=='p2')['normalized_text']=='A XY-weight-gathered ends.'
