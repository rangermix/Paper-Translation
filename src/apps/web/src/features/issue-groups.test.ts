import { afterEach, describe, expect, it } from 'vitest';
import { setUiLocale } from '../i18n';
import type { Issue } from '../types';
import { groupIssues, issueCategoryLabel } from './issue-groups';

afterEach(() => setUiLocale('zh-Hans'));

describe('issue grouping', () => {
  it('localizes every source-check category and gives unknown categories a translated fallback', () => {
    setUiLocale('en');
    expect(issueCategoryLabel('table')).toBe('Table content');
    expect(issueCategoryLabel('typography')).toBe('Layout');
    expect(issueCategoryLabel('page_missing')).toBe('Content coverage');
    expect(issueCategoryLabel('future_category')).toBe('Other content notices');
    expect(issueCategoryLabel('toString')).toBe('Other content notices');
    expect(issueCategoryLabel('__proto__')).toBe('Other content notices');
    setUiLocale('zh-Hant');
    expect(issueCategoryLabel('table')).toBe('表格內容');
    expect(issueCategoryLabel('page_missing')).toBe('內容覆蓋');
  });
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
  it('places missing-page records last while retaining their original order', () => {
    const missing: Issue = { severity: 'info', message: '没有坐标' };
    const page: Issue = { severity: 'warning', page: 1, category: 'coverage' };
    const groups = groupIssues([missing, page, missing]);
    expect(groups).toHaveLength(2);
    expect(groups[0].page).toBe(1);
    expect(groups[1].page).toBeUndefined();
    expect(groups[1].issues).toEqual([missing, missing]);
  });
  it('sorts unordered pages numerically and categories consistently without reordering records', () => {
    const entries: Issue[] = [
      { id: 'a', severity: 'warning', page: 20, category: 'numeric', evidence: { order: 0 } },
      { id: 'b', severity: 'warning', category: 'numeric' },
      { id: 'c', severity: 'warning', page: 2, category: 'numeric' },
      { id: 'd', severity: 'warning', page: 2, category: 'coverage' },
      { id: 'e', severity: 'warning', page: 20, category: 'numeric', evidence: { order: 4 } },
      { id: 'f', severity: 'warning', page: 11, category: 'coverage' },
      { id: 'g', severity: 'warning', page: null, category: 'coverage' },
    ];
    const groups = groupIssues(entries);
    expect(groups.map(group => [group.page ?? null, group.category])).toEqual([
      [2, 'coverage'], [2, 'numeric'], [11, 'coverage'], [20, 'numeric'], [null, 'coverage'], [null, 'numeric'],
    ]);
    expect(groups[3].issues).toEqual([entries[0], entries[4]]);
    expect(groups[3].issues[0]).toBe(entries[0]);
    expect(groups[3].issues[1]).toBe(entries[4]);
    expect(entries.map(entry => entry.id)).toEqual(['a', 'b', 'c', 'd', 'e', 'f', 'g']);
  });
});
