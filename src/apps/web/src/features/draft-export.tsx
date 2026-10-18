import { t } from '../i18n';
import { errorMessage } from '../messages';
import { useRef, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Modal } from '../components';
import { localUrl, resourceId } from '../domain';
import { languageName } from '../languages';
import { useAction, useResource } from '../hooks';
import type { Document, Draft } from '../types';
import { ExportFormat } from './artifact-export';

export function DraftExport({ draft, close, title }: { draft: Draft; close: () => void; title?: string }) {
  const [snapshot] = useState(draft);
  const [format, setFormat] = useState('single_html');
  const [includeSource, setIncludeSource] = useState(false);
  const [exportId, setExportId] = useState('');
  const submitting = useRef(false);
  const document = useResource<Document>(title ? null : `/documents/${resourceId(snapshot.document_id)}`);
  const action = useAction();
  const result = useResource<{ status: string; download_url?: string; error?: { message?: string; code?: string } }>(exportId ? `/exports/${resourceId(exportId)}` : null, 2000);
  const missing = snapshot.segments.filter(segment => segment.translatable !== false && !segment.target_inline.length).length;
  const failed = ['failed', 'cancelled'].includes(result.data?.status ?? '');
  const locked = action.pending || Boolean(exportId);
  return <Modal title={t("导出当前草稿")} onClose={close}>
    <p><strong>{title ?? document.data?.title ?? t("当前文档")}</strong></p>
    <p className="notice">{t("{value0} · 草稿 · 缺译 {value1} 段", { value0: languageName(snapshot.target_locale), value1: missing })}</p>
    <p className="field-note">{t("导出当前已保存内容。缺失译文的段落将保留原文，并标注为未完成草稿。")}</p>
    <form onSubmit={event => { event.preventDefault(); if (locked || submitting.current) return; submitting.current = true; void action.run(async () => {
      try {
        const created = await api<{ export_id: string }>(`/drafts/${resourceId(snapshot.id)}/exports`, { method: 'POST', etag: etagFor(snapshot), body: { format, include_source: includeSource, confirm_draft: true } });
        setExportId(created.export_id);
      } finally { submitting.current = false; }
    }); }}>
      <ExportFormat format={format} setFormat={setFormat} includeSource={includeSource} setIncludeSource={setIncludeSource} disabled={locked}/>
      <details className="technical-details"><summary>{t("技术详情")}</summary><dl className="kv"><dt>{t("草稿 ID")}</dt><dd className="mono">{snapshot.id}</dd><dt>{t("并发校验版本")}</dt><dd>{snapshot.generation}</dd></dl></details>
      <ActionFeedback {...action}/><ErrorNotice error={result.error} retry={result.reload}/>
      {result.data?.error && <><p role="alert" className="error">{errorMessage(result.data.error.code ?? '', result.data.error.message)}</p>
        <details><summary>{t("错误技术详情")}</summary><code>{result.data.error.code}</code><p>{result.data.error.message}</p></details></>}
      {failed && <p role="alert">{t("下载文件未能生成，可重新选择导出选项。")}</p>}
      <div className="dialog-actions">{['succeeded', 'ready', 'completed'].includes(result.data?.status ?? '') ? <a className="btn primary" href={localUrl(result.data?.download_url, `/api/v1/exports/${resourceId(exportId)}/download`)}>{t("下载文件")}</a>
        : failed ? <button className="btn" type="button" onClick={() => { setExportId(''); action.clear(); }}>{t("重新选择导出选项")}</button>
          : <button className="btn primary" disabled={locked}>{exportId ? t("正在生成下载文件…") : t("生成下载文件")}</button>}</div>
    </form>
  </Modal>;
}

export function DraftExportLoader({ id, title, close }: { id: string; title: string; close: () => void }) {
  const result = useResource<Draft>(`/drafts/${resourceId(id)}`);
  if (!result.data) return <Modal title={t("导出当前草稿")} onClose={close}><p>{title}</p><ErrorNotice error={result.error} retry={result.reload}/>{result.loading && <p role="status">{t("正在读取草稿…")}</p>}</Modal>;
  return <DraftExport draft={result.data} title={title} close={close}/>;
}
