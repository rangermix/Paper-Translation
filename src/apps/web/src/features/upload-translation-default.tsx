import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback } from '../components';
import { useAction } from '../hooks';
import type { Preferences, Provider } from '../types';

export function uploadTranslationAllowed(preferences?: Preferences, provider?: Provider) {
  return Boolean(provider?.configured && provider.dispatch_configuration_ready && provider.profile_hash
    && preferences?.upload_translation_profile_hash === provider.profile_hash);
}

export function UploadTranslationDefault({ preferences, provider, disabled, onSaved, reload, onSavingChange }: {
  preferences?: Preferences; provider?: Provider; disabled?: boolean;
  onSaved: (preferences: Preferences) => void; reload: () => void;
  onSavingChange?: (saving: boolean) => void;
}) {
  const action = useAction();
  const [pendingChoice, setPendingChoice] = useState(false);
  const enabled = uploadTranslationAllowed(preferences, provider);
  const canEnable = Boolean(provider?.configured && provider.dispatch_configuration_ready && provider.profile_hash);
  function save(checked: boolean) {
    setPendingChoice(checked);
    void action.run(async () => {
      onSavingChange?.(true);
      try {
        const saved = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(preferences),
          body: { upload_translation_profile_hash: checked ? provider!.profile_hash : null } });
        onSaved(saved);
      } finally { onSavingChange?.(false); }
    }, checked ? '已保存：以后上传默认允许翻译。' : '已关闭上传默认翻译授权。');
  }
  return <div className="section-title">
    <label className="check"><input type="checkbox" checked={action.pending ? pendingChoice : enabled}
      disabled={disabled || action.pending || !preferences || !canEnable}
      onChange={e => save(e.target.checked)}/>
      以后上传默认允许翻译
    </label>
    <p className="field-note">开启即同意将以后上传的 PDF 必要文本、上下文和术语发送到当前服务进行翻译，服务可能收费。立即保存，适用于此实例；每次上传仍可取消授权或选择仅解析。</p>
    <p className="muted small">仅适用于当前已保存的服务配置和默认翻译前准备。配置变更后需重新开启；启用金额控制时仍须填写每份文档的预算。</p>
    {!canEnable && <p className="field-note">先在设置中保存完整的 AI 服务配置。</p>}
    {preferences?.upload_translation_profile_hash && !enabled && canEnable && <p className="field-note warn">翻译配置已变更，原默认授权已失效。请核对当前服务后重新开启。</p>}
    {preferences?.upload_translation_profile_hash && !enabled && <button className="btn sm" type="button"
      disabled={disabled || action.pending} onClick={() => save(false)}>清除已失效的默认授权</button>}
    <ActionFeedback {...action}/>
    {action.error && <button className="btn sm" type="button" onClick={() => { action.clear(); reload(); }}>重新读取默认设置</button>}
  </div>;
}
