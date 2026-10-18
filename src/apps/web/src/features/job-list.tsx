import { resourceReasons } from './resource-settings';
import { modelLabel, duration, jobFailureSummary } from './job-records';
import { useEffect, useRef, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, Empty, ErrorNotice, Icon, Loading, Modal } from '../components';
import { resourceId, statusLabel } from '../domain';
import { useAction, useResource } from '../hooks';
import type { Job, Page } from '../types';
import { JobDateParts, jobLocale, jobName, jobOperation, jobProgress, jobTone } from './job-presentation';
import './jobs.css';

const filters = [
  ['all', '全部任务'], ['active', '进行中'], ['attention', '需要处理'], ['completed', '已完成'], ['cancelled', '已取消'],
] as const;
const instanceStages = new Set(['maintenance', 'backup', 'restore', 'provider_test', 'prepare_parser_model', 'prepare_local_model']);
const documentStages = ['upload','inspect','parse','recovery','quality_check','translate','candidate','semantic_review','metadata_lookup','publish','rollback','rebuild','export','cleanup','index'];

function ClearHistoryDialog({ action, onClose, onCleared }: {
  action: ReturnType<typeof useAction>; onClose: () => void; onCleared: (count: number) => void;
}) {
  const preview = useResource<{ generation: number; clearable_count: number }>('/jobs/history');
  const requestKey = useRef(crypto.randomUUID());
  const refresh = () => {
    action.clear();
    preview.setData(undefined);
    requestKey.current = crypto.randomUUID();
    preview.reload();
  };
  return <Modal title="清除任务历史" onClose={onClose} busy={action.pending}>
    <p>清除所有筛选和分页中的已结束任务，包括已完成、部分完成、失败和已取消的任务。</p>
    <p>正在执行、等待处理或请求结果未知的任务会继续显示。文档、译文、日志和费用记录会保留，可勾选“显示已清除历史”再次查看。</p>
    <ErrorNotice error={preview.error} retry={refresh}/>
    {!preview.data && !preview.error && <Loading/>}
    {preview.data && <p>{preview.data.clearable_count > 0
      ? `当前有 ${preview.data.clearable_count} 项可清除，确认时按最新任务状态处理。`
      : '暂无可清除的已结束任务。'}</p>}
    <ActionFeedback {...action}/>
    <div className="stack">
      <button className="btn" disabled={action.pending} onClick={onClose}>暂不清除</button>
      {action.error && <button className="btn" disabled={action.pending} onClick={refresh}>刷新清除范围</button>}
      <button className="btn danger" disabled={action.pending || !!action.error || !!preview.error || !preview.data?.clearable_count}
        onClick={() => void action.run(async () => {
          const result = await api<{ cleared_count: number }>('/jobs/history/clear', {
            method: 'POST', etag: etagFor(preview.data), key: requestKey.current, body: { confirm: true },
          });
          onCleared(result.cleared_count);
        })}>{action.pending ? '正在清除…' : '确认清除'}</button>
    </div>
  </Modal>;
}

