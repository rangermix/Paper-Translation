import { t } from '../i18n';
import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorNotice } from '../components';
import { ModelMemory, type MemoryReference } from './resource-settings';

export type LocalModel = { id: string; label: string; model_id: string; family: string; family_label: string;
  parameter_size: string; bits: number; quantization: string; format: string; runtime: string; repo: string;
  revision: string; download_bytes: number; inference_backends?: string[]; default_backend?: string; memory_reference?: MemoryReference;
  backend_states?: Record<string, ModelState>; status?: string; downloaded_bytes?: number; total_bytes?: number; code?: string };
type ModelState = { status?: string; downloaded_bytes?: number; total_bytes?: number; code?: string };
type Choice = { family: string; size: string; format: string; model: string; backend: string };
const empty: Choice = { family: '', size: '', format: '', model: '', backend: '' };
export const inferenceLabels: Record<string, string> = { 'llama.cpp': 'llama.cpp', vllm: 'vLLM（CUDA）', mlx: 'vLLM Metal（MLX）' };
const sizeOf = (model: LocalModel) => `${model.parameter_size} · ${model.quantization.startsWith('BF') ? model.quantization : `Q${model.bits}`}`;
export const modelStatusLabels: Record<string, string> = { ready: '已下载', not_downloaded: '首次使用时下载', downloading: '正在下载',
  queued: '已排队，等待资源', loading: '正在加载', failed: '准备失败，可重试', unavailable: '本地模型服务未就绪' };
const backendLabels: Record<string, string> = { LOCAL_GGUF_UNAVAILABLE: 'llama.cpp 后端未就绪',
  LOCAL_VLLM_UNAVAILABLE: 'vLLM 后端未就绪', LOCAL_MLX_UNAVAILABLE: 'MLX 后端未就绪',
  LOCAL_CUDA_PROBE_MISSING: 'Docker Runner 缺少 CUDA 检测组件',
  LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED: '当前 Runner 部署未提供 vLLM 后端',
  LOCAL_MODEL_BACKEND_UNSUPPORTED: '当前模型或部署不支持此推理后端' };

