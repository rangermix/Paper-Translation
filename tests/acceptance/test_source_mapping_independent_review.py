"""Independent semantic-boundary checks of the content mapping implementation."""
import copy

from packages.ir import block_hash
from packages.source_revisions import revision_mapping
from tests.integration.test_source_revisions import fixture_source


def revised(source):
    after=copy.deepcopy(source)
    after['sha256']='b'*64
    next(a for a in after['assets'] if a['id']==after['original_asset_id'])['sha256']=after['sha256']
    return after


def row(before,after,bid):
    return next(r for r in revision_mapping(before,after) if r['old_block_ids']==[bid])


def test_referenced_footnote_semantics_participate_even_with_unchanged_visible_label():
    before=fixture_source();after=revised(before)
    note=next(b for b in after['blocks'] if b['id']=='fn1')
    note.update(raw_text='A completely different footnote.',normalized_text='A completely different footnote.',
        normalization_edits=[],source_inline=[{'type':'text','text':'A completely different footnote.'}])
    note['source_hash']=block_hash(note,after['protected_atoms'])
    referring=[b for b in before['blocks'] if any(n.get('target_block_id')=='fn1' for n in b['source_inline'])]
    assert referring
    for block in referring:assert not row(before,after,block['id'])['reusable']


def test_original_media_content_change_is_not_laundered_by_stable_asset_id():
    before=fixture_source();after=revised(before)
    asset=next(a for a in after['assets'] if a['media_type']=='image/png');asset['sha256']='c'*64
    owner=next(b for b in after['blocks'] if b['attributes'].get('asset_id')==asset['id'])
    assert not row(before,after,owner['id'])['reusable']


def test_corrupt_source_hash_never_becomes_reusable_semantic_identity():
    before=fixture_source();after=revised(before)
    for source in (before,after):next(b for b in source['blocks'] if b['id']=='p1')['source_hash']='d'*64
    assert not row(before,after,'p1')['reusable']


def test_resolved_cross_reference_cycles_fail_closed_without_recursing_forever():
    before=fixture_source()
    block=next(b for b in before['blocks'] if b['id']=='p1')
    block.update(raw_text='self',normalized_text='self',normalization_edits=[],source_inline=[{'type':'xref','target_block_id':'p1','label':'self'}])
    block['source_hash']=block_hash(block,before['protected_atoms'])
    assert not row(before,revised(before),'p1')['reusable']
