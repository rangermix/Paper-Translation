import { useEffect, useRef, useState } from 'react';
import { api, ApiError, etagFor } from '../api';
import { Modal } from '../components';
import type { Provider, ProviderConnectionTest } from '../types';
import { costControlEnabled } from './cost-control';
import { providerProtocols } from './provider-protocol';

const activeStates = ['pending', 'running', 'paused', 'waiting_config', 'waiting_budget'];
const explanations: Record<string, string> = {
  PROVIDER_AUTH: '密钥未通过认证。请检查 API 密钥，重新保存后再测试。',
  PROVIDER_FORBIDDEN: '服务拒绝访问。请检查密钥权限和模型访问权限。',
  PROVIDER_ENDPOINT_OR_MODEL: '接口路径或模型不存在。请核对完整 URL 和模型 ID。',
  PROVIDER_REQUEST_REJECTED: '服务拒绝了请求。请核对接口类型、URL、模型和 API 版本是否匹配。',
  PROVIDER_CONNECT: '无法连接服务。请检查后端容器的网络和完整 URL。',
  PROVIDER_RATE_LIMIT: '服务限流或额度不足。请核对服务商配额后再手动测试。',
  PROVIDER_MODEL_MISMATCH: '服务返回的模型与配置不匹配。请填写服务实际返回的模型 ID。',
  PROVIDER_TRUNCATED: '服务已响应，但测试输出未完整结束。模型可能需要更多输出或推理 token。',
  PROVIDER_REFUSAL: '服务已响应，但拒绝了固定测试请求。',
  PROVIDER_CONFIG: '服务配置不可用。请核对模型、接口和已保存的密钥。',
  PROVIDER_PROFILE_STALE: '配置已变化。请读取最新配置后重新确认测试。',
  PRECONDITION_FAILED: '配置版本已变化。请读取最新配置后重新确认测试。',
  PROVIDER_TEST_LIMITS: '当前请求限制不足以容纳测试。请检查高级选项中的 token 上限。',
  PROVIDER_TEST_IN_PROGRESS: '已有连接测试尚未结束。请读取最新配置查看状态。',
  PROVIDER_TEST_INTERRUPTED: '测试被中断，未自动重新发送。请检查任务状态后再手动测试。',
  DUPLICATE_CHARGE_CONFIRMATION_REQUIRED: '上次测试结果未知。请读取最新配置并确认重复计费风险。',
  BUDGET_PAUSED: '测试预算或实例剩余额度不足。请核对预算与费率。',
  DISPATCH_DISABLED: '模型请求已暂停，请刷新本页，在暂停提示中恢复模型请求后再测试连接。',
  MAINTENANCE: '实例正在维护，暂不能发送测试。',
  INSTANCE_CONCURRENCY_LIMIT: '实例正在处理其他请求。请稍后手动测试。',
  USAGE_MISSING: '服务已响应，但用量无法核算。请核对服务商记录。',
};
function description(code?: string | null) {
  return explanations[code ?? ''] ?? '测试未通过。请检查接口类型、完整 URL、模型及结构化输出支持。';
}

