import { t } from '../i18n';
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
  return <><PageHead title={t("搜索文档")}/><form className="tools search-controls" onSubmit={event => { event.preventDefault(); update({ q: query.trim(), cursor: '' }); }}>
    <label className="searchbox"><input aria-label={t("搜索文档")} required maxLength={300} value={query} onChange={event => setQuery(event.target.value)} placeholder={t("搜索文档…")}/></label>
    <label>{t("查找")}<select aria-label={t("查找内容")} value={state.scope} onChange={event => update({ scope: event.target.value, cursor: '' })}><option value="title">{t("标题")}</option><option value="body">{t("已发布正文")}</option></select></label>
    {state.scope === 'body' && <><select aria-label={t("搜索范围")} value={state.side} onChange={event => update({ side: event.target.value, cursor: '' })}><option value="both">{t("原文和译文")}</option><option value="source">{t("仅原文")}</option><option value="target">{t("仅译文")}</option></select><LanguageSelect label={t("目标语言筛选")} value={state.locale} emptyLabel={t("全部语言")} onChange={locale => update({ locale, cursor: '' })}/></>}
    <button className="btn primary">{t("搜索")}</button></form>
    <p className="muted small">{state.scope === 'body' ? t("搜索当前已发布的正文。未发布草稿暂不参与检索；结果打开命中时的固定阅读版本。") : t("按文档标题查找，包括尚未发布译文的文档。")}</p>
    <ErrorNotice error={result.error} retry={result.reload}/><ActionFeedback {...action}/>{position && <PositionNotice position={position}/>}
    {result.loading && <Loading/>}{state.q && result.data && <p role="status">{state.scope === 'body' ? t("本页 {value0} 处匹配 · {value1} 篇文档", { value0: result.data.items.length, value1: groups.size }) : t("本页 {value0} 篇文档", { value0: result.data.items.length })}{result.data.next_cursor ? t(" · 还有下一页") : ''}</p>}
    {result.data?.items.length === 0 && <Empty title={state.scope === 'body' ? t("没有已发布正文匹配") : t("没有匹配的标题")}>{t("试试更短的词，或切换标题与正文范围。")}</Empty>}
    {state.scope === 'title' && titles.data?.items.map(doc => <article className="panel search-document" key={doc.id}><h2><a href={`#/documents/${resourceId(doc.id)}`}><Highlight text={doc.title} query={state.q}/></a></h2><p className="muted small">{doc.editions.filter(edition => edition.current_artifact_id).map(edition => languageName(edition.target_locale)).join(' · ') || t("尚无已发布译文")}</p><a className="btn" href={`#/documents/${resourceId(doc.id)}`}>{t("打开文档")}</a></article>)}
    {state.scope === 'body' && [...groups].map(([id, rows]) => <section className="panel search-document" key={id}><header><h2><a href={`#/documents/${resourceId(id)}`}>{rows[0].document_title ?? rows[0].title}</a></h2><span className="muted small">{t("本页 {value0} 处匹配", { value0: rows.length })}</span></header>{rows.map((hit, i) => <article className="search-match" key={`${hit.artifact_id}-${hit.block_id}-${i}`}><small className="muted">{t("{value0} · 段落 {value1}", { value0: languageName(hit.locale), value1: hit.block_id })}</small><p className="source-block"><Highlight text={excerpt(hit.source_text, state.q)} query={state.q}/></p><p className="target-snippet">{hit.target_text ? <Highlight text={excerpt(hit.target_text, state.q)} query={state.q}/> : <span className="muted">{t("此段暂无译文")}</span>}</p><a href={readerPath(hit)} target="_blank" rel="noreferrer" title={t("打开本次命中的固定版本")} onClick={event => {
        event.currentTarget.href = readerPath(hit, window.scrollY);
        void action.run(async () => { const saved = await api<ReadingPosition>(positionPath(hit.document_id, hit.locale, hit.artifact_id)); setPosition(saved); await api('/reading-position', { method: 'PUT', etag: etagFor(saved), body: { document_id: hit.document_id, locale: hit.locale, artifact_id: hit.artifact_id, block_id: hit.block_id, offset: 0 } }); });
      }}>{t("打开匹配段落")}</a></article>)}</section>)}
    {state.q && <div className="pagination">{state.cursor && <button className="btn" onClick={() => update({ cursor: '' })}>{t("返回第一页")}</button>}{result.data?.next_cursor && <button className="btn" onClick={() => update({ cursor: result.data!.next_cursor! })}>{t("下一页结果")}</button>}</div>}
  </>;
}
