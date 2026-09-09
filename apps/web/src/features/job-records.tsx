import { useEffect, useState } from 'react';
import { ActionFeedback, ErrorNotice, Status } from '../components';
import { resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import type { ExecutionTimes, Job, ModelIdentity, TaskLog } from '../types';
import { jobOperation } from './job-presentation';

const terminal = new Set(['completed', 'succeeded', 'completed_with_warnings', 'partially_completed', 'cancelled', 'failed']);
export function modelLabel(model?: ModelIdentity | null, historical = false) {
  if (model?.kind === 'none') return '无需模型';
  if (model?.kind === 'historical_unknown' || historical) return '历史记录未保存';
  if (!model) return '尚未记录实际模型';
  return model.model_id || (model.kind === 'api' ? '服务未返回实际 model ID' : '本地模型信息未保存');
}
export function duration(milliseconds?: number | null) {
  if (milliseconds == null || !Number.isFinite(milliseconds)) return '未记录';
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds >= 3600 ? `${Math.floor(seconds / 3600)} 小时 ${Math.floor(seconds % 3600 / 60)} 分 ${seconds % 60} 秒`
    : seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}
function timestamp(value?: string | null, empty = '未记录') {
  if (!value) return empty;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : '未记录';
}
export function ExecutionTimesView({ value, status }: { value: ExecutionTimes; status: string }) {
  const [clock, setClock] = useState(Date.now());
  const running = !terminal.has(status) && !value.finished_at;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  const elapsed = running && value.started_at ? clock - Date.parse(value.started_at) : value.execution_ms;
  return <dl className="kv execution-times"><dt>开始时间</dt><dd>{timestamp(value.started_at)}</dd>
    <dt>结束时间</dt><dd>{timestamp(value.finished_at, running ? '尚未结束' : '历史记录未保存')}</dd>
    <dt>排队等待</dt><dd>{duration(value.queue_ms)}</dd><dt>执行耗时</dt><dd>{duration(elapsed)}</dd></dl>;
}
export function ModelView({ model, historical = false }: { model?: ModelIdentity | null; historical?: boolean }) {
  return <div className="model-record"><strong>{modelLabel(model, historical)}</strong>
    {model && model.kind !== 'none' && <details><summary>模型与运行配置</summary><dl className="kv">
      {model.api_protocol && <><dt>API 协议</dt><dd>{model.api_protocol}</dd></>}
      {model.endpoint && <><dt>服务地址</dt><dd className="mono">{model.endpoint}</dd></>}
      {model.config_revision && <><dt>配置版本</dt><dd>{model.config_revision}</dd></>}
      {model.engine && <><dt>本地引擎</dt><dd>{model.engine} {model.engine_version}</dd></>}
      {model.device && <><dt>运行设备</dt><dd>{model.device.toUpperCase()}{model.threads != null ? ` · ${model.threads} 线程` : ''}</dd></>}
      {model.timeout_seconds != null && <><dt>任务时限</dt><dd>{duration(model.timeout_seconds * 1000)}</dd></>}
      {model.models?.map(entry => <div className="model-revision" key={entry.model_id}><dt>{entry.model_id}</dt><dd className="mono">{entry.revision}</dd></div>)}
    </dl></details>}
  </div>;
}

type LogPage = { items: TaskLog[]; next_cursor?: number | null };
export function JobRecords({ job }: { job: Job }) {
  const [filter, setFilter] = useState({ level: '', stage: '', cursors: [] as number[] });
  const action = useAction();
  const params = new URLSearchParams({ limit: '50' });
  if (filter.level) params.set('level', filter.level);
  if (filter.stage) params.set('stage', filter.stage);
  const cursor = filter.cursors.at(-1);
  if (cursor != null) params.set('cursor', String(cursor));
  const logs = useResource<LogPage>(`/jobs/${resourceId(job.id)}/logs?${params}`, terminal.has(job.status) ? 0 : 3000);
  return <section className="job-records" aria-label="执行记录"><h3>执行记录</h3>
    <ModelView model={job.actual_model} historical={!job.actual_model && (!job.config_snapshot || String(job.config_snapshot.evidence_source || '').startsWith('historical'))}/>
    <ExecutionTimesView value={job} status={job.status}/>
    <p className="field-note">时间按 {Intl.DateTimeFormat().resolvedOptions().timeZone} 显示。执行耗时包含期间的暂停和重试，可在日志中查看。</p>
    {job.title_snapshot && <p className="small muted">运行时文档名：{job.title_snapshot}</p>}
    {job.config_snapshot && <details><summary>创建时的配置</summary><pre className="job-config">{JSON.stringify(job.config_snapshot, null, 2)}</pre></details>}
    {job.parent_job_id && <a className="btn sm" href={`#/jobs/${job.parent_job_id}`}>查看上级任务</a>}
    {!!job.child_jobs?.length && <div className="job-children"><h4>后续与子任务</h4>{job.child_jobs.map(child => <p key={child.id}>
      <a href={`#/jobs/${child.id}`}>{jobOperation(child.stage)}</a> <Status value={child.status}/>
    </p>)}</div>}
    <h4>任务日志</h4><div className="stack job-log-controls">
      <label>等级 <select value={filter.level} onChange={e => setFilter(old => ({ ...old, level: e.target.value, cursors: [] }))}>
        <option value="">全部</option><option value="info">信息</option><option value="warning">提示</option><option value="error">错误</option>
      </select></label>
      <label>阶段 <select value={filter.stage} onChange={e => setFilter(old => ({ ...old, stage: e.target.value, cursors: [] }))}>
        <option value="">全部</option>{[...new Set([job.stage, ...(logs.data?.items.map(item => item.stage) ?? [])])].map(stage => <option key={stage} value={stage}>{jobOperation(stage)}</option>)}
      </select></label>
      <a className="btn sm" href={`/api/v1/jobs/${resourceId(job.id)}/logs/download`} download>下载全部脱敏日志</a>
      <button className="btn sm" disabled={!logs.data?.items.length || action.pending} onClick={() => void action.run(async () => {
        await navigator.clipboard.writeText(logs.data!.items.map(item => JSON.stringify(item)).join('\n'));
      }, '本页日志已复制。')}>复制本页</button>
    </div><ActionFeedback {...action}/><ErrorNotice error={logs.error} retry={logs.reload}/>
    {logs.data?.items.length === 0 && <p className="muted">{job.config_snapshot ? '此筛选下暂无日志。' : '历史记录未保存日志。'}</p>}
    <ol className="task-logs">{logs.data?.items.map(entry => <li key={entry.sequence}>
      <time dateTime={entry.at}>{timestamp(entry.at)}</time> <span>{entry.message}</span>
      {entry.page != null && <span> · 第 {entry.page} 页</span>}
      <details><summary>日志详情</summary><pre>{JSON.stringify(entry, null, 2)}</pre></details>
    </li>)}</ol>
    <div className="stack"><button className="btn sm" disabled={!filter.cursors.length} onClick={() => setFilter(old => ({ ...old, cursors: old.cursors.slice(0, -1) }))}>上一页日志</button>
      <button className="btn sm" disabled={logs.data?.next_cursor == null} onClick={() => { const next = logs.data?.next_cursor; if (next != null) setFilter(old => ({ ...old, cursors: [...old.cursors, next] })); }}>下一页日志</button>
    </div>
  </section>;
}
