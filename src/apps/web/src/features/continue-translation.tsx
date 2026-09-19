import { useWorkflowPreferences } from './workflow-preferences';
import { useEffect, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading, Modal } from '../components';
import { resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import { languageName } from '../languages';
import type { Provider } from '../types';
import { CostControlNotice, budgetValid, costControlEnabled } from './cost-control';
import { ProviderDestination } from './provider-destination';

type Preflight = { generation: number; source_revision_id: string; source_hash: string; source_language: string;
  locale: string; profile: Provider; profile_hash: string; can_translate: boolean; blocked_reason?: string };
const reasons: Record<string, string> = {
  PROVIDER_CONFIG: '请先在设置中完成 AI 服务配置。', JOB_ACTIVE: '还有任务正在执行或暂停，请先等待完成或取消。',
  REQUEST_IN_FLIGHT: '仍有请求在途，请等待结果。', OUTCOME_UNKNOWN: '存在结果未知的付费请求，请先在任务中心处理。',
  DISPATCH_DISABLED: '模型请求已暂停，请在设置的暂停提示中恢复模型请求后刷新状态。',
};

export function ContinueTranslation({ draftId, close }: { draftId: string; close: () => void }) {
  const result = useResource<Preflight>(`/drafts/${resourceId(draftId)}/translation-preflight`);
  const { preferences, ready, policy, setPolicy } = useWorkflowPreferences();
  const action = useAction();
  const [consent, setConsent] = useState(false);
  const [budget, setBudget] = useState('');
  const p = result.data, controlled = costControlEnabled(p?.profile);
  useEffect(() => setConsent(false), [p?.profile_hash, p?.source_hash, p?.generation]);
  return <Modal title="翻译未完成内容" onClose={close}>
    <p>保留已有译文，为缺少译文的内容创建新任务。完成后生成阅读版，并按所选方式发布；仍未完成的部分会标明并保留原文。</p>
    <ErrorNotice error={result.error} retry={result.reload}/><ErrorNotice error={preferences.error} retry={preferences.reload}/><ActionFeedback {...action}/>{result.loading && <Loading/>}
    {p && <form onSubmit={event => { event.preventDefault(); void action.run(async () => {
      const job = await api<{ job_id: string }>(`/drafts/${resourceId(draftId)}/translate`, { method: 'POST',
        etag: etagFor(p), body: { source_revision_id: p.source_revision_id, source_hash: p.source_hash,
          profile_revision: p.profile.profile_revision, profile_hash: p.profile_hash,
          ...(controlled ? { budget_micro: Math.round(Number(budget) * 1_000_000) } : {}),
          external_processing_confirmed: consent, publish_policy: policy } });
      close(); location.hash = `/jobs/${job.job_id}`;
    }); }}>
      <p>{languageName(p.source_language)} → {languageName(p.locale)}</p>
      <ProviderDestination profile={p.profile}/><CostControlNotice enabled={controlled}/>
      {p.blocked_reason && <p className="notice">{reasons[p.blocked_reason] ?? '当前无法继续，请刷新页面查看最新状态。'}</p>}
      {controlled && <label className="field">本次任务预算（{p.profile.currency || 'USD'}）<input className="input" type="number"
        min="0.000001" step="0.000001" required value={budget} onChange={e => setBudget(e.target.value)}/></label>}
      <label className="field">发布方式<select value={policy} onChange={e => setPolicy(e.target.value as typeof policy)}><option value="manual_approval">由我选择发布时间</option><option value="auto_publish">完成后自动发布</option></select></label>
      <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>
        同意向上述服务发送必要源文、上下文和术语，{controlled ? '并在本次预算内翻译。' : '我了解未设置金额上限，服务仍可能收费。'}</label>
      <div className="dialog-actions"><a className="btn" href="#/settings" onClick={close}>AI 服务设置</a>
        <button className="btn" type="button" disabled={result.loading || action.pending} onClick={result.reload}>刷新状态</button>
        <button className="btn primary" disabled={!ready || action.pending || !p.can_translate || !consent || controlled && !budgetValid(budget)}>开始翻译未完成内容</button></div>
    </form>}
  </Modal>;
}
