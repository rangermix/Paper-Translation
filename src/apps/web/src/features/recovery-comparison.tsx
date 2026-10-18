import { t } from '../i18n';
import { useState } from 'react';
import { ErrorNotice, Loading } from '../components';
import { resourceId } from '../domain';
import { useResource } from '../hooks';
import './recovery-comparison.css';

type Comparison = { available: boolean; page?: number; before?: string[]; after?: string[];
  before_count?: number; after_count?: number; next_offset?: number | null; original_url?: string };

export function RecoveryComparison({ jobId }: { jobId: string }) {
  const [offset, setOffset] = useState(0);
  const result = useResource<Comparison>(`/jobs/${resourceId(jobId)}/recovery?offset=${offset}&limit=20`);
  const p = result.data;
  return <section className="recovery-comparison" aria-label={t("恢复前后对照")}>
    <h4>{t("恢复前后对照")}</h4><ErrorNotice error={result.error} retry={result.reload}/>
    {result.loading && <Loading/>}
    {p && !p.available && <p className="muted">{t("此历史任务未保存可用的恢复前后内容。")}</p>}
    {p?.available && <>
      <p className="field-note">{t("第 {value1} 页", { value1: String((p.page) ?? '') })}</p>
      {p.original_url && <a className="btn sm" href={p.original_url} target="_blank" rel="noreferrer">{t("查看原文 PDF 页面")}</a>}
      <div className="recovery-columns">{(['before', 'after'] as const).map(side => <div key={side}>
        <h5>{t("{value1} · {value2} 段", { value1: String((side === 'before' ? t("恢复前") : t("恢复后")) ?? ''), value2: String((p[`${side}_count`]) ?? '') })}</h5>
        {p[side]?.length ? <ol start={offset + 1}>{p[side]?.map((text, i) => <li key={offset + i}><p>{text || t("（空白内容）")}</p></li>)}</ol>
          : <p className="muted">{offset ? t("此页无更多内容。") : t("无文字内容。")}</p>}
      </div>)}</div>
      {(offset > 0 || p.next_offset != null) && <nav className="job-log-pages" aria-label={t("恢复对照分页")}>
        <button className="btn sm" disabled={result.loading || offset === 0} onClick={() => setOffset(old => Math.max(0, old - 20))}>{t("上一页对照")}</button>
        <span className="small muted">{t("第 {value1} 页", { value1: offset / 20 + 1 })}</span>
        <button className="btn sm" disabled={result.loading || !!result.error || p.next_offset == null}
          onClick={() => { if (p.next_offset != null) setOffset(p.next_offset); }}>{t("下一页对照")}</button>
      </nav>}
    </>}
  </section>;
}
