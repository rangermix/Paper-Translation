"""M2-AT13A literal source/target attribution through the real revision API."""
import copy
import json
from pathlib import Path
import pytest

from packages.domain.models import Document,Edition,SourceAsset,SourceRevision,TranslationRevision
from packages.ir import block_hash,digest,validate_source
from packages.storage import write_snapshot,file_hash
from packages.source_revisions.corrections import _set_order

ROOT=Path(__file__).resolve().parents[2]


def sample():return json.loads((ROOT/'tests/fixtures/sample-document.json').read_text(encoding='utf8'))


def changed_source(source):
    other=copy.deepcopy(source);other['id']='source_diff_after'
    return other


def seed(database,left,right,tx=None,ty=None,cross_locale=False):
    db,cfg=database
    with db.transaction() as session:
        original=next(a for a in left['assets'] if a['id']==left['original_asset_id'])
        session.add(SourceAsset(id='asset_diff',sha256=left['sha256'],byte_size=original['byte_size'],page_count=2,storage_key=original['storage_key']));session.flush()
        session.add(Document(id='doc_diff',title='Two revision axes',source_asset_id='asset_diff'));session.flush()
        for index,source in enumerate([left,right]):
            key=f'documents/doc_diff/source-{index}.json'
            session.add(SourceRevision(id=source['id'],document_id='doc_diff',asset_id='asset_diff',storage_key=key,snapshot_hash=write_snapshot(cfg.data,key,source)))
        if tx is not None:
            session.flush();session.add(Edition(id='edition_diff',document_id='doc_diff',target_locale='zh-Hans'))
            if cross_locale:session.add(Edition(id='edition_other',document_id='doc_diff',target_locale='en'))
            session.flush()
            for index,(translation,source) in enumerate([(tx,left),(ty,right)]):
                translation['id']=f'translation_diff_{index}';translation['source_revision_id']=source['id'];key=f'documents/doc_diff/target-{index}.json'
                session.add(TranslationRevision(id=translation['id'],document_id='doc_diff',edition_id='edition_other' if index and cross_locale else 'edition_diff',source_revision_id=source['id'],storage_key=key,snapshot_hash=write_snapshot(cfg.data,key,translation),qa_fingerprint='a'*64))
    return {str(p.relative_to(cfg.data)):file_hash(p) for p in cfg.data.rglob('*.json')}


def compare(client,left,right,axis='source'):
    return client.get('/api/v1/documents/doc_diff/diff',params={'before':left,'after':right,'axis':axis})


@pytest.mark.postgres
def test_original_locator_change_is_provenance_and_never_a_move_or_text_edit(client,database):
    x=sample()['source_revision'];y=changed_source(x)
    next(b for b in y['blocks'] if b['id']=='p1')['provenance'][0]['bbox'][0]+=1
    seed(database,x,y);reply=compare(client,x['id'],y['id']);assert reply.status_code==200
    row=next(r for r in reply.json()['changes'] if r['block_id']=='p1')
    assert row['kind']=='provenance_changed' and row['aspects']==['provenance']


@pytest.mark.postgres
def test_source_normalization_version_change_is_reported_without_a_text_edit(client,database):
    x=sample()['source_revision'];y=changed_source(x)
    y['normalization_version']='normalizer-next'
    validate_source(y)
    seed(database,x,y);reply=compare(client,x['id'],y['id']);assert reply.status_code==200
    assert reply.json()['changes']==[]
    assert reply.json()['revision_changes']=={'normalization_version':{
        'before':x['normalization_version'],'after':'normalizer-next'}}


@pytest.mark.postgres
def test_source_all_block_ids_drift_matches_content_instead_of_add_delete(client,database):
    x=sample()['source_revision'];y=changed_source(x);rename={b['id']:'shift-'+b['id'] for b in y['blocks']}
    def remap(value):
        if isinstance(value,list):return [remap(v) for v in value]
        if isinstance(value,dict):return {k:rename.get(v,v) if (k in {'id','parent_id','owner_id'} or k.endswith('_block_id')) and isinstance(v,str) else [rename.get(i,i) for i in v] if k=='reading_order' or k.endswith('_block_ids') else remap(v) for k,v in value.items()}
        return value
    y=remap(y)
    for b in y['blocks']:b['source_hash']=block_hash(b,y['protected_atoms'])
    validate_source(y)
    seed(database,x,y);reply=compare(client,x['id'],y['id']);assert reply.status_code==200
    assert not any(r['kind'] in {'added','deleted','changed'} or 'content' in r.get('aspects',[]) for r in reply.json()['changes'])


