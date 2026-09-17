import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, Modal, PdfLocator } from '../components';
import { useAction } from '../hooks';
import { resourceId } from '../domain';
import type { Draft, Issue } from '../types';

export function QualityResolution({ draft, issue, close, refresh }: {draft: Draft; issue: Issue; close: () => void; refresh: () => void}) {
  const [blockId, setBlockId] = useState(issue.block_id ?? draft.segments[0]?.block_id ?? '');
  const [reason, setReason] = useState('');
  const [checked, setChecked] = useState(false);
  const action = useAction();
  const segment = draft.segments.find(s => s.block_id === blockId);
  return <Modal title="核对质量提示" onClose={close}>
    <p>{issue.message}</p><p className="field-note">只处理当前提示及其指纹；修改段落或来源后需要重新检查。此记录是可选操作，不影响阅读和发布。</p>
    <form onSubmit={e => { e.preventDefault(); void action.run(async () => {
      await api(`/drafts/${resourceId(draft.id)}/issues/${resourceId(issue.fingerprint!)}/resolve`, { method: 'POST', etag: etagFor(draft), body: {reason, evidence: {page: segment!.locators![0].page, bbox: segment!.locators![0].bbox, quote: segment!.source_text}} });
      refresh(); close();
    }); }}>
      <label className="field">来源段落<select value={blockId} onChange={e => {setBlockId(e.target.value); setChecked(false);}}>{draft.segments.map(s => <option key={s.block_id}>{s.block_id}</option>)}</select></label>
      <PdfLocator documentId={draft.document_id} locators={segment?.locators}/><div className="source-block">{segment?.source_text}</div>
      <label className="field">核对结果与原件证据<textarea required value={reason} onChange={e => setReason(e.target.value)}/></label>
      <label className="check"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/>已对照原件确认这项提示不构成内容遗漏或错误。</label>
      <ActionFeedback {...action}/><button className="btn primary section-title" disabled={action.pending || !checked || !reason.trim() || !segment?.locators?.length}>记录该提示的核对证据</button>
    </form>
  </Modal>;
}
