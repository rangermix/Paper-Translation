import { useState } from 'react';
import { Issues } from '../components';
import type { Issue } from '../types';

export function isImportant(issue: Issue) {
  return ['important', 'hard', 'error', 'blocking'].includes(issue.severity);
}

export function EditorQuality({ issues, navigate, resolve, resolveDisabled }: {
  issues: Issue[]; navigate: (id: string) => void;
  resolve?: (issue: Issue) => void; resolveDisabled: boolean;
}) {
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState('');
  const [category, setCategory] = useState('');
  const selected = issues.filter(issue => (!page || String(issue.page) === page) && (!category || issue.category === category));
  const blockers = selected.filter(isImportant), risks = selected.filter(i => !isImportant(i));
  return <section className="editor-quality" aria-label="质量问题">
    <div className="stack between"><h3>质量问题</h3>
      <label>问题筛选 <select value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="all">全部（{issues.length}）</option>
        <option value="blockers">重要提示（{blockers.length}）</option>
        <option value="risks">一般提示（{risks.length}）</option>
      </select></label>
      <label>页码 <select value={page} onChange={e => setPage(e.target.value)}><option value="">全部页</option>{[...new Set(issues.map(i => i.page).filter((p): p is number => p != null))].sort((a, b) => a - b).map(p => <option key={p} value={p}>第 {p} 页</option>)}</select></label>
      <label>类型 <select value={category} onChange={e => setCategory(e.target.value)}><option value="">全部类型</option>{[...new Set(issues.map(i => i.category).filter(Boolean))].map(c => <option key={c} value={c}>{{numeric: '数字', coverage: '内容覆盖', terminology: '术语', semantic: '语义'}[c!] ?? c}</option>)}</select></label>
    </div>
    {filter !== 'risks' && <section aria-label="重要提示" className="quality-group">
      <h4>重要提示 · {blockers.length}</h4>
      <p className="small muted">可按需对照原文；不影响阅读、发布或导出。</p>
      {blockers.length ? <Issues issues={blockers} onNavigate={navigate} onResolve={resolve} resolveDisabled={resolveDisabled}/> : <p className="muted">没有重要提示。</p>}
    </section>}
    {filter !== 'blockers' && <details className="quality-group quality-risks" key={filter} open={filter === 'risks'}>
      <summary>一般提示 · {risks.length}</summary>
      {risks.length ? <Issues issues={risks} onNavigate={navigate} onResolve={resolve} resolveDisabled={resolveDisabled}/>
        : <p className="muted">没有风险提示。</p>}
    </details>}
  </section>;
}
