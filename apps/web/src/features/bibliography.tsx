import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback } from '../components';
import { resourceId } from '../domain';
import { useAction } from '../hooks';
import type { Document } from '../types';

const statuses: Record<string, string> = {
  pending: '正在查询文献信息', retrying: '查询暂时受限，稍后重试', succeeded: '文献信息已匹配',
  not_found: '暂未查到文献信息', no_doi: '未发现明确 DOI', ambiguous: '发现多个 DOI，尚未确认本篇标识',
  failed: '文献信息查询未完成', unverified: '返回信息与本篇内容不一致',
};
export function BibliographyLine({ doc }: { doc: Document }) {
  const data = doc.bibliography;
  if (!data) return doc.metadata_status && !['no_doi', 'not_found'].includes(doc.metadata_status)
    ? <p className="small muted">{statuses[doc.metadata_status] ?? '文献信息待查询'}</p> : null;
  const authors = data.authors.slice(0, 3).map(author => author.name).join('、') + (data.authors.length > 3 ? ' 等' : '');
  const text = [authors, data.year, data.container].filter(value => value != null && value !== '').join(' · ');
  return text ? <p className="bibliography-line">{text}</p> : null;
}
export function BibliographyDetails({ doc, refresh }: { doc: Document; refresh: () => void }) {
  const action = useAction();
  const [doi, setDoi] = useState('');
  const data = doc.bibliography;
  const retry = (identifier?: string) => void action.run(async () => {
    const result = await api<{job_id?: string}>(`/documents/${resourceId(doc.id)}/metadata/refresh`, {
      method: 'POST', etag: etagFor(doc), body: identifier ? { doi: identifier } : {},
    });
    refresh();
    return result;
  }, '文献信息查询已提交。');
  return <section className="bibliography-details" aria-label="文献信息"><h2>文献信息</h2>
    <BibliographyLine doc={doc}/><p className="field-note">{statuses[doc.metadata_status ?? ''] ?? '尚未查询文献信息'}</p>
    <dl className="kv"><dt>原文件名</dt><dd>{doc.original_filename || '历史记录未保存'}</dd>
      {data?.doi_url && <><dt>DOI</dt><dd><a href={data.doi_url} target="_blank" rel="noreferrer noopener">{data.doi}</a></dd></>}
      {data?.publisher && <><dt>出版者</dt><dd>{data.publisher}</dd></>}
      {data?.date && <><dt>发表日期</dt><dd>{data.date.parts.join('-')}（{data.date.precision === 'day' ? '日' : data.date.precision === 'month' ? '月' : '年'}）</dd></>}
      {data?.service && <><dt>信息来源</dt><dd>{data.service === 'doi' ? 'DOI Citation Formatter' : 'Crossref'}</dd></>}
    </dl>
    <button className="btn sm" disabled={action.pending} onClick={() => retry()}>刷新文献信息</button>
    <details><summary>手动补充 DOI（可选）</summary><p className="field-note">只向公开文献服务发送 DOI，不上传 PDF 或正文。</p>
      <form className="stack" onSubmit={e => { e.preventDefault(); retry(doi.trim()); }}><input className="input" aria-label="本篇 DOI" value={doi} onChange={e => setDoi(e.target.value)} placeholder="10.…" maxLength={2048}/>
        <button className="btn sm" disabled={action.pending || !doi.trim()}>按此 DOI 查询</button>
      </form></details><ActionFeedback {...action}/>
  </section>;
}
