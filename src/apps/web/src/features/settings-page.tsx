import { t } from '../i18n';
import { useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading, PageHead } from '../components';
import { useAction, useResource } from '../hooks';
import { isLanguageTag } from '../languages';
import type { Preferences, Provider } from '../types';
import { AnalystSettings } from './analyst-settings';
import { LanguageSelect } from './language-select';
import { ParserSettings } from './parser-select';
import { ProviderSettings } from './provider-settings';
import { ResourceSettings } from './resource-settings';
import { SettingsDraftBoundary, useSettingsForm, useSettingsRefresh } from './settings-state';
import './settings.css';
import './settings-navigation.css';

function ReadingPreferences({ preferences, loading, onSaved, onTheme, reload }: {
  preferences?: Preferences; loading: boolean; onSaved: (value: Preferences) => void;
  onTheme: (theme: string) => void; reload: () => void;
}) {
  const [edits, setEdits] = useState<Partial<Preferences>>({});
  const action = useAction();
  const prefs = { ...preferences, ...edits };
  const theme = prefs.theme === 'paper' ? 'light' : prefs.theme ?? 'system';
  const savedTheme = preferences?.theme === 'paper' ? 'light' : preferences?.theme ?? 'system';
  const dirty = Boolean(preferences && (theme !== savedTheme || prefs.locale !== preferences.locale));
  const canSave = Boolean(preferences && etagFor(preferences) && isLanguageTag(prefs.locale) && !action.pending && !action.error);
  const session = useSettingsForm('reading', { label: '阅读偏好', dirty, pending: action.pending, canSave, save,
    discard: () => { setEdits({}); action.clear(); } });
  const refresh = useSettingsRefresh(dirty, () => { action.clear(); reload(); });
  async function save() {
    if (!canSave) return false;
    let saved = false;
    await action.run(async () => {
      const current = session?.preferences() ?? preferences;
      const value = await api<Preferences>('/settings/preferences', { method: 'PATCH', etag: etagFor(current), body: { locale: prefs.locale, theme } });
      session?.remember(value); onSaved(value); onTheme(theme); setEdits({}); saved = true;
    }, '偏好已保存。');
    return saved;
  }
  return <section className="panel preferences-panel" aria-labelledby="preferences-title"><h2 id="preferences-title">{t("阅读偏好")}</h2>
    <p className="settings-hint">{t("界面主题保存后立即应用。默认语言用于之后选择翻译语言；已有译文和阅读版不会改动。")}</p>
    {loading && <Loading/>}
    {preferences && <form onSubmit={event => { event.preventDefault(); void save(); }}>
      {dirty && <p className="settings-unsaved small">{t("未保存")}</p>}
      <div className="field"><label htmlFor="default-locale">{t("默认翻译语言")}</label><LanguageSelect id="default-locale" value={prefs.locale ?? 'zh-Hans'} disabled={action.pending} onChange={locale => { setEdits(old => ({ ...old, locale })); if (!action.error) action.clear(); }}/></div>
      <div className="field"><label htmlFor="theme">{t("管理界面主题")}</label><select id="theme" value={theme} disabled={action.pending} onChange={event => { setEdits(old => ({ ...old, theme: event.target.value as Preferences['theme'] })); if (!action.error) action.clear(); }}>
        <option value="system">{t("自动（跟随系统）")}</option><option value="light">{t("浅色纸面")}</option><option value="dark">{t("深色")}</option>
      </select></div>
      <ActionFeedback notice={action.notice}/>
      <ErrorNotice error={action.error} retry={refresh.request}/>
      <div className="settings-actions"><button className="btn primary" disabled={!canSave}>{t("保存偏好")}</button></div>
    </form>}
    {refresh.confirmation}
  </section>;
}

const categories = [['service', '翻译服务'], ['parser', 'PDF 解析'], ['reading', '阅读偏好'], ['advanced', '高级与运行状态']] as const;
export function SettingsPage({ onTheme }: { onTheme: (theme: string) => void }) {
  const preferences = useResource<Preferences>('/settings/preferences');
  const provider = useResource<Provider>('/settings/provider');
  return <div className="settings-page settings-categories"><PageHead title={t("设置")}/>
    <SettingsDraftBoundary preferences={preferences.data}>
      <nav className="settings-category-nav" aria-label={t("设置分区")}>{categories.map(([id, label]) => <button key={id} type="button" className="btn" onClick={() => {
        const section = document.getElementById(`settings-${id}`);
        section?.focus({ preventScroll: true }); section?.scrollIntoView({ block: 'start' });
      }}>{t(label)}</button>)}</nav>
      <ErrorNotice error={preferences.error} retry={preferences.reload}/>
      <section id="settings-service" className="settings-category" aria-label={t("翻译服务设置")} tabIndex={-1}>
        <p className="settings-scope">{t("保存服务或模型配置用于后续新任务。已有任务继续使用创建时的配置；保存后仍需单独测试或准备模型。")}</p>
        <ProviderSettings provider={provider.data} loading={provider.loading} error={provider.error} reload={provider.reload} onSaved={provider.setData} onDispatchSaved={preferences.reload}/>
        <details className="settings-model-preparation"><summary>{t("翻译前准备模型")}</summary>
          <AnalystSettings preferences={preferences.data} loading={preferences.loading} onSaved={preferences.setData}/>
        </details>
      </section>
      <section id="settings-parser" className="settings-category" aria-label={t("PDF 解析设置")} tabIndex={-1}>
        <p className="settings-scope">{t("默认方案和超时用于新解析任务。已有任务保留原配置；保存设置不下载模型，“准备解析模型”会单独启动准备任务。")}</p>
        <ParserSettings preferences={preferences.data} loading={preferences.loading} onSaved={preferences.setData} reload={preferences.reload}/>
      </section>
      <section id="settings-reading" className="settings-category" aria-label={t("阅读偏好设置")} tabIndex={-1}>
        <ReadingPreferences preferences={preferences.data} loading={preferences.loading} onSaved={preferences.setData} onTheme={onTheme} reload={preferences.reload}/>
      </section>
      <section id="settings-advanced" className="settings-category" aria-label={t("高级与运行状态")} tabIndex={-1}>
        <h2>{t("高级与运行状态")}</h2>
        <p className="settings-scope">{t("资源与并发设置用于后续调度，可能影响已排队任务；不会终止正在执行的请求。容量和模型内存参考是调度依据与估算。")}</p>
        <details className="settings-resource-details"><summary>{t("资源与并发 · 查看状态和调整上限")}{preferences.data?.resources && <span className="settings-resource-summary">{t("已保存并发上限：{masters} 个主任务 · 每个主任务 {subjobs} 个子任务", { masters: preferences.data.resources.master_concurrency, subjobs: preferences.data.resources.subjob_concurrency })}</span>}
        </summary>
          <ResourceSettings preferences={preferences.data} onSaved={preferences.setData} reload={preferences.reload}/>
        </details>
      </section>
    </SettingsDraftBoundary>
  </div>;
}