export function ProviderConnection({ provider, disabled, dirty, onResult }: {
  provider: Provider; disabled: boolean; dirty: boolean; onResult: (value: ProviderConnectionTest) => void;
}) {
  const [result, setResult] = useState(provider.connection_test);
  const [confirm, setConfirm] = useState(false);
  const [sending, setSending] = useState(false);
  const [budget, setBudget] = useState('');
  const [risk, setRisk] = useState(false);
  const [message, setMessage] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [readVersion, setReadVersion] = useState(0);
  const running = useRef(false);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;
  const active = !!result && activeStates.includes(result.status);
  const local = provider.api_protocol === 'local_translation';
  const controlled = costControlEnabled(provider);
  const unknown = result?.status === 'outcome_unknown';
  const riskRequired = unknown || provider.connection_test_has_unknown === true;
  const budgetMicro = /^\d+(?:\.\d{1,6})?$/.test(budget) ? Math.round(Number(budget) * 1_000_000) : NaN;
  const canTest = !disabled && !dirty && !sending && !active && !uncertain && !!etagFor(provider)
    && !!provider.profile_hash && !!provider.configured && provider.dispatch_configuration_ready !== false;

  useEffect(() => {
    if (!result?.id || !active) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api<ProviderConnectionTest>(`/settings/provider/test/${encodeURIComponent(result!.id)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (value.profile_hash !== provider.profile_hash) { setMessage('配置已变化，请读取最新配置。'); return; }
        setResult(value); onResultRef.current(value); setMessage('');
        if (activeStates.includes(value.status)) timer = setTimeout(() => void poll(), 1000);
      } catch {
        if (!controller.signal.aborted) setMessage('暂时无法读取测试结果。后台测试会继续；读取状态不会重新发送请求。');
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [result?.id, active, provider.profile_hash, readVersion]);

  async function send() {
    if (running.current || !canTest || (riskRequired && !risk) || (controlled && (!Number.isSafeInteger(budgetMicro) || budgetMicro <= 0))) return;
    running.current = true; setSending(true); setConfirm(false); setMessage('');
    try {
      const value = await api<ProviderConnectionTest>('/settings/provider/test', { method: 'POST', etag: etagFor(provider),
        body: { profile_hash: provider.profile_hash, external_processing_confirmed: true,
          duplicate_charge_risk_confirmed: risk, ...(controlled ? { budget_micro: budgetMicro } : {}) } });
      setResult(value); onResultRef.current(value);
    } catch (reason) {
      const error = reason instanceof ApiError ? reason : undefined;
      if (!error || error.status === 0 || error.status >= 500 || error.code === 'INVALID_RESPONSE') {
        setUncertain(true); setMessage('测试提交结果尚不确定，可能已发送。请读取最新配置查看后台测试，勿立即重复发送。');
      } else setMessage(description(error.code));
    } finally { running.current = false; setSending(false); }
  }

  return <div className="provider-connection">
    <button className="btn" type="button" disabled={!canTest} onClick={() => { setRisk(false); setConfirm(true); }}>
      {sending ? '正在提交测试…' : active ? '正在测试连接…' : local ? '测试本地翻译模型' : '测试 API 连接 / 密钥'}
    </button>
    {dirty && <p className="field-note">请先保存当前修改，再测试连接。</p>}
    {message && <p role="alert" className="notice error-notice">{message}{active && <button className="btn sm" type="button" onClick={() => setReadVersion(value => value + 1)}>读取测试状态</button>}</p>}
    {result && <div role={['failed', 'outcome_unknown'].includes(result.status) ? 'alert' : 'status'} className={`notice ${result.status === 'succeeded' ? 'success-notice' : ''}`}>
      <strong>{result.status === 'succeeded' ? '连接测试通过：服务已接受请求并返回有效结果。'
        : active ? '正在测试已保存的配置，请稍候…'
        : unknown ? '测试结果未知，可能已计费；不会自动重试。'
        : result.status === 'cancelled' ? '测试已取消。已发送的请求仍可能计费。' : description(result.code)}</strong>
      {unknown && result.code && result.code !== 'OUTCOME_UNKNOWN' && <p>{description(result.code)}</p>}
      {result.completed_at && <p className="small muted">上次测试：{new Date(result.completed_at).toLocaleString()}{result.elapsed_ms != null ? ` · ${(result.elapsed_ms / 1000).toFixed(2)} 秒` : ''}</p>}
      {!active && <p className="small muted">费用：{result.actual_micro == null || unknown ? '未计算' : `USD ${(result.actual_micro / 1_000_000).toFixed(6)}`}</p>}
      <a className="small" href={`#/jobs/${encodeURIComponent(result.id)}`}>查看测试任务</a>
    </div>}
    {confirm && <Modal title={local ? '测试本地翻译模型' : '测试 API 连接 / 密钥'} onClose={() => setConfirm(false)}>
      {local ? <p>按需下载已选模型并在本机翻译固定测试文本 <code>Hello.</code>，不发送论文内容。</p> : <p>向以下已保存的服务发送一次固定测试文本 <code>Hello.</code> 和结构化输出要求，检查连接、鉴权及模型响应。使用后端保存的密钥，不发送论文内容。</p>}
      <dl className="kv"><dt>接口</dt><dd>{providerProtocols[provider.api_protocol ?? 'responses'].label}</dd><dt>服务地址</dt><dd>{provider.endpoint}</dd><dt>模型</dt><dd>{provider.model_id}</dd></dl>
      <p className="field-note">本次输入上限 {Math.min(provider.max_input_tokens ?? 32768, 8192)} token，输出上限 {Math.min(provider.max_output_tokens ?? 8192, 256)} token。{local ? '测试在本机运行。' : '服务可能收费；'}测试通过仅代表本次连接和响应有效。</p>
      {controlled ? <label className="field">本次测试预算（USD）<input className="input" inputMode="decimal" value={budget} onChange={event => setBudget(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') event.preventDefault(); }} placeholder="例如 0.10"/></label>
        : <p className="field-note">成本控制未启用，本次不设金额预算；未知费用显示为未计算。</p>}
      {riskRequired && <label className="check"><input type="checkbox" checked={risk} onChange={event => setRisk(event.target.checked)}/>我接受再次测试可能重复计费的风险</label>}
      <div className="stack"><button className="btn primary" type="button" disabled={!canTest || (riskRequired && !risk) || (controlled && (!Number.isSafeInteger(budgetMicro) || budgetMicro <= 0))} onClick={() => void send()}>确认并发送一次测试</button><button className="btn" type="button" onClick={() => setConfirm(false)}>取消</button></div>
    </Modal>}
  </div>;
}
