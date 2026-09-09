import { useRef, useState } from 'react';
import { api, ApiError, etagFor } from '../api';
import { ErrorNotice, Loading } from '../components';
import type { Provider, ProviderPrice } from '../types';
import { costControlEnabled, defaultTokenLimits } from './cost-control';
import { providerProtocols } from './provider-protocol';
import { ProviderConnection } from './provider-connection';
import { DispatchSettings } from './dispatch-settings';

type Fields = {
  endpoint: string; protocol: NonNullable<Provider['api_protocol']>; auth: NonNullable<Provider['auth_mode']>;
  model: string; version: string; inputPrice: string; cachedPrice: string; outputPrice: string;
  costControl: boolean; inputTokens: string; outputTokens: string; unitCharacters: string; includesReasoning: boolean;
};
const dollar = (value?: number | null) => value == null ? '' : String(value / 1_000_000);
const missingLabels: Record<string, string> = {
  endpoint: '完整请求地址', model_id: '模型 ID', api_key: 'API 密钥', api_protocol: '接口类型', auth_mode: '鉴权方式', api_version: 'Anthropic API 版本',
  max_input_tokens: '输入 token 上限', max_output_tokens: '输出 token 上限', max_unit_characters: '单元字符上限',
  price: '实际计费价格', 'price.input_micro_per_million': '输入价格', 'price.cached_input_micro_per_million': '缓存输入价格',
  'price.output_micro_per_million': '输出价格', 'price.output_includes_reasoning': '推理 token 计费确认',
  'price.currency': 'USD 计费币种', 'price.input_bound_rule': '输入用量计费口径',
};
const fromProvider = (value: Provider): Fields => ({
  endpoint: value.endpoint ?? '', protocol: value.api_protocol ?? 'responses', auth: value.auth_mode ?? providerProtocols[value.api_protocol ?? 'responses'].auth,
  model: value.model_id ?? '', version: value.api_version ?? (value.api_protocol === 'claude_messages' ? '2023-06-01' : ''), costControl: costControlEnabled(value), inputPrice: dollar(value.price?.input_micro_per_million),
  cachedPrice: dollar(value.price?.cached_input_micro_per_million), outputPrice: dollar(value.price?.output_micro_per_million),
  inputTokens: String(value.max_input_tokens ?? value.token_limits_defaults?.max_input_tokens ?? defaultTokenLimits.max_input_tokens),
  outputTokens: String(value.max_output_tokens ?? value.token_limits_defaults?.max_output_tokens ?? defaultTokenLimits.max_output_tokens),
  unitCharacters: String(value.max_unit_characters ?? value.token_limits_defaults?.max_unit_characters ?? defaultTokenLimits.max_unit_characters), includesReasoning: value.price?.output_includes_reasoning === true,
});
// Decimal strings avoid rounding away a micro-dollar during the UI conversion.
function micro(value: string): number | undefined {
  if (!value) return undefined;
  if (!/^\d+(?:\.\d{1,6})?$/.test(value)) return NaN;
  const [whole, fraction = ''] = value.split('.');
  const integer = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, '0'));
  return integer <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(integer) : NaN;
}
function endpointInvalid(value: string) {
  if (!value) return false;
  try {
    const url = new URL(value);
    return !['http:', 'https:'].includes(url.protocol) || !url.hostname || !!url.username || !!url.password
      || /[\s\\?#]/.test(value) || !url.pathname || url.pathname === '/' || url.port === '0';
  } catch { return true; }
}
function tokenInvalid(value: string, max: number) {
  return (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > max);
}
function saveError(reason: unknown) {
  const original = reason instanceof ApiError ? reason : undefined;
  const code = original?.code ?? 'PROVIDER_SAVE_FAILED';
  const message = original?.status === 412 ? '配置版本已变化。请读取最新配置并比较，当前非密钥输入已保留。'
    : code === 'PROVIDER_KEY_REBIND_REQUIRED' ? '服务地址或接口类型已变化，请重新输入密钥或明确清除已保存的密钥。'
    : code === 'PROVIDER_KEY_REQUIRED' ? '后端无法沿用外部密钥。请重新输入密钥，或明确清除后先保存未完成配置。'
    : original?.status === 0 ? '连接中断，保存结果尚不确定。请读取最新配置后再决定是否保存。'
    : original?.status === 409 ? '配置暂不能保存。请读取最新状态并核对配置。'
    : '配置未能保存，请检查服务地址、模型、价格和请求限制。输入的密钥已从表单清空。';
  // Never copy a server validation message/details that could echo a credential.
  return new ApiError(original?.status ?? 0, /^[A-Z0-9_]+$/.test(code) ? code : 'PROVIDER_SAVE_FAILED', message);
}

export function ProviderSettings({ provider, loading, error, reload, onSaved, onDispatchSaved }: {
  provider?: Provider; loading: boolean; error?: Error; reload: () => void; onSaved: (value: Provider) => void; onDispatchSaved?: () => void;
}) {
  return <section className="panel provider-panel" aria-labelledby="provider-title">
    <div className="stack between"><h2 id="provider-title">AI 服务</h2><span className="pill">兼容与原生接口</span></div>
    <p className="muted">设置翻译使用的服务地址与模型。保存只更新配置；开始翻译时仍需单独确认外发；预算与成本控制可以选择启用。</p>
    <DispatchSettings onSaved={onDispatchSaved}/>
    <ErrorNotice error={error} retry={reload}/>
    {loading && <Loading/>}
    {provider && !error && <ProviderForm initial={provider} onSaved={onSaved}/>}
  </section>;
}

function ProviderForm({ initial, onSaved }: { initial: Provider; onSaved: (value: Provider) => void }) {
  const [base, setBase] = useState(initial);
  const [fields, setFields] = useState(() => fromProvider(initial));
  const [apiKey, setApiKey] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError>();
  const [notice, setNotice] = useState('');
  const [refreshRequired, setRefreshRequired] = useState(false);
  const [latest, setLatest] = useState<Provider>();
  const [loadedVersion, setLoadedVersion] = useState(0);
  const running = useRef(false);
  const update = <K extends keyof Fields>(key: K, value: Fields[K]) => {
    setFields(old => ({ ...old, [key]: value })); setNotice('');
  };
  const protocol = providerProtocols[fields.protocol];
  function changeProtocol(value: Fields['protocol']) {
    if (value === fields.protocol) return;
    const selected = providerProtocols[value];
    setFields(old => ({ ...old, protocol: value, endpoint: selected.defaultEndpoint, model: selected.defaultModel,
      version: value === 'claude_messages' ? old.version || '2023-06-01' : old.version, auth: old.auth === 'none' ? 'none' : selected.auth }));
    setApiKey(''); setNotice('');
  }
  const rebind = base.has_api_key !== false && (fields.endpoint.trim() !== (base.endpoint ?? '') || fields.protocol !== (base.api_protocol ?? 'responses') || fields.auth !== (base.auth_mode ?? 'bearer'));
  const mustRebind = rebind && !apiKey && !clearKey;
  const invalidUrl = endpointInvalid(fields.endpoint.trim());
  const invalidPrice = [fields.inputPrice, fields.cachedPrice, fields.outputPrice].some(value => Number.isNaN(micro(value)));
  const invalidTokens = tokenInvalid(fields.inputTokens, 1_000_000) || tokenInvalid(fields.outputTokens, 1_000_000) || tokenInvalid(fields.unitCharacters, 10_000);
  const invalidKey = /[\r\n]/.test(apiKey) || apiKey.length > 8192;
  const invalidVersion = fields.protocol === 'claude_messages' && fields.version !== '' && !/^\d{4}-\d{2}-\d{2}$/.test(fields.version);
  const canSave = !pending && !refreshRequired && !latest && !mustRebind && !invalidUrl && !invalidPrice && !invalidTokens && !invalidKey && !invalidVersion && !!etagFor(base);
  function applyLatest(value: Provider, keepInput: boolean) {
    setLoadedVersion(version => version + 1);
    setBase(value); onSaved(value); setLatest(undefined); setRefreshRequired(false); setError(undefined); setApiKey('');
    if (!keepInput) { setFields(fromProvider(value)); setClearKey(false); }
  }
  async function readLatest() {
    if (running.current) return;
    running.current = true; setPending(true); setApiKey(''); setNotice('');
    try { setLatest(await api<Provider>('/settings/provider')); }
    catch (reason) { setError(saveError(reason)); }
    finally { running.current = false; setPending(false); }
  }
  async function save() {
    if (!canSave || running.current) return;
    running.current = true; setPending(true); setNotice(''); setError(undefined);
    const price: ProviderPrice = { currency: 'USD', input_bound_rule: 'utf8-byte-ceiling-v1' };
    if (fields.inputPrice !== '') price.input_micro_per_million = micro(fields.inputPrice);
    if (fields.cachedPrice !== '') price.cached_input_micro_per_million = micro(fields.cachedPrice);
    if (fields.outputPrice !== '') price.output_micro_per_million = micro(fields.outputPrice);
    if (fields.includesReasoning) price.output_includes_reasoning = true;
    const hasPrice = !!fields.inputPrice || !!fields.cachedPrice || !!fields.outputPrice || fields.includesReasoning;
    const profile = {
      provider: protocol.provider, endpoint: fields.endpoint.trim(), api_protocol: fields.protocol, auth_mode: fields.auth, model_id: fields.model.trim(),
      ...(fields.protocol === 'claude_messages' && fields.version ? { api_version: fields.version } : {}),
      cost_control_enabled: fields.costControl, enabled_pairs: base.enabled_pairs ?? [], semantic_review_enabled: base.semantic_review_enabled ?? false,
      ...(fields.inputTokens !== '' ? { max_input_tokens: Number(fields.inputTokens) } : {}),
      ...(fields.outputTokens !== '' ? { max_output_tokens: Number(fields.outputTokens) } : {}),
      ...(fields.unitCharacters !== '' ? { max_unit_characters: Number(fields.unitCharacters) } : {}),
      ...(hasPrice ? { price } : {}),
    };
    const key = fields.auth !== 'none' ? apiKey : '';
    setApiKey('');
    try {
      const value = await api<Provider>('/settings/provider', { method: 'PUT', etag: etagFor(base),
        body: { profile, ...(key ? { api_key: key } : {}), ...(clearKey ? { clear_api_key: true } : {}) } });
      applyLatest(value, false);
      setNotice(value.configured && value.dispatch_configuration_ready !== false ? 'AI 服务配置已保存。保存未请求模型；凭据有效性尚未通过模型调用验证。'
        : 'AI 服务配置已保存，仍等待配置。补全缺失字段后才能发起翻译。');
    } catch (reason) {
      const safe = saveError(reason); setError(safe);
      if ([0, 409, 412].includes(safe.status)) setRefreshRequired(true);
    } finally { running.current = false; setPending(false); }
  }
  const credentialLabel = base.config_source === 'external' && base.has_api_key == null ? '外部密钥状态未核验'
    : base.has_api_key === true ? '后端已保存密钥（不回显）' : '后端未保存密钥';
  const latestFields = latest ? fromProvider(latest) : undefined;
  const ready = base.configured && base.dispatch_configuration_ready !== false;
  const dirty = JSON.stringify(fields) !== JSON.stringify(fromProvider(base)) || !!apiKey || clearKey;
  return <form className="provider-form" onSubmit={event => { event.preventDefault(); void save(); }} autoComplete="off">
    <div className="provider-state stack"><span className={`pill ${ready ? 'ready' : 'warn'}`}>{ready ? (base.connection_test ? '配置完整 · 连接测试结果见下方' : '配置完整 · 尚未验证服务连接') : '等待配置'}</span><span className="small muted">{credentialLabel}</span></div>
    {base.missing_fields?.length ? <p className="field-note">待补全：{[...new Set(base.missing_fields.map(field => missingLabels[field] ?? '其他服务配置（请检查高级选项）'))].join('、')}</p> : null}
    <fieldset disabled={pending} className="provider-fields">
      <div className="two-cols">
        <label className="field">接口类型<select aria-label="接口类型" value={fields.protocol} onChange={event => changeProtocol(event.target.value as Fields['protocol'])}>{Object.entries(providerProtocols).map(([value, entry]) => <option key={value} value={value}>{entry.label}</option>)}</select></label>
        <label className="field">鉴权方式<select aria-label="鉴权方式" value={fields.auth} onChange={event => { update('auth', event.target.value as Fields['auth']); setApiKey(''); }}><option value={protocol.auth}>API 密钥（{protocol.keyLabel}）</option><option value="none">无鉴权（本地或无需密钥的服务）</option></select></label>
      </div>
      <label className="field">完整请求 URL<input className="input" type="url" value={fields.endpoint} onChange={event => { update('endpoint', event.target.value); setApiKey(''); }} maxLength={2048} placeholder={protocol.defaultEndpoint} autoCapitalize="none" spellCheck={false}/></label>
      <p className="field-note">切换接口类型会填入默认地址和模型，仍可手动修改。填写完整接口路径，不自动追加路由。地址从后端容器访问；localhost 指该容器自身。URL 不得包含密钥、用户名、查询参数或片段。</p>
      {invalidUrl && <p className="field-note error-text">请输入包含接口路径的 HTTP(S) 地址，不含鉴权信息、查询参数或片段。</p>}
      <label className="field">模型 ID<input className="input" value={fields.model} onChange={event => update('model', event.target.value)} maxLength={160} placeholder="服务实际提供的模型 ID" autoCapitalize="none" spellCheck={false}/></label>
      <label className="field">API 密钥<input className="input" type="password" value={apiKey} onChange={event => { setApiKey(event.target.value); setNotice(''); }} disabled={clearKey || fields.auth === 'none'} autoComplete="new-password" autoCapitalize="none" spellCheck={false} maxLength={8192} placeholder="留空保留后端现有密钥"/></label>
      <p className="field-note">密钥只提交到本实例的后端，不回显、不写入浏览器存储。保存后输入框清空；留空不会清除已有密钥。</p>
      <label className="check"><input type="checkbox" checked={clearKey} onChange={event => { setClearKey(event.target.checked); setApiKey(''); setNotice(''); }}/>清除已保存的密钥</label>
      {fields.auth === 'none' && <p className="field-note">已明确选择无鉴权：请求不发送 Authorization 或 API 密钥头。清除密钥与选择无鉴权是两个独立操作。</p>}
      {rebind && <p className="notice">服务地址或接口类型已变化，或已切换鉴权方式。请重新输入用于新配置的密钥，或明确清除已保存的密钥；旧密钥不会自动绑定到新配置。</p>}
      <label className="check"><input type="checkbox" checked={fields.costControl} onChange={event => update('costControl', event.target.checked)}/>启用预算与成本控制</label>
      <p className="field-note">保存后生效，仅用于采用新配置的请求。{fields.costControl ? '启用时须填写实际费率，并在外发前确认任务预算。' : '关闭时无需费率或任务预算，不限制金额；服务仍可能收费。已有价格保留，无法计算的费用不会显示成 0。'}</p>
      <details className="provider-advanced"><summary>高级选项：价格与请求限制</summary>
        {fields.protocol === 'claude_messages' && <><label className="field">Anthropic API 版本<input className="input" value={fields.version} onChange={event => update('version', event.target.value)} placeholder="2023-06-01" maxLength={10}/></label><p className="field-note">留空由后端使用 2023-06-01；自定义版本使用 YYYY-MM-DD 格式，并作为 anthropic-version 请求头发送。</p>{invalidVersion && <p className="field-note error-text">API 版本须为 YYYY-MM-DD 格式。</p>}</>}
        <p className="field-note">价格为可选配置，币种为 USD。启用成本控制时，须按服务实际费率填写；关闭时可留空。未知价格不按 0 处理，免费服务可明确填 0。</p>
        <div className="two-cols">
          <label className="field">输入价格（USD / 百万 token）<input className="input" inputMode="decimal" value={fields.inputPrice} onChange={event => update('inputPrice', event.target.value)}/></label>
          <label className="field">缓存输入价格（USD / 百万 token）<input className="input" inputMode="decimal" value={fields.cachedPrice} onChange={event => update('cachedPrice', event.target.value)}/></label>
          <label className="field">输出价格（USD / 百万 token）<input className="input" inputMode="decimal" value={fields.outputPrice} onChange={event => update('outputPrice', event.target.value)}/></label>
        </div>
        <label className="check"><input type="checkbox" checked={fields.includesReasoning} onChange={event => update('includesReasoning', event.target.checked)}/>我已核对输出费率适用于推理 token（如有）；费用按合并后的输出用量计算。</label>
        <div className="two-cols">
          <label className="field">单次输入 token 上限<input className="input" inputMode="numeric" value={fields.inputTokens} onChange={event => update('inputTokens', event.target.value)}/></label>
          <label className="field">单次输出 token 上限<input className="input" inputMode="numeric" value={fields.outputTokens} onChange={event => update('outputTokens', event.target.value)}/></label>
          <label className="field">单个翻译单元字符上限<input className="input" inputMode="numeric" value={fields.unitCharacters} onChange={event => update('unitCharacters', event.target.value)}/></label>
        </div>
        <p className="field-note">Token 上限范围为 1–1,000,000；单元字符上限范围为 1–10,000。请求限制始终生效，不等于金额上限。</p>
        <div className="stack"><button className="btn" type="button" onClick={() => { const limits = base.token_limits_defaults ?? defaultTokenLimits; setFields(old => ({ ...old, inputTokens: String(limits.max_input_tokens), outputTokens: String(limits.max_output_tokens), unitCharacters: String(limits.max_unit_characters) })); setNotice(''); }}>重置请求限制</button><button className="btn" type="button" onClick={() => { const saved = fromProvider(base); setFields(old => ({ ...old, inputTokens: saved.inputTokens, outputTokens: saved.outputTokens, unitCharacters: saved.unitCharacters })); setNotice(''); }}>撤销限额修改</button></div>
        <p className="field-note">重置只填入当前系统的三项默认限制，保存后生效；撤销恢复当前已保存的三项限制。服务地址、密钥、模型、价格和成本开关均保持不变。</p>
        {(invalidPrice || invalidTokens) && <p className="field-note error-text">价格须为非负数（最多六位小数）；请求限制须为范围内的整数。</p>}
      </details>
    </fieldset>
    <ErrorNotice error={error}/>
    {notice && <p role="status" className="notice success-notice">{notice}</p>}
    {latest && latestFields && <section className="notice" aria-label="配置版本比较"><h3>读取到的最新配置</h3><dl className="kv"><dt>服务地址</dt><dd>{latest.endpoint || '未填写'}</dd><dt>模型 ID</dt><dd>{latest.model_id || '未填写'}</dd><dt>接口 / 鉴权</dt><dd>{latest.api_protocol} / {latest.auth_mode}</dd>{latest.api_protocol === 'claude_messages' && <><dt>Anthropic API 版本</dt><dd>{latest.api_version || '2023-06-01（服务端默认）'}</dd></>}<dt>预算与成本控制</dt><dd>{latestFields.costControl ? '已启用' : '未启用'}</dd><dt>输入 / 缓存 / 输出价格</dt><dd>{latestFields.inputPrice || '未填写'} / {latestFields.cachedPrice || '未填写'} / {latestFields.outputPrice || '未填写'} USD / 百万 token</dd><dt>输入 / 输出上限</dt><dd>{latestFields.inputTokens || '未填写'} / {latestFields.outputTokens || '未填写'} token</dd><dt>单元字符上限</dt><dd>{latestFields.unitCharacters || '服务端默认'}</dd><dt>推理用量计费</dt><dd>{latestFields.includesReasoning ? '已确认包含' : '未确认'}</dd><dt>已启用语言对</dt><dd>{latest.enabled_pairs?.map(pair => pair.join(' → ')).join('；') || '无'}</dd></dl><p>比较后选择重新加载全部字段，或保留当前非密钥输入并采用最新版本。密钥需要时请重新输入。</p><div className="stack"><button className="btn" type="button" onClick={() => applyLatest(latest, false)}>使用最新配置</button><button className="btn" type="button" onClick={() => applyLatest(latest, true)}>保留输入并采用最新版本</button></div></section>}
    <div className="stack provider-actions"><button className="btn primary" type="submit" disabled={!canSave}>{pending ? '正在处理配置…' : '保存 AI 服务配置'}</button><button className="btn" type="button" disabled={pending} onClick={() => void readLatest()}>读取最新配置</button>
      <ProviderConnection key={`${base.profile_hash}-${loadedVersion}`} provider={base} disabled={pending || refreshRequired || !!latest} dirty={dirty} onResult={value => setBase(old => ({ ...old, connection_test: value, connection_test_has_unknown: old.connection_test_has_unknown || value.status === 'outcome_unknown' }))}/>
    </div>
    {!etagFor(base) && <p className="field-note">服务端未提供配置版本，暂不能保存。请重新读取配置。</p>}
    <p className="muted small section-title">配置、费率、提示词与隐私版本由系统管理。更换配置后，新翻译任务须重新确认服务地址和外发范围；启用成本控制时另确认预算。</p>
  </form>;
}
