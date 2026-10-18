import { PreparationControls, PreparationView, preparationAllowed } from './translation-preparation';
import { ContinueTranslation } from './continue-translation';
import { EditorQuality, isImportant } from './editor-quality';
import { SegmentEditor } from './segment-editor';
import { useEditorState } from './editor-state';
import { requestNavigation, useNavigationGuard } from '../navigation-guard';
import './editor.css';
import { languageName } from '../languages';
import { costControlEnabled, budgetValid } from './cost-control';
import { ProviderDestination } from './provider-destination';
import { useEffect, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading, Modal, PageHead, PdfLocator } from '../components';
import { money, resourceId, sourceTextEdit } from '../domain';
import { useAction, useResource } from '../hooks';
import { SemanticSummary } from './semantic-summary';
import { DraftExport } from './draft-export';
import { QualityResolution } from './quality-resolution';
import { CandidateGroupView } from './candidates';
import type { Document, Draft, Issue, Provider, QA, PreparationMode } from '../types';
export function Editor({ id }: { id: string }) {
  const result = useResource<Draft>(`/drafts/${resourceId(id)}`); const provider = useResource<Provider>('/settings/provider'); const costControlled = costControlEnabled(provider.data); const doc = useResource<Document>(result.data ? `/documents/${resourceId(result.data.document_id)}` : null); const action = useAction();
  const editing = useEditorState(result.data, saved => { result.setData(saved); setSealed(undefined); });
  const [composing, setComposing] = useState<Set<string>>(new Set());
  const guard = useNavigationGuard(editing.hasDirty || composing.size > 0 || editing.saving);
  const refreshVersion = () => { void requestNavigation().then(proceed => { if (proceed) result.reload(); }); };
  const [preparation, setPreparation] = useState<PreparationMode>('extractive');
  const [continueOpen, setContinueOpen] = useState(false); const [draftExportOpen, setDraftExportOpen] = useState(false); const [allowReviewedSelection, setAllowReviewedSelection] = useState(false); const [requestMode, setRequestMode] = useState<'candidate' | 'semantic'>('candidate'); const [correctionKind, setCorrectionKind] = useState('replace_text'); const [correctionOffset, setCorrectionOffset] = useState('0'); const [correctionOrder, setCorrectionOrder] = useState(''); const [resolveIssue, setResolveIssue] = useState<Issue>(); const [selected, setSelected] = useState<Set<string>>(new Set()); const [filter, setFilter] = useState('all'); const [candidateDialog, setCandidateDialog] = useState(false); const [budget, setBudget] = useState(''); const [consent, setConsent] = useState(false); const [sealed, setSealed] = useState<string>(); const [sourceDialog, setSourceDialog] = useState(false); const [correctionBlock, setCorrectionBlock] = useState(''); const [correctionText, setCorrectionText] = useState(''); const [correctionReason, setCorrectionReason] = useState(''); const [sourceDraft, setSourceDraft] = useState<{id: string; source_hash: string; generation: number}>();
  const glossary = useResource<{revision: string}>(result.data?.source?.language ? `/glossaries/effective?document_id=${resourceId(result.data.document_id)}&source_language=${resourceId(result.data.source.language)}&target_language=${resourceId(result.data.target_locale)}` : null);
  useEffect(() => { setConsent(false); }, [JSON.stringify(provider.data), glossary.data?.revision, result.data?.source_hash, result.data?.generation]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [jump, setJump] = useState<{ id: string; sequence: number }>();
  useEffect(() => {
    if (!jump) return;
    const element = document.getElementById(`segment-${jump.id}`);
    element?.focus({ preventScroll: true });
    element?.scrollIntoView({ block: 'start' });
  }, [jump]);
  const draft = result.data;
  if (!draft) return <><ErrorNotice error={result.error} retry={result.reload}/>{result.loading && <Loading/>}</>;
  const hasDirty = editing.hasDirty || composing.size > 0 || editing.saving; const qaCurrent = draft.qa && draft.qa.generation === draft.generation && !draft.qa.stale; const validQa = qaCurrent && (draft.qa!.valid === true || ['passed', 'ready', 'valid'].includes(draft.qa!.status)); const edition = doc.data?.editions.find(e => e.id === draft.edition_id);
  const issues = draft.qa?.issues ?? draft.issues ?? [];
  const blockerIds = new Set(issues.filter(isImportant).flatMap(i => i.block_id ? [i.block_id] : []));
  const firstEditableId = draft.segments.find(segment => segment.translatable !== false)?.block_id;
  const isExpanded = (blockId: string) => expanded[blockId] ?? (blockId === firstEditableId || blockerIds.has(blockId));
  const navigate = (blockId: string) => {
    setFilter('all'); setExpanded(old => ({ ...old, [blockId]: true }));
    setJump(old => ({ id: blockId, sequence: (old?.sequence ?? 0) + 1 }));
  };
  const translatableCount = draft.segments.filter(segment => segment.translatable !== false).length;
  const retainedCount = draft.segments.length - translatableCount;
  const visible = draft.segments.filter(segment => {
    if (segment.block_id === jump?.id) return true;
    if (filter === 'retained') return segment.translatable === false;
    if (filter === 'selected') return selected.has(segment.block_id);
    if (filter === 'unreviewed') return segment.translatable !== false && segment.review_status !== 'human_reviewed';
    return segment.translatable !== false || blockerIds.has(segment.block_id);
  });
  const visibleIds = new Set(visible.map(segment => segment.block_id));
  const qualityLabel = !draft.qa ? '尚未运行质量检查' : !qaCurrent ? '质量报告已过期' : draft.qa.state === 'failed' ? '质量检查未完成' : validQa ? '本次检查未发现重要问题' : '当前版本有内容提示';
  return <>
    <PageHead title="译文编辑" actions={<>
      {firstEditableId && <button className="btn editor-jump" onClick={() => navigate(firstEditableId)}>开始编辑正文</button>}
      <button className="btn primary" disabled={!editing.hasDirty || editing.saving || composing.size > 0} onClick={() => void editing.save()}>{editing.saving ? '正在保存…' : `保存修改${editing.dirtyCount ? `（${editing.dirtyCount} 段）` : ''}`}</button>
      <button className="btn" disabled={editing.saving} onClick={refreshVersion}>刷新版本</button>
      <a className="btn" href={`#/documents/${draft.document_id}`}>文档详情</a>
    </>}/>
    <ErrorNotice error={result.error} retry={refreshVersion}/><ActionFeedback {...action}/>
    <ActionFeedback error={editing.error} notice={editing.notice}/>
    <section className="panel editor-summary">
      <div className="stack between"><div><h2>{doc.data?.title ?? draft.document_id}</h2>
        <span className="muted small">{languageName(draft.target_locale)} · {translatableCount} 段可翻译 · {retainedCount} 项保留原文</span>
      </div><span className="pill">{editing.hasDirty ? `${editing.dirtyCount} 段未保存` : '当前草稿已保存'}</span></div>
      <p className="small editor-progress">{draft.segments.filter(segment => segment.translatable !== false && segment.target_inline.length > 0).length} / {translatableCount} 段已有译文 · 已人工核对 {draft.segments.filter(segment => segment.review_status === 'human_reviewed').length} 段（可选）</p>
      <p className="muted small editor-reading-state">正在编辑当前草稿。{edition?.current_artifact_id ? '已有阅读版保持不变，保存草稿不会自动发布。' : '保存草稿后，可另行生成阅读版本。'}</p>
      <div className="editor-action-groups">
        <button className="btn" disabled={hasDirty} onClick={() => setContinueOpen(true)}>翻译未完成内容</button>
        <details className="editor-tool-group"><summary>检查与版本</summary><div className="editor-tool-content">
          <p className={`field-note ${validQa ? '' : 'warn'}`}><strong>{qualityLabel}</strong>{action.pending && <span> · 正在处理…</span>}</p>
          <SemanticSummary draft={draft}/>
          <div className="stack">
            <button className="btn" disabled={action.pending || hasDirty} onClick={() => void action.run(async () => { await api<QA>(`/drafts/${resourceId(id)}/validate`, { method: 'POST', etag: etagFor(draft), body: {} }); setSealed(undefined); result.reload(); }, '已运行当前草稿的质量检查。')}>运行质量检查</button>
            <button className="btn" disabled={action.pending || hasDirty} onClick={() => void action.run(async () => { const response = await api<{ translation_revision_id: string }>(`/drafts/${resourceId(id)}/seal`, { method: 'POST', etag: etagFor(draft), body: { qa_id: draft.qa?.id, qa_fingerprint: draft.qa?.fingerprint, generation: draft.generation } }); setSealed(response.translation_revision_id); result.reload(); }, '已保存为不可修改的新版本，尚未切换当前阅读版。')}>保存为新版本</button>
            {sealed && <button className="btn primary" disabled={action.pending || !edition || hasDirty} onClick={() => void action.run(async () => { const job = await api<{ job_id: string }>(`/editions/${resourceId(draft.edition_id)}/publish`, { method: 'POST', etag: etagFor(edition), body: { translation_revision_id: sealed, expected_generation: edition?.generation } }); location.hash = `/jobs/${job.job_id}`; })}>构建并发布封存版</button>}
          </div>
          <p className="muted small">保存为新版本会形成不可修改的快照；发布后才更新阅读版。内容提示不阻止保存或发布。</p>
          {draft.qa && <details><summary>检查与草稿版本详情</summary><small>草稿版本 {draft.generation} · 报告 {draft.qa.id} · {draft.qa.fingerprint}</small></details>}
        </div></details>
        <details className="editor-tool-group"><summary>批量处理（已选 {selected.size} 段）</summary><div className="editor-tool-content">
          <p>仅处理已选择的 {selected.size} 段。修改候选需要另行接受。</p>
          <div className="stack"><button className="btn" disabled={!selected.size || hasDirty} onClick={() => { setRequestMode('candidate'); setCandidateDialog(true); setConsent(false); glossary.reload(); }}>局部重译（{selected.size} 段）</button>
            <button className="btn" disabled={!selected.size || hasDirty || !provider.data?.semantic_review_enabled} onClick={() => { setRequestMode('semantic'); setCandidateDialog(true); setConsent(false); }}>检查译文含义</button></div>
          <p className="muted small">由模型辅助检查，结果供参考。</p>
          <label className="check"><input type="checkbox" checked={allowReviewedSelection} onChange={event => { setAllowReviewedSelection(event.target.checked); if (!event.target.checked) setSelected(old => new Set([...old].filter(blockId => draft.segments.find(segment => segment.block_id === blockId)?.review_status !== 'human_reviewed'))); }}/>允许明确选择已人工核对段落</label>
        </div></details>
        <details className="editor-tool-group"><summary>翻译依据与原文</summary><div className="editor-tool-content">
          <PreparationView draftId={draft.id} revision={`${draft.source_hash}:${draft.preparation_revision ?? ''}:${draft.generation}`} navigate={navigate}/>
          <div className="stack"><button className="btn" disabled={hasDirty} onClick={() => { setSourceDraft(undefined); setCorrectionKind('replace_text'); setCorrectionOrder((draft.source?.reading_order ?? []).join('\n')); setSourceDialog(true); setCorrectionBlock(draft.segments[0]?.block_id ?? ''); setCorrectionText(draft.segments[0]?.source_text ?? ''); }}>修正原文识别</button><a className="btn" href="#/glossary">术语表</a></div>
        </div></details>
        <button className="btn" disabled={hasDirty || action.pending} onClick={() => setDraftExportOpen(true)}>导出已有内容</button>
      </div>
      {hasDirty && <p className="muted small">先保存或处理当前未保存修改，再运行检查、重译或发布。</p>}
      {issues.length > 0 ? <details className="editor-check-results"><summary>检查结果 · {issues.length} 条提示{!qaCurrent ? '（待更新）' : ''}</summary><EditorQuality issues={issues} navigate={navigate} resolve={qaCurrent ? setResolveIssue : undefined} resolveDisabled={hasDirty}/></details> : <p className="muted small editor-quality-compact">{qualityLabel}</p>}
    </section>
    {draft.candidates?.length ? <details className="panel editor-candidate-results"><summary>待接受候选 · {draft.candidates.length} 组</summary>{draft.candidates.map(candidate => <CandidateGroupView key={candidate.id} candidate={candidate} draft={draft} hasDirty={hasDirty} refresh={result.reload} navigate={navigate}/>)}</details> : null}
    <div className="stack section-title editor-segment-tools">
      <label>显示 <select value={filter} onChange={event => { setFilter(event.target.value); setJump(undefined); }}><option value="all">全部可翻译段落</option><option value="retained">保留原文内容</option><option value="unreviewed">尚未人工确认</option><option value="selected">已选择段落</option></select></label>
      <button className="btn sm" onClick={() => setExpanded(Object.fromEntries(draft.segments.map(segment => [segment.block_id, true])))}>展开全部段落</button>
      <button className="btn sm" onClick={() => setExpanded(Object.fromEntries(draft.segments.map(segment => [segment.block_id, blockerIds.has(segment.block_id)])))}>折叠无重要提示的段落</button>
      <span className="small muted">显示 {visible.filter(segment => segment.translatable !== false).length} 段可翻译内容、{visible.filter(segment => segment.translatable === false).length} 项保留原文</span>
    </div>
    {filter !== 'retained' && visible.some(segment => segment.translatable === false) && <p className="muted small">另展示有重要提示或刚定位到的保留原文内容，便于对照。</p>}
    <div className="segments">{draft.segments.map(segment => <SegmentEditor key={segment.block_id}
      expanded={isExpanded(segment.block_id)} toggle={() => setExpanded(old => ({ ...old, [segment.block_id]: !isExpanded(segment.block_id) }))}
      hidden={!visibleIds.has(segment.block_id)} blocked={blockerIds.has(segment.block_id)} stale={!qaCurrent}
      segment={{ ...segment, protected_atoms: segment.protected_atoms ?? Object.fromEntries(Object.entries(draft.source?.protected_atoms ?? {}).map(([key, atom]) => [key, atom.value])) }}
      draft={draft} navigate={navigate} allowReviewedSelection={allowReviewedSelection} refresh={() => { setSealed(undefined); result.reload(); }}
      selected={selected.has(segment.block_id)} select={checked => setSelected(old => { const next = new Set(old); if (checked) next.add(segment.block_id); else next.delete(segment.block_id); return next; })}
      edit={editing.editFor(segment)} change={patch => editing.change(segment, patch)} save={() => editing.save(segment.block_id)} saving={editing.saving} composing={composing.size > 0}
      rebase={() => editing.rebase(segment)} compositionChanged={active => setComposing(old => { const next = new Set(old); if (active) next.add(segment.block_id); else next.delete(segment.block_id); return next; })}/>)}</div>
    {guard.requested && <Modal title="有未保存的修改" onClose={() => guard.resolve(false)} busy={editing.saving}><p>{editing.dirtyCount} 段修改尚未保存。离开前请选择如何处理。</p>{composing.size > 0 && <p role="status">请先完成当前输入法组合，再保存或放弃修改。</p>}<ActionFeedback error={editing.error} notice={editing.notice}/><div className="stack"><button className="btn primary" disabled={editing.saving} onClick={() => guard.resolve(false)}>继续编辑</button><button className="btn" disabled={editing.saving || composing.size > 0} onClick={() => { editing.discard(); guard.resolve(true); }}>放弃修改</button><button className="btn" disabled={editing.saving || composing.size > 0} onClick={() => void editing.save().then(saved => { if (saved) guard.resolve(true); })}>保存后离开</button></div></Modal>}{continueOpen && <ContinueTranslation draftId={draft.id} close={() => setContinueOpen(false)}/>} {draftExportOpen && <DraftExport draft={draft} close={() => setDraftExportOpen(false)}/>} {resolveIssue && <QualityResolution draft={draft} issue={resolveIssue} close={() => setResolveIssue(undefined)} refresh={result.reload}/>} {candidateDialog && <Modal title={requestMode === 'candidate' ? '为所选段落生成候选' : '检查译文含义'} onClose={() => setCandidateDialog(false)}><p>已选择 {selected.size} 段</p><dl className="kv"><dt>模型</dt><dd>{provider.data?.model_id ?? '未配置'}</dd><dt>配置</dt><dd>{provider.data?.profile_revision ?? '未配置'}</dd><dt>术语修订</dt><dd>{glossary.data?.revision ?? draft.glossary_revision ?? '无'}</dd></dl><ProviderDestination profile={provider.data}/><form onSubmit={e => { e.preventDefault(); void action.run(async () => { const job = await api<{ job_id: string }>(`/drafts/${resourceId(id)}/${requestMode === 'candidate' ? 'candidates' : 'semantic-review'}`, { method: 'POST', etag: etagFor(draft), body: { block_ids: [...selected], profile_revision: provider.data?.profile_revision, profile_hash: provider.data?.profile_hash, glossary_revision: requestMode === 'candidate' ? glossary.data?.revision ?? draft.glossary_revision : draft.glossary_revision, ...(costControlled ? { budget_micro: Math.round(Number(budget) * 1_000_000) } : {}), external_processing_confirmed: consent, ...(requestMode === 'candidate' ? { preparation: { mode: preparation } } : {}) } }); setCandidateDialog(false); location.hash = `/jobs/${job.job_id}`; }); }}>{requestMode === 'candidate' && <PreparationControls value={preparation} onChange={mode => { setPreparation(mode); setConsent(false); }} profile={provider.data} disabled={action.pending}/>}{costControlled && <div className="field"><label htmlFor="candidate-budget">候选任务预算（{provider.data?.currency ?? 'USD'}）</label><input className="input" id="candidate-budget" type="number" min="0.000001" step="0.000001" value={budget} onChange={e => setBudget(e.target.value)} required/></div>}<label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>我同意向上述服务地址发送所选源文、必要上下文与术语，{costControlled ? `并确认 ${budgetValid(budget) ? money(Math.round(Number(budget) * 1_000_000), provider.data?.currency) : '尚未填写的'} 预算。` : '我了解未设置任务金额上限，服务仍可能收费。'}</label><ActionFeedback {...action}/><button className="btn primary section-title" disabled={action.pending || requestMode === 'candidate' && !preparationAllowed(preparation, provider.data) || !provider.data?.profile_hash || !provider.data?.configured || provider.data.dispatch_configuration_ready === false || !consent || costControlled && !budgetValid(budget)}>{requestMode === 'candidate' ? '创建局部候选任务' : '创建含义检查任务'}</button></form></Modal>}{sourceDialog && <Modal title="修正原文识别" onClose={() => setSourceDialog(false)}><form onSubmit={e => { e.preventDefault(); const segment = draft.segments.find(s => s.block_id === correctionBlock)!; void action.run(async () => { const corrected = await api<{id: string; source_hash: string; generation: number}>(`/sources/${resourceId(draft.source_revision_id)}/corrections`, { method: 'POST', etag: etagFor(doc.data), body: { reason: correctionReason, evidence: { page: segment.locators![0].page, bbox: segment.locators![0].bbox, quote: segment.source_text }, operations: [correctionKind === 'replace_text' ? { kind: 'replace_text', block_id: correctionBlock, ...sourceTextEdit(segment.source_text, correctionText) } : correctionKind === 'split' ? {kind: 'split', block_id: correctionBlock, offset: Number(correctionOffset)} : {kind: correctionKind, block_ids: correctionOrder.split(/[\s,，]+/).filter(Boolean)}] } }); setSourceDraft(corrected); doc.reload(); result.reload(); }, '已创建来源草稿；可查看修正结果并保存为新来源。'); }}><div className="field"><label htmlFor="correct-block">来源段落</label><select id="correct-block" value={correctionBlock} onChange={e => { setCorrectionBlock(e.target.value); setCorrectionText(draft.segments.find(s => s.block_id === e.target.value)?.source_text ?? ''); }}>{draft.segments.map(s => <option key={s.block_id}>{s.block_id}</option>)}</select></div><PdfLocator originalUrl={draft.original_url} documentId={draft.document_id} locators={draft.segments.find(s => s.block_id === correctionBlock)?.locators}/><label className="field">机械修正操作<select value={correctionKind} onChange={e => {setCorrectionKind(e.target.value); setCorrectionOrder((draft.source?.reading_order ?? []).join('\n'));}}><option value="replace_text">修正机械提取字符</option><option value="reorder">调整根块阅读顺序</option><option value="split">拆分正文段落</option><option value="merge">合并相邻正文段落</option></select></label>{correctionKind === 'replace_text' ? <div className="field"><label htmlFor="correct-text">核对后的原文</label><textarea id="correct-text" required value={correctionText} onChange={e => setCorrectionText(e.target.value)}/></div> : correctionKind === 'split' ? <label className="field">Unicode 字符拆分位置<input className="input" type="number" min="1" step="1" value={correctionOffset} onChange={e => setCorrectionOffset(e.target.value)}/></label> : <label className="field">{correctionKind === 'reorder' ? '完整根块顺序（每行一个 ID，不得增删）' : '要合并的相邻正文 ID（按原顺序，每行一个）'}<textarea required value={correctionOrder} onChange={e => setCorrectionOrder(e.target.value)}/></label>}<div className="field"><label htmlFor="correct-reason">原件证据与机械修正理由</label><textarea id="correct-reason" required value={correctionReason} onChange={e => setCorrectionReason(e.target.value)}/></div><ActionFeedback {...action}/><button className="btn primary" disabled={!!sourceDraft || action.pending || !correctionReason.trim() || !draft.segments.find(s => s.block_id === correctionBlock)?.locators?.length}>创建来源修正</button>{sourceDraft && <div className="notice"><p>新来源草稿：{sourceDraft.id}</p><button type="button" className="btn primary" disabled={action.pending} onClick={() => void action.run(async () => { await api(`/sources/drafts/${resourceId(sourceDraft.id)}/confirm`, { method: 'POST', etag: etagFor(sourceDraft), body: { source_hash: sourceDraft.source_hash } }); setSourceDraft(undefined); setSourceDialog(false); doc.reload(); result.reload(); }, '已确认新来源修订，旧版保持不变。')}>保存新来源修订</button></div>}</form></Modal>}</>;
}