function JobRow({ job, selected, onOpen }: { job: Job; selected: boolean; onOpen?: (trigger: HTMLAnchorElement) => void }) {
  const steps = job.workflow?.job_count ?? 1;
  const progress = steps > 1 ? null : jobProgress(job);
  const created = JobDateParts(job.created_at);
  const status = job.workflow?.status ?? job.status;
  const tone = jobTone(status);
  const name = jobName(job), operation = jobOperation(job.operation ?? job.stage);
  const model = job.actual_model?.kind === 'none' ? null : modelLabel(job.actual_model, !job.config_snapshot && !job.actual_model);
  return <li><a href={`#/jobs/${resourceId(job.id)}`} className={`job-entry ${selected ? 'selected' : ''}`} aria-current={selected ? 'page' : undefined} onClick={event => {
    if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) onOpen?.(event.currentTarget);
  }}>
    <div className="job-subject">
      <span className="job-document-icon"><Icon name="pdf"/></span>
      <div className="job-info"><strong className="job-name">{name}</strong>
        {(name !== operation || job.target_locale) && <div className="job-context">{name !== operation && <span>{operation}</span>}{job.target_locale && <span>{jobLocale(job.target_locale)}</span>}</div>}
        {(steps > 1 || model || job.execution_ms != null) && <div className="small muted">{steps > 1 ? `共 ${steps} 个处理阶段` : <>{model}{model && job.execution_ms != null ? ' · ' : ''}{job.execution_ms != null ? duration(job.execution_ms) : ''}</>}</div>}
      </div>
    </div>
    <div className={`job-state ${tone}`}>
      <span className="job-status"><span className="dot"/>{statusLabel(status)}</span>
      {progress && <div className="job-progress"><small>{progress.label}</small><progress aria-label={progress.label} value={progress.value} max={progress.total}/></div>}
      {job.progress?.resource_wait && ['pending', 'running'].includes(job.status) && <small>{resourceReasons[job.progress.resource_wait] ?? '等待资源'}</small>}
      {job.error && job.stage !== 'cleanup' && <span className="job-error-summary" title={job.error.message}>{jobFailureSummary(job.error)}</span>}
    </div>
    <div className="job-created">{created ? <time dateTime={job.created_at} title={created.full}><span>{created.date}</span><span>{created.time}</span></time> : <span>时间未提供</span>}</div>
    <span className="job-open"><Icon name="arrow"/></span>
  </a></li>;
}

