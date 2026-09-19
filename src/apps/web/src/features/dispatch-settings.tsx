import { useEffect, useRef, useState } from 'react';
import { api, ApiError, etagFor } from '../api';
import { money } from '../domain';

type DispatchState = { generation: number; dispatch_disabled: boolean; maintenance: boolean;
  unknown_attempts: number; unknown_micro: number | null; inflight_requests: number };
function messageFor(reason: unknown) {
  const error = reason instanceof ApiError ? reason : undefined;
  if (error?.status === 412) return '模型请求状态已变化，当前填写的说明已保留。请刷新状态后重新确认。';
  if (error?.code === 'UNRESOLVED_BILLING_RISK') return '仍有可能已计费的未知请求。请读取最新状态，核对后确认风险并填写说明。';
  if (error?.code === 'MAINTENANCE') return '实例正在维护，暂不能恢复模型请求。维护结束后可刷新状态。';
  return '无法确认模型请求的最新状态。请刷新状态后再操作。';
}

export function DispatchRecovery({ onSaved }: { onSaved?: () => void }) {
  const [state, setState] = useState<DispatchState>();
  const [risk, setRisk] = useState(false);
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [readVersion, setReadVersion] = useState(0);
  const [mustRead, setMustRead] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const running = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api<DispatchState>('/settings/dispatch', { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      if (typeof value.dispatch_disabled !== 'boolean' || !Number.isSafeInteger(value.generation)) throw new Error('Invalid dispatch settings');
      setState(value); setRisk(false); setReason(''); setError(''); setMustRead(false);
    }).catch(reason => { if (!controller.signal.aborted) { setError(messageFor(reason)); setMustRead(true); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [readVersion]);
  const riskRequired = state?.dispatch_disabled === true && state.unknown_attempts > 0;
  const canResume = state?.dispatch_disabled && !loading && !saving && !mustRead && !state.maintenance && (!riskRequired || risk && !!reason.trim());
  async function resume() {
    if (!canResume || running.current) return;
    running.current = true; setSaving(true); setError(''); setNotice('');
    try {
      const value = await api<DispatchState>('/settings/dispatch', { method: 'PATCH', etag: etagFor(state),
        body: { dispatch_disabled: false, ...(riskRequired ? { accept_unknown_risk: risk, reason: reason.trim() } : {}) } });
      setState(value); setRisk(false); setReason('');
      setNotice('已恢复模型请求。测试连接和翻译仍需各自确认。');
      onSaved?.();
    } catch (reason) { setError(messageFor(reason)); setMustRead(true); }
    finally { running.current = false; setSaving(false); }
  }
  const needsAttention = state && (state.dispatch_disabled || state.maintenance || state.unknown_attempts > 0);
  if (!needsAttention && !error && !notice) return null;
  return <section className="provider-dispatch" aria-labelledby="dispatch-title" id="model-request-status">
    <div className="stack between"><h3 id="dispatch-title">模型请求状态</h3>{state?.dispatch_disabled && <span className="pill warn">已暂停</span>}</div>
    {state?.dispatch_disabled && <p className="muted small">模型请求已暂停。恢复后，已确认的排队任务可继续；暂停和结果未知的任务仍需单独处理。</p>}
    {state?.maintenance && <p className="field-note">实例正在维护，暂不能恢复模型请求。维护结束后，请刷新状态并恢复。</p>}
    {state && state.unknown_attempts > 0 && <p className="field-note">仍有 {state.unknown_attempts} 个请求结果未知，可能已计费。保留的未知费用：{money(state.unknown_micro)}。恢复不会清除费用或自动重试这些请求。</p>}
    {riskRequired && <><label className="check"><input type="checkbox" checked={risk} disabled={saving || loading || state?.maintenance} onChange={event => setRisk(event.target.checked)}/>我已核对未知请求，并接受保留其潜在费用后继续外发</label><label className="field">风险确认说明<textarea className="input" rows={2} maxLength={2000} value={reason} disabled={saving || loading || state?.maintenance} onChange={event => setReason(event.target.value)}/></label></>}
    {loading && <p className="muted small">正在读取模型请求状态…</p>}
    {error && <p role="alert" className="notice error-notice">{error}</p>}
    {notice && <p role="status" className="notice success-notice">{notice}</p>}
    <div className="stack">{state?.dispatch_disabled && <button type="button" className="btn" disabled={!canResume} onClick={() => void resume()}>{saving ? '正在恢复…' : '恢复模型请求'}</button>}<button type="button" className="btn" disabled={saving || loading} onClick={() => { setNotice(''); setReadVersion(value => value + 1); }}>刷新请求状态</button></div>
  </section>;
}
