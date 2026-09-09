import { NumberEvidence } from './number-evidence';
import { errorMessage } from './messages';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError } from './api';
import { localUrl, locatorStyle, resourceId, statusLabel } from './domain';
import type { Issue, Locator } from './types';
export function Icon({ name, big = false }: { name: string; big?: boolean }) {
  const paths: Record<string, ReactNode> = {
    book: <><path d="M3 4h6a4 4 0 0 1 3 2 4 4 0 0 1 3-2h6v15h-6a4 4 0 0 0-3 2 4 4 0 0 0-3-2H3z"/><path d="M12 6v15"/></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/></>,
    tasks: <><rect x="4" y="3" width="16" height="18" rx="2"/><path d="m7 8 1 1 2-2m2 1h5M7 13h10M7 17h7"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
    terms: <><path d="M4 4h13M10 2v3M6 7c1 5 6 8 10 9M15 6c-2 5-6 9-12 11m12 4 4-10 4 10m-6-3h4"/></>,
    settings: <><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="16" cy="17" r="3"/></>,
    star: <path d="m12 3 2.8 5.8 6.4.9-4.6 4.5 1.1 6.3L12 17.5l-5.7 3 1.1-6.3-4.6-4.5 6.4-.9z"/>,
    pdf: <><path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6"/></>,
    history: <><path d="M3 10a9 9 0 1 1 1 8M3 4v6h6M12 7v6l4 2"/></>,
    menu: <path d="M3 6h18M3 12h18M3 18h18"/>,
    close: <path d="m5 5 14 14M5 19 19 5"/>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
    memory: <><path d="M6 3h12v18l-6-4-6 4z"/></>,
  };
  return <svg aria-hidden="true" className={`icon ${big ? 'big' : ''}`} viewBox="0 0 24 24">{paths[name] ?? paths.book}</svg>;
}
export function PageHead({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) { return <header className="page-head"><div><h1>{title}</h1>{children && <p>{children}</p>}</div>{actions && <div className="stack">{actions}</div>}</header>; }
export function Status({ value }: { value?: string }) { return <span className={`pill ${['published', 'succeeded', 'completed', 'verified', 'human_reviewed'].includes(value ?? '') ? 'ready' : value === 'not_reviewed' ? '' : 'warn'}`}>{statusLabel(value)}</span>; }
export function ErrorNotice({ error, retry }: { error?: Error; retry?: () => void }) {
  if (!error) return null;
  return <div role="alert" className="notice error-notice"><strong>{error instanceof ApiError ? errorMessage(error.code, error.message) : error.message}</strong>{error instanceof ApiError && <details><summary>技术详情</summary><p className="mono">{error.code}{error.requestId ? ` · 请求 ${error.requestId}` : ''}</p><p>{error.message}</p></details>}{retry && <button className="btn sm" onClick={retry}>重新读取</button>}</div>;
}
export function ActionFeedback({ error, notice }: { error?: Error; notice: string }) { return <><ErrorNotice error={error}/>{notice && <p role="status" className="notice success-notice">{notice}</p>}</>; }
export function Loading() { return <p role="status" className="loading">正在读取服务端数据…</p>; }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <section className="empty"><Icon name="book" big/><h2>{title}</h2>{children}</section>; }
export function Issues({ issues, checkState, onNavigate, onResolve, resolveDisabled }: {
  issues?: Issue[]; checkState?: string; onNavigate?: (id: string) => void;
  onResolve?: (issue: Issue) => void; resolveDisabled?: boolean;
}) {
  const rows = issues ?? [];
  const state = checkState ?? (issues ? 'completed' : 'not_checked');
  if (!rows.length) return <p className="muted">{state === 'completed' ? '本次检查未发现问题。' : state === 'checking' ? '正在检查内容。' : state === 'failed' ? '检查未完成，已有内容仍可继续使用。' : state === 'stale' ? '内容已更新，检查结果待刷新。' : '尚未检查内容。'}</p>;
  return <ul className="issues">{rows.map((issue, i) => {
    const important = ['hard', 'error', 'blocking', 'important'].includes(issue.severity);
    const label = important ? '重要提示' : issue.severity === 'info' ? '排版提示' : '一般提示';
    const blockId = issue.block_id ?? issue.block_ids?.[0];
    const content = <><div className="stack"><strong>{label}</strong>{issue.page ? <span>第 {issue.page} 页</span> : null}{issue.diagnostic_count && issue.diagnostic_count > 1 ? <span>合并 {issue.diagnostic_count} 条诊断</span> : null}</div>
      <p>{issue.message ?? issue.explanation}</p>
      {issue.source_quote !== undefined && <div className="field-note"><strong>原文摘录</strong><p aria-label="原文摘录">{issue.source_quote}</p></div>}
      {issue.target_quote !== undefined && <div className="field-note"><strong>译文摘录</strong><p aria-label="译文摘录">{issue.target_quote}</p></div>}
      {(issue.code ?? issue.rule) === 'NUMBER_MISMATCH' && <NumberEvidence evidence={issue.evidence}/>}
      {onNavigate && <div className="stack issue-actions">{blockId ? <button className="btn sm" onClick={() => onNavigate(blockId)}>跳转段落 {blockId}</button> : <span className="small muted">文档级提示</span>}{onResolve && issue.fingerprint && <button className="btn sm" disabled={resolveDisabled} onClick={() => onResolve(issue)}>记录核对结果（可选）</button>}</div>}
      {(issue.evidence !== undefined || issue.evidence_refs?.length || issue.code || issue.rule) ? <details><summary>诊断详情</summary><pre>{JSON.stringify({ code: issue.code ?? issue.rule, evidence: issue.evidence, references: issue.evidence_refs }, null, 2)}</pre></details> : null}</>;
    return <li key={issue.id ?? i} className={`issue ${important ? 'important' : issue.severity}`}>{issue.severity === 'info' ? <details><summary>{issue.message ?? label}</summary>{content}</details> : content}</li>;
  })}</ul>;
}
export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); const el = ref.current; return () => el?.close(); }, []);
  return <dialog ref={ref} aria-label={title} onCancel={onClose}><div className="stack between"><h2>{title}</h2><button className="icon-btn" type="button" aria-label="关闭" onClick={onClose}><Icon name="close"/></button></div>{children}</dialog>;
}
export function PdfLocator({ documentId, originalUrl, locators = [] }: { documentId: string; originalUrl?: string; locators?: Locator[] }) {
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const original = localUrl(originalUrl, `/api/v1/documents/${resourceId(documentId)}/original`);
  if (!locators.length) return <div className="field-note"><strong>无精确定位</strong><p>这份来源没有可靠的逐块坐标。</p><a className="btn" href={original} target="_blank" rel="noreferrer">打开原 PDF</a></div>;
  return <div className="pdf-locators">{locators.map((loc, i) => {
    let bounds; try { bounds = locatorStyle(loc); } catch { return <p className="error" key={i}>来源坐标无效，无法高亮。请核对原 PDF。</p>; }
    const imageUrl = localUrl(loc.page_image_url, `/api/v1/documents/${resourceId(documentId)}/pages/${loc.page}.png`);
    const key = `${imageUrl}-${i}`;
    return <figure key={key} className="pdf-page"><div className="stack between"><figcaption>原 PDF · 第 {loc.page} 页</figcaption><a href={`${original.split('#')[0]}#page=${loc.page}`} target="_blank" rel="noreferrer">打开原页</a></div>{failed[key] ? <p className="field-note warn">页图读取失败。可通过上方原 PDF 链接继续核对。</p> : <div className="page-canvas" style={{ aspectRatio: `${loc.page_size[0]} / ${loc.page_size[1]}` }}><img src={imageUrl} alt={`原 PDF 第 ${loc.page} 页`} onError={() => setFailed(previous => ({ ...previous, [key]: true }))}/><span className="bbox" data-page={loc.page} style={bounds} aria-label={`来源高亮 ${loc.bbox.join(', ')}`}/></div>}<small className="muted">左上角 point 坐标：{loc.bbox.join(', ')} · 页面 {loc.page_size.join(' × ')} pt{loc.rotation ? ` · 原页旋转 ${loc.rotation}°` : ''}</small></figure>;
  })}</div>;
}
