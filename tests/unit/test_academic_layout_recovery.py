"""PDF geometry must prove relationships; translator guesses cannot join source."""
from copy import deepcopy

from packages.parsers.recovery import recover_items


def row(ref, text, box, page=1, label='text', **extra):
    return dict(self_ref=ref, label=label, orig=text, text=text,
                prov=[dict(page_no=page, bbox=dict(zip(('l','t','r','b'),box), coord_origin='TOPLEFT'))], **extra)


def pages_for(items):
    return [dict(page=p, page_size=[600,800], text_regions=[dict(text=r['orig'], bbox=list(r['prov'][0]['bbox'].values())[:4])
            for r in items if r['prov'][0]['page_no']==p and r['label'] not in {'picture','table'}]) for p in (1,2)]


def test_cross_page_sentence_skips_float_and_footnote_but_keeps_pdf_evidence():
    items=[row('title','Paper',[40,40,550,60],label='title'),row('left','We establish',[310,695,550,710]),
           row('note','Author contact.',[40,680,270,700],label='footnote'),
           row('fig','',[40,70,270,200],2,'picture',captions=[{'$ref':'caption'}]),
           row('caption','Figure 1. Scaling.',[40,210,270,240],2,'caption'),
           row('right','a baseline with a large model.',[40,310,270,340],2)]
    original=deepcopy(items)
    result,audit=recover_items(items,pages_for(items))
    merged=next(r for r in result if r['self_ref']=='left')
    assert merged['text']=='We establish a baseline with a large model.'
    assert [p['page_no'] for p in merged['prov']]==[1,2]
    assert {'fig','caption','note'} <= {r['self_ref'] for r in result}
    assert not any(r['self_ref']=='right' for r in result)
    assert any(a['action']=='native_paragraph_continuation' and a['before']==['We establish','a baseline with a large model.'] for a in audit)
    assert items==original


def test_native_hyphen_handles_model_completed_word_without_duplicate_suffix():
    items=[row('title','Paper',[40,40,550,60],label='title'),
           row('left','We train for 300k iterations.',[310,695,550,710]),
           row('right','tions. Our learning rate decays.',[40,70,270,100],2)]
    pages=pages_for(items);pages[0]['text_regions'][-1]['text']='We train for 300k itera-'
    result,_=recover_items(items,pages)
    assert next(r for r in result if r['self_ref']=='left')['text']=='We train for 300k iterations. Our learning rate decays.'


def test_completed_sentence_and_intervening_heading_are_not_joined():
    for ending, heading in [('This is complete.',False),('We establish',True)]:
        items=[row('title','Paper',[40,40,550,60],label='title'),row('left',ending,[310,695,550,710]),
               *([row('section','New section',[40,60,270,70],2,'section_header')] if heading else []),
               row('right','a different paragraph.',[40,80,270,110],2)]
        result,_=recover_items(items,pages_for(items))
        assert next(r for r in result if r['self_ref']=='left')['text']==ending
        assert any(r['self_ref']=='right' for r in result)


def test_equation_number_and_subfigure_labels_have_correct_owners():
    items=[row('title','Paper',[40,40,550,60],label='title'),
           row('eq',r'$$Y=X A$$',[80,200,220,220],label='formula'),row('number','(3)',[270,201,290,218]),
           row('fig','',[320,70,550,180],label='picture',captions=[{'$ref':'caption'}]),
           row('sub','(b) Self-Attention',[370,184,500,196],label='caption'),
           row('caption','Figure 3. Blocks.',[310,202,550,230],label='caption')]
    result,audit=recover_items(items,pages_for(items))
    eq=next(r for r in result if r['self_ref']=='eq')
    assert eq.get('_equation_number')=='(3)'
    assert not any(r['self_ref']=='number' for r in result)
    assert next(r for r in result if r['self_ref']=='fig')['captions']==[{'$ref':'sub'},{'$ref':'caption'}]
    assert any(a['action']=='native_equation_number' for a in audit)


