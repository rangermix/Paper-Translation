import { useEffect, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, Empty, ErrorNotice, Loading, PageHead } from '../components';
import { resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import { languageName } from '../languages';
import type { Document, Page, SearchHit } from '../types';
import { LanguageSelect } from './language-select';
import { PositionNotice, positionPath, type ReadingPosition } from './reading-position';
import './search.css';

type SearchState = { q: string; scope: string; side: string; locale: string; cursor: string; y: number };
function readSearch(): SearchState {
  const params = new URLSearchParams(location.hash.split('?')[1] ?? '');
  return { q: (params.get('q') ?? '').slice(0, 300), scope: params.get('scope') === 'title' ? 'title' : 'body',
    side: ['source', 'target'].includes(params.get('side') ?? '') ? params.get('side')! : 'both',
    locale: params.get('locale') ?? '', cursor: params.get('cursor') ?? '', y: Math.max(0, Number(params.get('y')) || 0) };
}
export function searchHash(state: SearchState) {
  const params = new URLSearchParams({ q: state.q, scope: state.scope });
  if (state.scope === 'body') { params.set('side', state.side); if (state.locale) params.set('locale', state.locale); }
  if (state.cursor) params.set('cursor', state.cursor);
  if (state.y) params.set('y', String(Math.round(state.y)));
  return `#/search?${params}`;
}

function excerpt(text: string, query: string) {
  const found = text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
  const start = Math.max(0, found - 70), end = Math.min(text.length, start + Math.max(230, query.length + 100));
  return `${start ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`;
}
export function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const parts = []; let start = 0;
  const lower = text.toLocaleLowerCase(), term = query.toLocaleLowerCase();
  while (start < text.length) {
    const index = lower.indexOf(term, start);
    if (index < 0) { parts.push(text.slice(start)); break; }
    parts.push(text.slice(start, index), <mark key={index}>{text.slice(index, index + query.length)}</mark>);
    start = index + query.length;
  }
  return <>{parts}</>;
}

