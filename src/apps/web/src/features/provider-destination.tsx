import type { Provider } from '../types';
import { providerProtocols } from './provider-protocol';

export function ProviderDestination({ profile }: { profile?: Provider }) {
  const protocol = profile?.api_protocol ? providerProtocols[profile.api_protocol] : undefined;
  return <section className="notice provider-destination" aria-label="本次翻译服务">
    <strong>本次翻译服务</strong>
    <dl className="kv"><dt>服务地址</dt><dd><code>{profile?.endpoint || '服务端未提供地址，请重新读取配置'}</code></dd>
      <dt>模型</dt><dd>{profile?.model_display_name || profile?.model_id || '未配置'}</dd></dl>
    <details className="technical-details"><summary>连接技术详情</summary><dl className="kv">
      {profile?.model_display_name && <><dt>模型 ID</dt><dd className="mono">{profile.model_id || '未配置'}</dd></>}
      <dt>接口类型</dt><dd>{protocol?.label ?? '未提供'}</dd>
      <dt>鉴权方式</dt><dd>{profile?.auth_mode === 'none' ? '无鉴权' : profile?.auth_mode === 'bearer' ? 'Bearer 密钥' : profile?.auth_mode === 'api_key' && protocol?.auth === 'api_key' ? `${protocol.keyLabel} 密钥` : '未提供'}</dd>
      {profile?.api_protocol === 'claude_messages' && <><dt>Anthropic API 版本</dt><dd>{profile.api_version || '2023-06-01（服务端默认）'}</dd></>}</dl></details>
  </section>;
}
