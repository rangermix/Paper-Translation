"""Optional money controls through actual API, PostgreSQL jobs and fake transport."""
from copy import deepcopy
import pytest
from sqlalchemy import func, select

from packages.domain.models import Attempt, Document, Edition, Job, Permit, SegmentVersion, Settings, SourceDraft, SourceRevision
from packages.ir import digest
from packages.jobs.queue import claim
from packages.providers.contract import ProviderFailure
from packages.providers.fake import FakeProvider
from packages.providers.settings import managed_profile, save_configuration
from packages.storage import read_snapshot
from packages.translation.execution import execute_translation
from tests.integration.test_translation_execution import PROFILE
from tests.support import seed_editor

pytestmark=pytest.mark.postgres


def prepare(client,database,monkeypatch,tmp_path,controlled=False):
    db,cfg=database
    monkeypatch.setenv('PROVIDER_CONFIG_DIR',str(tmp_path/'cost-config'))
    monkeypatch.setenv('PROVIDER_PROFILE_FILE',str(tmp_path/'no-external'))
    p=deepcopy(PROFILE)|{'endpoint':'http://localhost:9/synthetic','auth_mode':'none','api_protocol':'responses',
        'cost_control_enabled':controlled,'semantic_review_enabled':True}
    if not controlled:p.pop('price')
    save_configuration(p,None,True,'"0"','cost-settings')
    frozen=managed_profile();seed_editor(db,cfg)
    with db.transaction() as session:
        settings=session.get(Settings,'singleton');settings.dispatch_disabled=False;settings.instance_budget_micro=0
        source=read_snapshot(cfg.data,session.get(SourceRevision,'src_fixture'))
        session.add(SourceDraft(id='cost_import',document_id='doc_fixture',asset_id='source_pdf',source=source,
            coverage={'can_translate':True,'unresolved':[]},evidence={'kind':'controlled-local-fixture'}))
    return db,cfg,frozen,source


def start(client,db,profile,source,flow,**extra):
    body={'profile_hash':digest(profile),'profile_revision':profile['profile_revision'],'external_processing_confirmed':True}|extra
    if flow=='import':
        path='/imports/cost_import/confirm'
        body|={'source_hash':digest(source),'preflight_generation':1,'locale':'zh-Hans'}
    elif flow=='edition':
        with db.transaction() as session:
            session.get(Edition,'edition_fixture').target_locale='en';session.flush()
            session.add(Edition(id='cost_edition',document_id='doc_fixture',target_locale='zh-Hans'))
            revision=session.get(SourceRevision,'src_fixture')
            body|={'source_revision_id':revision.id,'source_hash':revision.snapshot_hash}
        path='/editions/cost_edition/translate'
    else:
        path='/drafts/draft_fixture/'+('candidates' if flow=='candidate' else 'semantic-review')
        body|={'block_ids':['p1'],'glossary_revision':'empty-v1'}
    return client.post('/api/v1'+path,json=body,headers={'If-Match':'"1"','Idempotency-Key':'start-'+flow})


@pytest.mark.parametrize('flow',['import','edition','candidate','semantic'])
def test_disabled_costs_allow_all_four_confirmed_flows_without_price_or_budget(client,database,monkeypatch,tmp_path,flow):
    db,cfg,p,source=prepare(client,database,monkeypatch,tmp_path)
    response=start(client,db,p,source,flow)
    assert response.status_code==202,response.text
    job_id=response.json()['job_id'];provider=FakeProvider()
    from workers.main import execute
    while lease:=claim(db):
        if lease.kind in {'translate','candidate','semantic_review'}:
            execute_translation(db,cfg,lease,provider)
        else:
            execute(db,cfg,lease)
    assert provider.calls
    view=client.get('/api/v1/jobs/'+job_id).json()
    assert view['cost_control_enabled'] is False and view['budget_micro'] is None
    assert view['costs']['actual_micro'] is None
    with db.transaction() as session:
        permits=list(session.scalars(select(Permit).where(Permit.job_id==job_id)))
        assert permits and all(row.state=='settled' and row.actual_micro is None and row.reserved_micro is None for row in permits)
        assert all(row.price_snapshot['cost_control_enabled'] is False for row in permits)
        assert session.get(Settings,'singleton').dispatch_disabled is False
        assert session.get(Job,job_id).status not in ('waiting_budget','waiting_config','outcome_unknown','failed')


