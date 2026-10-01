import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorNotice } from '../components';

type LocalModel = { id: string; label: string; model_id: string; family: string; family_label: string;
  parameter_size: string; bits: number; quantization: string; format: string; runtime: string; repo: string;
  revision: string; download_bytes: number; inference_backends?: string[]; default_backend?: string;
  backend_states?: Record<string, ModelState>; status?: string; downloaded_bytes?: number; total_bytes?: number; code?: string };
type ModelState = { status?: string; downloaded_bytes?: number; total_bytes?: number; code?: string };
type Choice = { family: string; size: string; format: string; model: string; backend: string };
const empty: Choice = { family: '', size: '', format: '', model: '', backend: '' };
const inferenceLabels: Record<string, string> = { 'llama.cpp': 'llama.cpp', vllm: 'vLLM（CUDA）', mlx: 'vLLM Metal（MLX）' };
const sizeOf = (model: LocalModel) => `${model.parameter_size} · ${model.quantization.startsWith('BF') ? model.quantization : `Q${model.bits}`}`;
const labels: Record<string, string> = { ready: '已下载', not_downloaded: '首次使用时下载', downloading: '正在下载',
  loading: '正在加载', failed: '准备失败，可重试', unavailable: '本地模型服务未就绪' };
const backendLabels: Record<string, string> = { LOCAL_GGUF_UNAVAILABLE: 'llama.cpp 后端未就绪',
  LOCAL_VLLM_UNAVAILABLE: 'vLLM 后端未就绪', LOCAL_MLX_UNAVAILABLE: 'MLX 后端未就绪',
  LOCAL_CUDA_PROBE_MISSING: 'Docker Runner 缺少 CUDA 检测组件',
  LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED: '当前 Runner 部署未提供 vLLM 后端',
  LOCAL_MODEL_BACKEND_UNSUPPORTED: '当前模型或部署不支持此推理后端' };

