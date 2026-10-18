import { t } from '../i18n';
import { useState } from 'react';
import { ErrorNotice, Loading, Status } from '../components';
import { resourceId } from '../domain';
import { useResource } from '../hooks';
import type { Job, Page } from '../types';
import { jobOperation } from './job-presentation';

export function JobChildren({ jobId, relationship = 'internal' }: { jobId: string; relationship?: 'internal' | 'related' }) {
  const [cursors, setCursors] = useState<string[]>([]);
  const params = new URLSearchParams({ parent_job_id: jobId, relationship, include_cleared: 'true', limit: '30' });
  const label = relationship === 'internal' ? t("处理步骤") : t("后续任务");
  const cursor = cursors.at(-1);
  if (cursor) params.set('cursor', cursor);
  const children = useResource<Page<Job>>(`/jobs?${params}`, 5000);
  if (!children.error && !cursors.length && !children.data?.items.length) return null;
  return <div className={relationship === 'internal' ? 'job-children' : 'job-related'}><h4>{label}</h4>
    <ErrorNotice error={children.error} retry={children.reload}/>
    {children.loading && <Loading/>}
    {children.data?.items.map(child => <p key={child.id}>
      <a href={`#/jobs/${resourceId(child.id)}`}>{jobOperation(child.operation ?? child.stage)}</a> <Status value={child.workflow?.status ?? child.status}/>
    </p>)}
    {(cursors.length > 0 || children.data?.next_cursor) && <nav className="job-log-pages" aria-label={t("{value0}分页", { value0: label })}>
      <button className="btn sm" disabled={children.loading || !cursors.length} onClick={() => setCursors(old => old.slice(0, -1))}>{t("上一页{value0}", { value0: label })}</button>
      <span className="small muted" aria-live="polite">{t("第 {value0} 页{value1}", { value0: cursors.length + 1, value1: label })}</span>
      <button className="btn sm" disabled={children.loading || !!children.error || !children.data?.next_cursor} onClick={() => {
        const next = children.data?.next_cursor;
        if (next) setCursors(old => [...old, next]);
      }}>{t("下一页{value0}", { value0: label })}</button>
    </nav>}
  </div>;
}
