import { t, formatList } from '../i18n';
import { useId, useState } from 'react';
import { api } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { money, resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import type { Preferences, PreparationEstimates, PreparationMode, PreparationPack, PreparationProgress, Provider, TranslationContextMode } from '../types';
import { inferenceLabels, modelStatusLabels, type LocalModel } from './local-models';
import './translation-preparation.css';

export function preparationAllowed(mode: PreparationMode, profile?: Provider) {
  return mode !== 'provider' || Boolean(profile?.api_protocol && profile.api_protocol !== 'local_translation');
}

export function PreparationControls({ value, onChange, profile, estimates, disabled = false }: {
  value: PreparationMode; onChange: (mode: PreparationMode) => void; profile?: Provider;
  estimates?: PreparationEstimates; disabled?: boolean;
}) {
  const id = useId();
  const estimate = estimates?.[value];
  return <section className="translation-preparation-controls" aria-label={t("翻译准备选项")}>
    <div className="field"><label htmlFor={id}>{t("翻译前准备")}</label>
      <select id={id} value={value} disabled={disabled} onChange={event => onChange(event.target.value as PreparationMode)}>
        <option value="extractive">{t("提取参考内容和术语")}</option>
        <option value="local">{t("独立本地小模型：概述与术语建议")}</option>
        <option value="provider" disabled={!preparationAllowed('provider', profile)}>{t("当前 API 模型：概述与术语建议")}</option>
        <option value="off">{t("不做论文级准备")}</option>
      </select>
    </div>
    {value === 'local' && <LocalAnalyst disabled={disabled}/>}
    {estimate && <p className="field-note preparation-estimate">{t("额外分析请求：{value1} 次 · 额外分析费用估算：{value2}{value3}", { value1: String((estimate.additional_requests) ?? ''), value2: String((money(estimate.additional_cost_micro, profile?.currency)) ?? ''), value3: String((value === 'local' ? t("（本地运行，无托管 API 费用）") : '') ?? '') })}</p>}
    {!preparationAllowed(value, profile) && <p className="notice">{t("当前翻译服务不提供 API 分析，请选择“提取参考内容和术语”或独立本地模型。")}</p>}
  </section>;
}

function LocalAnalyst({ disabled }: { disabled: boolean }) {
  const result = useResource<{ models: LocalModel[] }>('/settings/local-models?purpose=analysis', 5000);
  const preferences = useResource<Preferences>('/settings/preferences');
  const action = useAction();
  const model = result.data?.models?.find(row => row.model_id === preferences.data?.local_analyst_model_id);
  const backend = preferences.data?.local_analyst_backend ?? model?.default_backend ?? model?.runtime ?? '';
  const compatible = Boolean(model && (model.inference_backends ?? [model.runtime]).includes(backend));
  const state = model?.backend_states?.[backend] ?? model;
  return <section className="notice local-analyst" aria-label={t("本地分析模型")}>
    <strong>{t("本地分析模型")}</strong>
    {model ? <>
      <p><strong>{model.label}</strong> · {model.format?.toUpperCase()} {model.quantization ?? `${model.bits} bit`} · {inferenceLabels[backend] ? t(inferenceLabels[backend]) : backend}</p>
      <p role="status">{t("{value1} · 下载约 {value2} MiB", { value1: String((result.error || preferences.error ? t("状态更新失败，请刷新后核对") : compatible ? t(modelStatusLabels[state?.status ?? ''] ?? "状态未提供") : t("已保存的推理后端在当前部署中不可用")) ?? ''), value2: String((Math.round(model.download_bytes / 1024 / 1024)) ?? '') })}</p>
      <details className="model-choice-details"><summary>{t("模型 ID 与性能说明")}</summary><p>{t("用途：翻译前的背景与术语准备，不生成正文译文。当前设备的速度与质量对比：未提供。")}</p><dl className="kv"><dt>{t("模型 ID")}</dt><dd className="mono">{model.model_id}</dd></dl><p>{t("选择和保存不会下载或加载模型。")}</p></details>
      {state?.status === 'downloading' && state.total_bytes ? <progress aria-label={t("分析模型下载进度")} value={state.downloaded_bytes ?? 0} max={state.total_bytes}/> : null}
      <button className="btn" type="button" disabled={disabled || action.pending || !compatible || Boolean(preferences.error || result.error) || ['downloading', 'loading', 'unavailable'].includes(state?.status ?? 'unavailable')}
        onClick={() => void action.run(async () => { await api(`/settings/local-models/${resourceId(model.id)}/prepare?backend=${encodeURIComponent(backend)}`, { method: 'POST', body: {} }); result.reload(); })}>{t("准备本地分析模型")}</button>
    </> : result.loading || preferences.loading ? <Loading/> : result.error || preferences.error ? <p>{t("模型信息读取失败，请刷新后核对。")}</p> : <p>{t("已保存的分析模型在当前部署中不可用，请到设置选择支持的模型和推理后端。")}</p>}
    <a href="#/settings">{t("设置分析模型")}</a>
    <ErrorNotice error={result.error} retry={result.reload}/><ErrorNotice error={preferences.error} retry={preferences.reload}/><ActionFeedback {...action}/>
  </section>;
}

type PreparationScope = { kind: 'segment' | 'candidate'; id: string };
export function PreparationView({ draftId, revision, navigate, scope }: {
  draftId: string; revision?: string; navigate: (blockId: string) => void; scope?: PreparationScope;
}) {
  const [open, setOpen] = useState(false);
  const label = scope?.kind === 'segment' ? t("本段翻译准备与依据") : scope?.kind === 'candidate' ? t("此候选的翻译准备与依据") : t("翻译依据");
  return <details className="preparation-view section-title" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{label}</summary>
    {open && <PreparationContents key={`${draftId}:${scope?.kind ?? 'draft'}:${scope?.id ?? ''}:${revision ?? ''}`} draftId={draftId} navigate={navigate} scope={scope}/>}
  </details>;
}

function PreparationContents({ draftId, navigate, scope }: { draftId: string; navigate: (blockId: string) => void; scope?: PreparationScope }) {
  const query = scope ? `?${scope.kind === 'segment' ? 'block_id' : 'candidate_id'}=${resourceId(scope.id)}` : '';
  const result = useResource<{ available: boolean; preparation: PreparationPack | null; scope: 'draft' | 'segment' | 'candidate' }>(`/drafts/${resourceId(draftId)}/preparation${query}`);
  const pack = result.data?.preparation;
  const label = scope?.kind === 'segment' ? t("段落 {value1} 的翻译准备与依据", { value1: scope.id }) : scope?.kind === 'candidate' ? t("候选 {value1} 的翻译准备与依据", { value1: scope.id }) : t("翻译依据");
  const emptyNote = scope?.kind === 'segment' ? t("本段没有已保存的准备记录。")
    : scope?.kind === 'candidate' ? t("此候选没有已保存的准备记录。")
    : t("此草稿尚无基准准备记录。");
  const headings = new Map(pack?.headings.map(heading => [heading.block_id, heading.text]) ?? []);
  const evidence = new Map(pack?.evidence.map(item => [item.id, item]) ?? []);
  const scopeName = (scope: string | null) => scope ? headings.get(scope) ?? scope : t("全文");
  const references = (ids: string[]) => <span className="preparation-references">{ids.map(id => {
    const item = evidence.get(id);
    return item ? <button className="btn sm" type="button" key={id} onClick={() => navigate(item.block_id)}>{t("查看来源段落 {value1}", { value1: String((item.block_id) ?? '') })}</button> : null;
  })}</span>;
  return <section className="preparation-content" aria-label={label}>
    <ErrorNotice error={result.error} retry={result.reload}/>{result.loading && <Loading/>}
    {result.data && !pack && <p className="field-note">{emptyNote}</p>}
    {pack && <>
      <ContextModeNotice mode={pack.translation_context_mode}/>
      <dl className="kv"><dt>{t("准备修订")}</dt><dd className="mono">{pack.revision}</dd><dt>{t("来源修订")}</dt><dd className="mono">{pack.source_revision_id}</dd>
        <dt>{t("收集范围")}</dt><dd>{t("扫描 {value1} 个来源块；受限而未收录的摘录 {value2} 项、术语 {value3} 项，其中过长段落 {value4} 项。", { value1: String((pack.coverage.scanned_blocks) ?? ''), value2: String((pack.coverage.omitted_evidence) ?? ''), value3: String((pack.coverage.omitted_concepts ?? 0) ?? ''), value4: String((pack.coverage.oversized_passages) ?? '') })}</dd>
        <dt>{t("模型阅读范围")}</dt><dd>{pack.analysis ? t("仅分析有限来源摘录，未阅读全文。") : t("使用来源摘录，未调用分析模型。")}</dd>
      </dl>
      {pack.summary.length ? <><h3>{t("模型概述建议")}</h3><ul className="preparation-summary">{pack.summary.map((item, index) => <li key={index}><p>{item.text}</p>{references(item.evidence_ids)}</li>)}</ul></> : <h3>{t("来源摘录概览")}</h3>}
      <div className="preparation-evidence">{pack.evidence.map(item => <article key={item.id}>
        <p className="small muted">{evidenceRole[item.role] ? t(evidenceRole[item.role]) : item.role} · {scopeName(item.scope)}</p>
        <blockquote>{item.quote}</blockquote>{references([item.id])}
      </article>)}</div>
      {!pack.evidence.length && <p className="field-note">{t("未收集到可展示的来源摘录。")}</p>}
      <h3>{t("术语与适用范围")}</h3>
      {pack.concepts.length ? <div className="table-shell"><table><thead><tr><th>{t("来源术语")}</th><th>{t("译名建议")}</th><th>{t("范围与依据")}</th></tr></thead>
        <tbody>{pack.concepts.map(concept => <tr key={concept.id}><td data-label={t("来源术语")}><strong>{concept.source}</strong>{concept.aliases.length ? <p className="small muted">{t("别名：{value1}", { value1: String((formatList(concept.aliases)) ?? '') })}</p> : null}</td>
          <td data-label={t("译名建议")}>{concept.target ?? t("尚无译名建议")}<p className="small muted">{t("{value1} · 未经人工核对", { value1: String((concept.origin === 'model' ? t("模型建议") : t("来源提取")) ?? '') })}</p></td>
          <td data-label={t("范围与依据")}>{scopeName(concept.scope)}{references(concept.evidence_ids)}</td></tr>)}</tbody></table></div> : <p className="field-note">{t("未提取到术语。")}</p>}
      {pack.warnings.length ? <details><summary>{t("准备提示（{value1}）", { value1: String((pack.warnings.length) ?? '') })}</summary><ul>{pack.warnings.map((warning, index) => <li key={index}>{t(preparationWarnings[warning] ?? "部分分析结果未能采用，请对照来源摘录。")}</li>)}</ul></details> : null}
      <a className="btn section-title" href="#/glossary">{t("管理术语表")}</a>
    </>}
  </section>;
}

const evidenceRole: Record<string, string> = { definition: '作者定义', acronym: '缩写', abstract: '摘要', contribution: '贡献陈述',
  conclusion: '结论', title: '题名', heading: '章节标题', caption: '图注', table_cell: '表格内容', passage: '正文摘录' };
const preparationWarnings: Record<string, string> = {
  PREPARATION_CONTEXT_LIMIT: '输入范围超出分析请求限制，已使用来源摘录。',
  PREPARATION_NO_EVIDENCE: '没有可供分析的来源摘录，已保留直接提取的结果。',
  PREPARATION_SCHEMA: '模型返回内容未符合准备格式，已保留来源摘录。',
  PREPARATION_EVIDENCE: '模型返回的依据未通过来源校验，已保留来源摘录。',
  PREPARATION_CONFLICT: '模型译名建议存在冲突，已保留来源摘录和已有术语。',
  PREPARATION_INCOMPLETE: '模型分析未完整返回，已保留来源摘录。',
};
const progressStatus: Record<string, string> = { pending: '准备等待中', running: '正在收集和分析', completed: '准备已完成' };
function ContextModeNotice({ mode }: { mode?: TranslationContextMode }) {
  return mode === 'terms_only' ? <p className="field-note warn">{t("当前翻译模型仅使用准备的术语；论文概述和来源摘录不随翻译请求发送。")}</p> : null;
}
export function PreparationJobProgress({ progress }: { progress?: PreparationProgress }) {
  if (!progress?.preparation_status) return null;
  const warnings = Array.isArray(progress.preparation_warnings) ? progress.preparation_warnings.length : progress.preparation_warnings ?? 0;
  return <section className="notice preparation-job-progress" aria-label={t("翻译准备进度")}>
    <strong>{t(progressStatus[progress.preparation_status] ?? "翻译准备")}</strong>
    <p>{t("译名建议：{value1} · 分析请求：{value2} · 提示：{value3}", { value1: String((progress.preparation_terms ?? '—') ?? ''), value2: String((progress.preparation_requests ?? 0) ?? ''), value3: String((warnings) ?? '') })}</p>
    <ContextModeNotice mode={progress.preparation_context_mode}/>
    {(progress.preparation_omitted_units ?? 0) > 0 && <p className="field-note warn">{t("因请求限额，{value1} 个翻译单元未携带论文级上下文。", { value1: String((progress.preparation_omitted_units) ?? '') })}</p>}
  </section>;
}