export function LocalModels({ value, backend, onChange, active, onAvailabilityChange }: {
  value: string; backend: string; onChange: (model: string, backend: string) => void; active: boolean; onAvailabilityChange: (available: boolean) => void;
}) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [choice, setChoice] = useState<Choice>(empty);
  const [remembered, setRemembered] = useState<Record<string, Choice>>({});
  const [modelBackends, setModelBackends] = useState<Record<string, string>>({});
  const [error, setError] = useState<Error>();
  const [catalogCode, setCatalogCode] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    let timer: number;
    const controller = new AbortController();
    const read = async () => {
      try { const result = await api<{ models: LocalModel[]; code?: string }>('/settings/local-models', { signal: controller.signal });
        if (alive) { setModels(result.models); setCatalogCode(result.code ?? ''); setError(undefined); }
      } catch (reason) { if (alive) setError(reason as Error); }
      finally { if (alive) timer = window.setTimeout(() => void read(), 5000); }
    };
    void read();
    return () => { alive = false; controller.abort(); window.clearTimeout(timer); };
  }, [active, refresh]);
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
  return <section className="local-model-settings" aria-label="本地翻译模型" hidden={!active}>
    <label className="field">模型系列<select aria-label="模型系列" value={choice.family} onChange={event => changeFamily(event.target.value)}>
      <option value="">请选择模型系列</option>
      {families.map(([family, label]) => <option key={family} value={family}>{label}</option>)}
    </select></label>
    <label className="field">参数规模与量化<select aria-label="参数规模与量化" value={choice.size} onChange={event => changeSize(event.target.value)} disabled={!choice.family}>
      <option value="">请选择参数规模与量化</option>
      {sizes.map(size => <option key={size} value={size}>{size}</option>)}
    </select></label>
    <label className="field">模型格式<select aria-label="模型格式" value={choice.format} onChange={event => changeFormat(event.target.value)} disabled={!choice.size}>
      <option value="">请选择格式</option>
      {formats.map(format => <option key={format} value={format}>{format === 'mlx' ? 'MLX' : format === 'gguf' ? 'GGUF' : 'Safetensors'}</option>)}
    </select></label>
    <label className="field">具体模型 ID<select aria-label="具体模型 ID" value={selected?.model_id ?? ''} onChange={event => changeModel(event.target.value)} disabled={!choice.format}>
      <option value="">请选择模型 ID</option>
      {finalModels.map(model => <option key={model.id} value={model.model_id}>{model.repo} · {model.id}</option>)}
    </select></label>
    <label className="field">推理后端<select aria-label="推理后端" value={selected ? selectedBackend : ''} onChange={event => changeBackend(event.target.value)} disabled={!selected}>
      <option value="">请选择推理后端</option>
      {backendOptions.map(option => <option key={option} value={option}>{inferenceLabels[option] ?? option}</option>)}
      {selected && selectedBackend && !compatible && <option value={selectedBackend}>已保存后端（当前模型或部署不支持）</option>}
    </select></label>
    {selected && !compatible && <p className="field-note error-text">所选后端与当前模型或部署不兼容，请选择支持的推理后端。</p>}
    {selected?.format === 'gguf' && !backendOptions.includes('vllm') && <p className="field-note">此模型当前通过 llama.cpp 接入。vLLM 的 GGUF 加载适配尚未接入。</p>}
    {value && !selected && <p className="field-note error-text">已保存的模型在当前部署中不可用。请选择当前后端提供的模型。</p>}
    {catalogCode === 'LOCAL_MODEL_SERVICE_UNAVAILABLE' && <p className="field-note">本地翻译服务未启动或无法连接，仍可选择和保存模型。准备模型和翻译前，请在部署中启用本地翻译服务。</p>}
    {!models.length && <p className="field-note">当前部署没有声明受平台与硬件支持的本地翻译格式与后端。MLX 仅适用于 Apple Silicon macOS；CUDA vLLM 需要受支持的 NVIDIA GPU 和 Linux／WSL2 部署。</p>}
    {selected && <><p className="local-model-status" role="status">{!compatible ? backendLabels.LOCAL_MODEL_BACKEND_UNSUPPORTED : backendLabels[state?.code ?? ''] ?? labels[state?.status ?? 'unavailable'] ?? '状态待刷新'} · {selected.format.toUpperCase()} {selected.quantization} · 下载约 {(selected.download_bytes / 1e9).toFixed(1)} GB</p>
      {state?.code === 'LOCAL_CUDA_PROBE_MISSING' && <p className="field-note">Docker Model Runner 已启用，但缺少 GPU 检测组件。请修复 Docker Desktop 的推理组件后刷新状态。</p>}
      {state?.code === 'LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED' && <p className="field-note">这台设备可通过 Linux／WSL2 的 CUDA vLLM 部署运行 Safetensors；当前连接的 Runner 没有提供该后端。启用 Runner 开关不会自动接入另一种部署。</p>}
      <p className="local-model-id mono">{selected.model_id}</p>
      {state?.status === 'downloading' && state.total_bytes ? <progress aria-label="模型下载进度" value={state.downloaded_bytes ?? 0} max={state.total_bytes}/> : null}
      <div className="stack"><button type="button" className="btn" onClick={() => void prepare()} disabled={!compatible || pending || ['downloading', 'loading', 'unavailable'].includes(state?.status ?? 'unavailable')}>{pending ? '正在请求…' : '立即准备模型'}</button><button type="button" className="btn" onClick={() => setRefresh(n => n + 1)}>刷新模型状态</button></div>
      </>}
    <details className="settings-details"><summary>本地模型说明</summary>
      <p>通过 Docker Model Runner 在本机翻译，无需密钥。首次使用或明确准备时下载所选模型；切换格式不会自动下载。</p>
      <p>推理后端按具体模型的兼容性及部署的平台与硬件能力提供，安装和模型准备状态另行显示。切换模型会恢复该模型的后端选择，保存配置不会自动下载或测试。资源不足时不会自动换后端、模型或转用云端。本地模型不执行语义评审。</p>
      {selected && <p className="mono">{selected.repo}<br/>{selected.revision}</p>}
    </details>
    <ErrorNotice error={error}/>
  </section>;
}
