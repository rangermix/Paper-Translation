import { t } from '../i18n';
import { languageName } from '../languages';
import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, Empty, ErrorNotice, Loading, PageHead } from '../components';
import { resourceId } from '../domain';
import { useAction, useResource } from '../hooks';
import type { Document, History, Page } from '../types';
import { ArtifactExport } from './artifact-export';
import { readingVersions, readingVersionStatus, versionTime } from './reading-versions';
import './library.css';

export function HistoryPage({ id }: { id: string }) {
  const result = useResource<History>(`/documents/${resourceId(id)}/history`);
  const doc = useResource<Document>(`/documents/${resourceId(id)}`);
  const templates = useResource<Page<{ id: string; version?: string; name?: string }>>('/templates');
  const action = useAction();
  const [locale, setLocale] = useState('');
  const [exportArtifact, setExportArtifact] = useState('');
  const [template, setTemplate] = useState('reader-v15');
  const [left, setLeft] = useState('');
  const [right, setRight] = useState('');
  const [axis, setAxis] = useState('source');
  const artifacts = readingVersions(result.data, doc.data).filter(artifact => !locale || artifact.locale === locale);
  const sources = result.data?.sources ?? result.data?.source_revisions ?? [];
  const translations = result.data?.translations ?? result.data?.translation_revisions ?? [];
  const revisions: { id: string; created_at?: string }[] = axis === 'source' ? sources : translations;
  const events = result.data?.publication_events ?? result.data?.publications?.map(event => ({ ...event, reason: event.operation }));
  const difference = useResource<{ changes: unknown[] }>(left && right ? `/documents/${resourceId(id)}/diff?before=${resourceId(left)}&after=${resourceId(right)}&axis=${axis}` : null);
  return <><PageHead title={t("版本历史")} actions={<a className="btn" href={`#/documents/${id}`}>{t("返回文档")}</a>}/>
    {doc.data && <p className="history-document-title">{doc.data.title}</p>}
    <ErrorNotice error={result.error} retry={result.reload}/><ErrorNotice error={doc.error} retry={doc.reload}/><ActionFeedback {...action}/>
    <div className="tools"><label>{t("语言 ")}<select value={locale} onChange={event => setLocale(event.target.value)}><option value="">{t("全部语言")}</option>
      {doc.data?.editions.map(edition => <option key={edition.id} value={edition.target_locale}>{languageName(edition.target_locale)}</option>)}
    </select></label></div>
    {result.loading && <Loading/>}{result.data && !result.loading && !result.error && !artifacts.length && <Empty title={t("尚无阅读版本")}>{t("已保存的草稿可从文档页继续编辑或导出。")}</Empty>}
    <section className="history-list" aria-label={t("阅读版本")}>
      {artifacts.map(artifact => {
        const edition = doc.data?.editions.find(item => item.id === artifact.edition_id) ?? doc.data?.editions.find(item => item.target_locale === artifact.locale);
        const current = edition?.current_artifact_id === artifact.id;
        const available = !artifact.state || artifact.state === 'verified';
        const label = readingVersionStatus(artifact, result.data, doc.data);
        return <article className={`panel artifact ${current ? 'artifact-current' : ''}`} key={artifact.id} data-artifact-id={artifact.id}>
          <div className="stack between"><h2>{languageName(artifact.locale)} · {versionTime(artifact.created_at)}</h2><span className={`pill ${current ? 'ready' : ''}`}>{label}</span></div>
          <div className="stack">
            {available && <a className={`btn ${current ? 'primary' : ''}`} href={`/artifacts/${resourceId(artifact.id)}/index.html`} target="_blank" rel="noreferrer">{current ? t("阅读当前版") : t("阅读这个版本")}</a>}
            <button className="btn" disabled={!available || !doc.data} onClick={() => setExportArtifact(artifact.id)}>{t("导出此版本")}</button>
            <button className="btn" disabled={action.pending || !edition || artifact.legacy || !available} onClick={() => void action.run(async () => {
              const draft = await api<{ id: string }>(`/editions/${resourceId(edition!.id)}/drafts`, { method: 'POST', etag: etagFor(edition), body: { translation_revision_id: artifact.translation_revision_id } });
              location.hash = `/drafts/${draft.id}`;
            })}>{t("以此版本继续编辑")}</button>
          </div>
          <p className="small muted">{t("继续编辑会创建新草稿，此阅读版本保持不变。")}</p>
          <details className="history-version-actions"><summary>{t("阅读样式与发布操作")}</summary>
            <label className="field">{t("阅读样式")}<select value={template} onChange={event => setTemplate(event.target.value)}>
              {templates.data?.items.length ? templates.data.items.map(item => <option value={item.id} key={item.id}>{t(item.name ?? "双语阅读样式")} · {item.id}</option>) : <option value="reader-v15">{t("多语言双语阅读")} · reader-v15</option>}
            </select></label>
            <ErrorNotice error={templates.error} retry={templates.reload}/>
            <div className="stack">
              <button className="btn" disabled={action.pending || !edition || artifact.legacy || !available} onClick={() => void action.run(async () => {
                const job = await api<{ job_id: string }>(`/artifacts/${resourceId(artifact.id)}/rebuild`, { method: 'POST', etag: etagFor(edition), body: { template_id: template, preview_only: true, expected_generation: edition?.generation } });
                location.hash = `/jobs/${job.job_id}`;
              })}>{t("用所选样式生成预览")}</button>
              <button className="btn" disabled={action.pending || current || !edition || !available} onClick={() => void action.run(async () => {
                await api(`/editions/${resourceId(edition!.id)}/rollback`, { method: 'POST', etag: etagFor(edition), body: { artifact_id: artifact.id, expected_generation: edition?.generation } });
                doc.reload(); result.reload();
              }, "已设为当前阅读版，其他历史版本保持不变。")}>{t("设为当前阅读版")}</button>
              {current && <button className="btn danger" disabled={action.pending || !edition} onClick={() => void action.run(async () => {
                await api(`/editions/${resourceId(edition!.id)}/unpublish`, { method: 'POST', etag: etagFor(edition), body: { expected_generation: edition?.generation } });
                doc.reload(); result.reload();
              }, "已撤下当前阅读版，历史固定版本保留。")}>{t("撤下当前版本")}</button>}
            </div><p className="small muted">{t("样式预览不会替换当前阅读版，也不会重新翻译。")}</p>
          </details>
          <details className="technical-details"><summary>{t("技术详情")}</summary><dl className="kv">
            <dt>{t("阅读版本 ID")}</dt><dd className="mono">{artifact.id}</dd><dt>{t("阅读样式 ID")}</dt><dd>{artifact.template_id}</dd>
            <dt>{t("来源修订")}</dt><dd className="mono">{artifact.source_revision_id || t("旧版未记录逐块来源")}</dd><dt>{t("译文修订")}</dt><dd className="mono">{artifact.translation_revision_id}</dd>
            <dt>{t("资源状态")}</dt><dd>{artifact.state ?? t("历史记录未提供")}</dd>{edition && <><dt>{t("并发校验版本")}</dt><dd>{edition.generation ?? t("未记录")}</dd></>}
          </dl></details>
        </article>;
      })}
    </section>
    {(sources.length > 0 || translations.length > 0) && <details className="panel section-title sealed-history"><summary>{t("已封存内容（原文 {value0} · 译文 {value1}）", { value0: sources.length, value1: translations.length })}</summary>
      <p className="small muted">{t("封存内容是不可修改的内容快照；阅读版本由这些快照生成，可使用不同阅读样式。")}</p>
      <dl className="kv"><dt>{t("原文快照")}</dt><dd>{t("{value0} 份", { value0: sources.length })}</dd><dt>{t("译文快照")}</dt><dd>{t("{value0} 份", { value0: translations.length })}</dd></dl>
      <details className="technical-details"><summary>{t("快照技术详情")}</summary><ul>{sources.map(item => <li key={item.id}>{t("原文：")}<code>{item.id}</code></li>)}{translations.map(item => <li key={item.id}>{t("译文：")}<code>{item.id}</code></li>)}</ul></details>
    </details>}
    {(sources.length > 1 || translations.length > 1) && <details className="panel section-title"><summary>{t("比较内容版本")}</summary>
      <label className="field">{t("比较内容 ")}<select value={axis} onChange={event => { setAxis(event.target.value); setLeft(''); setRight(''); }}><option value="source">{t("原文快照")}</option><option value="target">{t("译文快照")}</option></select></label>
      <div className="two-cols"><label className="field">{t("原版本")}<select value={left} onChange={event => setLeft(event.target.value)}><option value="">{t("选择版本")}</option>{revisions.map((revision, index) => <option value={revision.id} key={revision.id}>{t("{value0} · 快照 {value1}", { value0: versionTime(revision.created_at), value1: index + 1 })}</option>)}</select></label>
        <label className="field">{t("比较版本")}<select value={right} onChange={event => setRight(event.target.value)}><option value="">{t("选择版本")}</option>{revisions.map((revision, index) => <option value={revision.id} key={revision.id}>{t("{value0} · 快照 {value1}", { value0: versionTime(revision.created_at), value1: index + 1 })}</option>)}</select></label></div>
      <ErrorNotice error={difference.error} retry={difference.reload}/>{difference.data && <><h3>{axis === 'source' ? t("原文变化") : t("译文变化")}</h3><pre>{JSON.stringify(difference.data.changes, null, 2)}</pre></>}
    </details>}
    {events?.length ? <details className="panel section-title"><summary>{t("发布记录（{value0}）", { value0: events.length })}</summary>{[...events].reverse().map(event => <div className="history-row" key={event.id}>
      <div><strong>{({ publish: t("发布阅读版"), rollback: t("切换阅读版"), unpublish: t("撤下阅读版") } as Record<string, string>)[event.reason] ?? t("阅读版更新")}</strong>
        <details className="technical-details"><summary>{t("技术详情")}</summary><p className="mono">{event.artifact_id}<br/>{t("{value0} · 并发校验版本 {value1}", { value0: event.reason, value1: event.generation })}</p></details></div>
      <small>{versionTime(event.created_at)}</small></div>)}</details> : null}
    {exportArtifact && doc.data && <ArtifactExport document={doc.data} initialArtifactId={exportArtifact} close={() => setExportArtifact('')}/>}
  </>;
}
