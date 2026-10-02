"""Real PostgreSQL/API immutable edits, publication and export over authored IR 4.0."""
from copy import deepcopy
from pathlib import Path
import shutil

import pytest
from sqlalchemy import delete,select

from packages.domain.models import Artifact, Draft, Edition, Export, Job, SearchEntry, SegmentVersion, Settings, SourceDraft, SourceRevision, Task, TranslationRevision
from packages.ir import canonical_bytes, digest, validate_source
from packages.jobs.queue import claim
from packages.storage import file_hash
from workers.main import execute
from tests.support import seed_editor
from tests.unit.test_semantic_consumers import source,render_snapshot

pytestmark=pytest.mark.postgres


def seed_rich(database,tmp_path):
    db,cfg=database
    root=tmp_path/'authored';src=source(root);src['id']='src_fixture'
    ir=render_snapshot(src);ir['document']['id']='doc_fixture'
    ir['translation_revision']['source_revision_id']='src_fixture'
    for asset in src['assets']:
        target=cfg.data/asset['storage_key'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/asset['storage_key'],target)
    for page in src['parser']['evidence']['pages']:
        target=cfg.data/page['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/page['path'],target)
    validate_source(src,asset_root=cfg.data)
    seed_editor(db,cfg,document_ir=ir)
    return ir


def drain(db,cfg):
    for _ in range(20):
        lease=claim(db)
        if lease is None:return
        execute(db,cfg,lease)
    raise AssertionError('Offline local workflow did not become idle')


def test_api_edit_cas_seal_publish_export_and_search_keep_semantics(client,database,tmp_path):
    db,cfg=database;ir=seed_rich(database,tmp_path)
    fetched=client.get('/api/v1/drafts/draft_fixture');assert fetched.status_code==200
    segment=next(s for s in fetched.json()['segments'] if any(n.get('marks')==['strong'] for n in s['target_inline']))
    target=deepcopy(segment['target_inline'])
    for n in target:
        if n.get('marks')==['strong'] and n['type']=='text':n['text']='重要的内容'
    body={'base_segment_version':segment['version'],'reason':'Authored semantic edit','target_inline':target}
    changed=client.patch('/api/v1/drafts/draft_fixture/segments/'+segment['block_id'],json=body,headers={'If-Match':fetched.headers['etag'],'Idempotency-Key':'rich-edit'})
    assert changed.status_code==200,changed.text
    saved=next(s for s in changed.json()['segments'] if s['block_id']==segment['block_id'])
    assert saved['target_inline']==target
    assert client.patch('/api/v1/drafts/draft_fixture/segments/'+segment['block_id'],json=body,headers={'If-Match':fetched.headers['etag'],'Idempotency-Key':'stale-edit'}).status_code==412
    hostile=deepcopy(body);hostile['base_segment_version']=saved['version'];hostile['target_inline'][0]['marks']=['onclick']
    rejected=client.patch('/api/v1/drafts/draft_fixture/segments/'+segment['block_id'],json=hostile,headers={'If-Match':changed.headers['etag'],'Idempotency-Key':'hostile-edit'})
    assert rejected.status_code in {409,422},rejected.text
    qa=client.post('/api/v1/drafts/draft_fixture/validate',json={},headers={'If-Match':changed.headers['etag'],'Idempotency-Key':'rich-qa'})
    assert qa.status_code==200,qa.text
    sealed=client.post('/api/v1/drafts/draft_fixture/seal',json={'qa_id':qa.json()['id'],'qa_fingerprint':qa.json()['fingerprint'],'generation':changed.json()['generation']},headers={'If-Match':changed.headers['etag'],'Idempotency-Key':'rich-seal'})
    assert sealed.status_code==201,sealed.text
    with db.transaction() as session:
        source_file=cfg.data/session.get(SourceRevision,'src_fixture').storage_key
        translation_file=cfg.data/session.get(TranslationRevision,sealed.json()['id']).storage_key
    hashes=(file_hash(source_file),file_hash(translation_file))
    result=client.post('/api/v1/editions/edition_fixture/publish',json={'translation_revision_id':sealed.json()['id'],'expected_generation':1},headers={'If-Match':'"1"','Idempotency-Key':'rich-publish'})
    assert result.status_code==202,result.text
    drain(db,cfg)
    with db.transaction() as session:
        edition=session.get(Edition,'edition_fixture');artifact=session.get(Artifact,edition.current_artifact_id)
        assert artifact and artifact.template_id=='reader-v10'
        artifact_id=artifact.id
        entries=session.scalars(select(SearchEntry)).all()
        assert any('重要的内容' in e.target_text for e in entries)
        assert any('original label' in e.source_text for e in entries)
    for format in ['single_html','bundle']:
        queued=client.post('/api/v1/artifacts/'+artifact_id+'/exports',json={'format':format,'include_source':False},headers={'Idempotency-Key':'rich-'+format})
        assert queued.status_code==202,queued.text
        drain(db,cfg)
        downloaded=client.get('/api/v1/exports/'+queued.json()['export_id'])
        assert downloaded.json()['status']=='succeeded',downloaded.text
        output=client.get(downloaded.json()['download_url'])
        assert output.status_code==200
        if format=='single_html':
            assert '<strong>重要的内容</strong>' in output.text and 'data-tex="x&lt;y"' in output.text
            assert '<th ' in output.text and 'scope="col"' in output.text and 'headers="b-' in output.text
        else:assert output.content.startswith(b'PK')
    assert (file_hash(source_file),file_hash(translation_file))==hashes


def test_rich_source_split_merge_owned_paragraphs_keep_styles(tmp_path):
    from packages.source_revisions import apply_corrections
    src=source(tmp_path);before=deepcopy(src)
    paragraph=next(b for b in src['blocks'] if b['owner_id'] is not None and b['kind']=='paragraph' and b['normalized_text'].startswith('A '))
    loc=paragraph['provenance'][0];evidence={'page':loc['page'],'bbox':loc['bbox'],'quote':paragraph['raw_text']}
    split=apply_corrections(src,[{'kind':'split','block_id':paragraph['id'],'offset':2}],evidence,'Authored PDF paragraph boundary')
    item=next(m for m in split['mapping'] if m['kind']=='split');ids=item['new_block_ids']
    by={b['id']:b for b in split['source']['blocks']}
    assert by[ids[1]]['owner_id']==paragraph['owner_id']
    assert by[ids[1]]['source_inline'][0]['marks']==['emphasis']
    loc=by[ids[0]]['provenance'][0];proof={'page':loc['page'],'bbox':loc['bbox'],'quote':by[ids[0]]['raw_text']}
    merged=apply_corrections(split['source'],[{'kind':'merge','block_ids':ids}],proof,'Restore the stored adjacent paragraph parts')
    validate_source(merged['source'],asset_root=tmp_path)
    restored=next(b for b in merged['source']['blocks'] if b['id']==paragraph['id'])
    assert restored['source_inline']==paragraph['source_inline'] and src==before


def test_parser_spool_promotes_verified_receipts_into_owned_source(database):
    from apps.api.library import enqueue
    from workers.main import parse_spool
    from tests.unit.test_parser_semantics import parse,document,layout
    db,cfg=database;seed_editor(db,cfg)
    with db.transaction() as session:
        enqueue(session,'parse',{'source_asset_id':'source_pdf','base_revision_id':'src_fixture',
            'parser_profile_revision':'chandra-ocr-2-v1','parser_accelerator':'dmr','parser_backend':'vllm'},'doc_fixture')
    lease=claim(db);output=cfg.parser_outputs/lease.task_id/str(lease.fence)
    payload=parse(document(layout('Text','<p>Some <b>printed</b> content <math>x&lt;y</math>.</p>')),output)
    (output/'payload.json').write_bytes(canonical_bytes(payload))
    files=[{'path':p.relative_to(output).as_posix(),'byte_size':p.stat().st_size,'sha256':file_hash(p)} for p in sorted(output.rglob('*')) if p.is_file()]
    result={'task_id':lease.task_id,'fence':lease.fence,'source_sha256':file_hash(cfg.data/'fixtures/sample.pdf'),
        'operation':'parse','status':'succeeded','files':files}
    (output/'result.json').write_bytes(canonical_bytes(result))
    parse_spool(db,cfg,lease)
    with db.transaction() as session:
        draft=session.scalar(select(SourceDraft).where(SourceDraft.document_id=='doc_fixture'))
        src=draft.source;validate_source(src,asset_root=cfg.data)
        receipt=src['parser']['evidence']['pages'][0]
        prefix=f'documents/doc_fixture/parser/{lease.task_id}/{lease.fence}/'
        assert receipt['path'].startswith(prefix+'evidence/')
        assert digest((cfg.data/receipt['path']).read_bytes())==receipt['sha256']
        assert all(a['storage_key'].startswith(prefix) for a in src['assets'])
        assert any(n.get('marks')==['strong'] for b in src['blocks'] for n in b['source_inline'])


def test_durable_translation_restores_rich_spans_after_provider_validation(database,tmp_path):
    from packages.providers.fake import FakeProvider
    from packages.translation.execution import execute_translation
    from tests.integration.test_translation_execution import PROFILE
    db,cfg=database;ir=seed_rich(database,tmp_path)
    with db.transaction() as session:
        session.execute(delete(SegmentVersion))
        settings=session.get(Settings,'singleton');settings.dispatch_disabled=False;settings.instance_budget_micro=10_000_000
        session.get(Draft,'draft_fixture').profile=PROFILE
        source_entity=session.get(SourceRevision,'src_fixture')
        job=Job(id='semantic_translate',document_id='doc_fixture',stage='translating',budget_micro=10_000_000,
            payload={'draft_id':'draft_fixture','source_revision_id':'src_fixture','source_hash':source_entity.snapshot_hash,
                'profile':PROFILE,'locale':'zh-Hans','external_processing_confirmed':True,
                'publish_policy':'manual_approval','glossary_revision':'empty-v1','glossary':[]})
        session.add(job);session.flush();session.add(Task(id='semantic_planner',job_id=job.id,kind='translate'))
    provider=FakeProvider()
    for _ in range(100):
        lease=claim(db)
        if lease is None:break
        execute_translation(db,cfg,lease,provider)
    else:raise AssertionError('Authored translation did not settle')
    assert provider.calls
    assert all(set(n)<=({'type','text'} if n['type']=='text' else {'type','ref'}) for call in provider.calls for u in call for n in u['source_inline'])
    with db.transaction() as session:
        assert session.get(Job,'semantic_translate').status in {'succeeded','completed_with_warnings'}
        nodes=[n for s in session.scalars(select(SegmentVersion)) for n in s.target_inline]
        assert any(n.get('marks')==['strong'] for n in nodes)
        assert any(n.get('marks')==['subscript'] for n in nodes)
        assert any(n['type']=='link' and n['href']=='https://example.org' for n in nodes)
        src=ir['source_revision']
        assert any(n['type']=='protected_ref' and src['protected_atoms'][n['ref']]['kind']=='math' for n in nodes)