export function JobList({ selectedId, onOpen }: { selectedId?: string; onOpen?: (trigger: HTMLAnchorElement) => void }) {
  const [showCleared, setShowCleared] = useState(false);
  const [clearDialog, setClearDialog] = useState(false);
  const [clearNotice, setClearNotice] = useState('');
  const clearAction = useAction();
  const [stage, setStage] = useState('');
  const [model, setModel] = useState('');
  const [search, setSearch] = useState('');
  const [browse, setBrowse] = useState({ q: '', group: 'all', cursors: [] as string[] });
  useEffect(() => {
    const timer = setTimeout(() => setBrowse(previous => previous.q === search.trim() ? previous : { ...previous, q: search.trim(), cursors: [] }), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const params = new URLSearchParams({ limit: '30', top_level_only: 'true' });
  if (showCleared) params.set('include_cleared', 'true');
  if (stage) params.set('stage', stage);
  if (model.trim()) params.set('model', model.trim());
  if (browse.q) params.set('q', browse.q);
  if (browse.group !== 'all') params.set('group', browse.group);
  const cursor = browse.cursors.at(-1);
  if (cursor) params.set('cursor', cursor);
  const list = useResource<Page<Job>>(`/jobs?${params}`, 5000);
  const documentJobs: Job[] = [], instanceJobs: Job[] = [];
  for (const job of list.data?.items ?? []) (instanceStages.has(job.stage) ? instanceJobs : documentJobs).push(job);
  const attentionCount = instanceJobs.filter(job => jobTone(job.workflow?.status ?? job.status) !== 'quiet').length;
  const groups = [{ key: 'document', label: '文档处理', items: documentJobs }, { key: 'instance', label: '实例维护与服务', items: instanceJobs }];
  const filtered = !!browse.q || browse.group !== 'all' || !!stage || !!model;
  const reset = () => { setSearch(''); setStage(''); setModel(''); setBrowse({ q: '', group: 'all', cursors: [] }); };
  return <section className="job-browser" aria-label="后台任务列表">
    <div className="job-toolbar"><label className="searchbox"><Icon name="search"/><input aria-label="搜索任务" type="search" placeholder="搜索 PDF 名称或任务编号" maxLength={255} value={search} onChange={e => setSearch(e.target.value)}/></label></div>
    <div className="stack between job-history-controls">
      <label className="check"><input type="checkbox" checked={showCleared} onChange={e => {
        setShowCleared(e.target.checked); setBrowse(old => ({ ...old, cursors: [] }));
      }}/>显示已清除历史</label>
      <button className="btn sm" disabled={clearAction.pending} onClick={() => {
        clearAction.clear(); setClearNotice(''); setClearDialog(true);
      }}>清除已结束任务</button>
    </div>
    {!clearDialog && <ActionFeedback error={clearAction.error} notice={clearNotice}/>}
    <div className="job-filters" role="group" aria-label="按任务状态筛选">{filters.map(([value, label]) => <button key={value} type="button" aria-pressed={browse.group === value} onClick={() => setBrowse(previous => ({ ...previous, group: value, cursors: [] }))}>{label}</button>)}</div>
    <div className="job-extra-filters"><label>任务类型 <select value={stage} onChange={e => { setStage(e.target.value); setBrowse(old => ({ ...old, cursors: [] })); }}><option value="">全部类型</option><optgroup label="文档处理">{documentStages.map(kind => <option key={kind} value={kind}>{jobOperation(kind)}</option>)}</optgroup><optgroup label="实例维护与服务">{[...instanceStages].map(kind => <option key={kind} value={kind}>{jobOperation(kind)}</option>)}</optgroup></select></label><label>使用的模型 <input className="input" value={model} onChange={e => { setModel(e.target.value); setBrowse(old => ({ ...old, cursors: [] })); }} placeholder="按模型筛选"/></label></div>
    <ErrorNotice error={list.error} retry={list.reload}/>
    {list.loading && <Loading/>}
    {!list.loading && list.data && <>
      {list.data.items.length > 0 ? <div className="job-table">
        {attentionCount > 0 && <div className="job-instance-attention" role="status">本页有 {attentionCount} 项进行中或需要处理的实例任务。<button type="button" className="btn sm" onClick={() => {
          const heading = document.getElementById('instance-jobs-heading');
          heading?.focus({ preventScroll: true }); heading?.scrollIntoView({ block: 'start' });
        }}>查看实例任务</button></div>}
        <div className="jobs-column-head" aria-hidden="true"><span>文档 / 任务</span><span>状态 / 进度</span><span>创建时间</span><span/></div>
        {groups.filter(group => group.items.length).map(group => <section className="job-group" key={group.key} aria-labelledby={`${group.key}-jobs-heading`}>
          <h3 className="job-group-heading" id={`${group.key}-jobs-heading`} tabIndex={-1}>{group.label}<span>本页 {group.items.length} 项</span></h3>
          <ul className="job-entries">{group.items.map(job => <JobRow key={job.id} job={job} selected={selectedId === job.id} onOpen={onOpen}/>)}</ul>
        </section>)}
      </div> : <Empty title={filtered ? '没有匹配的任务' : browse.cursors.length ? '这一页已没有任务' : '还没有后台任务'}>
        {filtered ? <button className="btn" onClick={reset}>清除筛选</button> : browse.cursors.length ? <button className="btn" onClick={reset}>返回最新任务</button> : <a className="btn" href="#/library">打开文档库</a>}
      </Empty>}
      <div className="job-pagination"><span className="small muted" role="status">第 {browse.cursors.length + 1} 页 · {list.data.items.length} 项{filtered ? '匹配任务' : '任务'}</span>
        {(browse.cursors.length > 0 || list.data.next_cursor) && <div className="stack"><button className="btn sm" disabled={!browse.cursors.length} onClick={() => setBrowse(previous => ({ ...previous, cursors: previous.cursors.slice(0, -1) }))}>上一页</button><button className="btn sm" disabled={!list.data.next_cursor} onClick={() => { const next = list.data?.next_cursor; if (next) setBrowse(previous => ({ ...previous, cursors: [...previous.cursors, next] })); }}>下一页</button></div>}
      </div>
    </>}
    {clearDialog && <ClearHistoryDialog action={clearAction} onClose={() => setClearDialog(false)} onCleared={count => {
      setClearDialog(false); setShowCleared(false); reset(); list.reload();
      setClearNotice(count ? `已清除 ${count} 项已结束任务。` : '暂无可清除的已结束任务。');
    }}/>}
  </section>;
}
