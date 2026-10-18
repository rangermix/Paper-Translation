import { t, getUiLocale } from '../i18n';
import { PreparationControls, preparationAllowed } from './translation-preparation';
import { useWorkflowPreferences } from './workflow-preferences';
import { ParserSelect } from './parser-select';
import { UploadMetadata } from './upload-metadata';
import { ProviderDestination } from './provider-destination';
import { costControlEnabled, budgetValid } from './cost-control';
import { useResource } from '../hooks';
import { LanguageSelect } from './language-select';
import { isLanguageTag } from '../languages';
import { useRef, useState } from 'react';
import { api, ApiError, uploadPdf, validatePdfSelection, type UploadProgress } from '../api';
import { ErrorNotice, Icon, PageHead } from '../components';
import type { Capability, Document, Upload, Provider, ParserProfileRevision, PreparationMode } from '../types';
import './upload.css';

type Row = { id: string; file: File; error?: string; retryImport?: boolean; progress?: UploadProgress; upload?: Upload; document?: Document; busy?: boolean };
export function UploadPage({ capability }: { capability?: Capability }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<Error>();
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const submitting = useRef(false);
  const importing = useRef(new Set<string>());
  const provider = useResource<Provider>('/settings/provider');
  const { preferences, ready, locale: language, setLocale: setLanguage, policy } = useWorkflowPreferences();
  const [parser, setParser] = useState<ParserProfileRevision>();
  const [translate, setTranslate] = useState(true);
  const [preparation, setPreparation] = useState<PreparationMode>('extractive');
  const [budget, setBudget] = useState('');
  const profile = provider.data;
  const costControlled = costControlEnabled(profile);
  const translationConfigured = Boolean(profile?.configured && profile.dispatch_configuration_ready && profile.profile_hash);
  const canSubmit = ready && (!translate || Boolean(profile && !provider.error));
  const selectedParser = parser ?? preferences.data?.parser_profile_revision ?? 'surya-ocr-2-v1';
  const maxBytes = capability?.limits?.max_pdf_bytes ?? 50 * 1024 * 1024;
  const maxBatch = capability?.limits?.max_batch_files ?? 10;
  const locked = busy || rows.some(row => row.busy);
  const selectionValid = isLanguageTag(language) && (!translate || preparationAllowed(preparation, profile));
  const pendingCount = rows.filter(row => !row.error && !row.upload && !row.document).length;
  const actionLabel = translate ? t("上传并翻译") : t("上传并生成原文阅读版");
  const update = (id: string, changes: Partial<Row>) => setRows(old => old.map(row => row.id === id ? { ...row, ...changes } : row));

  function select(files: File[]) {
    try {
      setRows(validatePdfSelection(files, maxBytes, maxBatch).map(row => ({ ...row, id: crypto.randomUUID() })));
      setError(undefined);
    } catch (reason) { setError(reason as Error); }
  }

  async function importRow(row: Row, upload: Upload) {
    if (!canSubmit || !selectionValid || importing.current.has(row.id)) return;
    importing.current.add(row.id);
    update(row.id, { busy: true, error: undefined, retryImport: false });
    try {
      const doc = await api<Document>('/imports', { method: 'POST', body: {
        source: { kind: 'pdf_upload', upload_id: upload.upload_id }, source_language: 'auto', target_language: language,
        parser_profile_revision: selectedParser,
        workflow: { translate, preparation: { mode: preparation }, target_locale: language, publish_policy: policy,
          external_processing_confirmed: translate && translationConfigured, use_saved_upload_permission: false,
          profile_hash: translate ? profile?.profile_hash || undefined : undefined,
          ...(translate && costControlled && budgetValid(budget) ? { budget_micro: Math.round(Number(budget) * 1_000_000) } : {}) },
      } });
      update(row.id, { document: doc, busy: false });
    } catch (reason) {
      const retryImport = reason instanceof ApiError && reason.code === 'PROFILE_STALE';
      update(row.id, { busy: false, error: (reason as Error).message, retryImport });
      if (retryImport) { provider.setData(undefined); preferences.reload(); provider.reload(); }
    } finally { importing.current.delete(row.id); }
  }

  async function uploadAll() {
    if (!canSubmit || !selectionValid || submitting.current || locked) return;
    submitting.current = true;
    setBusy(true);
    try {
      for (const row of rows.filter(item => !item.error && !item.upload && !item.document)) {
        try {
          update(row.id, { busy: true });
          const upload = await uploadPdf(row.file, progress => update(row.id, { progress }));
          update(row.id, { upload, busy: false });
          if (!upload.duplicate_documents?.length) await importRow(row, upload);
        } catch (reason) { update(row.id, { busy: false, error: (reason as Error).message }); }
      }
    } finally { submitting.current = false; setBusy(false); }
  }

  return <><PageHead title={t("上传 PDF")}/><ErrorNotice error={error}/>
    <div className="panel upload-workflow">
      <section aria-labelledby="upload-files-heading">
        <h2 id="upload-files-heading"><span className="upload-step">1</span>{t("选择 PDF")}</h2>
        <input ref={input} id="pdf-files" className="visually-hidden" type="file" accept="application/pdf,.pdf" multiple disabled={locked} onChange={event => select(Array.from(event.target.files ?? []))}/>
        <button className="dropzone" type="button" disabled={locked} onClick={() => input.current?.click()}
          onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!locked) select(Array.from(event.dataTransfer.files)); }}>
          <Icon name="upload" big/><strong>{t("拖放 PDF，或点击选择文件")}</strong>
          <small>{t("最多 {value0} 份 · 每份 {value1} MiB · 最多 {value2} 页", { value0: maxBatch, value1: (maxBytes / 1024 / 1024).toFixed(0), value2: capability?.limits?.max_pages ?? 200 })}</small>
        </button>
        {rows.some(row => !row.upload && !row.progress) && <ul className="upload-files" aria-label={t("已选文件")}>{rows.filter(row => !row.upload && !row.progress).map(row => <li key={row.id}>
          <strong className="filename">{row.file.name}</strong><span className="small muted">{(row.file.size / 1024).toFixed(1)} KiB</span>
          {row.error && !row.upload && !row.progress && <p role="alert" className="error">{t(row.error)}</p>}
        </li>)}</ul>}
      </section>

      <section className="upload-section" aria-labelledby="upload-options-heading">
        <h2 id="upload-options-heading"><span className="upload-step">2</span>{t("处理方式与语言")}</h2>
        <ErrorNotice error={preferences.error} retry={preferences.reload}/>
        <div className="upload-options">
          <div className="field"><label htmlFor="upload-mode">{t("处理方式")}</label>
            <select id="upload-mode" value={translate ? 'translate' : 'source'} disabled={locked} onChange={event => setTranslate(event.target.value === 'translate')}>
              <option value="translate">{t("解析并翻译")}</option><option value="source">{t("仅生成原文阅读版")}</option>
            </select>
          </div>
          {translate && <div className="field"><label htmlFor="upload-language">{t("翻译为")}</label>
            <LanguageSelect id="upload-language" value={language} disabled={locked} onChange={setLanguage}/>
          </div>}
        </div>
        {translate ? <PreparationControls value={preparation} onChange={setPreparation} profile={profile} disabled={locked}/>
          : <p className="field-note">{t("只解析 PDF 并生成原文阅读版，不进行翻译，也不授权向翻译服务发送内容。")}</p>}
        <details className="upload-parser-options"><summary>{t("解析选项")}</summary>
          <ParserSelect id="upload-parser" label={t("本地解析方案")} value={selectedParser} onChange={setParser} disabled={locked}/>
          <p className="small muted">{t("解析时限：{value0} 分钟", { value0: (preferences.data?.parser_timeout_seconds ?? 7200) / 60 })}</p>
        </details>
      </section>

      <section className="upload-section" aria-labelledby="upload-service-heading">
        <h2 id="upload-service-heading"><span className="upload-step">3</span>{translate ? t("翻译服务与费用") : t("本次处理说明")}</h2>
        {translate ? <>
          <ErrorNotice error={provider.error} retry={provider.reload}/><ProviderDestination profile={profile}/>
          {costControlled && profile && <div className="field"><label htmlFor="upload-budget">{t("每份文档费用上限（USD）")}</label>
            <input className="input" id="upload-budget" type="number" min="0.000001" step="0.000001" value={budget} disabled={locked} onChange={event => setBudget(event.target.value)}/>
          </div>}
          {profile && <p className="small muted">{costControlled ? t("已启用费用上限；实际费用以服务返回和已配置价格为准。") : t("未启用费用上限；翻译服务仍可能收费。")}</p>}
          {translationConfigured && <p className="field-note">{t("点击“上传并翻译”即同意将本批 PDF 的必要文本、上下文和术语发送到上述服务进行翻译，服务可能收费。")}</p>}
          {profile && (!translationConfigured || costControlled && !budgetValid(budget)) && <p className="field-note warn">{t("先完成本地解析和原文阅读；翻译将在服务配置和所需预算齐备后开始。")}{!translationConfigured && <>{' '}<a href="#/settings">{t("配置翻译服务")}</a></>}</p>}
        </> : <p className="small muted">{t("PDF 将由本地解析服务处理。完成后可直接阅读原文，之后也可另行开始翻译。")}</p>}
      </section>

      <div className="form-actions upload-submit">
        <p className="small muted" role="status">{rows.length ? t("{value0} 份文件待上传{value1}", { value0: pendingCount, value1: rows.some(row => row.error) ? t("，请检查文件提示") : '' }) : t("请先选择 PDF 文件。")}</p>
        <button className="btn primary" disabled={!canSubmit || locked || !selectionValid || !pendingCount} onClick={() => void uploadAll()}>
          {busy ? t("正在接收与检查…") : actionLabel}
        </button>
      </div>

      {rows.some(row => row.upload || row.progress) && <section className="upload-section" aria-label={t("上传结果")}>
        <h2>{t("上传结果")}</h2>
        {rows.filter(row => row.upload || row.progress).map(row => <div className="file-result" key={row.id}>
          <strong className="filename">{row.file.name}</strong>
          {row.error && <p role="alert" className="error">{t(row.error)}</p>}
          {row.progress && !row.document && <><progress max={row.progress.totalBytes} value={row.progress.receivedBytes}/>
            <small>{t("{value0} / {value1} 字节 · {value2}", { value0: row.progress.receivedBytes.toLocaleString(getUiLocale()), value1: row.progress.totalBytes.toLocaleString(getUiLocale()), value2: row.upload ? row.error ? t("PDF 已上传，处理未开始") : t("PDF 检查通过") : row.error ? t("上传或 PDF 检查未完成") : row.progress.status === 'inspecting' ? t("检查原件，尚未入库") : t("接收中") })}</small></>}
          {row.upload && <UploadMetadata upload={row.upload}/>}
          {row.document && <p role="status"><a href={`#/documents/${row.document.id}`}>{t("已入库，后台处理中 · 查看文档")}</a></p>}
          {row.upload && row.retryImport && !row.document && !row.upload.duplicate_documents?.length && <button className="btn sm" disabled={!canSubmit || locked || !selectionValid} onClick={() => void importRow(row, row.upload!)}>{t("重新处理已上传的 PDF")}</button>}
          {row.upload?.duplicate_documents?.length && !row.document ? <div className="notice"><strong>{t("发现相同 PDF 内容")}</strong>
            {row.upload.duplicate_documents.map(doc => <a className="btn sm" key={doc.id} href={`#/documents/${doc.id}`}>{t("使用已有文档：{value0}", { value0: doc.title })}</a>)}
            <button className="btn sm" disabled={!canSubmit || locked || !selectionValid} onClick={() => void importRow(row, row.upload!)}>{t("建立独立文档")}</button>
          </div> : null}
        </div>)}
      </section>}
    </div>
  </>;
}
