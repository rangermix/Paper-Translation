import { useState } from 'react';
import { ErrorNotice, Loading, Status } from '../components';
import { resourceId } from '../domain';
import { useResource } from '../hooks';
import type { Job, Page } from '../types';
import { jobOperation } from './job-presentation';

export function JobChildren({ jobId, relationship = 'internal' }: { jobId: string; relationship?: 'internal' | 'related' }) {
  const [cursors, setCursors] = useState<string[]>([]);
  const params = new URLSearchParams({ parent_job_id: jobId, relationship, include_cleared: 'true', limit: '30' });
  const label = relationship === 'internal' ? '处理步骤' : '后续任务';
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
    {(cursors.length > 0 || children.data?.next_cursor) && <nav className="job-log-pages" aria-label={`${label}分页`}>
      <button className="btn sm" disabled={children.loading || !cursors.length} onClick={() => setCursors(old => old.slice(0, -1))}>上一页{label}</button>
      <span className="small muted" aria-live="polite">第 {cursors.length + 1} 页{label}</span>
      <button className="btn sm" disabled={children.loading || !!children.error || !children.data?.next_cursor} onClick={() => {
        const next = children.data?.next_cursor;
        if (next) setCursors(old => [...old, next]);
      }}>下一页{label}</button>
    </nav>}
  </div>;
}
