import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { useAction } from '../hooks';
import type { ParserProfileRevision, Preferences } from '../types';

const profiles = [
  { id: 'docling-v1', label: 'Docling 标准', description: '原生文本、OCR、表格及公式 / 代码增强。' },
  { id: 'granite-docling-v1', label: 'Granite Docling 258M', description: '本地视觉模型逐页识别文字与版面；CPU 解析较慢。' },
  { id: 'paddleocr-vl-1.6-v1', label: 'PaddleOCR-VL-1.6', description: '官方 PaddleOCR 套件识别文字、版面和表格，支持合并单元格并保留原表裁图；CPU 解析较慢。' },
] as const;

export function ParserSelect({ id, label, value, onChange, disabled = false }: {
  id: string; label: string; value: ParserProfileRevision; onChange: (value: ParserProfileRevision) => void; disabled?: boolean;
}) {
  return <div className="field"><label htmlFor={id}>{label}</label>
    <select id={id} value={value} onChange={e => onChange(e.target.value as ParserProfileRevision)} disabled={disabled} aria-describedby={`${id}-note`}>
      {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
    </select><p className="field-note" id={`${id}-note`}>{profiles.find(profile => profile.id === value)?.description}</p>
  </div>;
}

export function ParserSettings({ preferences, loading, onSaved, reload }: {
  preferences?: Preferences; loading: boolean; onSaved: (value: Preferences) => void; reload: () => void;
}) {
  const [choice, setChoice] = useState<ParserProfileRevision>();
  const [timeoutDraft, setTimeoutDraft] = useState<string>();
  const action = useAction();
  const selected = choice ?? preferences?.parser_profile_revision ?? 'docling-v1';
  const timeoutValue = timeoutDraft ?? String((preferences?.parser_timeout_seconds ?? 7200) / 60);
  const timeoutMinutes = Number(timeoutValue);
  const validTimeout = timeoutValue.trim() !== '' && Number.isInteger(timeoutMinutes) && timeoutMinutes >= 1 && timeoutMinutes <= 1440;
  return <section className="panel" aria-label="PDF 解析"><h2>PDF 解析</h2>
    <p className="muted">所有方案均在本机使用 CPU，解析内容不发送到外部 API。默认方案用于后续新任务，也可在文档详情中单次切换。</p>
    {loading && <Loading/>}
    {preferences && <form onSubmit={e => { e.preventDefault(); if (!validTimeout || action.pending || action.error) return; void action.run(async () => {
      const saved = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(preferences), body: { parser_profile_revision: selected, parser_timeout_seconds: timeoutMinutes * 60 } });
      onSaved(saved); setChoice(undefined); setTimeoutDraft(undefined);
    }, '解析设置已保存。'); }}>
      <ParserSelect id="default-parser" label="默认 PDF 解析方案" value={selected} onChange={setChoice} disabled={action.pending}/>
      <div className="field"><label htmlFor="parser-timeout">解析超时（分钟）</label>
        <input className="input" id="parser-timeout" type="number" min={1} max={1440} step={1} required value={timeoutValue}
          onChange={e => setTimeoutDraft(e.target.value)} disabled={action.pending} aria-invalid={!validTimeout}
          aria-describedby="parser-timeout-note"/>
        <p className="field-note" id="parser-timeout-note">默认 120 分钟，可设为 1–1440 的整数。时限按整份 PDF 计算，包含模型加载；多页文档在 CPU 上可能需要更长时间。保存后用于新建的解析任务。</p>
        {!validTimeout && <p className="field-note" role="alert">请输入 1–1440 之间的整数分钟。</p>}
      </div>
      <ActionFeedback notice={action.notice}/>
      <ErrorNotice error={action.error} retry={() => { action.clear(); reload(); }}/>
      <button className="btn primary" disabled={!validTimeout || action.pending || Boolean(action.error)}>保存解析设置</button>
    </form>}
    <p className="field-note">识别为公式或代码的区块不参与翻译，并保留原 PDF 裁图。模型识别可能有误，全文覆盖检查仍会执行；已排队或运行中的任务保留原有解析方案与超时设置。超时失败后，请重新发起解析以使用新设置。</p>
  </section>;
}
