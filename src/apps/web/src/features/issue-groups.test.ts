import { describe, expect, it } from 'vitest';
import type { Issue } from '../types';
import { groupIssues } from './issue-groups';

describe('issue grouping', () => {
  it('keeps every original record and evidence while grouping an eighty-item report', () => {
    const issues: Issue[] = Array.from({ length: 80 }, (_, index) => ({ id: `issue-${index}`, severity: 'warning', page: index % 4 + 1,
      category: Math.floor(index / 4) % 2 ? 'coverage' : 'numeric', message: '部分内容与原 PDF 不一致', diagnostic_count: 3,
      evidence: { original: index }, block_id: `b${index}` }));
    const groups = groupIssues(issues);
    expect(groups).toHaveLength(8);
    expect(groups.flatMap(group => group.issues)).toHaveLength(80);
    for (const issue of issues) expect(groups.flatMap(group => group.issues).find(row => row.id === issue.id)).toBe(issue);
    expect(groups.every(group => group.issues.length === 10)).toBe(true);
  });
  it('keeps missing-page records separate from a real first page and retains source order', () => {
    const missing: Issue = { severity: 'info', message: '没有坐标' };
    const page: Issue = { severity: 'warning', page: 1, category: 'coverage' };
    const groups = groupIssues([missing, page, missing]);
    expect(groups).toHaveLength(2);
    expect(groups[0].page).toBeUndefined();
    expect(groups[0].issues).toEqual([missing, missing]);
    expect(groups[1].page).toBe(1);
  });
});
