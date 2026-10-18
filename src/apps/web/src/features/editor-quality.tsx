import { t } from '../i18n';
import { useState } from 'react';
import { Issues } from '../components';
import { issueCategoryLabel } from './issue-groups';
import type { Issue } from '../types';

export function isImportant(issue: Issue) {
  return ['important', 'hard', 'error', 'blocking'].includes(issue.severity);
}

export function EditorQuality({ issues, navigate, resolve, resolveDisabled, checkState }: {
  issues: Issue[]; navigate: (id: string) => void;
  resolve?: (issue: Issue) => void; resolveDisabled: boolean; checkState?: string;
}) {
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState('');
  const [category, setCategory] = useState('');
  const selected = issues.filter(issue => (!page || String(issue.page) === page) && (!category || issue.category === category));
  const blockers = selected.filter(isImportant), risks = selected.filter(i => !isImportant(i));
  return <section className="editor-quality" aria-label={t("质量问题")}>
    <p className="small muted">{t("内容提示供对照，不阻止继续翻译、保存或发布。")}</p>
    <div className="stack between"><h3>{t("质量问题")}</h3>
      <label>{t("问题筛选 ")}<select value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="all">{t("全部（{value1}）", { value1: String((issues.length) ?? '') })}</option>
        <option value="blockers">{t("重要提示（{value1}）", { value1: String((blockers.length) ?? '') })}</option>
        <option value="risks">{t("一般提示（{value1}）", { value1: String((risks.length) ?? '') })}</option>
      </select></label>
      <label>{t("页码 ")}<select value={page} onChange={e => setPage(e.target.value)}><option value="">{t("全部页")}</option>{[...new Set(issues.map(i => i.page).filter((p): p is number => p != null))].sort((a, b) => a - b).map(p => <option key={p} value={p}>{t("第 {value1} 页", { value1: String((p) ?? '') })}</option>)}</select></label>
      <label>{t("类型 ")}<select value={category} onChange={e => setCategory(e.target.value)}><option value="">{t("全部类型")}</option>{[...new Set(issues.map(i => i.category).filter(Boolean))].map(c => <option key={c} value={c}>{issueCategoryLabel(c)}</option>)}</select></label>
    </div>
    {filter !== 'risks' && <section aria-label={t("重要提示")} className="quality-group">
      <h4>{t("重要提示 · {value1}", { value1: String((blockers.length) ?? '') })}</h4>

      {blockers.length ? <Issues issues={blockers} checkState={checkState} onNavigate={navigate} onResolve={resolve} resolveDisabled={resolveDisabled}/> : <p className="muted">{t("没有重要提示。")}</p>}
    </section>}
    {filter !== 'blockers' && <details className="quality-group quality-risks" key={filter} open={filter === 'risks'}>
      <summary>{t("一般提示 · {value1}", { value1: String((risks.length) ?? '') })}</summary>
      {risks.length ? <Issues issues={risks} checkState={checkState} onNavigate={navigate} onResolve={resolve} resolveDisabled={resolveDisabled}/>
        : <p className="muted">{t("没有风险提示。")}</p>}
    </details>}
  </section>;
}
