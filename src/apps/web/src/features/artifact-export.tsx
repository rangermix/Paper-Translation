import { useRef, useState } from 'react';
import { api } from '../api';
import { ActionFeedback, ErrorNotice, Loading, Modal } from '../components';
import { localUrl, resourceId } from '../domain';
import { languageName } from '../languages';
import { useAction, useResource } from '../hooks';
import type { Document, History } from '../types';
import { readingVersions, readingVersionStatus, versionTime } from './reading-versions';

export function ExportFormat({ format, setFormat, includeSource, setIncludeSource, disabled = false }: {
  format: string; setFormat: (value: string) => void; includeSource: boolean;
  setIncludeSource: (value: boolean) => void; disabled?: boolean;
}) {
  return <>
    <label className="field">导出格式<select aria-label="导出格式" value={format} onChange={event => setFormat(event.target.value)} disabled={disabled}>
      <option value="single_html">单文件 HTML</option><option value="bundle">资源包 ZIP</option>
    </select></label>
    <p className="field-note">{format === 'single_html' ? '保存为一个 HTML 文件，适合直接打开阅读或分享。' : '将网页和所需资源打包为 ZIP，解压后打开 index.html 离线阅读。'}</p>
    <label className="check"><input type="checkbox" checked={includeSource} onChange={event => setIncludeSource(event.target.checked)} disabled={disabled}/>同时打包原文 PDF</label>
    <p className="small muted">包含原文 PDF 后文件会更大。</p>
  </>;
}

export function ArtifactExport({ document, initialArtifactId, close }: { document: Document; initialArtifactId: string; close: () => void }) {
  // The selected immutable target belongs to this dialog, never to a later polled pointer.
  const [artifactId, setArtifactId] = useState(initialArtifactId);
  const [format, setFormat] = useState('single_html');
  const [includeSource, setIncludeSource] = useState(false);
  const [exportId, setExportId] = useState('');
  const [starting, setStarting] = useState(false);
  const submitting = useRef(false);
  const history = useResource<History>(`/documents/${resourceId(document.id)}/history`);
  const action = useAction();
  const exported = useResource<{ id: string; status: string; download_url?: string; error?: { message?: string; code?: string } }>(exportId ? `/exports/${resourceId(exportId)}` : null, 2000);
  const versions = readingVersions(history.data, document);
  const selected = versions.find(version => version.id === artifactId);
  const failed = ['failed', 'cancelled'].includes(exported.data?.status ?? '');
  const completed = ['completed', 'ready', 'succeeded'].includes(exported.data?.status ?? '');
  const locked = action.pending || starting || Boolean(exportId);
  return <Modal title="导出此版本" onClose={close}>
    <p className="export-document-title"><strong>{document.title}</strong></p>
    <ErrorNotice error={history.error} retry={history.reload}/>{history.loading && <Loading/>}
    {selected && <p>{languageName(selected.locale)} · {versionTime(selected.created_at)}<br/><span className="small muted">{readingVersionStatus(selected, history.data, document)}</span></p>}
    <form onSubmit={event => { event.preventDefault(); if (locked || !selected || submitting.current) return; submitting.current = true; setStarting(true); void action.run(async () => {
      try {
        const response = await api<{ export_id?: string; id?: string }>(`/artifacts/${resourceId(artifactId)}/exports`, { method: 'POST', body: { format, include_source: includeSource } });
        setExportId(response.export_id ?? response.id ?? '');
      } finally { submitting.current = false; setStarting(false); }
    }); }}>
      <label className="field">阅读版本<select aria-label="阅读版本" value={artifactId} disabled={locked || history.loading} onChange={event => setArtifactId(event.target.value)}>
        {!selected && <option value={artifactId}>{history.loading ? '正在读取版本信息…' : '所选版本信息暂不可用'}</option>}
        {versions.filter(version => !version.state || version.state === 'verified').map(version => <option key={version.id} value={version.id}>
          {languageName(version.locale)} · {versionTime(version.created_at)} · {readingVersionStatus(version, history.data, document)}
        </option>)}
      </select></label>
      <p className="small muted">导出所选固定版本；页面中的当前阅读版随后变化，不会改变本次选择。</p>
      <ExportFormat format={format} setFormat={setFormat} includeSource={includeSource} setIncludeSource={setIncludeSource} disabled={locked}/>
      <details className="technical-details"><summary>技术详情</summary><dl className="kv"><dt>阅读版本 ID</dt><dd className="mono">{artifactId}</dd>
        {selected && <><dt>阅读样式 ID</dt><dd>{selected.template_id}</dd><dt>译文修订</dt><dd className="mono">{selected.translation_revision_id}</dd></>}</dl></details>
      <ActionFeedback {...action}/><ErrorNotice error={exported.error} retry={exported.reload}/>
      {exported.data?.error && <p role="alert" className="error">{exported.data.error.message ?? exported.data.error.code}</p>}
      {failed && <p role="alert">下载文件未能生成。可重新生成，阅读版本保持不变。</p>}
      <div className="dialog-actions">{completed ? <a className="btn primary" href={localUrl(exported.data?.download_url, `/api/v1/exports/${resourceId(exportId)}/download`)}>下载文件</a>
        : failed ? <button className="btn" type="button" onClick={() => { setExportId(''); action.clear(); }}>重新选择导出选项</button>
          : <button className="btn primary" disabled={locked || !selected || Boolean(history.error)}>{exportId ? '正在生成下载文件…' : '生成下载文件'}</button>}</div>
    </form>
  </Modal>;
}
