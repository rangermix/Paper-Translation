import { useEffect, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, PdfLocator, Status } from '../components';
import { inlineText, resourceId } from '../domain';
import { useAction } from '../hooks';
import { languageName } from '../languages';
import type { Draft, Inline, Segment } from '../types';
import { PreparationView } from './translation-preparation';

function TargetFields({ nodes, atoms, change }: { nodes: Inline[]; atoms?: Record<string, string>; change: (nodes: Inline[]) => void }) {
  return <div className="target-fields">{nodes.map((node, index) => node.type === 'text'
    ? <textarea aria-label={`译文文本 ${index + 1}`} rows={Math.max(2, Math.min(8, Math.ceil(node.text.length / 65)))} key={index} value={node.text}
      onChange={e => change(nodes.map((n, i) => i === index ? { type: 'text', text: e.target.value } : n))}/>
    : <span className="protected-atom" key={index}>保护内容：{atoms?.[node.ref ?? node.id ?? node.ref_id ?? ''] ?? node.ref ?? node.id ?? node.ref_id}</span>)}</div>;
}

export function SegmentEditor({ segment, draft, refresh, selected, select, dirtyChanged, allowReviewedSelection,
  expanded, toggle, hidden, blocked, stale, navigate }: {
  segment: Segment; draft: Draft; refresh: () => void; selected: boolean; select: (checked: boolean) => void;
  dirtyChanged: (dirty: boolean) => void; allowReviewedSelection: boolean;
  expanded: boolean; toggle: () => void; hidden: boolean; blocked: boolean; stale: boolean;
  navigate: (blockId: string) => void;
}) {
  const initial: Inline[] = segment.target_inline.length ? segment.target_inline : [{ type: 'text', text: '' }];
  const [nodes, setNodes] = useState<Inline[]>(initial), [baseline, setBaseline] = useState<Inline[]>(initial);
  const [baseVersion, setBaseVersion] = useState(segment.version);
  const [reason, setReason] = useState(''), [showSource, setShowSource] = useState(false), [reviewReason, setReviewReason] = useState('');
  const action = useAction(), dirty = JSON.stringify(nodes) !== JSON.stringify(baseline);
  const editable = segment.translatable !== false;
  const contentId = `segment-content-${segment.block_id}`;
  useEffect(() => {
    if (segment.version !== baseVersion && !dirty) {
      const next: Inline[] = segment.target_inline.length ? segment.target_inline : [{ type: 'text', text: '' }];
      setNodes(next); setBaseline(next); setBaseVersion(segment.version);
    }
  }, [segment.version, segment.target_inline, baseVersion, dirty]);
  const change = (next: Inline[]) => { setNodes(next); dirtyChanged(JSON.stringify(next) !== JSON.stringify(baseline)); };
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
          : editable ? <Status value={segment.review_status}/> : <span className="pill">保留原文</span>}
        {dirty && <span className="unsaved">有未保存修改</span>}
      </div>
    </header>
    {!expanded && <p className="segment-preview">{segment.source_text.slice(0, 160)}{segment.source_text.length > 160 ? '…' : ''}</p>}
    <div className="segment-content" id={contentId} hidden={!expanded}>
      {blocked && <p className="field-note warn">{stale ? '上次检查有重要提示，可重新检查当前内容。' : '本段有重要提示，可按需对照原文或修改。'}已有内容仍可阅读、发布和导出。</p>}
      <div className="review-grid"><div>
        <p className="subhead">原文 · 只读</p><div className="source-block">{segment.source_text}</div>
        <button className="btn sm source-button" onClick={() => setShowSource(s => !s)}>{showSource ? '收起来源' : '对照原 PDF'}</button>
        {showSource && <><PdfLocator originalUrl={draft.original_url} documentId={draft.document_id} locators={segment.locators}/>
          {segment.raw_text && <details><summary>原始提取与机械清理</summary><pre>{segment.raw_text}</pre><pre>{JSON.stringify(segment.normalization_edits ?? segment.edits ?? [], null, 2)}</pre></details>}</>}
      </div><div>
        <p className="subhead">译文 · {languageName(draft.target_locale)}</p>
        {editable ? <><TargetFields nodes={nodes} atoms={segment.protected_atoms} change={change}/>
          <div className="field"><label htmlFor={`reason-${segment.block_id}`}>修改理由</label><input className="input" id={`reason-${segment.block_id}`} value={reason} placeholder="说明修正了什么" onChange={e => setReason(e.target.value)}/></div>
          <button className="btn" disabled={action.pending || !dirty || !reason.trim() || !inlineText(nodes).trim()} onClick={() => void action.run(async () => {
            const saved = await api<Draft>(`/drafts/${resourceId(draft.id)}/segments/${resourceId(segment.block_id)}`, { method: 'PATCH', etag: etagFor(draft), body: { target_inline: nodes, reason, base_segment_version: baseVersion } });
            const updated = saved.segments.find(s => s.block_id === segment.block_id)!;
            setBaseline(updated.target_inline); setNodes(updated.target_inline); setBaseVersion(updated.version); dirtyChanged(false); refresh();
          }, '新段落版本已保存；请重新运行质量检查。')}>保存译文</button>
          {!blocked && <details className="review-confirm"><summary>人工核对（可选）</summary>
            <p className="small muted">无需人工确认即可封存和发布。如需记录核对结果，可对照原件检查后在此标记。</p>
            <label className="field">核对说明<input className="input" value={reviewReason} onChange={e => setReviewReason(e.target.value)}/></label>
            <button className="btn" disabled={dirty || action.pending || !reviewReason.trim() || segment.review_status === 'human_reviewed'} onClick={() => void action.run(async () => {
              await api(`/drafts/${resourceId(draft.id)}/segments/${resourceId(segment.block_id)}/confirm-review`, { method: 'POST', etag: etagFor(draft), body: { source_hash: segment.source_hash, base_segment_version: segment.version, context_hash: segment.context_hash, glossary_revision: segment.glossary_revision ?? draft.glossary_revision ?? null, reason: reviewReason } }); refresh();
            }, '已记录当前源文与译文版本的人工确认。')}>确认本段已核对</button>
          </details>}
          {segment.review_status === 'human_reviewed' && <button className="btn sm" disabled={action.pending} onClick={() => void action.run(async () => {
            await api('/translation-memory', { method: 'POST', body: { draft_id: draft.id, block_id: segment.block_id, segment_version: segment.version, independent: false } });
          }, '已显式保存为个人翻译记忆，默认随来源删除。')}>另存到个人翻译记忆</button>}
        </> : <p className="muted">本段保留原文，无需编辑译文。</p>}
        <ActionFeedback {...action}/>
        {dirty && segment.version !== baseVersion && <p className="notice error-notice">服务端已有新版本，本地未保存文字仍在。请比较后手动合并，保存将使用原基准版本进行冲突检查。</p>}
      </div></div>
      {editable && <PreparationView draftId={draft.id} scope={{ kind: 'segment', id: segment.block_id }}
        revision={`${draft.generation}:${segment.version}:${segment.context_hash ?? ''}`} navigate={navigate}/>}
      {segment.history?.length ? <details><summary>段落修改历史</summary>{segment.history.map(h => <div key={h.version}><strong>版本 {h.version} · {h.reason}</strong><p>{inlineText(h.target_inline, segment.protected_atoms)}</p></div>)}</details> : null}
    </div>
  </article>;
}
