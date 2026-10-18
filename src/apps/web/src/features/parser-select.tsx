import { t } from '../i18n';
import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { useAction, useResource } from '../hooks';
import { ModelMemory, type MemoryReference } from './resource-settings';
import type { ParserAccelerator, ParserEnvironment, ParserProfileRevision, Preferences } from '../types';
import { useSettingsForm, useSettingsRefresh } from './settings-state';

const runtimeLabels: Record<ParserAccelerator, string> = { cpu: 'CPU（已停用）', cuda: 'CUDA（已停用）', mlx: '原生 MLX（已停用）', dmr: 'Docker Model Runner' };

const profiles = [
  { id: 'surya-ocr-2-v1', label: 'Surya OCR 2' },
  { id: 'chandra-ocr-2-v1', label: 'Chandra OCR 2' },
  { id: 'infinity-parser2-pro-v1', label: 'Infinity-Parser2 Pro' },
  { id: 'infinity-parser2-flash-v1', label: 'Infinity-Parser2 Flash' },
] as const;

const retiredLabels: Record<string, string> = {
  'docling-v1': 'Docling 标准', 'granite-docling-v1': 'Granite Docling 258M',
  'paddleocr-vl-1.6-v1': 'PaddleOCR-VL-1.6', 'teleocr-v1': 'TeleOCR', 'xiaomi-ocr-0-v1': 'Xiaomi-OCR-0',
};
export function isActiveParserProfile(value: string): boolean {
  return profiles.some(profile => profile.id === value);
}

type ParserModel = { id: ParserProfileRevision; label?: string; description?: string; model_id?: string; revision?: string;
  download_bytes: number; status?: string; downloaded_bytes?: number;
  total_bytes?: number; code?: string; license?: string | null; memory_reference?: MemoryReference };
const modelStatus: Record<string, string> = { ready: '已准备', not_downloaded: '首次使用时下载',
  queued: '已排队，等待资源', downloading: '正在下载', loading: '正在准备推理后端', failed: '准备失败，可重试', unavailable: '模型准备服务不可用' };

