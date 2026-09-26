import { useId, useState } from 'react';
import { api } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { money, resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import type { PreparationEstimates, PreparationMode, PreparationPack, PreparationProgress, Provider, TranslationContextMode } from '../types';
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
  return <section className="translation-preparation-controls" aria-label="翻译准备选项">
    <div className="field"><label htmlFor={id}>翻译前准备</label>
      <select id={id} value={value} disabled={disabled} onChange={event => onChange(event.target.value as PreparationMode)}>
        <option value="extractive">来源摘录与术语提取（无需额外模型请求）</option>
        <option value="local">独立本地小模型：概述与术语建议</option>
        <option value="provider" disabled={!preparationAllowed('provider', profile)}>当前 API 模型：概述与术语建议</option>
        <option value="off">不做论文级准备</option>
      </select>
    </div>
    {value === 'off' ? <p className="field-note">沿用逐段翻译和已有术语表。</p> : <>
      <p className="field-note">先收集来源摘录、章节与术语，再为每段选择相关上下文。准备结果随本次任务保存，可在译文编辑中查看依据。</p>
      {value === 'extractive' && <p className="field-note">直接使用原文摘录和已有术语表；此步骤不调用生成模型。</p>}
      {value === 'provider' && <p className="field-note">由上述 API 服务分析有限来源摘录，生成概述和译名建议；随后继续翻译。</p>}
      {value === 'local' && <LocalAnalyst disabled={disabled}/>}
      {(value === 'provider' || value === 'local') && <p className="field-note">通常增加 1 次分析请求；已确认未发送的失败可能重试。概述和译名建议未经人工核对，模型只会读取选中的有限摘录。</p>}
      <p className="field-note">逐段携带上下文会增加翻译输入量与耗时；这部分不包含在额外分析请求的费用估算中。</p>
    </>}
    {estimate && <p className="field-note preparation-estimate">额外分析请求：{estimate.additional_requests} 次 · 额外分析费用估算：{money(estimate.additional_cost_micro, profile?.currency)}{value === 'local' ? '（本地运行，无托管 API 费用）' : ''}</p>}
    {!preparationAllowed(value, profile) && <p className="notice">当前翻译服务不提供 API 分析，请选择来源摘录或独立本地模型。</p>}
  </section>;
}

type Analyst = { id: string; label: string; model_id: string; runtime: string; bits: number; download_bytes: number;
  status?: string; downloaded_bytes?: number; total_bytes?: number };
const modelStatus: Record<string, string> = { ready: '已下载', not_downloaded: '首次使用时下载', downloading: '正在下载',
  loading: '正在加载', failed: '准备失败，可重试', unavailable: '本地模型服务未就绪' };

function LocalAnalyst({ disabled }: { disabled: boolean }) {
  const result = useResource<{ models: Analyst[] }>('/settings/local-models?purpose=analysis', 5000);
  const action = useAction();
  const model = result.data?.models?.[0];
  return <section className="notice local-analyst" aria-label="本地分析模型">
    <strong>本地分析模型</strong>
    {model ? <>
      <p><strong>{model.label}</strong> · MLX {model.bits} bit</p>
      <p role="status">{modelStatus[model.status ?? 'unavailable'] ?? '状态待刷新'} · 下载约 {Math.round(model.download_bytes / 1024 / 1024)} MiB</p>
      {model.status === 'downloading' && model.total_bytes ? <progress aria-label="分析模型下载进度" value={model.downloaded_bytes ?? 0} max={model.total_bytes}/> : null}
      <button className="btn" type="button" disabled={disabled || action.pending || ['downloading', 'loading'].includes(model.status ?? '')}
        onClick={() => void action.run(async () => { await api(`/settings/local-models/${resourceId(model.id)}/prepare`, { method: 'POST', body: {} }); result.reload(); })}>准备本地分析模型</button>
    </> : result.loading ? <Loading/> : <p>分析模型状态暂不可用。</p>}
    <p className="field-note">在本机 Docker Model Runner 中分析，之后继续使用上述翻译服务。首次使用或点击准备时下载权重；下载、加载与生成会增加耗时。</p>
    <p className="field-note">选择 API 翻译时，选中的来源摘录、概述和术语也会随翻译请求发送到上述 API 地址。</p>
    <ErrorNotice error={result.error} retry={result.reload}/><ActionFeedback {...action}/>
  </section>;
}

type PreparationScope = { kind: 'segment' | 'candidate'; id: string };
export function PreparationView({ draftId, revision, navigate, scope }: {
  draftId: string; revision?: string; navigate: (blockId: string) => void; scope?: PreparationScope;
}) {
  const [open, setOpen] = useState(false);
  const label = scope?.kind === 'segment' ? '本段翻译准备与依据' : scope?.kind === 'candidate' ? '此候选的翻译准备与依据' : '草稿基准准备与依据';
  return <details className="preparation-view section-title" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{label}</summary>
    {open && <PreparationContents key={`${draftId}:${scope?.kind ?? 'draft'}:${scope?.id ?? ''}:${revision ?? ''}`} draftId={draftId} navigate={navigate} scope={scope}/>}
  </details>;
}