export function LocalModels({ value, backend, onChange, active, onAvailabilityChange, purpose = 'translation' }: {
  value: string; backend: string; onChange: (model: string, backend: string) => void; active: boolean; onAvailabilityChange: (available: boolean) => void;
  purpose?: 'translation' | 'analysis';
}) {
  const analysis = purpose === 'analysis';
  const [models, setModels] = useState<LocalModel[]>([]);
  const [choice, setChoice] = useState<Choice>(empty);
  const [remembered, setRemembered] = useState<Record<string, Choice>>({});
  const [modelBackends, setModelBackends] = useState<Record<string, string>>({});
  const [error, setError] = useState<Error>();
  const [catalogCode, setCatalogCode] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!active) return;
    setLoading(true);
    let alive = true;
    let timer: number;
    const controller = new AbortController();
    const read = async () => {
      try { const result = await api<{ models: LocalModel[]; code?: string }>(`/settings/local-models${analysis ? '?purpose=analysis' : ''}`, { signal: controller.signal });
        if (alive) { setModels(result.models ?? []); setCatalogCode(result.code ?? ''); setError(undefined); }
      } catch (reason) { if (alive) setError(reason as Error); }
      finally { if (alive) { setLoading(false); timer = window.setTimeout(() => void read(), 5000); } }
    };
    void read();
    return () => { alive = false; controller.abort(); window.clearTimeout(timer); };
  }, [active, refresh, analysis]);
  const selected = models.find(model => model.model_id === value);
  const backendOptions = selected?.inference_backends ?? (selected ? [selected.runtime] : []);
  const defaultBackend = selected?.default_backend ?? selected?.runtime ?? '';
  const selectedBackend = backend || defaultBackend;
  const compatible = !!selected && backendOptions.includes(selectedBackend);
  const state = selected?.backend_states?.[selectedBackend] ?? (selectedBackend === defaultBackend ? selected : undefined);
  useEffect(() => {
    if (selected) setChoice({ family: selected.family, size: sizeOf(selected), format: selected.format, model: selected.model_id, backend: selectedBackend });
  }, [selected?.model_id, selectedBackend]);
  useEffect(() => onAvailabilityChange(compatible), [onAvailabilityChange, compatible]);
  const families = [...new Map(models.map(model => [model.family, model.family_label])).entries()];
  const sizes = [...new Set(models.filter(model => model.family === choice.family).map(sizeOf))];
  const formats = [...new Set(models.filter(model => model.family === choice.family && sizeOf(model) === choice.size).map(model => model.format))];
  const finalModels = models.filter(model => model.family === choice.family && sizeOf(model) === choice.size && model.format === choice.format);
  function remember() {
    if (!choice.family) return;
    const current = { ...choice, backend: selectedBackend };
    if (selected) setModelBackends(old => ({ ...old, [selected.model_id]: selectedBackend }));
    setRemembered(old => ({ ...old,
      [choice.family]: current,
      ...(choice.size ? { [`${choice.family}|${choice.size}`]: current } : {}),
      ...(choice.format ? { [`${choice.family}|${choice.size}|${choice.format}`]: current } : {}),
    }));
  }
  function changeFamily(family: string) {
    remember();
    const next = remembered[family] ?? { ...empty, family };
    setChoice(next); onChange(next.model, next.backend);
  }
  function changeSize(size: string) {
    remember();
    const next = remembered[`${choice.family}|${size}`] ?? { ...empty, family: choice.family, size };
    setChoice(next); onChange(next.model, next.backend);
  }
  function changeFormat(format: string) {
    remember();
    const next = remembered[`${choice.family}|${choice.size}|${format}`] ?? { ...empty, family: choice.family, size: choice.size, format };
    setChoice(next); onChange(next.model, next.backend);
  }
  function changeModel(model: string) {
    remember();
    const entry = models.find(candidate => candidate.model_id === model);
    const options = entry?.inference_backends ?? (entry ? [entry.runtime] : []);
    const preferred = entry?.default_backend ?? entry?.runtime ?? '';
    const nextBackend = modelBackends[model] ?? (options.includes(preferred) ? preferred : options[0] ?? preferred);
    setChoice(old => ({ ...old, model, backend: nextBackend })); onChange(model, nextBackend);
  }
  function changeBackend(nextBackend: string) {
    if (!selected) return;
    setModelBackends(old => ({ ...old, [selected.model_id]: nextBackend }));
    setChoice(old => ({ ...old, backend: nextBackend })); onChange(selected.model_id, nextBackend);
  }
  async function prepare() {
    if (!selected || !compatible || pending) return;
    setPending(true); setError(undefined);
    try { await api(`/settings/local-models/${selected.id}/prepare?backend=${encodeURIComponent(selectedBackend)}`, { method: 'POST', body: {} }); setRefresh(n => n + 1); }
    catch (reason) { setError(reason as Error); }
    finally { setPending(false); }
  }
  return <section className="local-model-settings" aria-label={analysis ? t("本地分析模型") : t("本地翻译模型")} hidden={!active}>
    <p className="settings-hint">{analysis ? t("用途：翻译前的背景与术语准备。正文翻译仍使用翻译服务中的模型。") : t("用途：在当前实例中生成译文。")}{' '}{t("选择和保存不会下载或加载模型。")}</p>
    <label className="field">{t("模型系列")}<select aria-label={t("模型系列")} value={choice.family} onChange={event => changeFamily(event.target.value)}>
      <option value="">{t("请选择模型系列")}</option>
      {families.map(([family, label]) => <option key={family} value={family}>{label}</option>)}
    </select></label>
    <label className="field">{t("参数规模与量化")}<select aria-label={t("参数规模与量化")} value={choice.size} onChange={event => changeSize(event.target.value)} disabled={!choice.family}>
      <option value="">{t("请选择参数规模与量化")}</option>
      {sizes.map(size => <option key={size} value={size}>{size}</option>)}
    </select></label>
    <label className="field">{t("模型格式")}<select aria-label={t("模型格式")} value={choice.format} onChange={event => changeFormat(event.target.value)} disabled={!choice.size}>
      <option value="">{t("请选择格式")}</option>
      {formats.map(format => <option key={format} value={format}>{format === 'mlx' ? 'MLX' : format === 'gguf' ? 'GGUF' : 'Safetensors'}</option>)}
    </select></label>
    <label className="field">{t("具体模型 ID")}<select aria-label={t("具体模型 ID")} value={selected?.model_id ?? ''} onChange={event => changeModel(event.target.value)} disabled={!choice.format}>
      <option value="">{t("请选择模型 ID")}</option>
      {finalModels.map(model => <option key={model.id} value={model.model_id}>{model.label || model.repo} · {model.id}</option>)}
    </select></label>
    <label className="field">{t("推理后端")}<select aria-label={t("推理后端")} value={selected ? selectedBackend : ''} onChange={event => changeBackend(event.target.value)} disabled={!selected}>
      <option value="">{t("请选择推理后端")}</option>
      {backendOptions.map(option => <option key={option} value={option}>{t(inferenceLabels[option] ?? option)}</option>)}
      {selected && selectedBackend && !compatible && <option value={selectedBackend}>{t("已保存后端（当前模型或部署不支持）")}</option>}
    </select></label>
    {selected && !compatible && <p className="field-note error-text">{t("所选后端与当前模型或部署不兼容，请选择支持的推理后端。")}</p>}
    {!loading && !error && value && !selected && <p className="field-note error-text">{t("已保存的模型在当前部署中不可用，当前值仍保留：")}<code>{value}</code>{t("。请选择当前后端提供的模型。")}</p>}
    {catalogCode === 'LOCAL_MODEL_SERVICE_UNAVAILABLE' && <p className="field-note">{analysis ? t("本地翻译服务未启动或无法连接，仍可选择和保存模型。准备模型和分析前，请在部署中启用本地翻译服务。") : t("本地翻译服务未启动或无法连接，仍可选择和保存模型。准备模型和翻译前，请在部署中启用本地翻译服务。")}</p>}
    {loading && !models.length && <p className="settings-hint" role="status">{t("正在读取模型目录…")}</p>}
    {!loading && !error && !models.length && <p className="field-note">{analysis ? t("当前部署没有可选的本地分析模型，请检查部署支持的格式与后端。") : t("当前部署没有可选的本地翻译模型，请检查部署支持的格式与后端。")}</p>}
    {selected && <><strong className="model-choice-name">{selected.label || selected.repo}</strong><p className="local-model-status" role="status">{t("{status} · {format} {quantization} · 下载约 {size} GB", { status: t(error ? '状态更新失败，请刷新后核对' : !compatible ? backendLabels.LOCAL_MODEL_BACKEND_UNSUPPORTED : backendLabels[state?.code ?? ''] ?? modelStatusLabels[state?.status ?? ''] ?? '状态未提供'), format: selected.format.toUpperCase(), quantization: selected.quantization, size: (selected.download_bytes / 1e9).toFixed(1) })}</p>
      {state?.code === 'LOCAL_CUDA_PROBE_MISSING' && <p className="field-note">{t("Docker Model Runner 已启用，但缺少 GPU 检测组件。请修复 Docker Desktop 的推理组件后刷新状态。")}</p>}
      <details className="model-choice-details"><summary>{t("模型 ID 与性能说明")}</summary><dl className="kv"><dt>{t("模型 ID")}</dt><dd className="mono">{selected.model_id}</dd><dt>{t("来源")}</dt><dd>{selected.repo}</dd></dl><p>{t("当前设备的速度与质量对比：未提供。参数规模、量化与下载大小不代表实测效果。")}</p></details>
      <ModelMemory reference={selected.memory_reference} unified={backend === 'mlx'}/>
      {state?.status === 'downloading' && state.total_bytes ? <progress aria-label={t("模型下载进度")} value={state.downloaded_bytes ?? 0} max={state.total_bytes}/> : null}
      <div className="stack"><button type="button" className="btn" onClick={() => void prepare()} disabled={!compatible || pending || ['queued', 'downloading', 'loading', 'unavailable'].includes(state?.status ?? 'unavailable')}>{pending ? t("正在请求…") : t("立即准备模型")}</button><button type="button" className="btn" onClick={() => setRefresh(n => n + 1)}>{t("刷新模型状态")}</button></div>
      </>}
    <ErrorNotice error={error}/>
  </section>;
}
