import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { useAction, useResource } from '../hooks';
import type { ParserAccelerator, ParserEnvironment, ParserProfileRevision, Preferences } from '../types';

const runtimeLabels: Record<ParserAccelerator, string> = { deployment: '部署默认', cpu: 'CPU', cuda: 'NVIDIA CUDA', mlx: 'Apple MLX' };
const unavailableReasons: Record<string, string> = {
  CUDA_UNAVAILABLE_OR_MODEL_UNSUPPORTED: '未检测到可用 GPU，或当前镜像不支持此模型的 CUDA 运行。',
  MLX_IMAGE_BACKEND_UNAVAILABLE: '当前部署没有可用的 Docker MLX 图像推理后端。',
};

const profiles = [
  { id: 'docling-v1', label: 'Docling 标准', description: '原生文本、OCR、表格及公式 / 代码增强。' },
  { id: 'granite-docling-v1', label: 'Granite Docling 258M', description: '本地视觉模型逐页识别文字与版面。' },
  { id: 'paddleocr-vl-1.6-v1', label: 'PaddleOCR-VL-1.6', description: '官方 PaddleOCR 套件识别文字、版面和表格，支持合并单元格并保留原表裁图。' },
] as const;

export function ParserSelect({ id, label, value, onChange, disabled = false, showDescription = true }: {
  id: string; label: string; value: ParserProfileRevision; onChange: (value: ParserProfileRevision) => void; disabled?: boolean; showDescription?: boolean;
}) {
  return <div className="field"><label htmlFor={id}>{label}</label>
    <select id={id} value={value} onChange={e => onChange(e.target.value as ParserProfileRevision)} disabled={disabled} aria-describedby={showDescription ? `${id}-note` : undefined}>
      {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
    </select>{showDescription && <p className="field-note" id={`${id}-note`}>{profiles.find(profile => profile.id === value)?.description}</p>}
  </div>;
}

export function ParserSettings({ preferences, loading, onSaved, reload }: {
  preferences?: Preferences; loading: boolean; onSaved: (value: Preferences) => void; reload: () => void;
}) {
  const [choice, setChoice] = useState<ParserProfileRevision>();
  const [timeoutDraft, setTimeoutDraft] = useState<string>();
  const [runtimeDraft, setRuntimeDraft] = useState<ParserAccelerator>();
  const environment = useResource<ParserEnvironment>('/settings/parser-environment', 15000);
  const detected = environment.error ? undefined : environment.data;
  const runtime = runtimeDraft ?? preferences?.parser_accelerator ?? 'deployment';
  const action = useAction();
  const selected = choice ?? preferences?.parser_profile_revision ?? 'paddleocr-vl-1.6-v1';
  const effectiveDefault = detected?.default === 'mlx' && selected !== 'paddleocr-vl-1.6-v1' ? 'cpu' : detected?.default;
  const timeoutValue = timeoutDraft ?? String((preferences?.parser_timeout_seconds ?? 7200) / 60);
  const timeoutMinutes = Number(timeoutValue);
  const validTimeout = timeoutValue.trim() !== '' && Number.isInteger(timeoutMinutes) && timeoutMinutes >= 1 && timeoutMinutes <= 1440;
  const available = (id: ParserAccelerator | undefined) => Boolean(detected?.online && detected.options?.some(option => option.id === id && option.profiles.includes(selected)));
  const defaultAvailable = !detected?.online || available(effectiveDefault);
  const runtimeAvailable = runtime === 'deployment' ? defaultAvailable : available(runtime);
  return <section className="panel parser-panel" aria-label="PDF 解析"><h2>PDF 解析</h2>
    {!environment.loading && !detected?.online && <p className="settings-hint" role="status">解析环境暂不可用，请检查服务或刷新环境。</p>}
    {loading && <Loading/>}
    {preferences && <form onSubmit={e => { e.preventDefault(); if (!validTimeout || !runtimeAvailable || action.pending || action.error) return; void action.run(async () => {
      const saved = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(preferences), body: { parser_profile_revision: selected, parser_timeout_seconds: timeoutMinutes * 60, ...(runtimeDraft !== undefined || preferences.parser_accelerator ? { parser_accelerator: runtime } : {}) } });
      onSaved(saved); setChoice(undefined); setTimeoutDraft(undefined); setRuntimeDraft(undefined);
    }, '解析设置已保存。'); }}>
      <ParserSelect id="default-parser" label="默认 PDF 解析方案" value={selected} onChange={setChoice} disabled={action.pending} showDescription={false}/>
      <div className="two-cols parser-runtime-fields">
      <div className="field"><label htmlFor="parser-accelerator">运行设备</label>
        <select id="parser-accelerator" value={runtime} onChange={e => setRuntimeDraft(e.target.value as ParserAccelerator)} disabled={action.pending} aria-describedby="parser-accelerator-note">
          <option value="deployment" disabled={!defaultAvailable}>部署默认{detected?.online && effectiveDefault ? `（${runtimeLabels[effectiveDefault]}）` : ''}</option>
          {(['cpu', 'cuda', 'mlx'] as const).map(id => {
            return <option key={id} value={id} disabled={!available(id)}>{runtimeLabels[id]}{available(id) ? '' : '（不可用）'}</option>;
          })}
        </select>
      </div>
      <div className="field"><label htmlFor="parser-timeout">解析超时（分钟）</label>
        <input className="input" id="parser-timeout" type="number" min={1} max={1440} step={1} required value={timeoutValue}
          onChange={e => setTimeoutDraft(e.target.value)} disabled={action.pending} aria-invalid={!validTimeout}
          aria-describedby="parser-timeout-note"/>
        {!validTimeout && <p className="field-note" role="alert">请输入 1–1440 之间的整数分钟。</p>}
      </div>
      </div>
      {!runtimeAvailable && <p className="field-note" role="alert">当前选择的设备不可用，请重新选择。</p>}
      {selected === 'paddleocr-vl-1.6-v1' && detected?.memory_bytes && detected.memory_bytes < 10 * 1024 ** 3 ? <p className="settings-hint">当前内存较低，Paddle 可能加载失败。可增加 Docker 内存或选择较轻的方案。</p> : null}
      <details className="settings-details parser-details"><summary>设备与解析说明</summary>
        <div aria-label="检测到的解析环境">
          {environment.loading ? <Loading/> : detected?.online && <>
            <p>{detected.system} · {detected.architecture} · {detected.cpu_count} 核 CPU · 内存上限 {detected.memory_bytes ? `${(detected.memory_bytes / 1024 ** 3).toFixed(1)} GiB` : '未知'}</p>
            {detected.gpu_name && <p>GPU：{detected.gpu_name}</p>}
            <p>最近检测：{detected.detected_at ? new Date(detected.detected_at * 1000).toLocaleString() : '未知'}</p>
          </>}
          <button className="btn sm" type="button" onClick={environment.reload}>刷新环境</button>
        </div>
        <div id="parser-accelerator-note">{detected?.online && detected.options?.filter(option => !option.profiles.includes(selected)).map(option => <p key={option.id}>{runtimeLabels[option.id]}：{unavailableReasons[option.reason ?? ''] ?? '当前方案不可用。'}</p>)}</div>
        <p>{profiles.find(profile => profile.id === selected)?.description}</p>
        <p id="parser-timeout-note">超时范围 1–1440 分钟，按整份 PDF 计算，包含模型加载。保存只影响新任务。</p>
        <p>公式与代码保留原图，覆盖检查继续执行。超时后可调整设置并重新解析。</p>
      </details>
      <ActionFeedback notice={action.notice}/>
      <ErrorNotice error={action.error} retry={() => { action.clear(); reload(); }}/>
      <div className="settings-actions"><button className="btn primary" disabled={!validTimeout || !runtimeAvailable || action.pending || Boolean(action.error)}>保存解析设置</button></div>
    </form>}
  </section>;
}
