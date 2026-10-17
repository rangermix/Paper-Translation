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
    {!canEnable && <p className="field-note">先在设置中保存完整的 AI 服务配置。</p>}
    {preferences?.upload_translation_profile_hash && !enabled && canEnable && <p className="field-note warn">翻译配置已变更，原默认授权已失效。请核对当前服务后重新开启。</p>}
    {preferences?.upload_translation_profile_hash && !enabled && <button className="btn sm" type="button"
      disabled={disabled || action.pending} onClick={() => save(false)}>清除已失效的默认授权</button>}
    <ActionFeedback {...action}/>
    {action.error && <button className="btn sm" type="button" onClick={() => { action.clear(); reload(); }}>重新读取默认设置</button>}
  </div>;
}