function PreparationContents({ draftId, navigate, scope }: { draftId: string; navigate: (blockId: string) => void; scope?: PreparationScope }) {
  const query = scope ? `?${scope.kind === 'segment' ? 'block_id' : 'candidate_id'}=${resourceId(scope.id)}` : '';
  const result = useResource<{ available: boolean; preparation: PreparationPack | null; scope: 'draft' | 'segment' | 'candidate' }>(`/drafts/${resourceId(draftId)}/preparation${query}`);
  const pack = result.data?.preparation;
  const label = scope?.kind === 'segment' ? `段落 ${scope.id} 的翻译准备与依据` : scope?.kind === 'candidate' ? `候选 ${scope.id} 的翻译准备与依据` : '草稿基准准备与依据';
  const scopeNote = scope?.kind === 'segment' ? '当前段落版本保存的准备结果。'
    : scope?.kind === 'candidate' ? '此候选生成时保存的准备结果。'
    : '草稿的基准准备。已有段落和候选可能使用其他准备，请查看对应段落或候选的依据。';
  const emptyNote = scope?.kind === 'segment' ? '本段没有已保存的准备记录；草稿基准不代表本段的翻译依据。'
    : scope?.kind === 'candidate' ? '此候选没有已保存的准备记录；草稿基准不代表此候选的翻译依据。'
    : '此草稿尚无基准准备记录。各段落或候选的依据可在对应内容处查看。';
  const headings = new Map(pack?.headings.map(heading => [heading.block_id, heading.text]) ?? []);
  const evidence = new Map(pack?.evidence.map(item => [item.id, item]) ?? []);
  const scopeName = (scope: string | null) => scope ? headings.get(scope) ?? scope : '全文';
  const references = (ids: string[]) => <span className="preparation-references">{ids.map(id => {
    const item = evidence.get(id);
    return item ? <button className="btn sm" type="button" key={id} onClick={() => navigate(item.block_id)}>查看来源段落 {item.block_id}</button> : null;
  })}</span>;
  return <section className="preparation-content" aria-label={label}>
    <ErrorNotice error={result.error} retry={result.reload}/>{result.loading && <Loading/>}
    {result.data && !pack && <p className="field-note">{emptyNote}现有译文仍可编辑、封存和发布。</p>}
    {pack && <>
      <p className="field-note">{scopeNote}概述、术语提取与译名建议未经人工核对，可对照原文；已有术语表继续优先使用。</p>
      <ContextModeNotice mode={pack.translation_context_mode}/>
      <dl className="kv"><dt>准备修订</dt><dd className="mono">{pack.revision}</dd><dt>来源修订</dt><dd className="mono">{pack.source_revision_id}</dd>
        <dt>收集范围</dt><dd>扫描 {pack.coverage.scanned_blocks} 个来源块；受限而未收录的摘录 {pack.coverage.omitted_evidence} 项、术语 {pack.coverage.omitted_concepts ?? 0} 项，其中过长段落 {pack.coverage.oversized_passages} 项。</dd>
        <dt>模型阅读范围</dt><dd>{pack.analysis ? '仅分析有限来源摘录，未阅读全文。' : '使用来源摘录，未调用分析模型。'}</dd>
      </dl>
      {pack.summary.length ? <><h3>模型概述建议</h3><ul className="preparation-summary">{pack.summary.map((item, index) => <li key={index}><p>{item.text}</p>{references(item.evidence_ids)}</li>)}</ul></> : <h3>来源摘录概览</h3>}
      <div className="preparation-evidence">{pack.evidence.map(item => <article key={item.id}>
        <p className="small muted">{evidenceRole[item.role] ?? item.role} · {scopeName(item.scope)}</p>
        <blockquote>{item.quote}</blockquote>{references([item.id])}
      </article>)}</div>
      {!pack.evidence.length && <p className="field-note">未收集到可展示的来源摘录。</p>}
      <h3>术语与适用范围</h3>
      {pack.concepts.length ? <div className="table-shell"><table><thead><tr><th>来源术语</th><th>译名建议</th><th>范围与依据</th></tr></thead>
        <tbody>{pack.concepts.map(concept => <tr key={concept.id}><td data-label="来源术语"><strong>{concept.source}</strong>{concept.aliases.length ? <p className="small muted">别名：{concept.aliases.join('、')}</p> : null}</td>
          <td data-label="译名建议">{concept.target ?? '尚无译名建议'}<p className="small muted">{concept.origin === 'model' ? '模型建议' : '来源提取'} · 未经人工核对</p></td>
          <td data-label="范围与依据">{scopeName(concept.scope)}{references(concept.evidence_ids)}</td></tr>)}</tbody></table></div> : <p className="field-note">未提取到术语。</p>}
      {pack.warnings.length ? <details><summary>准备提示（{pack.warnings.length}）</summary><ul>{pack.warnings.map((warning, index) => <li key={index}>{preparationWarnings[warning] ?? '部分分析结果未能采用，请对照来源摘录。'}</li>)}</ul><p className="field-note">这些提示不阻止编辑、封存或发布。</p></details> : null}
      <a className="btn section-title" href="#/glossary">管理术语表</a>
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
  return mode === 'terms_only' ? <p className="field-note warn">当前翻译模型仅使用准备的术语；论文概述和来源摘录不随翻译请求发送。</p> : null;
}
export function PreparationJobProgress({ progress }: { progress?: PreparationProgress }) {
  if (!progress?.preparation_status) return null;
  const warnings = Array.isArray(progress.preparation_warnings) ? progress.preparation_warnings.length : progress.preparation_warnings ?? 0;
  return <section className="notice preparation-job-progress" aria-label="翻译准备进度">
    <strong>{progressStatus[progress.preparation_status] ?? '翻译准备'}</strong>
    <p>译名建议：{progress.preparation_terms ?? '—'} · 分析请求：{progress.preparation_requests ?? 0} · 提示：{warnings}</p>
    <ContextModeNotice mode={progress.preparation_context_mode}/>
    {(progress.preparation_omitted_units ?? 0) > 0 && <p className="field-note warn">因请求限额，{progress.preparation_omitted_units} 个翻译单元未携带论文级上下文。</p>}
    <p className="field-note">准备进度独立于已完成译文的段落数量。</p>
  </section>;
}
