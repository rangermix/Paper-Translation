import { t } from '../i18n';
import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, PdfLocator, Status } from '../components';
import { inlineText, resourceId } from '../domain';
import { useAction } from '../hooks';
import { languageName } from '../languages';
import type { Draft, Segment } from '../types';
import { PreparationView } from './translation-preparation';
import { ContinuousInlineEditor } from './continuous-inline-editor';
import { editIsDirty, type SegmentEdit } from './editor-state';

export function SegmentEditor({ segment, draft, refresh, selected, select, edit, change, save, saving, composing, compositionChanged, rebase, allowReviewedSelection,
  expanded, toggle, hidden, blocked, stale, navigate }: {
  segment: Segment; draft: Draft; refresh: () => void; selected: boolean; select: (checked: boolean) => void;
  edit: SegmentEdit; change: (patch: Partial<Pick<SegmentEdit, 'nodes' | 'reason'>>) => void;
  save: () => Promise<boolean>; saving: boolean; composing: boolean; compositionChanged: (active: boolean) => void; rebase: () => void; allowReviewedSelection: boolean;
  expanded: boolean; toggle: () => void; hidden: boolean; blocked: boolean; stale: boolean;
  navigate: (blockId: string) => void;
}) {
  const { nodes, baseVersion, reason } = edit;
  const [showSource, setShowSource] = useState(false), [reviewReason, setReviewReason] = useState('');
  const action = useAction(), dirty = editIsDirty(edit);
  const editable = segment.translatable !== false;
  const contentId = `segment-content-${segment.block_id}`;
  const hasTranslation = segment.target_inline.length > 0;
  const conflict = dirty && (segment.version !== baseVersion || segment.source_hash !== edit.sourceHash || draft.source_revision_id !== edit.sourceRevision);
  return <article className={`segment ${expanded ? 'expanded' : 'collapsed'} ${selected ? 'selected-segment' : ''} ${blocked ? 'blocked-segment' : ''}`}
    id={`segment-${segment.block_id}`} tabIndex={-1} hidden={hidden} aria-label={t("段落 {value1}", { value1: segment.block_id })}>
    <header className="segment-header">
      <div className="stack">
        {editable && <label className="check"><input type="checkbox" aria-label={t("选择段落 {value1}", { value1: segment.block_id })} checked={selected}
          disabled={segment.review_status === 'human_reviewed' && !allowReviewedSelection} onChange={e => select(e.target.checked)}/></label>}
        <button className="btn sm segment-toggle" aria-expanded={expanded} aria-controls={contentId}
          aria-label={t("{value1}段落 {value2}", { value1: expanded ? t("折叠") : t("展开"), value2: segment.block_id })} onClick={toggle}>
          <span aria-hidden="true">{expanded ? '▾' : '▸'}</span> <code>{segment.block_id}</code>
        </button>
      </div>
      <div className="stack"><small>{t("段落版本 {value1}", { value1: String((segment.version) ?? '') })}</small>
        {blocked ? <span className="pill warn">{stale ? t("曾有重要提示 · 待更新") : t("有重要提示")}</span>
          : editable ? hasTranslation ? <Status value={segment.review_status}/> : <span className="pill">{t("尚未翻译")}</span> : <span className="pill">{t("保留原文")}</span>}
        {dirty && <span className="unsaved">{t("有未保存修改")}</span>}
      </div>
    </header>
    {!expanded && <p className="segment-preview">{segment.source_text.slice(0, 160)}{segment.source_text.length > 160 ? '…' : ''}</p>}
    <div className="segment-content" id={contentId} hidden={!expanded}>

      <div className="review-grid"><div>
        <p className="subhead">{t("原文 · 只读")}</p><div className="source-block">{segment.source_text}</div>
        <button className="btn sm source-button" onClick={() => setShowSource(s => !s)}>{showSource ? t("收起来源") : t("对照原文 PDF")}</button>
        {showSource && <><PdfLocator originalUrl={draft.original_url} documentId={draft.document_id} locators={segment.locators}/>
          {segment.raw_text && <details><summary>{t("原始提取与机械清理")}</summary><pre>{segment.raw_text}</pre><pre>{JSON.stringify(segment.normalization_edits ?? segment.edits ?? [], null, 2)}</pre></details>}</>}
      </div><div>
        <p className="subhead">{!editable ? t("保留原文") : hasTranslation ? t("译文 · {value1}", { value1: languageName(draft.target_locale) }) : dirty ? t("译文草稿 · 未保存") : t("尚未翻译")}</p>
        {editable ? <>{!hasTranslation && !dirty && <p className="muted">{t("当前草稿还没有本段译文。左侧原文仅供参考。")}</p>}
          <ContinuousInlineEditor nodes={nodes} atoms={segment.protected_atoms} change={next => change({ nodes: next })} disabled={saving} label={t("译文段落")} onCompositionChange={compositionChanged}/>
          {!hasTranslation && !dirty && <button className="btn sm" disabled={saving} onClick={() => change({ nodes: segment.source_inline?.length ? structuredClone(segment.source_inline) : [{ type: 'text', text: segment.source_text }] })}>{t("以原文开始编辑")}</button>}
          <div className="field"><label htmlFor={`reason-${segment.block_id}`}>{t("修改理由")}</label><input className="input" id={`reason-${segment.block_id}`} value={reason} disabled={saving} placeholder={t("说明修正了什么")} onChange={e => change({ reason: e.target.value })}/></div>
          <button className="btn" disabled={saving || composing || action.pending || !dirty || !reason.trim() || !inlineText(nodes).trim()} onClick={() => void save()}>{t("保存译文")}</button>
          {!blocked && <details className="review-confirm"><summary>{t("人工核对（可选）")}</summary>

            <label className="field">{t("核对说明")}<input className="input" value={reviewReason} onChange={e => setReviewReason(e.target.value)}/></label>
            <button className="btn" disabled={dirty || saving || action.pending || !hasTranslation || !reviewReason.trim() || segment.review_status === 'human_reviewed'} onClick={() => void action.run(async () => {
              await api(`/drafts/${resourceId(draft.id)}/segments/${resourceId(segment.block_id)}/confirm-review`, { method: 'POST', etag: etagFor(draft), body: { source_hash: segment.source_hash, base_segment_version: segment.version, context_hash: segment.context_hash, glossary_revision: segment.glossary_revision ?? draft.glossary_revision ?? null, reason: reviewReason } }); refresh();
            }, "已记录当前源文与译文版本的人工确认。")}>{t("确认本段已核对")}</button>
          </details>}
          {segment.review_status === 'human_reviewed' && <button className="btn sm" disabled={action.pending} onClick={() => void action.run(async () => {
            await api('/translation-memory', { method: 'POST', body: { draft_id: draft.id, block_id: segment.block_id, segment_version: segment.version, independent: false } });
          }, "已显式保存为个人翻译记忆，默认随来源删除。")}>{t("另存到个人翻译记忆")}</button>}
        </> : <p className="muted">{t("保留原文")}</p>}
        <ActionFeedback {...action}/>
        {edit.error && <p className="notice error-notice" role="alert">{t(edit.error)}</p>}
        {conflict && <div className="notice error-notice"><p>{t("服务端已有新版本，本地文字和修改理由仍保留。请对照并合并；当前保存仍使用段落版本 {value1}。", { value1: String((baseVersion) ?? '') })}</p><p><strong>{t("服务端当前译文：")}</strong>{inlineText(segment.target_inline, segment.protected_atoms) || t("尚未翻译")}</p><button className="btn" disabled={saving} onClick={rebase}>{t("已对照新版本，保留我的文字继续编辑")}</button></div>}
      </div></div>
      {editable && <PreparationView draftId={draft.id} scope={{ kind: 'segment', id: segment.block_id }}
        revision={`${draft.generation}:${segment.version}:${segment.context_hash ?? ''}`} navigate={navigate}/>}
      {segment.history?.length ? <details><summary>{t("段落修改历史")}</summary>{segment.history.map(h => <div key={h.version}><strong>{t("版本 {value1} · {value2}", { value1: String((h.version) ?? ''), value2: String((h.reason) ?? '') })}</strong><p>{inlineText(h.target_inline, segment.protected_atoms)}</p></div>)}</details> : null}
    </div>
  </article>;
}
