import { useEffect, useRef, useState } from 'react';
import { api, ApiError, etagFor } from '../api';
import { money } from '../domain';

type DispatchState = { generation: number; dispatch_disabled: boolean; maintenance: boolean;
  unknown_attempts: number; unknown_micro: number | null; inflight_requests: number };
function messageFor(reason: unknown) {
  const error = reason instanceof ApiError ? reason : undefined;
  if (error?.status === 412) return '外部请求状态已变化，当前选择已保留。请读取最新状态后重新设置。';
  if (error?.code === 'UNRESOLVED_BILLING_RISK') return '仍有可能已计费的未知请求。请读取最新状态，核对后确认风险并填写说明。';
  if (error?.code === 'MAINTENANCE') return '实例正在维护，暂不能更改外部请求设置。维护结束后可重新读取状态。';
  return '无法确认外部请求设置的最新状态。请重新读取后再操作。';
}

export function DispatchSettings({ onSaved }: { onSaved?: () => void }) {
  const [state, setState] = useState<DispatchState>();
  const [selected, setSelected] = useState<boolean | null>(null);
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
      setState(value); setSelected(null); setRisk(false); setReason(''); setError(''); setMustRead(false);
    }).catch(reason => { if (!controller.signal.aborted) { setError(messageFor(reason)); setMustRead(true); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [readVersion]);
  const allowed = selected ?? (state ? !state.dispatch_disabled : false);
  const riskRequired = allowed && state?.dispatch_disabled === true && state.unknown_attempts > 0;
  const changed = !!state && allowed === state.dispatch_disabled;
  const canSave = changed && !loading && !saving && !mustRead && !state?.maintenance && (!riskRequired || risk && !!reason.trim());
  async function save() {
    if (!canSave || running.current) return;
    running.current = true; setSaving(true); setError(''); setNotice('');
    try {
      const value = await api<DispatchState>('/settings/dispatch', { method: 'PATCH', etag: etagFor(state),
        body: { dispatch_disabled: !allowed, ...(riskRequired ? { accept_unknown_risk: risk, reason: reason.trim() } : {}) } });
      setState(value); setSelected(null); setRisk(false); setReason('');
      setNotice(value.dispatch_disabled ? '已暂停新的外部 API 请求。已发出的请求仍可能完成并计费。' : '已允许外部 API 请求。测试连接和翻译仍需各自确认外发。');
      onSaved?.();
    } catch (reason) { setError(messageFor(reason)); setMustRead(true); }
    finally { running.current = false; setSaving(false); }
  }
  return <section className="provider-dispatch" aria-labelledby="dispatch-title" id="external-api-requests">
    <div className="stack between"><h3 id="dispatch-title">外部 API 请求</h3>{state && <span className={`pill ${state.dispatch_disabled ? 'warn' : 'ready'}`}>{state.dispatch_disabled ? '已暂停' : '已允许'}</span>}</div>
    <label className="check"><input type="checkbox" checked={allowed} disabled={loading || saving || !state || state.maintenance} onChange={event => { setSelected(event.target.checked); setNotice(''); setRisk(false); setReason(''); }}/>允许外部 API 请求</label>
    <p className="muted small">保存后立即生效，重启后保留。关闭会阻止新的连接测试和翻译请求；已发出的请求仍可能完成并计费。开启后，已确认的排队任务可继续；暂停和结果未知的任务仍需单独处理。</p>
    {state?.maintenance && <p className="field-note">实例正在维护，此开关暂不可修改；维护结束后仍保持暂停，须在此手动开启。</p>}
    {state && state.unknown_attempts > 0 && <p className="field-note">仍有 {state.unknown_attempts} 个请求结果未知，可能已计费。保留的未知费用：{money(state.unknown_micro)}。开启不会清除费用或自动重试这些请求。</p>}
    {riskRequired && <><label className="check"><input type="checkbox" checked={risk} disabled={saving || loading || state?.maintenance} onChange={event => setRisk(event.target.checked)}/>我已核对未知请求，并接受保留其潜在费用后继续外发</label><label className="field">风险确认说明<textarea className="input" rows={2} maxLength={2000} value={reason} disabled={saving || loading || state?.maintenance} onChange={event => setReason(event.target.value)}/></label></>}
    {loading && <p className="muted small">正在读取外部请求状态…</p>}
    {error && <p role="alert" className="notice error-notice">{error}</p>}
    {notice && <p role="status" className="notice success-notice">{notice}</p>}
    <div className="stack"><button type="button" className="btn" disabled={!canSave} onClick={() => void save()}>{saving ? '正在保存…' : '保存外部请求设置'}</button><button type="button" className="btn" disabled={saving || loading} onClick={() => { setNotice(''); setReadVersion(value => value + 1); }}>读取外部请求状态</button></div>
  </section>;
}
