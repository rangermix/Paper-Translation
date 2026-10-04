import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading } from '../components';
import { useAction } from '../hooks';
import type { Preferences } from '../types';
import { LocalModels } from './local-models';

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
  return <section className="panel analyst-panel" aria-labelledby="analyst-title">
    <h2 id="analyst-title">翻译前总结模型</h2>
    <p className="settings-hint">用于“独立本地小模型”的论文概述与术语建议，单独保存模型和推理后端。</p>
    {loading && <Loading/>}
    {preferences && <form onSubmit={event => {
      event.preventDefault();
      if (!canSave) return;
      void action.run(async () => {
        const saved = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(preferences),
          body: { local_analyst_model_id: model, local_analyst_backend: backend } });
        onSaved(saved); setChoice(undefined);
      }, '总结模型设置已保存，仅用于新任务。');
    }}>
      {dirty && <p className="settings-unsaved small">未保存</p>}
      <fieldset className="provider-fields" disabled={action.pending}>
        <LocalModels purpose="analysis" active value={model} backend={backend}
          onChange={(model, backend) => { setChoice({ model, backend }); if (!action.error) action.clear(); }} onAvailabilityChange={setAvailable}/>
      </fieldset>
      <p className="settings-hint">保存不会下载或调用模型。选择“独立本地小模型”创建任务时，使用这里已保存的配置；已有任务保留原模型。</p>
      <ActionFeedback notice={action.notice}/>
      <ErrorNotice error={action.error} retry={() => void action.run(async () => {
        onSaved(await api<Preferences>('/settings/preferences'));
      }, '已读取最新设置，请核对当前选择后保存。')}/>
      <div className="settings-actions"><button className="btn primary" disabled={!canSave}>保存总结模型设置</button></div>
    </form>}
  </section>;
}
