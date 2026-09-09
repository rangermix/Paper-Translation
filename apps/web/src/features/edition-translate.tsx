import { languageName } from '../languages';
import { CostControlNotice, costControlEnabled, budgetValid } from './cost-control';
import { ProviderDestination, privacyNote } from './provider-destination';
import { useEffect, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading, Modal } from '../components';
import { money, resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import type { Provider } from '../types';

type EditionPreflight = {profile_hash?: string; generation: number; source_revision_id: string; source_hash: string; source_language: string; locale: string; profile: Provider; current_draft_id?: string; can_translate: boolean; blocked_reason?: string; planned_units?: number; estimated_cost_micro?: number | null};
export function EditionTranslate({ editionId, close }: {editionId: string; close: () => void}) {
  const result = useResource<EditionPreflight>(`/editions/${resourceId(editionId)}/preflight`);
  const [budget, setBudget] = useState('');
  const [consent, setConsent] = useState(false);
  const [policy, setPolicy] = useState('auto_publish');
  const action = useAction();
  const p = result.data; const costControlled = costControlEnabled(p?.profile);
  useEffect(() => {setConsent(false);}, [p?.source_hash, p?.profile_hash, JSON.stringify(p?.profile), p?.locale]);
  return <Modal title="确认此语言版的翻译任务" onClose={close}>
    <ErrorNotice error={result.error} retry={result.reload}/><ActionFeedback {...action}/>{result.loading && <Loading/>}
    {p && <><p>复用已封存的来源修订。此语言版拥有独立草稿与当前阅读版本。</p>
      <dl className="kv"><dt>语言</dt><dd>{languageName(p.source_language)} → {languageName(p.locale)}</dd><dt>来源修订</dt><dd className="mono">{p.source_revision_id}</dd><dt>来源 SHA</dt><dd className="mono">{p.source_hash}</dd><dt>模型 ID</dt><dd>{p.profile.model_id ?? '未配置'}</dd><dt>配置版本</dt><dd>{p.profile.profile_revision ?? '未配置'}</dd><dt>计划单元</dt><dd>{p.planned_units ?? '待配置'}</dd><dt>费用估算</dt><dd>{money(p.estimated_cost_micro, p.profile.currency)}</dd></dl><ProviderDestination profile={p.profile}/>
      {p.current_draft_id ? <a className="btn primary" href={`#/drafts/${p.current_draft_id}`}>打开已有内容，继续翻译或编辑</a> : <form onSubmit={e => {e.preventDefault(); void action.run(async () => {
        const job = await api<{job_id: string}>(`/editions/${resourceId(editionId)}/translate`, {method: 'POST', etag: etagFor(p), body: {source_revision_id: p.source_revision_id, source_hash: p.source_hash, profile_revision: p.profile.profile_revision, profile_hash: p.profile_hash, ...(costControlled ? { budget_micro: Math.round(Number(budget)*1_000_000) } : {}), external_processing_confirmed: consent, publish_policy: policy}});
        close(); location.hash = `/jobs/${job.job_id}`;
      }); }}>
        {p.blocked_reason && <p className="notice error-notice">暂不能翻译：{p.blocked_reason}</p>}
        <CostControlNotice enabled={costControlled}/>{costControlled && <label className="field">此语言版任务预算（{p.profile.currency ?? 'USD'}）<input className="input" type="number" required min="0.000001" step="0.000001" value={budget} onChange={e => setBudget(e.target.value)}/></label>}
        <label className="field">发布方式<select value={policy} onChange={e => setPolicy(e.target.value)}><option value="manual_approval">手动发布</option><option value="auto_publish">完成后自动发布</option></select></label>
        <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>同意向上述服务地址发送必要源文、上下文和术语，{costControlled ? '并在确认的预算内翻译。' : '我了解未设置任务金额上限，服务仍可能收费。'}</label>
        <p className="field-note">{privacyNote(p.profile)}</p>
        <button className="btn primary" disabled={action.pending || !p.profile_hash || p.profile.dispatch_configuration_ready === false || !p.can_translate || !consent || costControlled && !budgetValid(budget)}>{costControlled ? '确认外发与预算，翻译此语言版' : '确认外发，翻译此语言版'}</button>
      </form>}
    </>}
  </Modal>;
}
