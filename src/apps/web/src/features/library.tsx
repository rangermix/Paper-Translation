import { BibliographyLine, BibliographyDetails } from './bibliography';
import { ParserSelect } from './parser-select';
import { useWorkflowPreferences } from './workflow-preferences';
import type { ParserProfileRevision } from '../types';
import { LanguageSelect } from './language-select';
import { languageName, isLanguageTag } from '../languages';
import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, Empty, ErrorNotice, Icon, Loading, Modal, PageHead, Status } from '../components';
import { resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import { EditionTranslate } from './edition-translate';
import { EditionReadingPosition } from './reading-position';
import { ArtifactExport } from './artifact-export';
import { DraftExportLoader } from './draft-export';
import type { Capability, Document, History, Page, Provider } from '../types';
import './library.css';

function processingLink(status?: string | null) {
  if (['succeeded', 'completed', 'completed_with_warnings', 'partially_completed', 'failed', 'cancelled'].includes(status ?? '')) return '最近处理记录';
  if (['pending', 'queued', 'running', 'paused', 'cancel_requested', 'waiting_config', 'waiting_configuration', 'waiting_budget', 'outcome_unknown', 'needs_review'].includes(status ?? '')) return '查看处理进度';
  return '查看处理记录';
}

function CurrentArtifactLinks({ doc }: { doc: Document }) {
  const editions = doc.editions.filter(edition => edition.current_artifact_id);
  return <>{editions.map(edition => <a className="btn primary" key={edition.id} href={`/read/${resourceId(doc.id)}/${resourceId(edition.target_locale)}`} target="_blank" rel="noreferrer" title={`阅读当前已发布版本 · ${languageName(edition.target_locale)}`}><Icon name="book"/>阅读{editions.length > 1 ? ` ${languageName(edition.target_locale)}` : ''}</a>)}</>;
}

export function Library() {
  const [query, setQuery] = useState('');
  const [submitted, setSubmitted] = useState('');
  const [starred, setStarred] = useState(false);
  const [lifecycle, setLifecycle] = useState('active');
  const [tag, setTag] = useState('');
  const [cursor, setCursor] = useState('');
  const params = new URLSearchParams({ limit: '30', lifecycle });
  if (submitted) params.set('q', submitted); if (starred) params.set('starred', 'true'); if (tag) params.set('tag', tag); if (cursor) params.set('cursor', cursor);
  const list = useResource<Page<Document>>(`/documents?${params}`, 5000);
  const action = useAction();
  return <><PageHead title="文档库" actions={<a className="btn primary" href="#/upload"><Icon name="upload"/>上传 PDF</a>}/>
    <form className="tools" onSubmit={event => { event.preventDefault(); setSubmitted(query); setCursor(''); }}>
      <label className="searchbox"><Icon name="search"/><input aria-label="搜索标题" placeholder="搜索标题…" value={query} onChange={event => setQuery(event.target.value)}/></label>
      <button className="btn" type="submit">搜索</button><button className={`btn ${starred ? 'selected' : ''}`} type="button" aria-pressed={starred} onClick={() => { setStarred(value => !value); setCursor(''); }}><Icon name="star"/>收藏</button>
      <select aria-label="文档范围" value={lifecycle} onChange={event => { setLifecycle(event.target.value); setCursor(''); }}><option value="active">未归档</option><option value="archived">已归档</option></select>
      <input className="tag-filter input" aria-label="筛选标签" placeholder="标签" value={tag} onChange={event => { setTag(event.target.value); setCursor(''); }}/>
    </form>
    <ActionFeedback {...action}/><ErrorNotice error={list.error} retry={list.reload}/>{list.loading && <Loading/>}
    {list.data && <><div className="filter-line"><span>本页 {list.data.items.length} 篇</span><a href={`#/search?q=${encodeURIComponent(submitted)}&scope=body`}>搜索文档正文 <Icon name="arrow"/></a></div>
      {list.data.items.length ? <div className="library-grid compact-library">{list.data.items.map(doc => <article className="doc-card" key={doc.id}>
        <div className="doc-top"><Status value={doc.editions.some(edition => edition.current_artifact_id) ? 'published' : doc.status ?? 'source_only'}/>
          <button className={`icon-btn ${doc.starred ? 'active' : ''}`} aria-label={`${doc.starred ? '取消收藏' : '收藏'} ${doc.title}`} disabled={action.pending} onClick={() => void action.run(async () => {
            const fresh = await api<Document>(`/documents/${resourceId(doc.id)}`);
            await api(`/documents/${resourceId(doc.id)}`, { method: 'PATCH', etag: etagFor(fresh), body: { starred: !fresh.starred } }); list.reload();
          })}><Icon name="star"/></button>
        </div>
        <div className="doc-main"><h2 className={doc.title.length > 65 ? 'has-full-title' : undefined}><a className="title-link" href={`#/documents/${doc.id}`}>{doc.title}</a></h2>
          {doc.title.length > 65 && <details className="doc-full-title"><summary>完整标题</summary><p>{doc.title}</p></details>}
          <BibliographyLine doc={doc}/>
          <div className="doc-meta"><span>{doc.editions.filter(edition => edition.current_artifact_id).map(edition => languageName(edition.target_locale)).join(' · ') || '原文 PDF 已保存'}</span><span>{doc.source_asset?.page_count ?? doc.page_count ?? '—'} 页</span>{doc.tags.map(value => <span key={value}>{value}</span>)}</div>
          {doc.current_job_id && <a className="current-job" href={`#/jobs/${doc.current_job_id}`}>{processingLink(doc.current_job_status)}</a>}
        </div>
        <div className="doc-footer"><CurrentArtifactLinks doc={doc}/><a className="btn" href={`/api/v1/documents/${resourceId(doc.id)}/original`} target="_blank" rel="noreferrer"><Icon name="pdf"/>原文 PDF</a><a className="btn ghost" href={`#/documents/${doc.id}`}>管理 <Icon name="arrow"/></a></div>
      </article>)}</div> : <Empty title={submitted || tag || starred ? '没有匹配的文档' : '从一份 PDF 开始'}><a className="btn primary" href="#/upload">上传 PDF</a></Empty>}
      <div className="pagination">{cursor && <button className="btn" onClick={() => setCursor('')}>返回第一页</button>}{list.data.next_cursor && <button className="btn" onClick={() => setCursor(list.data!.next_cursor!)}>下一页</button>}</div>
    </>}
  </>;
}

function LegacySourceNotice({ documentId, artifactIds }: { documentId: string; artifactIds: string[] }) {
  const history = useResource<Pick<History, 'artifacts'>>(artifactIds.length ? `/documents/${resourceId(documentId)}/history` : null, 5000);
  if (history.error) return <ErrorNotice error={history.error} retry={history.reload}/>;
  if (!history.data?.artifacts.some(artifact => artifact.legacy === true && artifactIds.includes(artifact.id))) return null;
  return <section className="field-note" aria-label="旧版来源定位说明"><strong>无精确定位</strong></section>;
}

export function DocumentDetail({ id, capability }: { id: string; capability?: Capability }) {
  const result = useResource<Document>(`/documents/${resourceId(id)}`, 5000);
  const provider = useResource<Provider>('/settings/provider');
  const action = useAction();
  const [translateEdition, setTranslateEdition] = useState('');
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteText, setDeleteText] = useState('');
  const [title, setTitle] = useState('');
  const [tags, setTags] = useState('');
  const [exportTarget, setExportTarget] = useState<{ kind: 'artifact' | 'draft'; id: string }>();
  const { preferences, ready, locale, setLocale, policy } = useWorkflowPreferences();
  const [parserChoice, setParserChoice] = useState<ParserProfileRevision>();
  const selectedParser = parserChoice ?? preferences.data?.parser_profile_revision ?? 'surya-ocr-2-v1';
  const doc = result.data;
  if (!doc) return <><ErrorNotice error={result.error} retry={result.reload}/>{result.loading && <Loading/>}</>;
  const asset = doc.source_asset;
  return <><PageHead title={doc.title} actions={<a className="btn" href="#/library">返回文档库</a>}/>
    <BibliographyLine doc={doc}/><ActionFeedback {...action}/><ErrorNotice error={result.error} retry={result.reload}/>
    <div className="split document-management">
      <section className="panel"><div className="stack between"><h2>文档信息</h2><Status value={doc.status ?? 'source_only'}/></div>
        <p className="small muted">PDF · {asset?.page_count ?? doc.page_count ?? '—'} 页 · {doc.lifecycle === 'archived' ? '已归档' : '未归档'}{doc.starred ? ' · 已收藏' : ''}</p>
        <p className="document-tags">{doc.tags.join(' · ') || '尚无标签'}</p>{doc.note && <p className="field-note">{doc.note}</p>}
        <div className="stack"><a className="btn" href={`/api/v1/documents/${resourceId(id)}/original`} target="_blank" rel="noreferrer"><Icon name="pdf"/>查看原文 PDF</a>
          <button className="btn" onClick={() => { setTitle(doc.title); setTags(doc.tags.join(', ')); setEditing(true); }}>编辑标题与标签</button>
          <a className="btn" href={`#/glossary?document=${encodeURIComponent(doc.id)}`}>管理本篇术语</a>
          <button className="btn" disabled={action.pending} onClick={() => void action.run(async () => { await api(`/documents/${resourceId(id)}`, { method: 'PATCH', etag: etagFor(doc), body: { starred: !doc.starred } }); result.reload(); })}>{doc.starred ? '取消收藏' : '收藏'}</button>
          {doc.import_id && <a className="btn" href={`#/preflight/${doc.import_id}`}>查看解析结果</a>}{doc.current_job_id && <a className="btn" href={`#/jobs/${doc.current_job_id}`}>{processingLink(doc.current_job_status)}</a>}
        </div>
        <LegacySourceNotice key={doc.id} documentId={doc.id} artifactIds={doc.editions.flatMap(edition => edition.current_artifact_id ? [edition.current_artifact_id] : [])}/>
        <details className="document-disclosure"><summary>文献信息与查询</summary><BibliographyDetails doc={doc} refresh={result.reload}/></details>
        <details className="technical-details document-disclosure"><summary>技术详情</summary><dl className="kv"><dt>文件大小</dt><dd>{((asset?.byte_size ?? doc.byte_size ?? 0) / 1024 / 1024).toFixed(2)} MiB</dd><dt>SHA-256</dt><dd className="mono">{asset?.sha256 ?? doc.sha256 ?? '尚未返回'}</dd><dt>文档 ID</dt><dd className="mono">{doc.id}</dd><dt>来源修订</dt><dd className="mono">{doc.source_revision_id ?? '尚无解析结果'}</dd></dl></details>
      </section>
      <section className="panel"><h2>阅读与编辑</h2>
        {doc.editions.length ? doc.editions.map(edition => <div className="edition" key={edition.id}>
          <div className="stack between"><strong>{languageName(edition.target_locale)}</strong><Status value={edition.current_artifact_id ? 'published' : edition.draft_id ? 'draft' : 'source_only'}/></div>
          <div className="stack">
            {edition.current_artifact_id && <><a className="btn primary" href={`/artifacts/${resourceId(edition.current_artifact_id)}/index.html`} target="_blank" rel="noreferrer">阅读当前版</a><button className="btn" onClick={() => setExportTarget({ kind: 'artifact', id: edition.current_artifact_id! })}>导出当前版</button></>}
            {!edition.draft_id && <button className="btn" onClick={() => setTranslateEdition(edition.id)}>确认此语言版翻译</button>}
            {edition.draft_id && <a className="btn" href={`#/drafts/${edition.draft_id}`}>编辑译文</a>}
            {!edition.current_artifact_id && edition.draft_id && <button className="btn" onClick={() => setExportTarget({ kind: 'draft', id: edition.draft_id! })}>导出当前草稿</button>}
          </div>
          {!edition.current_artifact_id && edition.draft_id && <p className="small muted">尚无阅读版。草稿可以导出，缺失译文将保留原文。</p>}
          {edition.current_artifact_id && <EditionReadingPosition documentId={doc.id} locale={edition.target_locale} artifactId={edition.current_artifact_id}/>}
        </div>) : <p className="muted">尚未建立语言版，可先解析 PDF。</p>}
        <a className="btn" href={`#/history/${doc.id}`}><Icon name="history"/>版本历史</a>
        {doc.source_revision_id && <details className="document-disclosure"><summary>添加翻译语言</summary><form className="field" onSubmit={event => { event.preventDefault(); void action.run(async () => {
          const created = await api<{ id: string }>(`/documents/${resourceId(id)}/editions`, { method: 'POST', etag: etagFor(doc), body: { target_locale: locale, source_revision_id: doc.source_revision_id, profile_hash: provider.data?.profile_hash } });
          result.reload(); setTranslateEdition(created.id);
        }, '已建立独立语言版，复用当前来源。'); }}><label htmlFor="new-locale">新增语言版</label><div className="stack"><LanguageSelect id="new-locale" value={locale} onChange={setLocale}/><button className="btn" disabled={!ready || action.pending || !provider.data?.profile_hash || !isLanguageTag(locale)}>新增</button></div></form></details>}
      </section>
    </div>
    <section className="panel section-title document-maintenance" aria-label="文档维护"><h2>文档维护</h2>
      <details open={!doc.source_revision_id}><summary>{doc.source_revision_id ? '重新解析原文' : '解析并生成阅读版'}</summary>
        {capability?.phase === 'M0' || capability?.features?.translation === false ? <p className="field-note">原文 PDF 已保存；当前部署未启用翻译。</p> : <>
          <ErrorNotice error={preferences.error} retry={preferences.reload}/><ParserSelect id="document-parser" label="本次 PDF 解析方案" value={selectedParser} onChange={setParserChoice} disabled={!preferences.data || action.pending}/>
          {doc.source_revision_id && <p className="small muted">重新处理原文 PDF，既有固定阅读版本保持不变。</p>}
          <button className="btn" disabled={action.pending || !preferences.data || Boolean(preferences.error)} onClick={() => void action.run(async () => {
            const job = await api<{ job_id: string }>(`/documents/${resourceId(id)}/parse`, { method: 'POST', etag: etagFor(doc), body: { source_asset_id: doc.source_asset_id || asset?.id, parser_profile_revision: selectedParser, workflow: { translate: false, target_locale: preferences.data?.locale || 'zh-Hans', publish_policy: policy } } });
            location.hash = `/jobs/${job.job_id}`;
          })}>解析并生成阅读版</button>
        </>}
      </details>
      <div className="document-retention"><div><h3>归档</h3><p className="small muted">从未归档列表移走，保留原文、译文和历史版本。</p></div><button className="btn" disabled={action.pending} onClick={() => void action.run(async () => {
        await api(`/documents/${resourceId(id)}`, { method: 'PATCH', etag: etagFor(doc), body: { archived: doc.lifecycle !== 'archived' } }); result.reload();
      })}>{doc.lifecycle === 'archived' ? '取消归档' : '归档文档'}</button></div>
      <details className="document-danger"><summary>永久删除文档</summary><p>删除后原文、译文、历史版本及导出将不可访问。只想收起文档时，请使用归档。</p><button className="btn danger" onClick={() => { setDeleteText(''); setDeleting(true); }}>永久删除</button></details>
    </section>
    {exportTarget?.kind === 'artifact' && <ArtifactExport document={doc} initialArtifactId={exportTarget.id} close={() => setExportTarget(undefined)}/>}
    {exportTarget?.kind === 'draft' && <DraftExportLoader id={exportTarget.id} title={doc.title} close={() => setExportTarget(undefined)}/>}
    {translateEdition && <EditionTranslate editionId={translateEdition} close={() => setTranslateEdition('')}/>}
    {editing && <Modal title="编辑目录信息" onClose={() => setEditing(false)}><form onSubmit={event => { event.preventDefault(); void action.run(async () => {
      await api(`/documents/${resourceId(id)}`, { method: 'PATCH', etag: etagFor(doc), body: { title, tags: tags.split(/[,，]/).map(value => value.trim()).filter(Boolean) } }); setEditing(false); result.reload();
    }, '目录信息已保存。'); }}><div className="field"><label htmlFor="doc-title">标题</label><input className="input" id="doc-title" required value={title} onChange={event => setTitle(event.target.value)}/></div><div className="field"><label htmlFor="doc-tags">标签（逗号分隔）</label><input className="input" id="doc-tags" value={tags} onChange={event => setTags(event.target.value)}/></div><ActionFeedback {...action}/><button className="btn primary" disabled={action.pending}>保存目录信息</button></form></Modal>}
    {deleting && <Modal title="永久删除文档" onClose={() => setDeleting(false)}><p><strong>{doc.title}</strong></p><p>原文、在线译文、版本及导出将立即不可访问，文件随后清理。归档可以保留所有版本。</p>
      <label className="field">输入「删除」确认<input className="input" value={deleteText} onChange={event => setDeleteText(event.target.value)}/></label><ActionFeedback {...action}/><div className="dialog-actions"><button className="btn" onClick={() => setDeleting(false)}>保留文档</button><button className="btn danger" disabled={deleteText !== '删除' || action.pending} onClick={() => void action.run(async () => {
        const deleted = await api<{ job_id: string }>(`/documents/${resourceId(id)}`, { method: 'DELETE', body: { confirm: true }, etag: etagFor(doc) }); location.hash = `/jobs/${resourceId(deleted.job_id)}`;
      })}>确认永久删除</button></div></Modal>}
  </>;
}