@pytest.mark.parametrize('flow',['import','edition','candidate','semantic'])
def test_enabled_controls_still_require_budget_at_each_api_entry(client,database,monkeypatch,tmp_path,flow):
    db,cfg,p,source=prepare(client,database,monkeypatch,tmp_path,True)
    result=start(client,db,p,source,flow)
    assert result.status_code==422 and result.json()['error']['code']=='BUDGET_REQUIRED',result.text
    with db.transaction() as session:assert session.scalar(select(func.count()).select_from(Job))==0


@pytest.mark.parametrize('flow',['import','edition','candidate','semantic'])
def test_disabled_money_never_removes_external_processing_confirmation(client,database,monkeypatch,tmp_path,flow):
    db,cfg,p,source=prepare(client,database,monkeypatch,tmp_path)
    result=start(client,db,p,source,flow,external_processing_confirmed=False)
    assert result.status_code==409 and result.json()['error']['code']=='EXTERNAL_PROCESSING_UNCONFIRMED'
    with db.transaction() as session:assert session.scalar(select(func.count()).select_from(Permit))==0


@pytest.mark.parametrize('mode',['missing_usage','unpriced_usage','model_mismatch','timeout'])
def test_uncontrolled_usage_uncertainty_is_distinct_from_unknown_execution(client,database,monkeypatch,tmp_path,mode):
    db,cfg,p,source=prepare(client,database,monkeypatch,tmp_path)
    response=start(client,db,p,source,'edition');assert response.status_code==202,response.text
    provider=FakeProvider()
    original=provider.translate
    def reply(units,profile,glossary):
        result=original(units,profile,glossary)
        if mode=='timeout':raise ProviderFailure('OUTCOME_UNKNOWN','unknown')
        if mode=='missing_usage':result['usage']=None
        elif mode=='unpriced_usage':result['usage']['unpriced_usage_dimensions']=['server_tool_use']
        else:result['failure_code']='PROVIDER_MODEL_MISMATCH'
        return result
    provider.translate=reply
    execute_translation(db,cfg,claim(db),provider)
    execute_translation(db,cfg,claim(db),provider)
    with db.transaction() as session:
        permit=session.scalar(select(Permit))
        if mode in ('timeout','model_mismatch'):
            assert permit.state=='unknown' and session.get(Job,response.json()['job_id']).status=='outcome_unknown'
        else:
            assert permit.state=='settled' and permit.actual_micro is None
    if mode in ('timeout','model_mismatch'):assert claim(db) is None
    assert len(provider.calls)==1


def test_unknown_retry_without_cost_control_needs_risk_confirmation_but_no_budget(client,database,monkeypatch,tmp_path):
    db,cfg,p,source=prepare(client,database,monkeypatch,tmp_path)
    started=start(client,db,p,source,'edition');assert started.status_code==202
    provider=FakeProvider([ProviderFailure('OUTCOME_UNKNOWN','unknown')])
    execute_translation(db,cfg,claim(db),provider);execute_translation(db,cfg,claim(db),provider)
    view=client.get('/api/v1/jobs/'+started.json()['job_id'])
    with db.transaction() as session:attempt=session.scalar(select(Attempt).where(Attempt.state=='outcome_unknown'));aid=attempt.id
    path='/api/v1/attempts/'+aid+'/resolve'
    body={'decision':'retry_accept_risk','reason':'Synthetic explicit retry after unknown result'}
    rejected=client.post(path,json=body,headers={'If-Match':view.headers['etag'],'Idempotency-Key':'no-risk'})
    assert rejected.status_code==409
    approved=client.post(path,json=body|{'duplicate_charge_risk_confirmed':True},headers={'If-Match':view.headers['etag'],'Idempotency-Key':'accept-risk'})
    assert approved.status_code==200,approved.text
    assert approved.json()['budget_micro'] is None and approved.json()['costs']['unknown_micro'] is None
    with db.transaction() as session:assert session.scalar(select(Permit)).state=='unknown'
    assert len(provider.calls)==1
