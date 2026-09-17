import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Modal } from '../components';
import { localUrl, resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import type { Draft } from '../types';

export function DraftExport({ draft, close }: {draft: Draft; close: () => void}) {
  const [format, setFormat] = useState('single_html');
  const [includeSource, setIncludeSource] = useState(false);
  const [exportId, setExportId] = useState('');
  const action = useAction();
  const result = useResource<{status: string; download_url?: string; error?: {message?: string; code?: string}}>(exportId ? `/exports/${resourceId(exportId)}` : null, 2000);
  const missing = draft.segments.filter(s => s.translatable !== false && !s.target_inline.length).length;
  return <Modal title="导出当前内容" onClose={close}>
    <p className="notice"><strong>当前内容快照</strong><br/>导出保存当前版本 {draft.generation}，带明显草稿标记及缺失译文提示。当前可见缺译 {missing} 段；文件会保留内容提示和原文占位。</p>
    <form onSubmit={e => {e.preventDefault(); void action.run(async () => {
      const created = await api<{export_id: string}>(`/drafts/${resourceId(draft.id)}/exports`, {method: 'POST', etag: etagFor(draft), body: {format, include_source: includeSource, confirm_draft: true}});
      setExportId(created.export_id);
    }); }}>
      <label className="field">草稿导出格式<select value={format} onChange={e => setFormat(e.target.value)} disabled={!!exportId}><option value="single_html">单文件 HTML</option><option value="bundle">离线目录 ZIP</option></select></label>
      <label className="check"><input type="checkbox" checked={includeSource} onChange={e => setIncludeSource(e.target.checked)} disabled={!!exportId}/>包含原 PDF</label>
      <ActionFeedback {...action}/><ErrorNotice error={result.error} retry={result.reload}/>
      {result.data?.error && <p className="notice error-notice">{result.data.error.message ?? result.data.error.code}</p>}
      {['succeeded', 'ready', 'completed'].includes(result.data?.status ?? '') ? <a className="btn primary section-title" href={localUrl(result.data?.download_url, `/api/v1/exports/${resourceId(exportId)}/download`)}>下载文件</a> : <button className="btn primary section-title" disabled={action.pending || !!exportId}>{exportId ? '正在生成固定草稿快照…' : '生成导出文件'}</button>}
    </form>
  </Modal>;
}