def test_paragraph_number_on_another_baseline_is_not_an_equation_label():
    items=[row('title','Paper',[40,40,550,60],label='title'),
           row('eq',r'$$Y=X A$$',[80,200,220,220],label='formula'),row('number','(3)',[270,250,290,268])]
    result,_=recover_items(items,pages_for(items))
    assert any(r['self_ref']=='number' for r in result)


def test_missing_locator_items_remain_untouched():
    items=[row('title','Paper',[40,40,550,60],label='title'),row('a','We establish',[310,695,550,710])]
    items.append({'self_ref':'container','label':'text','text':'container','prov':[]})
    result,_=recover_items(items,pages_for(items[:-1]))
    assert any(r['self_ref']=='container' for r in result)


def test_continuation_can_span_a_page_and_then_a_column():
    items=[row('title','Paper',[40,40,550,60],label='title'),row('a','We establish',[310,695,550,710]),
           row('b','a baseline that',[40,90,270,710],2),row('c','works reliably.',[310,75,550,95],2)]
    pages=pages_for(items)
    pages[1]['text_regions'][0]['bbox']=[40,695,270,710]
    result,_=recover_items(items,pages)
    assert next(r for r in result if r['self_ref']=='a')['text']=='We establish a baseline that works reliably.'


def test_cross_column_continuation_can_start_with_parenthesized_acronym():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'The model for video transcription', [40, 660, 270, 700]),
             row('figure', '', [310, 60, 550, 490], label='picture'),
             row('caption', 'Figure 1. Performance.', [310, 500, 550, 520], label='caption'),
             row('right', '(S2VT) spends time communicating.', [310, 530, 550, 570])]
    result, audit = recover_items(items, pages_for(items)[:1])
    assert next(r for r in result if r['self_ref'] == 'left')['text'] == (
        'The model for video transcription (S2VT) spends time communicating.')
    assert not any(r['self_ref'] == 'right' for r in result)
    assert any(r['action'] == 'native_paragraph_continuation' for r in audit)


def test_parenthesized_list_item_is_not_joined_across_columns():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'The model for video transcription', [40, 660, 270, 700]),
             row('right', '(A) A separately enumerated item.', [310, 80, 550, 100])]
    result, _ = recover_items(items, pages_for(items)[:1])
    assert result == items


def test_cross_page_continuation_can_start_with_a_flush_acronym():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'This does not reduce end-to-end', [310, 680, 550, 710]),
             row('right', 'DNN training time.', [40, 80, 270, 100], 2)]
    result, _ = recover_items(items, pages_for(items))
    assert next(r for r in result if r['self_ref'] == 'left')['text'] == (
        'This does not reduce end-to-end DNN training time.')


def test_indented_acronym_paragraph_stays_separate():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'This does not reduce end-to-end', [310, 680, 550, 710]),
             row('right', 'DNN training is different.', [40, 80, 270, 100], 2)]
    pages = pages_for(items)
    pages[1]['text_regions'][0]['bbox'] = [64, 80, 270, 100]
    result, _ = recover_items(items, pages)
    assert result == items


def test_native_split_word_joins_when_parser_keeps_only_the_stem():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'Similarly, after complet', [40, 680, 270, 710]),
             row('right', 'ing the backward pass, each stage continues.', [310, 200, 550, 230])]
    pages = pages_for(items)[:1]
    pages[0]['text_regions'][1]['text'] = 'Similarly, after complet\x02'
    result, _ = recover_items(items, pages)
    assert next(r for r in result if r['self_ref'] == 'left')['text'] == (
        'Similarly, after completing the backward pass, each stage continues.')


