import { t } from '../i18n';
import { useRef, useState } from 'react';
import { api, etagFor } from '../api';
import { inlineText, resourceId } from '../domain';
import type { Draft, Inline, Segment } from '../types';

export type SegmentEdit = {
  nodes: Inline[];
  baseline: Inline[];
  reason: string;
  baseVersion: number;
  sourceRevision: string;
  sourceHash: string;
  error?: string;
};
const inputNodes = (nodes: Inline[]): Inline[] => nodes.length ? nodes : [{ type: 'text', text: '' }];
export const editIsDirty = (edit: SegmentEdit) => JSON.stringify(edit.nodes) !== JSON.stringify(edit.baseline) || Boolean(edit.reason);
function initialEdit(segment: Segment, draft: Draft): SegmentEdit {
  const nodes = inputNodes(segment.target_inline);
  return { nodes, baseline: nodes, reason: '', baseVersion: segment.version, sourceRevision: draft.source_revision_id, sourceHash: segment.source_hash };
}

/** Local edits outlive filtering/collapsing; only an acknowledged PATCH clears them. */
export function useEditorState(draft: Draft | undefined, onSaved: (draft: Draft) => void) {
  const [edits, setEdits] = useState<Record<string, SegmentEdit>>({});
  const editsRef = useRef(edits);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const savingRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error>();
  const [notice, setNotice] = useState('');
  const update = (next: Record<string, SegmentEdit>) => { editsRef.current = next; setEdits(next); };
  const editFor = (segment: Segment) => {
    const existing = edits[segment.block_id];
    return existing && editIsDirty(existing) ? existing : initialEdit(segment, draft!);
  };
  const change = (segment: Segment, patch: Partial<Pick<SegmentEdit, 'nodes' | 'reason'>>) => {
    if (savingRef.current || !draftRef.current) return;
    const current = editsRef.current[segment.block_id];
    const edit = current && editIsDirty(current) ? current : initialEdit(segment, draftRef.current);
    update({ ...editsRef.current, [segment.block_id]: { ...edit, ...patch, error: undefined } });
    setNotice('');
  };
  const discard = () => { if (!savingRef.current) { update({}); setError(undefined); setNotice(''); } };
  const rebase = (segment: Segment) => {
    if (savingRef.current || !draftRef.current) return;
    const edit = editsRef.current[segment.block_id];
    if (!edit) return;
    update({ ...editsRef.current, [segment.block_id]: { ...initialEdit(segment, draftRef.current), nodes: edit.nodes, reason: edit.reason } });
    setError(undefined);
  };
  const save = async (onlyId?: string): Promise<boolean> => {
    if (savingRef.current || !draftRef.current) return false;
    const pending = Object.entries(editsRef.current).filter(([id, edit]) => editIsDirty(edit) && (!onlyId || id === onlyId));
    if (!pending.length) return true;
    setError(undefined); setNotice('');
    const invalid = pending.filter(([, edit]) => !edit.reason.trim() || !inlineText(edit.nodes).trim());
    if (invalid.length) {
      const next = { ...editsRef.current };
      for (const [id, edit] of invalid) next[id] = { ...edit, error: !edit.reason.trim() ? "请填写修改理由，再保存这一段。" : "请填写译文，再保存这一段。" };
      update(next);
      setError(new Error(t("尚有 {value1} 段未填写译文或修改理由，请继续编辑。", { value1: invalid.length })));
      return false;
    }
    savingRef.current = true; setSaving(true);
    let latest = draftRef.current;
    let completed = 0;
    try {
      for (const [blockId, edit] of pending) {
        try {
          if (latest.source_revision_id !== edit.sourceRevision || latest.segments.find(segment => segment.block_id === blockId)?.source_hash !== edit.sourceHash) throw new Error("原文版本已改变，本地输入仍保留。请先对照新原文，再处理这段修改。");
          const saved = await api<Draft>(`/drafts/${resourceId(latest.id)}/segments/${resourceId(blockId)}`, {
            method: 'PATCH', etag: etagFor(latest), body: { target_inline: edit.nodes, reason: edit.reason, base_segment_version: edit.baseVersion },
          });
          latest = saved; draftRef.current = saved; onSaved(saved);
          const next = { ...editsRef.current }; delete next[blockId]; update(next);
          completed += 1;
        } catch (cause) {
          const failure = cause instanceof Error ? cause : new Error(String(cause));
          update({ ...editsRef.current, [blockId]: { ...edit, error: failure.message } });
          setError(failure);
          setNotice(completed ? t("已保存 {value1} 段；其余 {value2} 段仍未保存。", { value1: completed, value2: pending.length - completed }) : "保存未完成，输入和修改理由仍保留。");
          // Refresh for comparison without replacing any local baseline or input.
          try { const current = await api<Draft>(`/drafts/${resourceId(latest.id)}`); draftRef.current = current; onSaved(current); } catch { /* Keep the known server snapshot when offline. */ }
          return false;
        }
      }
      setNotice(t("已保存 {value1} 段；请重新运行质量检查。", { value1: completed }));
      return true;
    } finally { savingRef.current = false; setSaving(false); }
  };
  const dirtyCount = Object.values(edits).filter(editIsDirty).length;
  return { editFor, change, rebase, discard, save, saving, error, notice, dirtyCount, hasDirty: dirtyCount > 0 };
}
