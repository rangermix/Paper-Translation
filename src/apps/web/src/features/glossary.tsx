import { useState } from 'react';
import { api } from '../api';
import { ActionFeedback, ErrorNotice, Modal, PageHead } from '../components';
import { resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import { isLanguageTag, languageName } from '../languages';
import { requestNavigation, useNavigationGuard } from '../navigation-guard';
import type { Document, Glossary, GlossaryEntry, Page } from '../types';
import { DocumentPicker } from './document-picker';
import { LanguageSelect } from './language-select';
import { versionTime } from './reading-versions';
import './knowledge.css';

type Form = Pick<Glossary, 'source_language' | 'target_language' | 'scope' | 'document_id' | 'entries'>;
type Impact = { block_id: string; document_id?: string; source_text?: string; locked?: boolean }[];
const emptyEntry = (): GlossaryEntry => ({ source: '', target: '', mode: 'preferred', variants: [], note: '' });
const initialForm = (documentId: string): Form => ({ source_language: 'en', target_language: 'zh-Hans', scope: documentId ? 'document' : 'global', document_id: documentId || null, entries: [] });
const fromVersion = (version: Glossary): Form => ({ source_language: version.source_language, target_language: version.target_language,
  scope: version.scope, document_id: version.document_id ?? null, entries: structuredClone(version.entries) });
const ruleNames = { preferred: '推荐译法', must: '必须使用', forbidden: '禁止译法', retain: '原样保留' };

export function Glossaries() {
  const [contextId] = useState(() => new URLSearchParams(location.hash.split('?')[1]).get('document') ?? '');
  const result = useResource<Page<Glossary>>('/glossaries?limit=100');
  const action = useAction();
  const preview = useAction();
  const [base, setBase] = useState<Glossary>();
  const [form, setForm] = useState<Form>(() => initialForm(contextId));
  const [baseline, setBaseline] = useState(() => JSON.stringify(initialForm(contextId)));
  const [entry, setEntry] = useState<GlossaryEntry>(emptyEntry);
  const [variantInput, setVariantInput] = useState('');
  const [editingIndex, setEditingIndex] = useState<number>();
  const [impactDoc, setImpactDoc] = useState(contextId);
  const [impact, setImpact] = useState<Impact>();
  const previewScopeId = base?.scope === 'document' ? base.document_id ?? '' : impactDoc;
  const chosenDocument = useResource<Document>(form.scope === 'document' && form.document_id ? `/documents/${resourceId(form.document_id)}` : null);
  const previewDocument = useResource<Document>(previewScopeId ? `/documents/${resourceId(previewScopeId)}` : null);
  const contextDocument = useResource<Document>(contextId ? `/documents/${resourceId(contextId)}` : null);
  const pendingEntry = Boolean(entry.source || entry.target || entry.note || variantInput || entry.mode !== 'preferred' || editingIndex !== undefined);
  const dirty = JSON.stringify(form) !== baseline || pendingEntry;
  const guard = useNavigationGuard(dirty || action.pending);
  const availableDocument = form.scope !== 'document' || Boolean(form.document_id && chosenDocument.data?.id === form.document_id && !chosenDocument.error);
  const canSave = isLanguageTag(form.source_language) && isLanguageTag(form.target_language) && availableDocument && !pendingEntry && !action.pending && !preview.pending;
  const versions = result.data?.items ?? [];
  const displayedVersions = base && !versions.some(version => version.id === base.id) ? [base, ...versions] : versions;
  const change = (values: Partial<Form>) => setForm(previous => ({ ...previous, ...values }));
  const clearEntry = () => { setEntry(emptyEntry()); setVariantInput(''); setEditingIndex(undefined); };

  function adopt(version?: Glossary) {
    const next = version ? fromVersion(version) : initialForm(contextId);
    setBase(version); setForm(next); setBaseline(JSON.stringify(next)); clearEntry(); setImpact(undefined); action.clear();
  }
  async function save() {
    if (!canSave) return false;
    let saved = false;
    await action.run(async () => {
      const revision = await api<Glossary>('/glossaries/revisions', { method: 'POST', body: { ...form, document_id: form.scope === 'document' ? form.document_id : null } });
      const next = fromVersion(revision);
      setBase(revision); setForm(next); setBaseline(JSON.stringify(next)); setImpact(undefined); result.reload(); saved = true;
    }, '新版本已保存，已有词条版本和历史译文保持不变。');
    return saved;
  }

  return <><PageHead title="术语表"/>
    <p className="muted">为常见术语保存译法。每次保存都会建立独立新版本，已有翻译不会自动改写。</p>
    {contextId && <p className="field-note glossary-context">本篇文档：{contextDocument.data?.title ?? (contextDocument.error ? '文档已删除或暂不可用' : '正在读取文档…')}</p>}
    <ErrorNotice error={result.error} retry={result.reload}/><ActionFeedback {...action}/>
    <div className="split"><section className="panel glossary-editor"><h2>{base ? '编辑术语' : '新建术语表'}</h2>
      <fieldset disabled={action.pending || preview.pending}>
        <div className="field"><label htmlFor="glossary-base">编辑基准</label><select id="glossary-base" value={base?.id ?? ''} onChange={event => {
          const id = event.target.value;
          void requestNavigation().then(proceed => { if (proceed) adopt(displayedVersions.find(version => version.id === id)); });
        }}><option value="">新建术语表</option>{displayedVersions.map(version => <option key={version.id} value={version.id}>
          {languageName(version.source_language)} → {languageName(version.target_language)} · {version.scope === 'global' ? '全库' : '指定文档'} · {versionTime(version.created_at)} · {version.entries.length} 个词条
        </option>)}</select></div>
        <button className="btn sm" type="button" onClick={result.reload}>刷新版本列表</button>
        <p className="small muted">其他窗口保存的版本会独立保留。刷新列表不会合并或替换这里正在编辑的词条。</p>
        <p className="glossary-status" role="status">{dirty ? '有未保存修改' : base ? '正在查看已保存版本' : '尚未保存'}</p>
        <div className="two-cols"><div className="field"><label htmlFor="glossary-source">原文语言</label><LanguageSelect id="glossary-source" value={form.source_language} onChange={value => change({ source_language: value })}/></div>
          <div className="field"><label htmlFor="glossary-target">翻译语言</label><LanguageSelect id="glossary-target" value={form.target_language} onChange={value => change({ target_language: value })}/></div></div>
        <label className="field">作用范围<select aria-label="作用范围" value={form.scope} onChange={event => change({ scope: event.target.value as Form['scope'] })}><option value="global">个人全库</option><option value="document">指定文档</option></select></label>
        {form.scope === 'document' && <><DocumentPicker label="选择文档" value={form.document_id ?? ''} selectedDocument={chosenDocument.data} onChange={value => change({ document_id: value || null })}/>
          {chosenDocument.error && <p className="error" role="alert">所选文档已删除或暂不可用，请重新选择。词条修改仍保留。</p>}</>}
        <form className="glossary-entry-form" onSubmit={event => { event.preventDefault(); if (!entry.source.trim() || entry.mode !== 'retain' && !entry.target.trim()) return;
          const next = { ...entry, source: entry.source.trim(), target: entry.target.trim(), variants: variantInput.split(/[,，]/).map(value => value.trim()).filter(Boolean) };
          change({ entries: editingIndex === undefined ? [...form.entries, next] : form.entries.map((item, index) => index === editingIndex ? next : item) }); clearEntry();
        }}><h3>{editingIndex === undefined ? '添加词条' : '修改词条'}</h3>
          <div className="two-cols"><label className="field">原文术语<input aria-label="原文术语" className="input" required value={entry.source} onChange={event => setEntry(previous => ({ ...previous, source: event.target.value }))} maxLength={200}/></label>
            <label className="field">译法<input aria-label="译法" className="input" required={entry.mode !== 'retain'} value={entry.target} onChange={event => setEntry(previous => ({ ...previous, target: event.target.value }))} maxLength={200}/></label></div>
          <label className="field">规则<select aria-label="规则" value={entry.mode} onChange={event => setEntry(previous => ({ ...previous, mode: event.target.value as GlossaryEntry['mode'] }))}>{Object.entries(ruleNames).map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select></label>
          <label className="field">允许变体（逗号分隔）<input className="input" value={variantInput} onChange={event => setVariantInput(event.target.value)}/></label>
          <label className="field">注释<input className="input" value={entry.note ?? ''} onChange={event => setEntry(previous => ({ ...previous, note: event.target.value }))}/></label>
          <div className="stack"><button className="btn" type="submit">{editingIndex === undefined ? '添加词条' : '更新词条'}</button>{pendingEntry && <button className="btn" type="button" onClick={clearEntry}>取消词条编辑</button>}</div>
          <p className="small muted">添加或更新后，再点击“保存新版本”。</p>
        </form>
        {form.entries.length ? <div className="table-shell section-title"><table><thead><tr><th>原文术语</th><th>译法 / 规则</th><th>操作</th></tr></thead><tbody>{form.entries.map((item, index) => <tr key={index}>
          <td>{item.source}<small className="block muted">{item.variants.join(' · ')}</small></td><td>{item.target || '原样'}<small className="block muted">{ruleNames[item.mode]}</small></td>
          <td><div className="glossary-entry-actions"><button className="btn sm" disabled={pendingEntry} onClick={() => { setEntry({ ...item }); setVariantInput(item.variants.join(', ')); setEditingIndex(index); }}>修改</button>
            <button className="btn sm" disabled={pendingEntry} onClick={() => change({ entries: form.entries.filter((_, candidate) => index !== candidate) })}>移除此项</button></div></td>
        </tr>)}</tbody></table></div> : <p className="small muted">尚无词条，可先添加一个常用术语。</p>}
        <div className="glossary-save-actions">{pendingEntry && <p className="field-note">请先添加或更新正在编辑的词条，或取消词条编辑，再保存新版本。</p>}
          <button className="btn primary" disabled={!canSave} onClick={() => void save()}>保存新版本</button></div>
      </fieldset>
      {base && <details className="technical-details"><summary>版本技术详情</summary><dl className="kv"><dt>术语版本 ID</dt><dd className="mono">{base.id}</dd><dt>保存时间</dt><dd>{versionTime(base.created_at)}</dd>{base.document_id && <><dt>关联文档 ID</dt><dd className="mono">{base.document_id}</dd></>}</dl></details>}
    </section>
    <aside className="panel glossary-impact"><h2>影响预览</h2><p className="small muted">只查找已保存版本匹配的段落，不会保存词条或修改译文。</p>
      {dirty && base && <p className="field-note">预览使用当前编辑基准，不包含未保存修改。</p>}
      {!base && <p className="field-note">选择一个已保存版本，或先保存新版本，再预览影响。</p>}
      {base?.scope === 'document'
        ? <p className="field-note">此版本仅适用于关联文档：{previewDocument.data?.title ?? (previewDocument.error ? '文档已删除或暂不可用' : '正在读取文档…')}</p>
        : <DocumentPicker label="预览范围" value={impactDoc} selectedDocument={previewDocument.data} allowAll onChange={value => { setImpactDoc(value); setImpact(undefined); }} disabled={preview.pending || action.pending}/>}
      {previewDocument.error && <p role="alert" className="error">所选文档已删除或暂不可用，请选择其他文档或全库。</p>}
      <button className="btn" disabled={!base || preview.pending || action.pending || Boolean(previewScopeId && (previewDocument.data?.id !== previewScopeId || previewDocument.error))} onClick={() => void preview.run(async () => {
        const response = await api<{ items?: Impact; blocks?: Impact }>(`/glossaries/${resourceId(base!.id)}/impact`, { method: 'POST', body: { document_id: previewScopeId || null } });
        setImpact(response.items ?? response.blocks ?? []);
      })}>预览受影响段落</button><ActionFeedback {...preview}/>
      {impact && <><h3 className="section-title">{impact.length} 段匹配</h3>{!impact.length && <p className="small muted">所选范围内没有匹配段落。</p>}{impact.map((item, index) => <div className="impact-row" key={`${item.block_id}-${index}`}>
        {item.locked && <span className="pill warn">已人工锁定</span>}<p>{item.source_text}</p>{item.document_id && <a href={`#/documents/${resourceId(item.document_id)}`}>打开来源文档</a>}
        <details className="technical-details"><summary>段落标识</summary><code>{item.block_id}</code></details>
      </div>)}</>}
    </aside></div>
    {guard.requested && <Modal title="术语表有未保存修改" onClose={() => guard.resolve(false)} busy={action.pending}>
      <p>切换版本或离开前，请处理尚未保存的词条修改。</p><ActionFeedback {...action}/>
      {pendingEntry && <p className="field-note">请返回编辑，将当前词条添加到列表后再保存。</p>}
      <div className="stack"><button className="btn primary" disabled={action.pending} onClick={() => guard.resolve(false)}>继续编辑</button>
        <button className="btn" disabled={action.pending} onClick={() => { adopt(base); guard.resolve(true); }}>放弃修改</button>
        <button className="btn" disabled={!canSave} onClick={() => void save().then(saved => { if (saved) guard.resolve(true); })}>保存后继续</button></div>
    </Modal>}
  </>;
}
