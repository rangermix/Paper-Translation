import { t, getUiLocale } from '../i18n';
import { useEffect, useState } from 'react';
import { ErrorNotice, Status } from '../components';
import { canResumeJob, resourceId } from '../domain';
import { useResource } from '../hooks';
import type { ExecutionTimes, Job, ModelIdentity, TaskLog } from '../types';
import { jobOperation } from './job-presentation';
import { JobChildren } from './job-children';
import { RecoveryComparison } from './recovery-comparison';
import { errorMessage } from '../messages';

const terminal = new Set(['completed', 'succeeded', 'completed_with_warnings', 'partially_completed', 'cancelled', 'failed']);
export function jobFailureSummary(error: NonNullable<Job['error']>) {
  if (error.code === 'WORKER_FAILED') return t("后台处理失败，当前记录未说明具体原因。");
  const message = errorMessage(error.code, error.message);
  return message === t("本次操作未完成，请查看技术详情或稍后重试。")
    ? t("处理未完成，请查看已记录的错误与执行记录。") : message;
}
export function JobFailure({ job, onReviewUnknown }: { job: Job; onReviewUnknown?: () => void }) {
  const error = job.error;
  if (!error || Object.keys(error).length === 0) return null;
  const unknown = job.status === 'outcome_unknown' || error.code === 'OUTCOME_UNKNOWN' || job.attempts?.some(attempt => attempt.status === 'outcome_unknown');
  const summary = jobFailureSummary(error);
  const parser = job.stage === 'parse' || job.stage === 'prepare_parser_model' || error.code.startsWith('PARSER_');
  const configuration = ['PROVIDER_CONFIG', 'PROFILE_STALE', 'DISPATCH_DISABLED'].includes(error.code) || job.stage === 'provider_test' || job.stage === 'prepare_local_model';
  const page = error.details?.page;
  return <div role="alert" aria-label={t("任务错误")} className="notice error-notice job-failure">
    <strong>{unknown ? t("{operation}：请求结果待核对", { operation: jobOperation(job.operation ?? job.stage) }) : ['completed', 'succeeded', 'completed_with_warnings'].includes(job.status) ? t("{operation}：存在处理提示", { operation: jobOperation(job.operation ?? job.stage) }) : t("{operation}未完成", { operation: jobOperation(job.operation ?? job.stage) })}</strong><p>{summary}</p>
    {typeof page === 'number' && Number.isInteger(page) && page > 0 && <p>{t("已记录位置：第 {value0} 页。", { value0: page })}</p>}
    {unknown ? <p>{t("先核对下方未知请求和供应商记录；结果未确定前，不要直接重发请求。已有费用风险会继续保留。")}</p>
      : canResumeJob(job.status) ? <p>{t("处理所记录的问题后，可使用下方“恢复安全缺失单元”。它不会重发结果未知的请求。")}</p>
      : parser || configuration ? <p>{t("先查看{value0}设置与本次执行记录，确认原因后再从对应入口继续。已有任务仍保留创建时的配置。", { value0: parser ? t("解析") : t("服务") })}</p>
      : <p>{t("先查看本次执行记录，确认原因后再决定下一步；本条记录不能说明其他独立任务是否成功。")}</p>}
    {!job.content_deleted && <div className="stack job-recovery-actions">
      {unknown && onReviewUnknown && <button type="button" className="btn sm" onClick={onReviewUnknown}>{t("查看未知请求")}</button>}
      {!unknown && (parser || configuration) && <a className="btn sm" href="#/settings">{parser ? t("查看解析设置") : t("查看服务设置")}</a>}
      {job.document_id && <a className="btn sm" href={`#/documents/${resourceId(job.document_id)}`}>{t("查看文档与已有结果")}</a>}
      {job.import_id && <a className="btn sm" href={`#/preflight/${resourceId(job.import_id)}`}>{t("查看解析结果")}</a>}
      {job.draft_id && <a className="btn sm" href={`#/drafts/${resourceId(job.draft_id)}`}>{t("查看已保存的译文")}</a>}
    </div>}
    <p>{t("错误代码：")}<code>{error.code}</code></p>
    {(error.message || error.details && Object.keys(error.details).length > 0) && <details><summary>{t("错误技术详情")}</summary>
      {error.message && <p>{error.message}</p>}
      {error.details && Object.keys(error.details).length > 0 && <pre className="job-config">{JSON.stringify(error.details, null, 2)}</pre>}
    </details>}
  </div>;
}
export function modelLabel(model?: ModelIdentity | null, historical = false) {
  if (model?.kind === 'none') return t("无需模型");
  if (model?.kind === 'historical_unknown' || historical) return t("历史记录未保存");
  if (!model) return t("尚未记录使用的模型");
  return model.display_name || model.model_id || (model.kind === 'api' ? t("服务未返回实际 model ID") : t("本地模型信息未保存"));
}
export function duration(milliseconds?: number | null) {
  if (milliseconds == null || !Number.isFinite(milliseconds)) return t("未记录");
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds >= 3600 ? t("{value0} 小时 {value1} 分 {value2} 秒", { value0: Math.floor(seconds / 3600), value1: Math.floor(seconds % 3600 / 60), value2: seconds % 60 })
    : seconds >= 60 ? t("{value0} 分 {value1} 秒", { value0: Math.floor(seconds / 60), value1: seconds % 60 }) : t("{value0} 秒", { value0: seconds });
}
function timestamp(value?: string | null, empty = t("未记录")) {
  if (!value) return empty;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString(getUiLocale(), { hour12: false }) : t("未记录");
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
  return <dl className="kv execution-times"><dt>{t("开始时间")}</dt><dd>{timestamp(value.started_at)}</dd>
    <dt>{t("结束时间")}</dt><dd>{timestamp(value.finished_at, running ? t("尚未结束") : t("历史记录未保存"))}</dd>
    <dt>{t("排队等待")}</dt><dd>{duration(value.queue_ms)}</dd><dt>{t("执行耗时")}</dt><dd>{duration(elapsed)}</dd></dl>;
}
export function ModelView({ model, historical = false }: { model?: ModelIdentity | null; historical?: boolean }) {
  if (model?.kind === 'none') return null;
  return <div className="model-record"><strong>{modelLabel(model, historical)}</strong>
    {model && <details><summary>{t("模型与运行配置")}</summary><dl className="kv">
      {model.model_id && <><dt>{t("模型 ID")}</dt><dd className="mono">{model.model_id}</dd></>}
      {model.api_protocol && <><dt>{t("API 协议")}</dt><dd>{model.api_protocol}</dd></>}
      {model.endpoint && <><dt>{t("服务地址")}</dt><dd className="mono">{model.endpoint}</dd></>}
      {model.config_revision && <><dt>{t("配置版本")}</dt><dd>{model.config_revision}</dd></>}
      {model.engine && <><dt>{t("本地引擎")}</dt><dd>{model.engine} {model.engine_version}</dd></>}
      {model.device && <><dt>{t("运行设备")}</dt><dd>{model.device.toUpperCase()}{model.threads != null ? t(" · {value0} 线程", { value0: model.threads }) : ''}</dd></>}
      {model.inference_engine && <><dt>{t("推理后端")}</dt><dd>{model.inference_engine}</dd></>}
      {model.layout_device && <><dt>{t("版面检测设备")}</dt><dd>{model.layout_device.toUpperCase()}</dd></>}
      {model.model_artifact_id && <><dt>{t("模型制品")}</dt><dd className="mono">{model.model_artifact_id}</dd></>}
      {model.timeout_seconds != null && <><dt>{t("任务时限")}</dt><dd>{duration(model.timeout_seconds * 1000)}</dd></>}
      {model.models?.map(entry => <div className="model-revision" key={entry.model_id}><dt>{entry.model_id}</dt><dd className="mono">{entry.revision}</dd></div>)}
    </dl></details>}
  </div>;
}

