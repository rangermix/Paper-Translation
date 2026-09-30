import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorNotice } from '../components';

type LocalModel = { id: string; label: string; model_id: string; family: string; family_label: string;
  parameter_size: string; bits: number; quantization: string; format: string; runtime: string; repo: string;
  revision: string; download_bytes: number; status?: string; downloaded_bytes?: number; total_bytes?: number; code?: string };
type Choice = { family: string; size: string; format: string; model: string };
const empty: Choice = { family: '', size: '', format: '', model: '' };
const sizeOf = (model: LocalModel) => `${model.parameter_size} · ${model.quantization.startsWith('BF') ? model.quantization : `Q${model.bits}`}`;
const labels: Record<string, string> = { ready: '已下载', not_downloaded: '首次使用时下载', downloading: '正在下载',
  loading: '正在加载', failed: '准备失败，可重试', unavailable: '本地模型服务未就绪' };
const backendLabels: Record<string, string> = { LOCAL_GGUF_UNAVAILABLE: 'llama.cpp 后端未就绪',
  LOCAL_VLLM_UNAVAILABLE: 'vLLM 后端未就绪', LOCAL_MLX_UNAVAILABLE: 'MLX 后端未就绪',
  LOCAL_CUDA_PROBE_MISSING: 'Docker Runner 缺少 CUDA 检测组件',
  LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED: '当前 Runner 部署未提供 vLLM 后端' };

export function LocalModels({ value, onChange, active, onAvailabilityChange }: {
  value: string; onChange: (model: string) => void; active: boolean; onAvailabilityChange: (available: boolean) => void;
}) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [choice, setChoice] = useState<Choice>(empty);
  const [remembered, setRemembered] = useState<Record<string, Choice>>({});
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
  useEffect(() => {
    if (selected) setChoice({ family: selected.family, size: sizeOf(selected), format: selected.format, model: selected.model_id });
  }, [selected?.model_id]);
  useEffect(() => onAvailabilityChange(!!selected), [onAvailabilityChange, selected]);
  const families = [...new Map(models.map(model => [model.family, model.family_label])).entries()];
  const sizes = [...new Set(models.filter(model => model.family === choice.family).map(sizeOf))];
  const formats = [...new Set(models.filter(model => model.family === choice.family && sizeOf(model) === choice.size).map(model => model.format))];
  const finalModels = models.filter(model => model.family === choice.family && sizeOf(model) === choice.size && model.format === choice.format);
  function remember() {
    if (!choice.family) return;
    setRemembered(old => ({ ...old,
      [choice.family]: choice,
      ...(choice.size ? { [`${choice.family}|${choice.size}`]: choice } : {}),
      ...(choice.format ? { [`${choice.family}|${choice.size}|${choice.format}`]: choice } : {}),
    }));
  }
  function changeFamily(family: string) {
    remember();
    const next = remembered[family] ?? { ...empty, family };
    setChoice(next); onChange(next.model);
  }
  function changeSize(size: string) {
    remember();
    const next = remembered[`${choice.family}|${size}`] ?? { ...empty, family: choice.family, size };
    setChoice(next); onChange(next.model);
  }
  function changeFormat(format: string) {
    remember();
    const next = remembered[`${choice.family}|${choice.size}|${format}`] ?? { ...empty, family: choice.family, size: choice.size, format };
    setChoice(next); onChange(next.model);
  }
  async function prepare() {
    if (!selected || pending) return;
    setPending(true); setError(undefined);
    try { await api(`/settings/local-models/${selected.id}/prepare`, { method: 'POST', body: {} }); setRefresh(n => n + 1); }
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
    <label className="field">具体模型 ID<select aria-label="具体模型 ID" value={selected?.model_id ?? ''} onChange={event => { setChoice(old => ({ ...old, model: event.target.value })); onChange(event.target.value); }} disabled={!choice.format}>
      <option value="">请选择模型 ID</option>
      {finalModels.map(model => <option key={model.id} value={model.model_id}>{model.repo} · {model.id}</option>)}
    </select></label>
    {value && !selected && <p className="field-note error-text">已保存的模型在当前部署中不可用。请选择当前后端提供的模型。</p>}
    {catalogCode === 'LOCAL_MODEL_SERVICE_UNAVAILABLE' && <p className="field-note">本地翻译服务未启动或无法连接，仍可选择和保存模型。准备模型和翻译前，请在部署中启用本地翻译服务。</p>}
    {!models.length && <p className="field-note">当前部署没有声明受平台与硬件支持的本地翻译格式。GGUF 使用 llama.cpp；Safetensors 使用受支持的 NVIDIA CUDA vLLM；MLX 仅适用于 Apple Silicon macOS。</p>}
    {selected && <><p className="local-model-status" role="status">{backendLabels[selected.code ?? ''] ?? labels[selected.status ?? 'unavailable'] ?? '状态待刷新'} · {selected.format.toUpperCase()} {selected.quantization} · 下载约 {(selected.download_bytes / 1e9).toFixed(1)} GB</p>
      {selected.code === 'LOCAL_CUDA_PROBE_MISSING' && <p className="field-note">Docker Model Runner 已启用，但缺少 GPU 检测组件。请修复 Docker Desktop 的推理组件后刷新状态。</p>}
      {selected.code === 'LOCAL_VLLM_DEPLOYMENT_UNSUPPORTED' && <p className="field-note">这台设备可通过 Linux／WSL2 的 CUDA vLLM 部署运行 Safetensors；当前连接的 Runner 没有提供该后端。启用 Runner 开关不会自动接入另一种部署。</p>}
      <p className="local-model-id mono">{selected.model_id}</p>
      {selected.status === 'downloading' && selected.total_bytes ? <progress aria-label="模型下载进度" value={selected.downloaded_bytes ?? 0} max={selected.total_bytes}/> : null}
      <div className="stack"><button type="button" className="btn" onClick={() => void prepare()} disabled={pending || ['downloading', 'loading', 'unavailable'].includes(selected.status ?? '')}>{pending ? '正在请求…' : '立即准备模型'}</button><button type="button" className="btn" onClick={() => setRefresh(n => n + 1)}>刷新模型状态</button></div>
      </>}
    <details className="settings-details"><summary>本地模型说明</summary>
      <p>通过 Docker Model Runner 在本机翻译，无需密钥。首次使用或明确准备时下载所选模型；切换格式不会自动下载。</p>
      <p>GGUF 使用 llama.cpp，Safetensors 使用受支持的 NVIDIA CUDA vLLM，MLX 使用 Apple Silicon macOS 上的 MLX 后端。格式按部署的平台与硬件能力提供，后端安装和模型准备状态另行显示。资源不足时不会自动换模型或转用云端。本地模型不执行语义评审。</p>
      {selected && <p className="mono">{selected.repo}<br/>{selected.revision}</p>}
    </details>
    <ErrorNotice error={error}/>
  </section>;
}