export function Search() {
  const [state, setState] = useState(readSearch), [query, setQuery] = useState(() => readSearch().q);
  const action = useAction(); const [position, setPosition] = useState<ReadingPosition>();
  useEffect(() => { const read = () => { const next = readSearch(); setState(next); setQuery(next.q); setPosition(undefined); };
    window.addEventListener('hashchange', read); return () => window.removeEventListener('hashchange', read); }, []);
  const update = (patch: Partial<SearchState>) => {
    const next = { ...state, ...patch, y: 0 }; setState(next); setPosition(undefined); location.hash = searchHash(next);
  };
  const params = new URLSearchParams({ q: state.q, limit: '30' });
  if (state.cursor) params.set('cursor', state.cursor);
  if (state.scope === 'body') { params.set('side', state.side); if (state.locale) params.set('locale', state.locale); }
  const hits = useResource<Page<SearchHit>>(state.q && state.scope === 'body' ? `/search?${params}` : null);
  const titles = useResource<Page<Document>>(state.q && state.scope === 'title' ? `/documents?${params}` : null);
  const result = state.scope === 'body' ? hits : titles;
  useEffect(() => { if (result.data && state.y) { const frame = requestAnimationFrame(() => window.scrollTo(0, state.y)); return () => cancelAnimationFrame(frame); } }, [result.data, state.y]);
  const groups = new Map<string, SearchHit[]>();
  for (const hit of hits.data?.items ?? []) { const group = groups.get(hit.document_id) ?? []; group.push(hit); groups.set(hit.document_id, group); }
  const readerPath = (hit: SearchHit, y = state.y) => `/artifacts/${resourceId(hit.artifact_id)}/index.html?return_to=${encodeURIComponent(searchHash({ ...state, y }))}#b-${encodeURIComponent(hit.block_id)}`;
  return <><PageHead title="搜索文档"/><form className="tools search-controls" onSubmit={event => { event.preventDefault(); update({ q: query.trim(), cursor: '' }); }}>
    <label className="searchbox"><input aria-label="搜索文档" required maxLength={300} value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索文档…"/></label>
    <label>查找<select aria-label="查找内容" value={state.scope} onChange={event => update({ scope: event.target.value, cursor: '' })}><option value="title">标题</option><option value="body">已发布正文</option></select></label>
    {state.scope === 'body' && <><select aria-label="搜索范围" value={state.side} onChange={event => update({ side: event.target.value, cursor: '' })}><option value="both">原文和译文</option><option value="source">仅原文</option><option value="target">仅译文</option></select><LanguageSelect label="目标语言筛选" value={state.locale} emptyLabel="全部语言" onChange={locale => update({ locale, cursor: '' })}/></>}
    <button className="btn primary">搜索</button></form>
    <p className="muted small">{state.scope === 'body' ? '搜索当前已发布的正文。未发布草稿暂不参与检索；结果打开命中时的固定阅读版本。' : '按文档标题查找，包括尚未发布译文的文档。'}</p>
    <ErrorNotice error={result.error} retry={result.reload}/><ActionFeedback {...action}/>{position && <PositionNotice position={position}/>}
    {result.loading && <Loading/>}{state.q && result.data && <p role="status">{state.scope === 'body' ? `本页 ${result.data.items.length} 处匹配 · ${groups.size} 篇文档` : `本页 ${result.data.items.length} 篇文档`}{result.data.next_cursor ? ' · 还有下一页' : ''}</p>}
    {result.data?.items.length === 0 && <Empty title={state.scope === 'body' ? '没有已发布正文匹配' : '没有匹配的标题'}>试试更短的词，或切换标题与正文范围。</Empty>}
    {state.scope === 'title' && titles.data?.items.map(doc => <article className="panel search-document" key={doc.id}><h2><a href={`#/documents/${resourceId(doc.id)}`}><Highlight text={doc.title} query={state.q}/></a></h2><p className="muted small">{doc.editions.filter(edition => edition.current_artifact_id).map(edition => languageName(edition.target_locale)).join(' · ') || '尚无已发布译文'}</p><a className="btn" href={`#/documents/${resourceId(doc.id)}`}>打开文档</a></article>)}
    {state.scope === 'body' && [...groups].map(([id, rows]) => <section className="panel search-document" key={id}><header><h2><a href={`#/documents/${resourceId(id)}`}>{rows[0].document_title ?? rows[0].title}</a></h2><span className="muted small">本页 {rows.length} 处匹配</span></header>{rows.map((hit, i) => <article className="search-match" key={`${hit.artifact_id}-${hit.block_id}-${i}`}><small className="muted">{languageName(hit.locale)} · 段落 {hit.block_id}</small><p className="source-block"><Highlight text={excerpt(hit.source_text, state.q)} query={state.q}/></p><p className="target-snippet">{hit.target_text ? <Highlight text={excerpt(hit.target_text, state.q)} query={state.q}/> : <span className="muted">此段暂无译文</span>}</p><a href={readerPath(hit)} target="_blank" rel="noreferrer" title="打开本次命中的固定版本" onClick={event => {
        event.currentTarget.href = readerPath(hit, window.scrollY);
        void action.run(async () => { const saved = await api<ReadingPosition>(positionPath(hit.document_id, hit.locale, hit.artifact_id)); setPosition(saved); await api('/reading-position', { method: 'PUT', etag: etagFor(saved), body: { document_id: hit.document_id, locale: hit.locale, artifact_id: hit.artifact_id, block_id: hit.block_id, offset: 0 } }); });
      }}>打开匹配段落</a></article>)}</section>)}
    {state.q && <div className="pagination">{state.cursor && <button className="btn" onClick={() => update({ cursor: '' })}>返回第一页</button>}{result.data?.next_cursor && <button className="btn" onClick={() => update({ cursor: result.data!.next_cursor! })}>下一页结果</button>}</div>}
  </>;
}
