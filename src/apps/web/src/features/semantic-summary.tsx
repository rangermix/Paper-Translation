import { t } from '../i18n';
import { resourceId, statusLabel } from '../domain';
import type { Draft } from '../types';

const labels = { not_requested: '尚未请求', incomplete: '未完成', stale: '最近所选范围已过期', completed: '最近所选范围已完成' };

export function SemanticSummary({ draft }: { draft: Draft }) {
  const latest = draft.semantic_reviews?.at(-1);
  return <section aria-label={t("检查译文含义范围")}>
    <p>{t("检查译文含义：{value1}。", { value1: String((draft.semantic_review_status ? t(labels[draft.semantic_review_status] ?? "状态暂不可用") : t("服务端未提供状态")) ?? '') })}</p>
    {latest && <>
      <p className="small">{t("最近请求：{value1} 段 · {value2} · {value3}", { value1: String((latest.block_ids.length) ?? ''), value2: String((latest.block_ids.join('、')) ?? ''), value3: String((latest.status === 'stale' ? t("所选译文或术语已改变") : statusLabel(latest.status)) ?? '') })}</p>
      <a href={`#/jobs/${resourceId(latest.job_id)}`}>{t("查看评审任务")}</a>
    </>}
  </section>;
}