def test_generated_page_tail_is_replaced_only_by_complete_matching_native_prefix():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'The workers keep the pipeline full and ensuring invented results.',
                 [310, 684, 550, 709]),
             row('right', 'ing concurrent processing on all workers.', [40, 80, 270, 100], 2)]
    pages = pages_for(items)
    pages[0]['text_regions'][1:] = [
        dict(text='The workers keep the pipeline', bbox=[310, 686, 550, 696]),
        dict(text='full and ensur\x02', bbox=[310, 698, 500, 708])]
    result, audit = recover_items(items, pages)
    assert next(r for r in result if r['self_ref'] == 'left')['text'] == (
        'The workers keep the pipeline full and ensuring concurrent processing on all workers.')
    record = next(r for r in audit if r['action'] == 'native_paragraph_continuation')
    assert record['repaired_generated_tail'] is True
    assert len(record['native_evidence']) == 3


def test_sparse_native_prefix_cannot_remove_generated_page_tail():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'The workers keep the pipeline full and ensuring all valid results.',
                 [310, 650, 550, 710]),
             row('right', 'ing concurrent processing on all workers.', [40, 80, 270, 100], 2)]
    pages = pages_for(items)
    pages[0]['text_regions'][1] = dict(text='The workers keep the pipeline full and ensur\x02',
                                          bbox=[310, 698, 550, 708])
    result, _ = recover_items(items, pages)
    assert result == items


def test_clipped_parser_box_does_not_drop_a_nearby_matching_native_line():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'The workers keep the pipeline full and ensuring accurate model training',
                 [310, 670, 550, 695]),
             row('right', 'ing concurrent processing on all workers.', [40, 80, 270, 100], 2)]
    pages = pages_for(items)
    pages[0]['text_regions'][1:] = [
        dict(text='The workers keep the pipeline', bbox=[310, 672, 550, 682]),
        dict(text='full and ensur\x02', bbox=[310, 684, 500, 694]),
        dict(text='ing accurate model train\x02', bbox=[310, 696, 540, 706])]
    result, audit = recover_items(items, pages)
    assert next(r for r in result if r['self_ref'] == 'left')['text'] == (
        'The workers keep the pipeline full and ensuring accurate model training '
        'concurrent processing on all workers.')
    record = next(r for r in audit if r['action'] == 'native_paragraph_continuation')
    assert record['repaired_generated_tail'] is False
    assert record['native_evidence'][0]['text'] == 'ing accurate model train\x02'


def test_native_prefix_with_room_for_a_missing_line_cannot_trim_source():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'The workers keep the pipeline full and ensuring accurate model training',
                 [310, 670, 550, 710]),
             row('right', 'ing concurrent processing on all workers.', [40, 80, 270, 100], 2)]
    pages = pages_for(items)
    pages[0]['text_regions'][1:] = [
        dict(text='The workers keep the pipeline', bbox=[310, 672, 550, 682]),
        dict(text='full and ensur\x02', bbox=[310, 684, 500, 694])]
    result, audit = recover_items(items, pages)
    assert result == items
    assert not any(r.get('repaired_generated_tail') for r in audit)


def test_last_native_line_uses_rightmost_run_despite_math_glyph_baseline_offsets():
    items = [row('title', 'Paper', [40, 40, 550, 60], label='title'),
             row('left', 'The speedup is 3.14× and 7.04× compared to', [310, 690, 550, 710]),
             row('right', 'single machine training.', [40, 80, 270, 100], 2)]
    pages = pages_for(items)
    pages[0]['text_regions'][1:] = [
        dict(text='The speedup is', bbox=[310, 690, 390, 698]),
        dict(text='3.14× and', bbox=[310, 701.2, 360, 708]),
        dict(text='7.04×', bbox=[380, 701.4, 414, 708]),
        dict(text='compared to', bbox=[440, 701.1, 550, 710])]
    result, _ = recover_items(items, pages)
    assert next(r for r in result if r['self_ref'] == 'left')['text'] == (
        'The speedup is 3.14× and 7.04× compared to single machine training.')
