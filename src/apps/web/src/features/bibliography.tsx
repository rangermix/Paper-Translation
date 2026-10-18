import { t, formatList } from '../i18n';
import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback } from '../components';
import { resourceId } from '../domain';
import { useAction } from '../hooks';
import type { Document } from '../types';

const statuses: Record<string, string> = {
  pending: '正在查询文献信息', retrying: '查询暂时受限，稍后重试', succeeded: '文献信息已匹配',
  not_found: '暂未查到文献信息', no_doi: '未发现明确 DOI 或可用标题', ambiguous: '发现多个可能的文献，尚未确认本篇',
  failed: '文献信息查询未完成', unverified: '返回信息与本篇内容不一致',
};
export function metadataStatusLabel(status?: string | null) {
  return t(statuses[status ?? ''] ?? "文献信息待查询");
}
export function BibliographyLine({ doc }: { doc: Pick<Document, 'bibliography' | 'metadata_status'> }) {
  const data = doc.bibliography;
  if (!data) return doc.metadata_status && !['no_doi', 'not_found'].includes(doc.metadata_status)
    ? <p className="small muted">{metadataStatusLabel(doc.metadata_status)}</p> : null;
  const authors = formatList(data.authors.slice(0, 3).map(author => author.name)) + (data.authors.length > 3 ? t(" 等") : '');
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
  }, "文献信息查询已提交。");
  return <section className="bibliography-details" aria-label={t("文献信息")}><h2>{t("文献信息")}</h2>
    <BibliographyLine doc={doc}/><p className="field-note">{t(statuses[doc.metadata_status ?? ''] ?? "尚未查询文献信息")}</p>
    <dl className="kv"><dt>{t("原文件名")}</dt><dd>{doc.original_filename || t("历史记录未保存")}</dd>
      {data?.doi_url && <><dt>DOI</dt><dd><a href={data.doi_url} target="_blank" rel="noreferrer noopener">{data.doi}</a></dd></>}
      {data?.publisher && <><dt>{t("出版者")}</dt><dd>{data.publisher}</dd></>}
      {data?.date && <><dt>{t("发表日期")}</dt><dd>{data.date.parts.join('-')}（{data.date.precision === 'day' ? t("日") : data.date.precision === 'month' ? t("月") : t("年")}）</dd></>}
      {data?.service && <><dt>{t("信息来源")}</dt><dd>{data.service === 'doi' ? 'DOI Citation Formatter' : 'Crossref'}</dd></>}
    </dl>
    <button className="btn sm" disabled={action.pending} onClick={() => retry()}>{t("刷新文献信息")}</button>
    <details><summary>{t("手动补充 DOI（可选）")}</summary>
      <form className="stack" onSubmit={e => { e.preventDefault(); retry(doi.trim()); }}><input className="input" aria-label={t("本篇 DOI")} value={doi} onChange={e => setDoi(e.target.value)} placeholder="10.…" maxLength={2048}/>
        <button className="btn sm" disabled={action.pending || !doi.trim()}>{t("按此 DOI 查询")}</button>
      </form></details><ActionFeedback {...action}/>
  </section>;
}
