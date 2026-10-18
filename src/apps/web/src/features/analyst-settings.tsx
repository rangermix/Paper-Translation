import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { useAction } from '../hooks';
import type { Preferences } from '../types';
import { LocalModels } from './local-models';
import { useSettingsForm, useSettingsRefresh } from './settings-state';

export function AnalystSettings({ preferences, loading, onSaved }: {
  preferences?: Preferences; loading: boolean; onSaved: (value: Preferences) => void;
}) {
  const [choice, setChoice] = useState<{ model: string; backend: string }>();
  const [available, setAvailable] = useState(false);
  const action = useAction();
  const model = choice?.model ?? preferences?.local_analyst_model_id ?? '';
  const backend = choice?.backend ?? preferences?.local_analyst_backend ?? '';
  const dirty = Boolean(choice && (model !== preferences?.local_analyst_model_id || backend !== preferences?.local_analyst_backend));
  const canSave = available && Boolean(model && backend && etagFor(preferences)) && !action.pending && !action.error;
  const session = useSettingsForm('analyst', { label: '翻译前准备模型', dirty, pending: action.pending, canSave, save,
    discard: () => { setChoice(undefined); action.clear(); } });
  const refresh = useSettingsRefresh(dirty, () => action.run(async () => {
    const saved = await api<Preferences>('/settings/preferences'); session?.remember(saved); onSaved(saved);
  }, '已读取最新设置，请核对当前选择后保存。'));
  async function save() {
    if (!canSave) return false;
    let success = false;
    await action.run(async () => {
      const current = session?.preferences() ?? preferences;
      const saved = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(current),
        body: { local_analyst_model_id: model, local_analyst_backend: backend } });
      session?.remember(saved); onSaved(saved); setChoice(undefined); success = true;
    }, '总结模型设置已保存，仅用于新任务。');
    return success;
  }
  return <section className="panel analyst-panel" aria-labelledby="analyst-title">
    <h2 id="analyst-title">翻译前总结模型</h2>
    {loading && <Loading/>}
    {preferences && <form onSubmit={event => { event.preventDefault(); void save(); }}>
      {dirty && <p className="settings-unsaved small">未保存</p>}
      <fieldset className="provider-fields" disabled={action.pending}>
        <LocalModels purpose="analysis" active value={model} backend={backend}
          onChange={(model, backend) => { setChoice({ model, backend }); if (!action.error) action.clear(); }} onAvailabilityChange={setAvailable}/>
      </fieldset>
      <ActionFeedback notice={action.notice}/>
      <ErrorNotice error={action.error} retry={refresh.request}/>
      <div className="settings-actions"><button className="btn primary" disabled={!canSave}>保存总结模型设置</button></div>
    </form>}
    {refresh.confirmation}
  </section>;
}
