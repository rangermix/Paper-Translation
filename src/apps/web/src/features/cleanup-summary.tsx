import { Status } from '../components';
import type { Job } from '../types';
import { jobName } from './job-presentation';

const labels = { pending: '等待文件清理', running: '文件正在清理', completed: '可清理文件已完成清理', failed: '文件清理失败' };

export function CleanupSummary({ job, connection }: { job: Job; connection: string }) {
  return <section aria-label="文档删除与文件清理">
    <div className="stack between"><h2>文档删除与文件清理</h2><Status value={job.status}/></div>
    <p className="small muted">{jobName(job)}</p>
    <p className="muted small">{connection === 'live' ? '事件连接正常，定时快照校对' : '使用服务端快照轮询'} · 快照 generation {job.generation ?? '—'}</p>
    <p>在线内容已不可访问。</p>
    <p role="status"><strong>{job.cleanup ? labels[job.cleanup.files] ?? '文件清理状态暂不可用' : '等待服务端返回文件清理状态'}</strong></p>
    {job.cleanup?.files === 'failed' && <p className="field-note warn">在线内容继续保持不可访问。请检查实例运行记录，处理文件清理故障。</p>}

    <a className="btn" href="#/library">返回文档库</a>
  </section>;
}
