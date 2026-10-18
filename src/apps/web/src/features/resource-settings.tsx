import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { useAction, useResource } from '../hooks';
import type { Preferences } from '../types';
import { useSettingsForm, useSettingsRefresh } from './settings-state';

export type ResourcePolicy = { max_ram_percent: number; max_vram_percent: number; master_concurrency: number;
  subjob_concurrency: number; auto_concurrency: boolean };
export type MemoryReference = { kind: 'estimate'; weights_bytes: number; kv_cache_bytes: number; workspace_bytes: number;
  ram_bytes: number; vram_bytes: number; context_tokens: number; unified_memory: boolean };
type Capacity = { ram_total_bytes: number | null; ram_used_bytes: number | null; vram_total_bytes: number | null;
  vram_used_bytes: number | null; effective_master_concurrency: number; effective_subjob_concurrency: number;
  active_master_jobs: number; active_subjobs: number; worker_limit: number; waiting_jobs: { id: string; reason: string }[];
  model_references: { id: string; label: string; memory_reference: MemoryReference }[] };
const defaults: ResourcePolicy = { max_ram_percent: 80, max_vram_percent: 80, master_concurrency: 2,
  subjob_concurrency: 1, auto_concurrency: true };
const gib = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
export const resourceReasons: Record<string, string> = {
  MASTER_CONCURRENCY_LIMIT: '等待主任务名额', SUBJOB_CONCURRENCY_LIMIT: '等待子任务名额',
  PARSER_CONCURRENCY_LIMIT: '等待解析器', RAM_BUDGET_LIMIT: '等待 RAM 预算', VRAM_BUDGET_LIMIT: '等待 VRAM 预算',
  RESOURCE_TELEMETRY_UNAVAILABLE: '等待可用的内存监测',
};

export function ModelMemory({ reference, unified }: { reference?: MemoryReference; unified?: boolean }) {
  if (!reference) return null;
  const shared = unified ?? reference.unified_memory;
  return <div className="model-memory" aria-label="模型内存参考">
    <p>运行参考（估算）：{shared ? `统一内存 ${gib(Math.max(reference.ram_bytes, reference.vram_bytes))}` :
      `RAM ${gib(reference.ram_bytes)} · VRAM ${gib(reference.vram_bytes)}`}</p>
    <p>权重 {gib(reference.weights_bytes)} · KV 缓存约 {gib(reference.kv_cache_bytes)} · 工作空间约 {gib(reference.workspace_bytes)}<br/>
      上下文 {reference.context_tokens.toLocaleString()} tokens</p>
  </div>;
}

function MemoryMeter({ label, total, used, percent }: { label: string; total: number | null; used: number | null; percent: number }) {
  const available = total != null && total > 0 && used != null;
  return <div className="resource-meter"><strong>{label}</strong>
    {available ? <><span>{gib(used)} / {gib(total)} · 预算 {gib(total * percent / 100)}</span>
      <meter aria-label={label} min={0} max={total} value={used} high={total * percent / 100}/></> : <span>容量暂不可用</span>}
  </div>;
}