@pytest.mark.postgres
def test_source_and_local_target_change_are_attributed_to_different_axes(client,database):
    data=sample();x=data['source_revision'];y=changed_source(x);tx=data['translation_revision'];ty=copy.deepcopy(tx)
    block=next(b for b in y['blocks'] if b['id']=='p2');block.update(raw_text='A changed original sentence.',normalized_text='A changed original sentence.',normalization_edits=[],source_inline=[{'type':'text','text':'A changed original sentence.'}]);block['source_hash']=block_hash(block,y['protected_atoms'])
    target=next(r for r in ty['results'] if r['block_id']=='p1');target['target_inline'][0]['text']='这个任务包含 '
    original=seed(database,x,y,tx,ty)
    source=compare(client,x['id'],y['id']).json();translation=compare(client,tx['id'],ty['id'],'target').json()
    assert [r['block_id'] for r in source['changes'] if 'content' in r.get('aspects',[])]==['p2']
    assert [r['block_id'] for r in translation['changes'] if 'content' in r.get('aspects',[])]==['p1']
    assert all(file_hash(database[1].data/key)==sha for key,sha in original.items())


@pytest.mark.postgres
def test_retranslation_review_and_profile_audit_do_not_claim_target_text_changed(client,database):
    data=sample();x=data['source_revision'];y=changed_source(x);tx=data['translation_revision'];ty=copy.deepcopy(tx)
    row=next(r for r in ty['results'] if r['block_id']=='p1')
    row['generation']={**row['generation'],'kind':'model','provider':'openai','model':'different-model','prompt_version':'new-prompt','glossary_revision':'glossary-new'}
    row['review_state']='human_reviewed';row['review_record']={'origin':'manual_ui','reason':'Confirmed against the original.'}
    ty['profile_version']='new-profile';ty['glossary_revision']='glossary-new'
    seed(database,x,y,tx,ty);reply=compare(client,tx['id'],ty['id'],'target');assert reply.status_code==200
    result=reply.json();change=next(r for r in result['changes'] if r['block_id']=='p1')
    assert 'content' not in change['aspects'] and set(change['aspects'])=={'generation','review'}
    assert change['kind']=='metadata_changed'
    assert {'profile_version','glossary_revision'}<=set(result['revision_changes'])


@pytest.mark.postgres
def test_target_diff_rejects_cross_locale_revisions(client,database):
    data=sample();x=data['source_revision'];y=changed_source(x);tx=data['translation_revision'];ty=copy.deepcopy(tx);ty['target_language']='en'
    seed(database,x,y,tx,ty,cross_locale=True)
    reply=compare(client,tx['id'],ty['id'],'target')
    assert reply.status_code==409 and reply.json()['error']['code']=='REVISION_LOCALE_MISMATCH'


@pytest.mark.postgres
def test_actual_reading_order_change_is_reported_as_moved(client,database):
    x=sample()['source_revision'];y=changed_source(x);order=list(y['reading_order']);order[1],order[2]=order[2],order[1];_set_order(y,order)
    seed(database,x,y);rows=compare(client,x['id'],y['id']).json()['changes']
    assert any(row['kind']=='moved' and 'order' in row['aspects'] and 'content' not in row['aspects'] for row in rows)


@pytest.mark.postgres
def test_same_target_atoms_with_new_internal_ids_are_source_binding_changes(client,database):
    data=sample();x=data['source_revision'];y=changed_source(x);tx=data['translation_revision'];ty=copy.deepcopy(tx)
    atoms={key:'new-'+key for key in y['protected_atoms']}
    y['protected_atoms']={atoms[key]:value for key,value in y['protected_atoms'].items()}
    def remap(nodes):
        for node in nodes:
            if node['type']=='protected_ref':node['ref']=atoms[node['ref']]
            if 'children' in node:remap(node['children'])
    for block in y['blocks']:remap(block['source_inline']);block['source_hash']=block_hash(block,y['protected_atoms'])
    by={b['id']:b for b in y['blocks']}
    for result in ty['results']:remap(result['target_inline']);result['source_hash']=by[result['block_id']]['source_hash']
    validate_source(y);seed(database,x,y,tx,ty)
    reply=compare(client,tx['id'],ty['id'],'target');assert reply.status_code==200
    assert reply.json()['changes'] and not any(row['kind'] in {'added','deleted'} or 'content' in row['aspects'] for row in reply.json()['changes'])
    assert all(row['aspects']==['source'] for row in reply.json()['changes'])