export function ParserSelect({ id, label, value, onChange, disabled = false, catalog, catalogError }: {
  id: string; label: string; value: ParserProfileRevision; onChange: (value: ParserProfileRevision) => void; disabled?: boolean; catalog?: ParserModel[]; catalogError?: Error;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const remote = useResource<{ models: ParserModel[] }>(detailsOpen && !catalog ? '/settings/parser-models' : null);
  const model = (catalog ?? remote.data?.models)?.find(model => model.id === value);
  const active = isActiveParserProfile(value);
  return <div className="field"><label htmlFor={id}>{t(label)}</label>
    <select id={id} value={value} onChange={e => onChange(e.target.value as ParserProfileRevision)} disabled={disabled}>
      {!isActiveParserProfile(value) && <option value={value} disabled>{t("{model}（已停用，请重新选择）", { model: t(retiredLabels[value] ?? value) })}</option>}
      {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
    </select>
    <details className="model-choice-details" onToggle={event => setDetailsOpen(event.currentTarget.open)}>
      <summary>{t("模型说明与准备状态")}</summary>
      <p>{active ? t("用途：识别 PDF 页面的原文、阅读顺序、表格与公式。") : t("此历史解析方案已停用；原选择和历史记录会保留，请明确选择可用方案。")}</p>
      {remote.loading && <Loading/>}<ErrorNotice error={remote.error} retry={remote.reload}/>
      {active && <><strong>{model?.label ?? profiles.find(profile => profile.id === value)?.label}</strong>
        {model?.description && <p>{t(model.description)}</p>}
        <p>{t("准备状态：{status}。选择或保存不会下载模型。", { status: t(catalogError || remote.error ? '状态读取失败' : modelStatus[model?.status ?? ''] ?? '状态未提供') })}</p>
        <p>{t("当前设备的速度与质量对比：未提供，不能仅凭模型名称判断。")}</p></>}
      <dl className="kv"><dt>{t("方案 ID")}</dt><dd className="mono">{value}</dd><dt>{t("模型 ID")}</dt><dd className="mono">{model?.model_id ?? t("目录未提供")}</dd></dl>
    </details>
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
  const preparing = ['queued', 'downloading', 'loading'].includes(model?.status ?? '');
  const dirty = Boolean(preferences && (selected !== (preferences.parser_profile_revision ?? 'surya-ocr-2-v1') || timeoutValue !== String((preferences.parser_timeout_seconds ?? 7200) / 60)));
  const canSave = Boolean(preferences && validTimeout && runtimeAvailable && !action.pending && !action.error);
  const session = useSettingsForm('parser', { label: 'PDF 解析', dirty, pending: action.pending, canSave, save,
    discard: () => { setChoice(undefined); setTimeoutDraft(undefined); action.clear(); } });
  const refresh = useSettingsRefresh(dirty, () => { action.clear(); reload(); });
  async function save() {
    if (!canSave) return false;
    let success = false;
    await action.run(async () => {
      const current = session?.preferences() ?? preferences;
      const saved = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(current), body: { parser_profile_revision: selected, parser_timeout_seconds: timeoutMinutes * 60 } });
      session?.remember(saved); onSaved(saved); setChoice(undefined); setTimeoutDraft(undefined); success = true;
    }, '解析设置已保存。');
    return success;
  }
  return <section className="panel parser-panel" aria-label={t("PDF 解析")}><h2>{t("PDF 解析")}</h2>
    {detected?.online && effectiveDefault && <p className="settings-hint parser-device">{t("运行设备：{device} · Compose", { device: t(runtimeLabels[effectiveDefault]) })}</p>}
    {!environment.loading && !detected?.online && <p className="settings-hint" role="status">{t("解析环境暂不可用，请检查解析服务。")}</p>}
    {loading && <Loading/>}
    {preferences && <form onSubmit={e => { e.preventDefault(); void save(); }}>
      {dirty && <p className="settings-unsaved small">{t("未保存")}</p>}
      <ParserSelect id="default-parser" label={t("默认 PDF 解析方案")} value={selected} onChange={value => { setChoice(value); if (!action.error) action.clear(); }} disabled={action.pending} catalog={models.data?.models} catalogError={models.error}/>
      <div className="field" aria-label={t("解析模型准备")}>
        {model && <p role="status">{t("{status} · 下载约 {size} GB", { status: t(models.error ? '准备状态更新失败' : modelStatus[model.status ?? ''] ?? '状态未提供'), size: (model.download_bytes / 10 ** 9).toFixed(2) })}
          {preparing && model.total_bytes ? ` · ${((model.downloaded_bytes ?? 0) / model.total_bytes * 100).toFixed(1)}%` : ''}</p>}
        {model?.status === 'failed' && <p className="field-note" role="alert">{t("准备失败（{code}），请检查磁盘空间、网络与推理后端后重试。", { code: model.code ?? '' })}</p>}
        <ModelMemory reference={model?.memory_reference}/>
        <button className="btn" type="button" disabled={!runtimeAvailable || preparing || prepare.pending || !detected?.online}
          onClick={() => void prepare.run(async () => {
            await api('/settings/parser-models/prepare', { method: 'POST', body: { parser_profile_revision: selected } });
            models.reload();
          }, '已开始准备解析模型。')}>{t("准备解析模型")}</button>
        <ActionFeedback notice={prepare.notice}/>
        <ErrorNotice error={prepare.error} retry={() => { prepare.clear(); models.reload(); }}/>
      </div>
      <div className="field"><label htmlFor="parser-timeout">{t("解析超时（分钟）")}</label>
        <input className="input" id="parser-timeout" type="number" min={1} max={1440} step={1} required value={timeoutValue}
          onChange={e => { setTimeoutDraft(e.target.value); if (!action.error) action.clear(); }} disabled={action.pending} aria-invalid={!validTimeout}/>
        {!validTimeout && <p className="field-note" role="alert">{t("请输入 1–1440 之间的整数分钟。")}</p>}
      </div>
      {!runtimeAvailable && <p className="field-note" role="alert">{t("Compose 配置的设备不支持当前方案或暂不可用，请检查部署配置或选择兼容的解析方案。")}</p>}
      <details className="settings-details parser-details"><summary>{t("解析环境")}</summary>
        <div aria-label={t("检测到的解析环境")}>
          {environment.loading ? <Loading/> : detected?.online && <>
            <p>{t("{system} · {architecture} · {cores} 核 CPU · 内存上限 {memory}", { system: detected.system ?? t("未知"), architecture: detected.architecture ?? t("未知"), cores: detected.cpu_count ?? t("未知"), memory: detected.memory_bytes ? `${(detected.memory_bytes / 1024 ** 3).toFixed(1)} GiB` : t("未知") })}</p>
            {detected.gpu_name && <p>GPU：{detected.gpu_name}</p>}
          </>}
        </div>
      </details>
      <ActionFeedback notice={action.notice}/>
      <ErrorNotice error={action.error} retry={refresh.request}/>
      <div className="settings-actions"><button className="btn primary" disabled={!canSave}>{t("保存解析设置")}</button></div>
    </form>}
    {refresh.confirmation}
  </section>;
}
