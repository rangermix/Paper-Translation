import type { Provider } from '../types';
import { providerProtocols } from './provider-protocol';

export function privacyNote(profile?: Pick<Provider, 'api_protocol' | 'privacy_note'>) {
  if (profile?.privacy_note && !profile.privacy_note.startsWith('Only confirmed text and bounded context')) return profile.privacy_note;
  return profile?.api_protocol === 'claude_messages'
    ? '只发送本次授权的必要文本与有限上下文。Claude Messages 没有关闭服务端存储的请求选项；数据保留由所选服务决定，不主动创建提示词缓存。'
    : '只发送本次授权的必要文本与有限上下文。请求关闭服务端存储选项，但这不保证服务商完全不保留数据。';
}

export function ProviderDestination({ profile }: { profile?: Provider }) {
  const protocol = profile?.api_protocol ? providerProtocols[profile.api_protocol] : undefined;
  return <section className="notice provider-destination" aria-label="本次请求目的地">
    <strong>本次请求目的地</strong>
    <dl className="kv"><dt>完整请求地址</dt><dd><code>{profile?.endpoint || '服务端未提供地址，请重新读取配置'}</code></dd>
      <dt>接口类型</dt><dd>{protocol?.label ?? '未提供'}</dd>
      <dt>模型 ID</dt><dd>{profile?.model_id || '未配置'}</dd>
      <dt>鉴权方式</dt><dd>{profile?.auth_mode === 'none' ? '无鉴权，不发送 Authorization 或 API 密钥头' : profile?.auth_mode === 'bearer' ? 'Bearer 密钥（由后端使用，不回显）' : profile?.auth_mode === 'api_key' && protocol?.auth === 'api_key' ? `${protocol.keyLabel} 密钥（由后端使用，不回显）` : '未提供'}</dd>
      {profile?.api_protocol === 'claude_messages' && <><dt>Anthropic API 版本</dt><dd>{profile.api_version || '2023-06-01（服务端默认）'}</dd></>}</dl>
    <p className="field-note">必要文本将发送到该地址。服务的数据保留规则由服务提供者决定；配置或来源变更后须重新确认。</p>
  </section>;
}