export function ResourceSettings({ preferences, onSaved, reload }: {
  preferences?: Preferences; onSaved: (value: Preferences) => void; reload: () => void;
}) {
  const [draft, setDraft] = useState<Partial<ResourcePolicy>>({});
  const values = { ...defaults, ...preferences?.resources, ...draft };
  const status = useResource<Capacity>('/settings/resources', 5000);
  const action = useAction();
  const fields = [
    ['max_ram_percent', 'RAM 使用上限（%）', 1, 100], ['max_vram_percent', 'VRAM 使用上限（%）', 1, 100],
    ['master_concurrency', '主任务并发上限', 1, 8], ['subjob_concurrency', '每个主任务的子任务并发上限', 1, 8],
  ] as const;
  const valid = fields.every(([key, , min, max]) => Number.isInteger(values[key]) && values[key] >= min && values[key] <= max);
  const saved = preferences?.resources ?? defaults;
  const capacity = status.error ? undefined : status.data;
  const dirty = Boolean(preferences && JSON.stringify(values) !== JSON.stringify({ ...defaults, ...preferences.resources }));
  const canSave = Boolean(preferences && valid && !action.pending && !action.error);
  const session = useSettingsForm('resources', { label: '资源与并发', dirty, pending: action.pending, canSave, save,
    discard: () => { setDraft({}); action.clear(); } });
  const refresh = useSettingsRefresh(dirty, () => { action.clear(); reload(); });
  async function save() {
    if (!canSave) return false;
    let success = false;
    await action.run(async () => {
      const current = session?.preferences() ?? preferences;
      const result = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(current), body: { resources: values } });
      session?.remember(result); onSaved(result); setDraft({}); status.reload(); success = true;
    }, '资源设置已保存，将用于后续任务调度。');
    return success;
  }
  return <section className="panel resource-panel" aria-labelledby="resources-title"><h2 id="resources-title">资源与并发</h2>
    {!preferences ? <Loading/> : <form onSubmit={event => { event.preventDefault(); void save(); }}>
      {dirty && <p className="settings-unsaved small">未保存</p>}
      <div className="resource-fields">{fields.map(([key, label, min, max]) => <label className="field" key={key}>{label}
        <input className="input" type="number" min={min} max={max} step={1} required value={Number.isNaN(values[key]) ? '' : values[key]}
          disabled={action.pending} onChange={event => { setDraft(previous => ({ ...previous, [key]: event.target.value === '' ? NaN : Number(event.target.value) })); if (!action.error) action.clear(); }}/>
      </label>)}</div>
      <label className="check"><input type="checkbox" checked={values.auto_concurrency} disabled={action.pending}
        onChange={event => { setDraft(previous => ({ ...previous, auto_concurrency: event.target.checked })); if (!action.error) action.clear(); }}/>根据 RAM / VRAM 余量自动调整并发</label>
      <div className="resource-meters">
        <MemoryMeter label="RAM（Docker 可见内存）" total={capacity?.ram_total_bytes ?? null} used={capacity?.ram_used_bytes ?? null} percent={saved.max_ram_percent}/>
        <MemoryMeter label="VRAM（GPU 0）" total={capacity?.vram_total_bytes ?? null} used={capacity?.vram_used_bytes ?? null} percent={saved.max_vram_percent}/>
      </div>
      {capacity && <p className="settings-hint">运行中：{capacity.active_master_jobs} 个主任务 / {capacity.active_subjobs} 个子任务；当前并发上限：{capacity.effective_master_concurrency} / 每个主任务 {capacity.effective_subjob_concurrency}。</p>}
      {capacity?.waiting_jobs?.length ? <p role="status">{capacity.waiting_jobs.length} 个任务等待：{[...new Set(capacity.waiting_jobs.map(job => resourceReasons[job.reason] ?? job.reason))].join('、')}。</p> : null}
      <ErrorNotice error={status.error} retry={status.reload}/>
      <ActionFeedback notice={action.notice}/>
      <ErrorNotice error={action.error} retry={refresh.request}/>
      <div className="settings-actions"><button className="btn primary" disabled={!canSave}>保存资源设置</button></div>
    </form>}
    {!!capacity?.model_references?.length && <details className="settings-details"><summary>全部模型的内存参考（估算）</summary>
      <div className="resource-table-scroll"><table><thead><tr><th>模型</th><th>RAM</th><th>VRAM / 统一内存</th><th>上下文</th></tr></thead>
        <tbody>{capacity.model_references.map(({ id, label, memory_reference: ref }) => <tr key={id}><td>{label}</td><td>{gib(ref.ram_bytes)}</td><td>{gib(ref.vram_bytes)}{ref.unified_memory ? '（统一）' : ''}</td><td>{ref.context_tokens.toLocaleString()}</td></tr>)}</tbody></table></div>
    </details>}
    {refresh.confirmation}
  </section>;
}
