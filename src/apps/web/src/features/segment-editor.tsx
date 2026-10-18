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
    id={`segment-${segment.block_id}`} tabIndex={-1} hidden={hidden} aria-label={`段落 ${segment.block_id}`}>
    <header className="segment-header">
      <div className="stack">
        {editable && <label className="check"><input type="checkbox" aria-label={`选择段落 ${segment.block_id}`} checked={selected}
          disabled={segment.review_status === 'human_reviewed' && !allowReviewedSelection} onChange={e => select(e.target.checked)}/></label>}
        <button className="btn sm segment-toggle" aria-expanded={expanded} aria-controls={contentId}
          aria-label={`${expanded ? '折叠' : '展开'}段落 ${segment.block_id}`} onClick={toggle}>
          <span aria-hidden="true">{expanded ? '▾' : '▸'}</span> <code>{segment.block_id}</code>
        </button>
      </div>
      <div className="stack"><small>段落版本 {segment.version}</small>
        {blocked ? <span className="pill warn">{stale ? '曾有重要提示 · 待更新' : '有重要提示'}</span>
          : editable ? hasTranslation ? <Status value={segment.review_status}/> : <span className="pill">尚未翻译</span> : <span className="pill">保留原文</span>}
        {dirty && <span className="unsaved">有未保存修改</span>}
      </div>
    </header>
    {!expanded && <p className="segment-preview">{segment.source_text.slice(0, 160)}{segment.source_text.length > 160 ? '…' : ''}</p>}
    <div className="segment-content" id={contentId} hidden={!expanded}>

      <div className="review-grid"><div>
        <p className="subhead">原文 · 只读</p><div className="source-block">{segment.source_text}</div>
        <button className="btn sm source-button" onClick={() => setShowSource(s => !s)}>{showSource ? '收起来源' : '对照原文 PDF'}</button>
        {showSource && <><PdfLocator originalUrl={draft.original_url} documentId={draft.document_id} locators={segment.locators}/>
          {segment.raw_text && <details><summary>原始提取与机械清理</summary><pre>{segment.raw_text}</pre><pre>{JSON.stringify(segment.normalization_edits ?? segment.edits ?? [], null, 2)}</pre></details>}</>}
      </div><div>
        <p className="subhead">{!editable ? '保留原文' : hasTranslation ? `译文 · ${languageName(draft.target_locale)}` : dirty ? '译文草稿 · 未保存' : '尚未翻译'}</p>
        {editable ? <>{!hasTranslation && !dirty && <p className="muted">当前草稿还没有本段译文。左侧原文仅供参考。</p>}
          <ContinuousInlineEditor nodes={nodes} atoms={segment.protected_atoms} change={next => change({ nodes: next })} disabled={saving} label="译文段落" onCompositionChange={compositionChanged}/>
          {!hasTranslation && !dirty && <button className="btn sm" disabled={saving} onClick={() => change({ nodes: segment.source_inline?.length ? structuredClone(segment.source_inline) : [{ type: 'text', text: segment.source_text }] })}>以原文开始编辑</button>}
          <div className="field"><label htmlFor={`reason-${segment.block_id}`}>修改理由</label><input className="input" id={`reason-${segment.block_id}`} value={reason} disabled={saving} placeholder="说明修正了什么" onChange={e => change({ reason: e.target.value })}/></div>
          <button className="btn" disabled={saving || composing || action.pending || !dirty || !reason.trim() || !inlineText(nodes).trim()} onClick={() => void save()}>保存译文</button>
          {!blocked && <details className="review-confirm"><summary>人工核对（可选）</summary>

            <label className="field">核对说明<input className="input" value={reviewReason} onChange={e => setReviewReason(e.target.value)}/></label>
            <button className="btn" disabled={dirty || saving || action.pending || !hasTranslation || !reviewReason.trim() || segment.review_status === 'human_reviewed'} onClick={() => void action.run(async () => {
              await api(`/drafts/${resourceId(draft.id)}/segments/${resourceId(segment.block_id)}/confirm-review`, { method: 'POST', etag: etagFor(draft), body: { source_hash: segment.source_hash, base_segment_version: segment.version, context_hash: segment.context_hash, glossary_revision: segment.glossary_revision ?? draft.glossary_revision ?? null, reason: reviewReason } }); refresh();
            }, '已记录当前源文与译文版本的人工确认。')}>确认本段已核对</button>
          </details>}
          {segment.review_status === 'human_reviewed' && <button className="btn sm" disabled={action.pending} onClick={() => void action.run(async () => {
            await api('/translation-memory', { method: 'POST', body: { draft_id: draft.id, block_id: segment.block_id, segment_version: segment.version, independent: false } });
          }, '已显式保存为个人翻译记忆，默认随来源删除。')}>另存到个人翻译记忆</button>}
        </> : <p className="muted">保留原文</p>}
        <ActionFeedback {...action}/>
        {edit.error && <p className="notice error-notice" role="alert">{edit.error}</p>}
        {conflict && <div className="notice error-notice"><p>服务端已有新版本，本地文字和修改理由仍保留。请对照并合并；当前保存仍使用段落版本 {baseVersion}。</p><p><strong>服务端当前译文：</strong>{inlineText(segment.target_inline, segment.protected_atoms) || '尚未翻译'}</p><button className="btn" disabled={saving} onClick={rebase}>已对照新版本，保留我的文字继续编辑</button></div>}
      </div></div>
      {editable && <PreparationView draftId={draft.id} scope={{ kind: 'segment', id: segment.block_id }}
        revision={`${draft.generation}:${segment.version}:${segment.context_hash ?? ''}`} navigate={navigate}/>}
      {segment.history?.length ? <details><summary>段落修改历史</summary>{segment.history.map(h => <div key={h.version}><strong>版本 {h.version} · {h.reason}</strong><p>{inlineText(h.target_inline, segment.protected_atoms)}</p></div>)}</details> : null}
    </div>
  </article>;
}
