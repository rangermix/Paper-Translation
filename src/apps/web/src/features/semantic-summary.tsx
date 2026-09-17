import { resourceId, statusLabel } from '../domain';
import type { Draft } from '../types';

const labels = { not_requested: '尚未请求', incomplete: '未完成', stale: '最近所选范围已过期', completed: '最近所选范围已完成' };

export function SemanticSummary({ draft }: { draft: Draft }) {
  const latest = draft.semantic_reviews?.at(-1);
  return <section aria-label="辅助语义评审范围">
    <p>辅助语义评审：{draft.semantic_review_status ? labels[draft.semantic_review_status] ?? '状态暂不可用' : '服务端未提供状态'}。</p>
    {latest && <>
      <p className="small">最近请求：{latest.block_ids.length} 段 · {latest.block_ids.join('、')} · {latest.status === 'stale' ? '所选译文或术语已改变' : statusLabel(latest.status)}</p>
      <a href={`#/jobs/${resourceId(latest.job_id)}`}>查看评审任务</a>
    </>}
    <p className="small muted">仅适用于该次明确所选段落，不代表全文完成、语义准确率或人工确认。</p>
  </section>;
}
