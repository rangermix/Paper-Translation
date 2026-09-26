import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, Status } from '../components';
import { inlineText, resourceId } from '../domain';
import { useAction } from '../hooks';
import type { CandidateGroup, Draft } from '../types';
import { PreparationView } from './translation-preparation';

export function CandidateGroupView({ candidate, draft, refresh, hasDirty, navigate }: {
  candidate: CandidateGroup; draft: Draft; refresh: () => void; hasDirty: boolean;
  navigate: (blockId: string) => void;
}) {
  const action = useAction();
  const [unlock, setUnlock] = useState<Record<string, boolean>>({});
  const atoms = Object.fromEntries(Object.entries(draft.source?.protected_atoms ?? {}).map(([id, atom]) => [id, atom.value]));
  const sourceConflict = candidate.base.source_revision_id !== draft.source_revision_id || candidate.base.source_hash !== draft.source_hash || candidate.base.glossary_revision !== draft.glossary_revision;
  return <article className="candidate">
    <div className="stack between"><strong>候选任务 {candidate.id}</strong><Status value={candidate.status}/></div>
    {candidate.job_id && <a href={`#/jobs/${candidate.job_id}`}>查看生成任务</a>}
    <PreparationView draftId={draft.id} scope={{ kind: 'candidate', id: candidate.id }}
      revision={`${candidate.generation}:${candidate.status}:${draft.source_hash}`} navigate={navigate}/>
    {Object.entries(candidate.base.segments).map(([blockId, base]) => {
      const segment = draft.segments.find(s => s.block_id === blockId);
      const target = candidate.results[blockId];
      const conflict = sourceConflict || !segment || segment.version !== base.version || segment.source_hash !== base.source_hash || segment.context_hash !== base.context_hash;
      const locked = segment?.review_status === 'human_reviewed';
      return <section className="candidate-block" key={blockId}>
        <h3>{blockId}</h3>
        <div className="review-grid"><div><p className="subhead">当前译文 · 版本 {segment?.version}</p><p>{inlineText(segment?.target_inline, segment?.protected_atoms ?? atoms)}</p></div><div><p className="subhead">候选译文 · 基准版本 {base.version}</p><p>{target ? inlineText(target, atoms) : '尚未返回候选'}</p></div></div>
        {conflict && <p className="notice error-notice">候选基准已变化。两份内容都已保留，请在译文编辑区手动合并；此候选不能直接覆盖当前内容。</p>}
        {locked && !conflict && <label className="check"><input type="checkbox" checked={!!unlock[blockId]} onChange={e => setUnlock(old => ({ ...old, [blockId]: e.target.checked }))}/>我已比较本段，明确解除人工锁定并接受此候选；此段需要重新核对。</label>}
        <button className="btn" disabled={hasDirty || action.pending || conflict || !target || candidate.status !== 'ready' || locked && !unlock[blockId]} onClick={() => void action.run(async () => {
          await api(`/candidates/${resourceId(candidate.id)}/accept`, { method: 'POST', etag: etagFor(candidate), body: { block_ids: [blockId], allow_reviewed: !!unlock[blockId], glossary_revision: candidate.base.requested_glossary_revision } });
          refresh();
        }, '已接受这一段候选为新草稿版本，尚未发布。')}>接受 {blockId} 候选</button>
      </section>;
    })}
    <ActionFeedback {...action}/>
  </article>;
}
