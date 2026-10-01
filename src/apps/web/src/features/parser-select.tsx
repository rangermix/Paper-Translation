import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { useAction, useResource } from '../hooks';
import type { ParserAccelerator, ParserEnvironment, ParserProfileRevision, Preferences } from '../types';

const runtimeLabels: Record<ParserAccelerator, string> = { cpu: 'CPU', cuda: 'NVIDIA CUDA', mlx: 'Apple MLX', dmr: 'Docker Model Runner' };
const unavailableReasons: Record<string, string> = {
  CUDA_UNAVAILABLE_OR_MODEL_UNSUPPORTED: '未检测到可用 GPU，或当前镜像不支持此模型的 CUDA 运行。',
  MLX_IMAGE_BACKEND_UNAVAILABLE: '当前部署没有可用的 Docker MLX 图像推理后端。',
};

const profiles = [
  { id: 'docling-v1', label: 'Docling 标准', description: '原生文本、OCR、表格及公式 / 代码增强。' },
  { id: 'granite-docling-v1', label: 'Granite Docling 258M', description: '本地视觉模型逐页识别文字与版面。' },
  { id: 'paddleocr-vl-1.6-v1', label: 'PaddleOCR-VL-1.6', description: '官方 PaddleOCR 套件识别文字、版面和表格，支持合并单元格并保留原表裁图。' },
  { id: 'surya-ocr-2-v1', label: 'Surya OCR 2', description: '0.65B 视觉模型识别文字、版面、公式与表格。' },
  { id: 'chandra-ocr-2-v1', label: 'Chandra OCR 2', description: '4B 视觉模型识别复杂表格、手写与多语种内容。' },
  { id: 'infinity-parser2-pro-v1', label: 'Infinity-Parser2 Pro', description: '35.1B 高精度方案，约 70.2 GB 权重，需要足够内存的 Docker Model Runner。' },
  { id: 'infinity-parser2-flash-v1', label: 'Infinity-Parser2 Flash', description: '2B 低延迟方案，输出阅读顺序、文字、表格与公式。' },
  { id: 'teleocr-v1', label: 'TeleOCR', description: '1.5B 文档识别，使用锁定的自定义模型；选择 CPU / CUDA 模式。' },
  { id: 'xiaomi-ocr-0-v1', label: 'Xiaomi-OCR-0', description: '0.8B 轻量文档识别，保留原始页图与内容核对提示。' },
] as const;

type ParserModel = { id: ParserProfileRevision; download_bytes: number; status?: string; downloaded_bytes?: number;
  total_bytes?: number; code?: string; license?: string | null };
