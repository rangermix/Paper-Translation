import { modelLabel, duration } from './job-records';
import { useEffect, useState } from 'react';
import { Empty, ErrorNotice, Icon, Loading } from '../components';
import { resourceId, statusLabel } from '../domain';
import { useResource } from '../hooks';
import type { Job, Page } from '../types';
import { JobDateParts, jobLocale, jobName, jobOperation, jobProgress, jobTone } from './job-presentation';
import './jobs.css';

const filters = [
  ['all', '全部任务'], ['active', '进行中'], ['attention', '需要处理'], ['completed', '已完成'], ['cancelled', '已取消'],
] as const;

function JobRow({ job, selected }: { job: Job; selected: boolean }) {
  const progress = jobProgress(job);
  const created = JobDateParts(job.created_at);
  const tone = jobTone(job.status);
  return <li><a href={`#/jobs/${resourceId(job.id)}`} className={`job-entry ${selected ? 'selected' : ''}`} aria-current={selected ? 'page' : undefined}>
    <div className="job-subject">
      <span className="job-document-icon"><Icon name="pdf"/></span>
      <div className="job-info"><strong className="job-name">{jobName(job)}</strong>
        <div className="job-context"><span>{jobOperation(job.stage)}</span>{job.target_locale && <span>{jobLocale(job.target_locale)}</span>}</div><div className="small muted">{modelLabel(job.actual_model, !job.config_snapshot && !job.actual_model)} · {duration(job.execution_ms)}</div>
      </div>
    </div>
    <div className={`job-state ${tone}`}>
      <span className="job-status"><span className="dot"/>{statusLabel(job.status)}</span>
      {progress && <div className="job-progress"><small>{progress.label}</small><progress aria-label={progress.label} value={progress.value} max={progress.total}/></div>}
      {job.error && job.stage !== 'cleanup' && <span className="job-error-summary" title={job.error.message}>{job.error.message}</span>}
    </div>
    <div className="job-created">{created ? <time dateTime={job.created_at} title={created.full}><span>{created.date}</span><span>{created.time}</span></time> : <span>时间未提供</span>}</div>
    <span className="job-open"><Icon name="arrow"/></span>
  </a></li>;
}

export function JobList({ selectedId }: { selectedId?: string }) {
  const [stage, setStage] = useState('');
  const [model, setModel] = useState('');
  const [search, setSearch] = useState('');
  const [browse, setBrowse] = useState({ q: '', group: 'all', cursors: [] as string[] });
  useEffect(() => {
    const timer = setTimeout(() => setBrowse(previous => previous.q === search.trim() ? previous : { ...previous, q: search.trim(), cursors: [] }), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const params = new URLSearchParams({ limit: '30' });
  if (stage) params.set('stage', stage);
  if (model.trim()) params.set('model', model.trim());
  if (browse.q) params.set('q', browse.q);
  if (browse.group !== 'all') params.set('group', browse.group);
  const cursor = browse.cursors.at(-1);
  if (cursor) params.set('cursor', cursor);
  const list = useResource<Page<Job>>(`/jobs?${params}`, 5000);
  const filtered = !!browse.q || browse.group !== 'all' || !!stage || !!model;
  const reset = () => { setSearch(''); setStage(''); setModel(''); setBrowse({ q: '', group: 'all', cursors: [] }); };
  return <section className="job-browser" aria-label="后台任务列表">
    <div className="job-toolbar"><label className="searchbox"><Icon name="search"/><input aria-label="搜索任务" type="search" placeholder="搜索 PDF 名称或任务编号" maxLength={255} value={search} onChange={e => setSearch(e.target.value)}/></label><span className="small muted">最新创建在前</span></div>
    <div className="job-filters" role="group" aria-label="按任务状态筛选">{filters.map(([value, label]) => <button key={value} type="button" aria-pressed={browse.group === value} onClick={() => setBrowse(previous => ({ ...previous, group: value, cursors: [] }))}>{label}</button>)}</div>
    <div className="job-extra-filters"><label>任务类型 <select value={stage} onChange={e => { setStage(e.target.value); setBrowse(old => ({ ...old, cursors: [] })); }}><option value="">全部类型</option>{['inspect','parse','recovery','quality_check','translate','candidate','semantic_review','metadata_lookup','publish','rebuild','export','cleanup','provider_test','index','maintenance'].map(kind => <option key={kind} value={kind}>{jobOperation(kind)}</option>)}</select></label><label>实际模型 <input className="input" value={model} onChange={e => { setModel(e.target.value); setBrowse(old => ({ ...old, cursors: [] })); }} placeholder="按执行记录筛选"/></label></div>
    <ErrorNotice error={list.error} retry={list.reload}/>
    {list.loading && <Loading/>}
    {!list.loading && list.data && <>
      {list.data.items.length > 0 ? <div className="job-table">
        <div className="jobs-column-head" aria-hidden="true"><span>文档 / 任务</span><span>状态 / 进度</span><span>创建时间</span><span/></div>
        <ul className="job-entries">{list.data.items.map(job => <JobRow key={job.id} job={job} selected={selectedId === job.id}/>)}</ul>
      </div> : <Empty title={filtered ? '没有匹配的任务' : browse.cursors.length ? '这一页已没有任务' : '还没有后台任务'}>
        {filtered ? <><p>试试其他 PDF 名称，或切换任务状态。</p><button className="btn" onClick={reset}>清除筛选</button></> : browse.cursors.length ? <button className="btn" onClick={reset}>返回最新任务</button> : <><p>上传 PDF 或从文档详情开始解析，进度会显示在这里。</p><a className="btn" href="#/library">打开文档库</a></>}
      </Empty>}
      <div className="job-pagination"><span className="small muted" role="status">第 {browse.cursors.length + 1} 页 · {list.data.items.length} 项{filtered ? '匹配任务' : '任务'}</span>
        {(browse.cursors.length > 0 || list.data.next_cursor) && <div className="stack"><button className="btn sm" disabled={!browse.cursors.length} onClick={() => setBrowse(previous => ({ ...previous, cursors: previous.cursors.slice(0, -1) }))}>上一页</button><button className="btn sm" disabled={!list.data.next_cursor} onClick={() => { const next = list.data?.next_cursor; if (next) setBrowse(previous => ({ ...previous, cursors: [...previous.cursors, next] })); }}>下一页</button></div>}
      </div>
    </>}
  </section>;
}
