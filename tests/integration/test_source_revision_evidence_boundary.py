"""Sealed-source evidence continuity and source-PDF replacement boundaries."""
from pathlib import Path
import pytest

from packages.domain.models import Document,SourceAsset,SourceRevision
from packages.storage import atomic_write,write_snapshot
from tests.integration.test_source_revisions import fixture_source,evidence

ROOT=Path(__file__).resolve().parents[2]


def setup_source(database):
    db,cfg=database;source=fixture_source();key='documents/doc_evidence/source.json'
    atomic_write(cfg.data,'original.pdf',(ROOT/'tests/fixtures/sample.pdf').read_bytes())
    metadata={'inspection':{'sha256':source['sha256'],'pages':[]},'page_images':{'1':'pages/original-1.png'},
        'coverage':{'can_translate':True,'unresolved':[]},'origin':'parser','unrelated_field':'not blindly inherited'}
    with db.transaction() as session:
        session.add(SourceAsset(id='asset_evidence',sha256=source['sha256'],byte_size=3822,page_count=1,storage_key='original.pdf'));session.flush()
        session.add(Document(id='doc_evidence',title='Source evidence continuity',source_asset_id='asset_evidence',current_source_id=source['id']));session.flush()
        session.add(SourceRevision(id=source['id'],document_id='doc_evidence',asset_id='asset_evidence',snapshot_hash=write_snapshot(cfg.data,key,source),storage_key=key,metadata_json=metadata))
    payload={'reason':'Agent verifies original order.', 'evidence':evidence(source),'operations':[{'kind':'reorder','block_ids':source['reading_order']}]}
    return source,payload,metadata


def replace_document_asset(database):
    db,cfg=database
    with db.transaction() as session:
        session.add(SourceAsset(id='asset_replacement',sha256='e'*64,byte_size=1,page_count=1,storage_key='replacement.pdf'));session.flush()
        session.get(Document,'doc_evidence').source_asset_id='asset_replacement'


@pytest.mark.postgres
def test_correction_and_confirmation_preserve_trusted_native_page_evidence(client,database):
    source,payload,metadata=setup_source(database)
    created=client.post(f'/api/v1/sources/{source["id"]}/corrections',json=payload,headers={'If-Match':'"1"','Idempotency-Key':'evidence-correction'})
    assert created.status_code==201,created.text
    draft=created.json()
    for key in ['inspection','page_images']:assert draft['evidence'].get(key)==metadata[key]
    assert 'unrelated_field' not in draft['evidence']
    confirmed=client.post(f'/api/v1/sources/drafts/{draft["id"]}/confirm',json={'source_hash':draft['source_hash']},headers={'If-Match':created.headers['etag'],'Idempotency-Key':'evidence-confirm'})
    assert confirmed.status_code==201,confirmed.text
    with database[0].transaction() as session:
        revision=session.get(SourceRevision,confirmed.json()['id'])
        for key in ['inspection','page_images']:assert revision.metadata_json.get(key)==metadata[key]
        assert revision.metadata_json['mapping'] and revision.metadata_json['evidence']==payload['evidence']


@pytest.mark.postgres
@pytest.mark.parametrize('stage',['correction','confirm'])
def test_replaced_document_pdf_cannot_be_reactivated_through_old_source(client,database,stage):
    source,payload,_=setup_source(database)
    if stage=='confirm':
        created=client.post(f'/api/v1/sources/{source["id"]}/corrections',json=payload,headers={'If-Match':'"1"','Idempotency-Key':'before-replacement'});assert created.status_code==201
        draft=created.json()
    replace_document_asset(database)
    if stage=='correction':
        reply=client.post(f'/api/v1/sources/{source["id"]}/corrections',json=payload,headers={'If-Match':'"1"','Idempotency-Key':'after-replacement'})
    else:
        reply=client.post(f'/api/v1/sources/drafts/{draft["id"]}/confirm',json={'source_hash':draft['source_hash']},headers={'If-Match':created.headers['etag'],'Idempotency-Key':'after-replacement'})
    assert reply.status_code==409 and reply.json()['error']['code']=='SOURCE_BASE_STALE'
