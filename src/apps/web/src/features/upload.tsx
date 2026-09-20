import { useWorkflowPreferences } from './workflow-preferences';
import { ParserSelect } from './parser-select';
import { UploadMetadata } from './upload-metadata';
import { ProviderDestination } from './provider-destination';
import { CostControlNotice, costControlEnabled, budgetValid } from './cost-control';
import { useResource } from '../hooks';
import { LanguageSelect } from './language-select';
import { isLanguageTag } from '../languages';
import { useRef, useState } from 'react';
import { api, uploadPdf, validatePdfSelection, type UploadProgress } from '../api';
import { ErrorNotice, Icon, PageHead } from '../components';
import type { Capability, Document, Upload, Provider, ParserProfileRevision } from '../types';
type Row = { id: string; file: File; error?: string; progress?: UploadProgress; upload?: Upload; document?: Document; busy?: boolean };
export function UploadPage({ capability }: { capability?: Capability }) {
  const [rows, setRows] = useState<Row[]>([]); const [error, setError] = useState<Error>(); const [busy, setBusy] = useState(false); const input = useRef<HTMLInputElement>(null);
  const provider = useResource<Provider>('/settings/provider');
  const { preferences, ready, locale: language, setLocale: setLanguage, policy, setPolicy } = useWorkflowPreferences();
  const [parser, setParser] = useState<ParserProfileRevision>();
  const [translate, setTranslate] = useState(true);
  const [consentHash, setConsentHash] = useState('');
  const [budget, setBudget] = useState('');
  const profile = provider.data;
  const costControlled = costControlEnabled(profile);
  const consent = Boolean(profile?.profile_hash && consentHash === profile.profile_hash);
  const selectedParser = parser ?? preferences.data?.parser_profile_revision ?? 'paddleocr-vl-1.6-v1';
  const maxBytes = capability?.limits?.max_pdf_bytes ?? 50 * 1024 * 1024; const maxBatch = capability?.limits?.max_batch_files ?? 10;
  const update = (id: string, changes: Partial<Row>) => setRows(old => old.map(row => row.id === id ? { ...row, ...changes } : row));
  function select(files: File[]) { try { setRows(validatePdfSelection(files, maxBytes, maxBatch).map(x => ({ ...x, id: crypto.randomUUID() }))); setConsentHash(''); setError(undefined); } catch (reason) { setError(reason as Error); } }
  async function importRow(row: Row, upload: Upload) {
    if (!ready) return;
    update(row.id, { busy: true });
    try { const doc = await api<Document>('/imports', { method: 'POST', body: { source: { kind: 'pdf_upload', upload_id: upload.upload_id }, source_language: 'auto', target_language: language, parser_profile_revision: selectedParser, workflow: { translate, target_locale: language, publish_policy: policy, external_processing_confirmed: translate && consent, profile_hash: profile?.profile_hash, ...(costControlled && budgetValid(budget) ? { budget_micro: Math.round(Number(budget) * 1_000_000) } : {}) } } }); update(row.id, { document: doc, busy: false }); }
    catch (reason) { update(row.id, { busy: false, error: (reason as Error).message }); }
  }
  async function uploadAll() {
    if (!ready) return;
    setBusy(true);
    for (const row of rows.filter(r => !r.error && !r.upload && !r.document)) {
      try { update(row.id, { busy: true }); const upload = await uploadPdf(row.file, progress => update(row.id, { progress })); update(row.id, { upload, busy: false }); if (!upload.duplicate_documents?.length) await importRow(row, upload); }
      catch (reason) { update(row.id, { busy: false, error: (reason as Error).message }); }
    }
    setBusy(false);
  }
  return <><PageHead title="上传 PDF">保存原件后自动解析、恢复缺失内容并生成阅读结果。内容异常会集中提示。</PageHead><ErrorNotice error={error}/><div className="split"><section className="panel"><h2>选择原件</h2><input ref={input} id="pdf-files" className="visually-hidden" type="file" accept="application/pdf,.pdf" multiple disabled={busy} onChange={e => select(Array.from(e.target.files ?? []))}/><button className="dropzone" type="button" disabled={busy} onClick={() => input.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) select(Array.from(e.dataTransfer.files)); }}><Icon name="upload" big/><strong>拖放 PDF，或点击选择文件</strong><small>最多 {maxBatch} 份 · 每份 {(maxBytes / 1024 / 1024).toFixed(0)} MiB · 最多 {capability?.limits?.max_pages ?? 200} 页</small></button><p className="field-note">上传后自动从 Crossref 查询标题、作者和发表信息；查不到时保留文件名。</p><p className="field-note">查询仅发送 DOI，或提取的标题与作者；不发送 PDF 或正文。</p><div className="field"><label htmlFor="upload-language">默认目标语言</label><LanguageSelect id="upload-language" value={language} disabled={busy} onChange={setLanguage}/><small>原文语言自动识别；目标语言可自由选择。</small></div>{rows.map(row => <div className="file-result" key={row.id}><strong className="filename">{row.file.name}</strong><small className="muted">{(row.file.size / 1024).toFixed(1)} KiB</small>{row.error && <p role="alert" className="error">{row.error}</p>}{row.progress && !row.document && <><progress max={row.progress.totalBytes} value={row.progress.receivedBytes}/><small>{row.progress.receivedBytes.toLocaleString()} / {row.progress.totalBytes.toLocaleString()} 字节 · {row.error ? 'PDF 检查未通过' : row.upload ? 'PDF 检查通过' : row.progress.status === 'inspecting' ? '检查原件，尚未入库' : '接收中'}</small></>}{row.upload && <UploadMetadata upload={row.upload}/>}
{row.document && <p role="status"><a href={`#/documents/${row.document.id}`}>已入库，后台处理中 · 查看文档</a></p>}{row.upload?.duplicate_documents?.length && !row.document ? <div className="notice"><strong>发现相同 PDF 内容</strong><p>可继续使用已有文档，或建立独立目录条目；不会按文件名覆盖旧版本。</p>{row.upload.duplicate_documents.map(doc => <a className="btn sm" key={doc.id} href={`#/documents/${doc.id}`}>使用已有文档：{doc.title}</a>)}<button className="btn sm" disabled={!ready || row.busy || !isLanguageTag(language)} onClick={() => void importRow(row, row.upload!)}>建立独立文档</button></div> : null}</div>)}<div className="form-actions"><span className="muted small">有效性、加密状态和页数以服务端检查为准。</span><button className="btn primary" disabled={!ready || busy || !isLanguageTag(language) || !rows.some(r => !r.error && !r.upload && !r.document)} onClick={() => void uploadAll()}>{busy ? '正在接收与检查…' : '上传并开始处理'}</button></div></section><aside className="panel"><h2>处理方式</h2>
      <ErrorNotice error={preferences.error} retry={preferences.reload}/>
      <ParserSelect id="upload-parser" label="本地解析方案" value={selectedParser} onChange={setParser} disabled={busy}/>
      <p className="field-note">解析时限：{(preferences.data?.parser_timeout_seconds ?? 7200) / 60} 分钟。模型在本机运行。</p>
      <div className="field"><label htmlFor="upload-mode">生成内容</label><select id="upload-mode" value={translate ? 'translate' : 'source'} disabled={busy} onChange={e => setTranslate(e.target.value === 'translate')}>
        <option value="translate">解析并翻译</option><option value="source">仅解析阅读</option>
      </select></div>
      <div className="field"><label htmlFor="upload-publish">阅读结果</label><select id="upload-publish" value={policy} disabled={busy} onChange={e => setPolicy(e.target.value as typeof policy)}>
        <option value="auto_publish">完成后自动发布</option><option value="manual_approval">由我选择发布时间</option>
      </select></div>
      {translate && <><ErrorNotice error={provider.error} retry={provider.reload}/><ProviderDestination profile={profile}/>
        <p className="field-note">翻译模型：{profile?.model_id || '尚未配置'}</p><CostControlNotice enabled={costControlled}/>
        {costControlled && <div className="field"><label htmlFor="upload-budget">每份文档费用上限（USD）</label><input className="input" id="upload-budget" type="number" min="0.000001" step="0.000001" value={budget} disabled={busy} onChange={e => setBudget(e.target.value)}/></div>}
        {profile?.configured && <label className="check"><input type="checkbox" checked={consent} disabled={busy || !profile.profile_hash} onChange={e => setConsentHash(e.target.checked ? profile.profile_hash ?? '' : '')}/>
          同意将所选 PDF 的必要文本、上下文和术语发送到上述服务地址进行翻译，服务可能收费。
        </label>}
        {(!profile?.configured || !consent || costControlled && !budgetValid(budget)) && <p className="field-note">先完成本地解析和原文阅读；翻译将在配置、外发授权和所需预算齐备后开始。</p>}
      </>}
      <p className="field-note">系统会尝试恢复缺失页和文字。无法可靠识别的内容保留原页图像；检查提示不阻止阅读或导出。</p>
      <p className="muted small">接收完成后，后台处理不依赖此页面。</p></aside></div></>;
}
