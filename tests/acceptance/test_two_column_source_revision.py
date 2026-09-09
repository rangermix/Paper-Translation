"""Correct a controlled historical column misorder using genuine parsed PDF text."""
import copy
import json
import os
from pathlib import Path
import shutil
import uuid

import pytest
from sqlalchemy import func, select

from packages.domain.models import Artifact, Document, Draft, Edition, Publication, SourceAsset, SourceDraft, SourceRevision, TranslationRevision
from packages.ir import digest, validate_source
from packages.jobs.queue import claim
from packages.source_revisions.corrections import _set_order
from packages.storage import file_hash, read_snapshot, write_snapshot
from workers.main import execute

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.postgres
def test_double_column_reorder_new_sealed_source_diff_and_old_publication_immutable(client,database):
    corpus=Path(os.environ.get('TWO_COLUMN_SOURCE_CORPUS',ROOT/'.agent/tmp/evidence/two-column-source-runs/fcbd77bc/outputs/two-column/1'))
    if not (corpus/'payload.json').is_file():pytest.skip('Requires actual production-spool two-column PDF inference.')
    actual=json.loads((corpus/'payload.json').read_text(encoding='utf8'));correct=actual['source_revision']
    assert actual['coverage']['can_translate']
    assert file_hash(corpus/'original.pdf')==correct['sha256']==file_hash(ROOT/'fixtures/two-column-source/two-column-source.pdf')
    validate_source(correct,asset_root=corpus)
    wrong=copy.deepcopy(correct);wrong['id']='src_two_column_wrong'
    wrong_order=list(wrong['reading_order']);wrong_order[2],wrong_order[3]=wrong_order[3],wrong_order[2]
    _set_order(wrong,wrong_order);validate_source(wrong)
    # Deliberately introduced historical misorder; never attributed to this
    # parser run, whose original correct source and model output stay unchanged.
    db,cfg=database
    for asset in correct['assets']:
        destination=cfg.data/asset['storage_key'];destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(corpus/asset['storage_key'],destination)
    shutil.copytree(corpus/'pages',cfg.data/'pages')
    original_pdf_hash=file_hash(cfg.data/'original.pdf')
    key='documents/doc_two_column/sources/wrong.json';old_hash=write_snapshot(cfg.data,key,wrong)
    with db.transaction() as session:
        asset=correct['assets'][0]
        session.add(SourceAsset(id=asset['id'],sha256=asset['sha256'],byte_size=asset['byte_size'],page_count=2,storage_key='original.pdf'));session.flush()
        session.add(Document(id='doc_two_column',title='Two column source ordering fixture',source_asset_id=asset['id'],current_source_id=wrong['id'],source_language='en'));session.flush()
        session.add(SourceRevision(id=wrong['id'],document_id='doc_two_column',asset_id=asset['id'],snapshot_hash=old_hash,storage_key=key,
            metadata_json={'origin':'controlled_historical_order_perturbation','inspection':actual['inspection'],'coverage':actual['coverage'],
                'page_images':{'1':'pages/page-0001.png','2':'pages/page-0002.png'}}))
        # Same-language retained publication isolates source-history behavior;
        # there is no fabricated bilingual or model-quality claim.
        session.add(Edition(id='edition_two_column',document_id='doc_two_column',target_locale='en',current_draft_id='draft_two_column'));session.flush()
        session.add(Draft(id='draft_two_column',document_id='doc_two_column',edition_id='edition_two_column',source_revision_id=wrong['id']))
    qa=client.post('/api/v1/drafts/draft_two_column/validate',json={},headers={'If-Match':'"1"','Idempotency-Key':'old-qa'})
    assert qa.status_code==200 and qa.json()['valid'],qa.text
    sealed=client.post('/api/v1/drafts/draft_two_column/seal',json={'qa_id':qa.json()['id'],'qa_fingerprint':qa.json()['fingerprint'],'generation':1},
        headers={'If-Match':'"1"','Idempotency-Key':'old-seal'})
    assert sealed.status_code==201,sealed.text
    published=client.post('/api/v1/editions/edition_two_column/publish',json={'translation_revision_id':sealed.json()['id'],'expected_generation':1},
        headers={'If-Match':'"1"','Idempotency-Key':'old-publish'})
    assert published.status_code==202,published.text
    execute(db,cfg,claim(db))
    with db.transaction() as session:
        edition=session.get(Edition,'edition_two_column');artifact=session.get(Artifact,edition.current_artifact_id)
        artifact_id=artifact.id;artifact_path=cfg.data/artifact.storage_key
        translation=session.get(TranslationRevision,sealed.json()['id']);translation_path=cfg.data/translation.storage_key;translation_hash=translation.snapshot_hash
    old_artifact_files={p.relative_to(artifact_path).as_posix():file_hash(p) for p in artifact_path.rglob('*') if p.is_file()}
    old_read=client.get(f'/artifacts/{artifact_id}/index.html');assert old_read.status_code==200
    old_read_hash=digest(old_read.content)
    block=next(b for b in wrong['blocks'] if b['id']==correct['reading_order'][2]);loc=block['provenance'][0]
    proof={'page':loc['page'],'bbox':loc['bbox'],'quote':block['raw_text']}
    document=client.get('/api/v1/documents/doc_two_column')
    correction=client.post('/api/v1/sources/src_two_column_wrong/corrections',json={
        'reason':'Compared both original PDF columns: finish the left column before starting the right. Restore beta before gamma without changing any author text.',
        'evidence':proof,'operations':[{'kind':'reorder','block_ids':correct['reading_order']}]},
        headers={'If-Match':document.headers['etag'],'Idempotency-Key':'column-correction'})
    assert correction.status_code==201,correction.text
    draft=correction.json()
    confirmed=client.post(f'/api/v1/sources/drafts/{draft["id"]}/confirm',json={'source_hash':draft['source_hash']},
        headers={'If-Match':correction.headers['etag'],'Idempotency-Key':'column-confirm'})
    assert confirmed.status_code==201,confirmed.text
    new_id=confirmed.json()['source_revision_id'];assert new_id!=wrong['id']
    diff=client.get('/api/v1/documents/doc_two_column/diff',params={'before':wrong['id'],'after':new_id,'axis':'source'})
    assert diff.status_code==200,diff.text
    moved=[change for change in diff.json()['changes'] if 'order' in change['aspects']]
    assert {c['block_id'] for c in moved}=={correct['reading_order'][2],correct['reading_order'][3]}
    assert all(c['kind']=='moved' and 'content' not in c['aspects'] for c in moved)
    with db.transaction() as session:
        new=session.get(SourceRevision,new_id);fixed=read_snapshot(cfg.data,new)
        assert new.parent_id==wrong['id'] and new.asset_id==correct['original_asset_id']
        assert fixed['reading_order']==correct['reading_order']
        assert {b['id']:(b['raw_text'],b['normalized_text'],b['source_inline'],b['provenance']) for b in fixed['blocks']}=={
            b['id']:(b['raw_text'],b['normalized_text'],b['source_inline'],b['provenance']) for b in correct['blocks']}
        assert new.metadata_json['mapping']==confirmed.json()['mapping'] and new.metadata_json['inspection']==actual['inspection']
        assert session.get(Document,'doc_two_column').current_source_id==new_id
        assert session.get(Edition,'edition_two_column').current_artifact_id==artifact_id
        assert session.scalar(select(func.count()).select_from(SourceAsset))==1
        assert session.scalar(select(func.count()).select_from(Publication))==1
    assert file_hash(cfg.data/key)==old_hash and file_hash(translation_path)==translation_hash
    assert file_hash(cfg.data/'original.pdf')==original_pdf_hash
    assert old_artifact_files=={p.relative_to(artifact_path).as_posix():file_hash(p) for p in artifact_path.rglob('*') if p.is_file()}
    assert digest(client.get(f'/artifacts/{artifact_id}/index.html').content)==old_read_hash
    output=ROOT/'.agent/tmp/evidence/two-column-source-api'/uuid.uuid4().hex;output.mkdir(parents=True)
    for name,value in [('source-correct-parser',correct),('source-wrong-historical',wrong),('source-fixed',fixed),('correction-response',draft),('source-diff',diff.json())]:
        (output/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    shutil.copytree(cfg.data,output/'data')
    report={'scope':'Real original PDF and production parser; a declared controlled historical order perturbation is fixed by public APIs. Same-language retained publication; no Provider or bilingual-quality claim.',
        'parser_corpus':str(corpus),'parser_result_sha256':file_hash(corpus/'payload.json'),'original_pdf_sha256':original_pdf_hash,
        'old_source_sha256':old_hash,'new_source_sha256':digest(fixed),'old_translation_sha256':translation_hash,
        'old_artifact_id':artifact_id,'old_artifact_files':old_artifact_files,'old_reader_sha256':old_read_hash,
        'new_source_revision_id':new_id,'source_asset_count':1,'publication_count':1,'original_bytes_unchanged':True,
        'page_images':{'1':'data/pages/page-0001.png','2':'data/pages/page-0002.png'},'provider_calls':0}
    (output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
