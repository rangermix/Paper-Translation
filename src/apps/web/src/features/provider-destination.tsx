import { t } from '../i18n';
import type { Provider } from '../types';
import { providerProtocols } from './provider-protocol';

export function ProviderDestination({ profile }: { profile?: Provider }) {
  const protocol = profile?.api_protocol ? providerProtocols[profile.api_protocol] : undefined;
  return <section className="notice provider-destination" aria-label={t("本次翻译服务")}>
    <strong>{t("本次翻译服务")}</strong>
    <dl className="kv"><dt>{t("服务地址")}</dt><dd><code>{profile?.endpoint || t("服务端未提供地址，请重新读取配置")}</code></dd>
      <dt>{t("模型")}</dt><dd>{profile?.model_display_name || profile?.model_id || t("未配置")}</dd></dl>
    <details className="technical-details"><summary>{t("连接技术详情")}</summary><dl className="kv">
      {profile?.model_display_name && <><dt>{t("模型 ID")}</dt><dd className="mono">{profile.model_id || t("未配置")}</dd></>}
      <dt>{t("接口类型")}</dt><dd>{protocol ? t(protocol.label) : t("未提供")}</dd>
      <dt>{t("鉴权方式")}</dt><dd>{profile?.auth_mode === 'none' ? t("无鉴权") : profile?.auth_mode === 'bearer' ? t("Bearer 密钥") : profile?.auth_mode === 'api_key' && protocol?.auth === 'api_key' ? t("{kind} 密钥", { kind: t(protocol.keyLabel) }) : t("未提供")}</dd>
      {profile?.api_protocol === 'claude_messages' && <><dt>{t("Anthropic API 版本")}</dt><dd>{profile.api_version || t("2023-06-01（服务端默认）")}</dd></>}</dl></details>
  </section>;
}
