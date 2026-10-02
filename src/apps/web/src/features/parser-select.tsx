import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { useAction, useResource } from '../hooks';
import type { ParserAccelerator, ParserEnvironment, ParserProfileRevision, Preferences } from '../types';

const runtimeLabels: Record<ParserAccelerator, string> = { cpu: 'CPU（已停用）', cuda: 'CUDA（已停用）', mlx: '原生 MLX（已停用）', dmr: 'Docker Model Runner' };

const profiles = [
  { id: 'surya-ocr-2-v1', label: 'Surya OCR 2', description: '0.65B 视觉模型识别文字、版面、公式与表格。' },
  { id: 'chandra-ocr-2-v1', label: 'Chandra OCR 2', description: '4B 视觉模型识别复杂表格、手写与多语种内容。' },
  { id: 'infinity-parser2-pro-v1', label: 'Infinity-Parser2 Pro', description: '35.1B 高精度方案，约 70.2 GB 权重，需要足够内存的 Docker Model Runner。' },
  { id: 'infinity-parser2-flash-v1', label: 'Infinity-Parser2 Flash', description: '2B 低延迟方案，输出阅读顺序、文字、表格与公式。' },
] as const;

const retiredLabels: Record<string, string> = {
  'docling-v1': 'Docling 标准', 'granite-docling-v1': 'Granite Docling 258M',
  'paddleocr-vl-1.6-v1': 'PaddleOCR-VL-1.6', 'teleocr-v1': 'TeleOCR', 'xiaomi-ocr-0-v1': 'Xiaomi-OCR-0',
};
export function isActiveParserProfile(value: string): boolean {
  return profiles.some(profile => profile.id === value);
}

type ParserModel = { id: ParserProfileRevision; download_bytes: number; status?: string; downloaded_bytes?: number;
  total_bytes?: number; code?: string; license?: string | null };
const modelStatus: Record<string, string> = { ready: '已准备', not_downloaded: '首次使用时下载',
  downloading: '正在下载', loading: '正在准备推理后端', failed: '准备失败，可重试', unavailable: '模型准备服务不可用' };

export function ParserSelect({ id, label, value, onChange, disabled = false, showDescription = true }: {
  id: string; label: string; value: ParserProfileRevision; onChange: (value: ParserProfileRevision) => void; disabled?: boolean; showDescription?: boolean;
}) {
  return <div className="field"><label htmlFor={id}>{label}</label>
    <select id={id} value={value} onChange={e => onChange(e.target.value as ParserProfileRevision)} disabled={disabled} aria-describedby={showDescription ? `${id}-note` : undefined}>
      {!isActiveParserProfile(value) && <option value={value} disabled>{retiredLabels[value] ?? value}（已停用，请重新选择）</option>}
      {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
    </select>{showDescription && <p className="field-note" id={`${id}-note`}>{isActiveParserProfile(value) ? profiles.find(profile => profile.id === value)?.description : '保存的旧方案已停用；请选择全页 DMR 方案。历史解析结果保持可读。'}</p>}
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
  const selected = choice ?? preferences?.parser_profile_revision ?? 'surya-ocr-2-v1';
  const effectiveDefault = detected?.default;
  const timeoutValue = timeoutDraft ?? String((preferences?.parser_timeout_seconds ?? 7200) / 60);
  const timeoutMinutes = Number(timeoutValue);
  const validTimeout = timeoutValue.trim() !== '' && Number.isInteger(timeoutMinutes) && timeoutMinutes >= 1 && timeoutMinutes <= 1440;
  const device = detected?.options?.find(option => option.id === effectiveDefault);
  const runtimeAvailable = isActiveParserProfile(selected) && (!detected?.online || Boolean(device?.profiles.includes(selected)));
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
      <details className="settings-details parser-details"><summary>设备与解析说明</summary>
        <div aria-label="检测到的解析环境">
          {environment.loading ? <Loading/> : detected?.online && <>
            <p>{detected.system} · {detected.architecture} · {detected.cpu_count} 核 CPU · 内存上限 {detected.memory_bytes ? `${(detected.memory_bytes / 1024 ** 3).toFixed(1)} GiB` : '未知'}</p>
            {detected.gpu_name && <p>GPU：{detected.gpu_name}</p>}
          </>}
        </div>
        {detected?.default === 'dmr' && <p>四个方案均由 Docker Model Runner 的 vLLM / vLLM Metal 后端进行全页推理。客户端镜像不包含模型或推理框架；具体架构和硬件支持由当前后端决定。</p>}
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
