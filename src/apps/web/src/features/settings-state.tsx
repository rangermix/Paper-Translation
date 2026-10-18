import { createContext, useContext, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Modal } from '../components';
import { useNavigationGuard } from '../navigation-guard';
import type { Preferences } from '../types';

type SettingsForm = {
  label: string;
  dirty: boolean;
  pending: boolean;
  canSave: boolean;
  save: () => Promise<boolean>;
  discard: () => void;
};
type FormReader = () => SettingsForm;
type SettingsSession = {
  register: (id: string, read: FormReader) => () => void;
  changed: () => void;
  preferences: () => Preferences | undefined;
  remember: (value: Preferences) => void;
};
const SettingsContext = createContext<SettingsSession | null>(null);

/** Only callbacks and current render state live here; nothing is written to browser storage. */
export function useSettingsForm(id: string, value: SettingsForm) {
  const session = useContext(SettingsContext);
  const latest = useRef(value);
  latest.current = value;
  useLayoutEffect(() => session?.register(id, () => latest.current), [id, session]);
  useLayoutEffect(() => { session?.changed(); }, [session, value.label, value.dirty, value.pending, value.canSave]);
  return session;
}

export function useSettingsRefresh(dirty: boolean, refresh: () => void | Promise<unknown>, clearsKey = false) {
  const [confirm, setConfirm] = useState(false);
  return {
    request: () => { if (dirty) setConfirm(true); else void refresh(); },
    confirmation: confirm && <Modal title="刷新设置并保留输入" onClose={() => setConfirm(false)}>
      <p>刷新会读取最新的已保存设置，保留当前非密钥输入供核对，不会替你保存或测试服务。</p>
      {clearsKey && <p>未保存的密钥会从表单清空，需要时请重新输入。</p>}
      <div className="stack"><button type="button" className="btn primary" onClick={() => setConfirm(false)}>继续编辑</button>
        <button type="button" className="btn" onClick={() => { setConfirm(false); void refresh(); }}>刷新并保留输入</button></div>
    </Modal>,
  };
}

export function SettingsDraftBoundary({ preferences, children }: { preferences?: Preferences; children: ReactNode }) {
  const entries = useRef(new Map<string, FormReader>());
  const latestPreferences = useRef(preferences);
  const [, setRevision] = useState(0);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  if (preferences && (!latestPreferences.current || (preferences.generation ?? -1) >= (latestPreferences.current.generation ?? -1))) latestPreferences.current = preferences;
  const session = useMemo<SettingsSession>(() => ({
    register(id, read) {
      entries.current.set(id, read);
      setRevision(value => value + 1);
      return () => { if (entries.current.get(id) === read) entries.current.delete(id); setRevision(value => value + 1); };
    },
    changed() { setRevision(value => value + 1); },
    preferences: () => latestPreferences.current,
    remember: value => { latestPreferences.current = value; },
  }), []);
  const forms = [...entries.current.values()].map(read => read());
  const dirty = forms.filter(form => form.dirty);
  const pending = saving || forms.some(form => form.pending);
  const guard = useNavigationGuard(dirty.length > 0 || pending);
  async function saveAll() {
    if (pending) return;
    setSaving(true); setNotice('');
    try {
      for (const read of entries.current.values()) {
        const form = read();
        if (!form.dirty) continue;
        if (!form.canSave || !await form.save()) {
          setNotice(`${form.label}尚未保存。请继续编辑，处理该分区中的提示后再离开。`);
          return;
        }
      }
      guard.resolve(true);
    } catch {
      setNotice('设置未全部保存。已保存的分区会保留，其余输入仍在当前页面。请继续编辑并查看对应提示。');
    } finally { setSaving(false); }
  }
  return <SettingsContext.Provider value={session}>
    {dirty.length > 0 && <p className="settings-draft-summary" role="status">未保存：{dirty.map(form => form.label).join('、')}。切换分区会保留输入。</p>}
    {children}
    {guard.requested && <Modal title="有未保存的设置" busy={pending} onClose={() => { setNotice(''); guard.resolve(false); }}>
      <p>{dirty.length ? `${dirty.map(form => form.label).join('、')}尚未保存。` : '设置仍在保存，请等待结果。'}</p>
      <p>保存仅更新对应配置；不会自动测试服务、准备模型或修改已有任务的配置快照。</p>
      {notice && <p role="alert" className="notice">{notice}</p>}
      {dirty.some(form => !form.canSave) && <p>部分分区尚不能保存。请继续编辑，处理字段校验、版本冲突或其他接口的未保存输入。</p>}
      <div className="stack">
        <button type="button" className="btn primary" disabled={pending} onClick={() => { setNotice(''); guard.resolve(false); }}>继续编辑</button>
        <button type="button" className="btn" disabled={pending} onClick={() => {
          for (const read of entries.current.values()) if (read().dirty) read().discard();
          setNotice(''); guard.resolve(true);
        }}>放弃修改</button>
        <button type="button" className="btn" disabled={pending || dirty.some(form => !form.canSave)} onClick={() => void saveAll()}>保存后离开</button>
      </div>
    </Modal>}
  </SettingsContext.Provider>;
}