type LogPage = { items: TaskLog[]; next_cursor?: number | null };
const logLevels = { info: '信息', warning: '提示', error: '错误' };
// Match stable application operations, never translate arbitrary stored log text.
const logOperations: Record<string, string> = {
  created: '任务已创建', started: '开始执行', finished: '执行结束', state_changed: '任务状态已更新',
  lease_expired: '执行租约已到期', model_loaded: '模型已加载', loading_model: '正在加载模型',
  page_started: '正在解析页面', page_completed: '页面解析完成', check_failed: '检查未完成',
  recovery_started: '开始恢复缺失内容', recovery_completed: '内容恢复结束', metadata_lookup: '正在查询文献信息',
  dispatch: '已派发 API 请求', response_received: '已收到 API 响应', progress: '执行进度已更新',
  history_backfill: '已从原有记录补全文档和任务信息',
};
export function logSummary(operation: string) {
  return t(Object.hasOwn(logOperations, operation) ? logOperations[operation] : '任务执行记录');
}
export function JobRecords({ job }: { job: Job }) {
  const [filter, setFilter] = useState({ level: '', stage: '', limit: 50, cursors: [] as number[] });
  const params = new URLSearchParams({ limit: String(filter.limit) });
  if (filter.level) params.set('level', filter.level);
  if (filter.stage) params.set('stage', filter.stage);
  const cursor = filter.cursors.at(-1);
  if (cursor != null) params.set('cursor', String(cursor));
  const logs = useResource<LogPage>(`/jobs/${resourceId(job.id)}/logs?${params}`, terminal.has(job.status) ? 0 : 3000);
  return <section className="job-records" aria-label={t("执行记录")}><h3>{t("执行记录")}</h3>
    {job.workflow && job.workflow.job_count > 1 && <div className="notice" aria-label={t("整体任务状态")}>
      <div className="stack between"><strong>{t("整体任务")}</strong><Status value={job.workflow.status}/></div>
      <p>{t("共 {value0} 个处理阶段", { value0: job.workflow.job_count })}</p>
    </div>}
    <ModelView model={job.actual_model} historical={!job.actual_model && (!job.config_snapshot || String(job.config_snapshot.evidence_source || '').startsWith('historical'))}/>
    <ExecutionTimesView value={job} status={job.status}/>
    {job.title_snapshot && <p className="small muted">{t("运行时文档名：{value0}", { value0: job.title_snapshot })}</p>}
    {job.config_snapshot && <details><summary>{t("创建时的配置")}</summary><pre className="job-config">{JSON.stringify(job.config_snapshot, null, 2)}</pre></details>}
    {job.parent_job_id && <a className="btn sm" href={`#/jobs/${resourceId(job.parent_job_id)}`}>{job.task_role === 'main' ? t("查看来源任务") : t("查看所属任务")}</a>}
    {job.stage === 'recovery' && !job.content_deleted && <RecoveryComparison key={job.id} jobId={job.id}/>}
    <JobChildren key={`${job.id}-internal`} jobId={job.id}/>
    <JobChildren key={`${job.id}-related`} jobId={job.id} relationship="related"/>
    <h4>{t("任务日志")}</h4><div className="job-log-controls">
      <label>{t("等级 ")}<select value={filter.level} onChange={e => setFilter(old => ({ ...old, level: e.target.value, cursors: [] }))}>
        <option value="">{t("全部")}</option><option value="info">{t("信息")}</option><option value="warning">{t("提示")}</option><option value="error">{t("错误")}</option>
      </select></label>
      <label>{t("阶段 ")}<select value={filter.stage} onChange={e => setFilter(old => ({ ...old, stage: e.target.value, cursors: [] }))}>
        <option value="">{t("全部")}</option>{[...new Set([job.stage, filter.stage, ...(logs.data?.items.map(item => item.stage) ?? [])])].filter(Boolean).map(stage => <option key={stage} value={stage}>{jobOperation(stage)}</option>)}
      </select></label>
    </div><ErrorNotice error={logs.error} retry={logs.reload}/>
    {logs.loading && <p className="small muted" role="status">{t("正在加载日志…")}</p>}
    {logs.data?.items.length === 0 && <p className="muted">{job.config_snapshot ? t("此筛选下暂无日志。") : t("历史记录未保存日志。")}</p>}
    <ol className="task-logs" aria-label={t("任务日志")} aria-busy={logs.loading}>{logs.data?.items.map(entry => <li key={entry.sequence}>
      <details><summary className="task-log-summary">
        <time dateTime={entry.at}>{timestamp(entry.at)}</time>
        <span className={`task-log-level ${entry.level}`}>{t(logLevels[entry.level])}</span>
        <span className="task-log-message">{logSummary(entry.operation)}</span>
        <span className="task-log-page">{entry.page != null ? t("第 {value0} 页", { value0: entry.page }) : ''}</span>
        <span className="task-log-chevron" aria-hidden="true">›</span>
      </summary><pre>{JSON.stringify(entry, null, 2)}</pre></details>
    </li>)}</ol>
    <div className="job-log-pagination">
      <label>{t("每页日志 ")}<select value={filter.limit} onChange={e => setFilter(old => ({ ...old, limit: Number(e.target.value), cursors: [] }))}>
        {[10, 25, 50, 100].map(limit => <option key={limit} value={limit}>{t("{value0} 条", { value0: limit })}</option>)}
      </select></label>
      <nav className="job-log-pages" aria-label={t("日志分页")}>
        <button className="btn sm" disabled={logs.loading || !filter.cursors.length} onClick={() => setFilter(old => ({ ...old, cursors: old.cursors.slice(0, -1) }))}>{t("上一页日志")}</button>
        <span className="small muted" aria-live="polite">{t("第 {value0} 页", { value0: filter.cursors.length + 1 })}</span>
        <button className="btn sm" disabled={logs.loading || !!logs.error || logs.data?.next_cursor == null} onClick={() => { const next = logs.data?.next_cursor; if (next != null) setFilter(old => ({ ...old, cursors: [...old.cursors, next] })); }}>{t("下一页日志")}</button>
      </nav>
    </div>
  </section>;
}