const modelStatus: Record<string, string> = { ready: '已准备', not_downloaded: '首次使用时下载',
  downloading: '正在下载', loading: '正在准备推理后端', failed: '准备失败，可重试', unavailable: '模型准备服务不可用' };

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
  const environment = useResource<ParserEnvironment>('/settings/parser-environment');
  const detected = environment.error ? undefined : environment.data;
  const action = useAction();
  const prepare = useAction();
  const models = useResource<{ models: ParserModel[] }>('/settings/parser-models', 5000);
  const selected = choice ?? preferences?.parser_profile_revision ?? 'paddleocr-vl-1.6-v1';
  const effectiveDefault = detected?.default === 'mlx' && selected !== 'paddleocr-vl-1.6-v1' ? 'cpu' : detected?.default;
  const timeoutValue = timeoutDraft ?? String((preferences?.parser_timeout_seconds ?? 7200) / 60);
  const timeoutMinutes = Number(timeoutValue);
  const validTimeout = timeoutValue.trim() !== '' && Number.isInteger(timeoutMinutes) && timeoutMinutes >= 1 && timeoutMinutes <= 1440;
  const device = detected?.options?.find(option => option.id === effectiveDefault);
  const runtimeAvailable = !detected?.online || Boolean(device?.profiles.includes(selected));
  const model = models.data?.models?.find(row => row.id === selected);
  const preparing = model?.status === 'downloading' || model?.status === 'loading';
  return <section className="panel parser-panel" aria-label="PDF 解析"><h2>PDF 解析</h2>
    {detected?.online && effectiveDefault && <p className="settings-hint parser-device">运行设备：{runtimeLabels[effectiveDefault]} · Compose</p>}
    {!environment.loading && !detected?.online && <p className="settings-hint" role="status">解析环境暂不可用，请检查解析服务。</p>}
    {loading && <Loading/>}
    {preferences && <form onSubmit={e => { e.preventDefault(); if (!validTimeout || !runtimeAvailable || action.pending || action.error) return; void action.run(async () => {
      const saved = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(preferences), body: { parser_profile_revision: selected, parser_timeout_seconds: timeoutMinutes * 60 } });
      onSaved(saved); setChoice(undefined); setTimeoutDraft(undefined);
    }, '解析设置已保存。'); }}>
      <ParserSelect id="default-parser" label="默认 PDF 解析方案" value={selected} onChange={setChoice} disabled={action.pending} showDescription={false}/>
      <div className="field" aria-label="解析模型准备">
        <p className="field-note">模型按需下载并保存在 Docker 卷中。保存设置不会下载；首次解析会自动准备。</p>
        {model && <p role="status">{modelStatus[model.status ?? 'not_downloaded']} · 下载约 {(model.download_bytes / 10 ** 9).toFixed(2)} GB
          {preparing && model.total_bytes ? ` · ${((model.downloaded_bytes ?? 0) / model.total_bytes * 100).toFixed(1)}%` : ''}</p>}
        {model?.status === 'failed' && <p className="field-note" role="alert">准备失败（{model.code}），请检查磁盘空间、网络与推理后端后重试。</p>}
        <button className="btn" type="button" disabled={!runtimeAvailable || preparing || prepare.pending || !detected?.online}
          onClick={() => void prepare.run(async () => {
            await api('/settings/parser-models/prepare', { method: 'POST', body: { parser_profile_revision: selected } });
            models.reload();
          }, '已开始准备解析模型。')}>准备解析模型</button>
        <ActionFeedback notice={prepare.notice}/>
        <ErrorNotice error={prepare.error} retry={() => { prepare.clear(); models.reload(); }}/>
      </div>
      <div className="field"><label htmlFor="parser-timeout">解析超时（分钟）</label>
        <input className="input" id="parser-timeout" type="number" min={1} max={1440} step={1} required value={timeoutValue}
          onChange={e => setTimeoutDraft(e.target.value)} disabled={action.pending} aria-invalid={!validTimeout}
          aria-describedby="parser-timeout-note"/>
        {!validTimeout && <p className="field-note" role="alert">请输入 1–1440 之间的整数分钟。</p>}
      </div>
      {!runtimeAvailable && <p className="field-note" role="alert">Compose 配置的设备不支持当前方案或暂不可用，请检查部署配置或选择兼容的解析方案。</p>}
      {selected === 'paddleocr-vl-1.6-v1' && detected?.memory_bytes && detected.memory_bytes < 10 * 1024 ** 3 ? <p className="settings-hint">当前内存较低，Paddle 可能加载失败。可增加 Docker 内存或选择较轻的方案。</p> : null}
      <details className="settings-details parser-details"><summary>设备与解析说明</summary>
        <div aria-label="检测到的解析环境">
          {environment.loading ? <Loading/> : detected?.online && <>
            <p>{detected.system} · {detected.architecture} · {detected.cpu_count} 核 CPU · 内存上限 {detected.memory_bytes ? `${(detected.memory_bytes / 1024 ** 3).toFixed(1)} GiB` : '未知'}</p>
            {detected.gpu_name && <p>GPU：{detected.gpu_name}</p>}
          </>}
        </div>
        {detected?.default === 'mlx' && <p>Compose 的 MLX 模式使用 MLX 识别 Paddle 内容；版面分析及 Docling / Granite 使用 CPU。</p>}
        {detected?.default === 'dmr' && <p>Docker 提供 vLLM / vLLM Metal 图像推理后端。TeleOCR 和 Docling / Paddle 需要 CPU / CUDA 模式；具体硬件与模型架构须由当前后端支持。</p>}
        {!runtimeAvailable && device?.reason && <p>{unavailableReasons[device.reason] ?? '当前方案不可用。'}</p>}
        <p>{profiles.find(profile => profile.id === selected)?.description}</p>
        <p id="parser-timeout-note">超时范围 1–1440 分钟，按整份 PDF 计算，包含首次下载和模型加载。大模型可先准备，再上传解析。保存只影响新任务。</p>
        <p>公式与代码保留原图，覆盖检查继续执行。超时后可调整设置并重新解析。</p>
      </details>
      <ActionFeedback notice={action.notice}/>
      <ErrorNotice error={action.error} retry={() => { action.clear(); reload(); }}/>
      <div className="settings-actions"><button className="btn primary" disabled={!validTimeout || !runtimeAvailable || action.pending || Boolean(action.error)}>保存解析设置</button></div>
    </form>}
  </section>;
}
