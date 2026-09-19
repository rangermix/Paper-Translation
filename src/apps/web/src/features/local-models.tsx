import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorNotice } from '../components';

type LocalModel = { id: string; label: string; model_id: string; runtime: string; bits: number; repo: string;
  revision: string; download_bytes: number; status?: string; downloaded_bytes?: number; total_bytes?: number; code?: string };
const labels: Record<string, string> = { ready: '已下载', not_downloaded: '首次使用时下载', downloading: '正在下载',
  loading: '正在加载', failed: '准备失败，可重试', unavailable: '本地模型服务未就绪' };

export function LocalModels({ value, onChange }: { value: string; onChange: (model: string) => void }) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [error, setError] = useState<Error>();
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: number;
    const controller = new AbortController();
    const read = async () => {
      try { const result = await api<{ models: LocalModel[] }>('/settings/local-models', { signal: controller.signal });
        if (active) { setModels(result.models); setError(undefined); }
      } catch (reason) { if (active) setError(reason as Error); }
      finally { if (active) timer = window.setTimeout(() => void read(), 5000); }
    };
    void read();
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, [refresh]);
  const selected = models.find(model => model.model_id === value);
  async function prepare() {
    if (!selected || pending) return;
    setPending(true); setError(undefined);
    try { await api(`/settings/local-models/${selected.id}/prepare`, { method: 'POST', body: {} }); setRefresh(n => n + 1); }
    catch (reason) { setError(reason as Error); }
    finally { setPending(false); }
  }
  return <section className="local-model-settings" aria-label="本地翻译模型">
    <label className="field">本地翻译模型<select value={value} onChange={event => onChange(event.target.value)}>
      <option value="">请选择模型</option>
      {models.map(model => <option key={model.id} value={model.model_id}>{model.label}</option>)}
    </select></label>
    {selected && <><p className="local-model-status" role="status">{labels[selected.status ?? 'unavailable'] ?? '状态待刷新'} · MLX {selected.bits} bit · 下载约 {(selected.download_bytes / 1e9).toFixed(1)} GB</p>
      {selected.status === 'downloading' && selected.total_bytes ? <progress aria-label="模型下载进度" value={selected.downloaded_bytes ?? 0} max={selected.total_bytes}/> : null}
      <div className="stack"><button type="button" className="btn" onClick={() => void prepare()} disabled={pending || ['downloading', 'loading'].includes(selected.status ?? '')}>{pending ? '正在请求…' : '立即准备模型'}</button><button type="button" className="btn" onClick={() => setRefresh(n => n + 1)}>刷新模型状态</button></div>
      </>}
    <details className="settings-details"><summary>本地模型说明</summary>
      <p>通过 Docker Model Runner 在本机翻译，无需密钥。首次使用或准备时下载所选模型。</p>
      <p>较大模型需要更多统一内存；资源不足时不会自动换模型或转用云端。本地模型不执行语义评审。</p>
      {selected && <p className="mono">{selected.repo}<br/>{selected.revision}</p>}
    </details>
    <ErrorNotice error={error}/>
  </section>;
}
