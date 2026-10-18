import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, Empty, ErrorNotice, Loading, PageHead } from '../components';
import { resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import { languageName } from '../languages';
import type { Document, Draft, MemoryEntry, Page } from '../types';
import './knowledge.css';

function MemoryStart() {
  const documents = useResource<Page<Document>>('/documents?limit=6&lifecycle=all');
  const editable = documents.data?.items.flatMap(document => document.editions.filter(edition => edition.draft_id).map(edition => ({ document, draftId: edition.draft_id! })))[0];
  const draft = useResource<Draft>(editable ? `/drafts/${resourceId(editable.draftId)}` : null);
  const reviewed = draft.data?.segments.some(segment => segment.translatable !== false && segment.review_status === 'human_reviewed' && segment.target_inline.length);
  return <div className="empty memory-start"><h2>还没有保存的译文片段</h2>
    <p>保存你确认过的译文，供以后参考。</p>
    <p>翻译记忆收集你主动保存的原文与译文，方便以后查找相似表达。</p>
    <ol><li>打开一篇文档的译文，找到希望保留的段落。</li><li>保存译文，在“人工核对（可选）”中选择“确认本段已核对”，再选择“另存到个人翻译记忆”。</li></ol>
    <p className="small muted">例如：把已核对的专业定义另存为记忆，供其他论文参考。浏览和查找不会自动保存，也不会替你确认译文。</p>
    <ErrorNotice error={documents.error} retry={documents.reload}/>{documents.loading && <Loading/>}
    <div className="stack">{documents.data?.items.length === 0 ? <a className="btn primary" href="#/upload">上传第一篇 PDF</a>
      : editable ? <a className="btn primary" href={`#/drafts/${resourceId(editable.draftId)}`}>{reviewed ? '查看已核对译文' : '打开译文并核对'}</a>
        : documents.data?.items[0] ? <a className="btn primary" href={`#/documents/${resourceId(documents.data.items[0].id)}`}>打开文档，开始处理</a> : null}
      <a className="btn" href="#/library">去文档库选择文档</a></div>
    {editable && <p className="small muted">{editable.document.title}</p>}
  </div>;
}

export function Memories() {
  const result = useResource<Page<MemoryEntry>>('/translation-memory?limit=100');
  const action = useAction();
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<MemoryEntry[]>();
  const entries = matches ?? result.data?.items;
  return <><PageHead title="个人翻译记忆"/><ErrorNotice error={result.error} retry={result.reload}/><ActionFeedback {...action}/>
    {result.loading && <Loading/>}
    {result.data?.items.length === 0 ? <MemoryStart/> : result.data && <>
      <p className="muted">查找你已保存的原文与译文，作为后续翻译的参考。</p>
      <form className="tools" onSubmit={event => { event.preventDefault(); void action.run(async () => {
        const found = await api<Page<MemoryEntry>>(`/translation-memory?q=${encodeURIComponent(query)}&limit=100`); setMatches(found.items);
      }); }}><input className="input" aria-label="查找相似词句" placeholder="查找相似原文…" value={query} onChange={event => setQuery(event.target.value)}/><button className="btn" disabled={action.pending}>查找记忆</button>
        {matches && <button className="btn" type="button" onClick={() => { setMatches(undefined); setQuery(''); }}>查看全部记忆</button>}</form>
      {entries?.map(entry => <article className="panel memory-entry" key={entry.id}>
        <div className="source-block">{entry.source_text}</div><p>{entry.target_text}</p>{entry.difference && <p className="field-note warn">差异：{entry.difference}</p>}
        <p className="muted small">{entry.independent ? '独立个人条目' : '随来源文档删除'} · {languageName(entry.target_language)}</p>
        <div className="stack">{entry.document_id && <a className="btn sm" href={`#/documents/${resourceId(entry.document_id)}`}>查看来源文档</a>}
          {!entry.independent && <button className="btn sm" disabled={action.pending} onClick={() => void action.run(async () => {
            await api(`/translation-memory/${resourceId(entry.id)}`, { method: 'PATCH', etag: etagFor(entry), body: { independent: true } }); result.reload(); setMatches(undefined);
          }, '已另存为独立条目，来源删除后仍会保留。')}>独立保留此条目</button>}
          <button className="btn sm danger" disabled={action.pending} onClick={() => void action.run(async () => {
            await api(`/translation-memory/${resourceId(entry.id)}`, { method: 'DELETE', etag: etagFor(entry) }); result.reload(); setMatches(undefined);
          })}>删除记忆</button></div>
      </article>)}
      {entries?.length === 0 && <Empty title="没有匹配的记忆">试试更短的原文，或查看全部记忆。</Empty>}
    </>}
  </>;
}
