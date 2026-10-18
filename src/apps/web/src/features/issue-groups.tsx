import type { ReactNode } from 'react';
import type { Issue } from '../types';
import './issue-groups.css';

const categoryNames: Record<string, string> = {
  numeric: '数字差异', coverage: '内容覆盖', terminology: '术语', semantic: '含义',
  structure: '内容结构', assets: '图表资源', layout: '排版', formula: '公式', general: '其他内容提示',
};

export function groupIssues(issues: Issue[]) {
  const groups = new Map<string, { page?: number | null; category: string; issues: Issue[] }>();
  for (const issue of issues) {
    const category = issue.category || 'general';
    const key = `${issue.page ?? 'unknown'}:${category}`;
    const group = groups.get(key) ?? { page: issue.page, category, issues: [] };
    group.issues.push(issue); groups.set(key, group);
  }
  return [...groups.values()].sort((left, right) => {
    const pageOrder = (left.page ?? Infinity) - (right.page ?? Infinity);
    if (pageOrder && !Number.isNaN(pageOrder)) return pageOrder;
    return left.category.localeCompare(right.category, 'en');
  });
}

/** Group presentation never deduplicates or drops an original diagnostic. */
export function IssueGroups({ issues, render }: { issues: Issue[]; render: (items: Issue[]) => ReactNode }) {
  const groups = groupIssues(issues);
  return <div className="issue-groups">
    <p className="small muted">共 {issues.length} 条提示，按页和类型展开查看；每条记录及其证据均保留。</p>
    {groups.map(group => <details className="issue-group" key={`${group.page ?? 'unknown'}:${group.category}`}>
      <summary>{group.page != null ? `第 ${group.page} 页` : '未提供页码'} · {categoryNames[group.category] ?? '其他内容提示'} · {group.issues.length} 条</summary>
      {render(group.issues)}
    </details>)}
  </div>;
}
