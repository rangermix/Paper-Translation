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
  return <section className="recovery-comparison" aria-label="恢复前后对照">
    <h4>恢复前后对照</h4><ErrorNotice error={result.error} retry={result.reload}/>
    {result.loading && <Loading/>}
    {p && !p.available && <p className="muted">此历史任务未保存可用的恢复前后内容。</p>}
    {p?.available && <>
      <p className="field-note">第 {p.page} 页 · 以下为此任务执行时保存的内容。左右段落数量可能不同，序号不表示一一对应。</p>
      {p.original_url && <a className="btn sm" href={p.original_url} target="_blank" rel="noreferrer">查看原 PDF 页面</a>}
      <div className="recovery-columns">{(['before', 'after'] as const).map(side => <div key={side}>
        <h5>{side === 'before' ? '恢复前' : '恢复后'} · {p[`${side}_count`]} 段</h5>
        {p[side]?.length ? <ol start={offset + 1}>{p[side]?.map((text, i) => <li key={offset + i}><p>{text || '（空白内容）'}</p></li>)}</ol>
          : <p className="muted">{offset ? '此页无更多内容。' : '无文字内容。'}</p>}
      </div>)}</div>
      {(offset > 0 || p.next_offset != null) && <nav className="job-log-pages" aria-label="恢复对照分页">
        <button className="btn sm" disabled={result.loading || offset === 0} onClick={() => setOffset(old => Math.max(0, old - 20))}>上一页对照</button>
        <span className="small muted">第 {offset / 20 + 1} 页</span>
        <button className="btn sm" disabled={result.loading || !!result.error || p.next_offset == null}
          onClick={() => { if (p.next_offset != null) setOffset(p.next_offset); }}>下一页对照</button>
      </nav>}
    </>}
  </section>;
}
