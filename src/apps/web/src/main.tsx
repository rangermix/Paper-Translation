import { t, useUiLocale, setUiLocale, uiLocales } from './i18n';
import { StrictMode, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ErrorNotice, Icon } from './components';
import { useResource, useRoute } from './hooks';
import { DocumentDetail, Library } from './features/library';
import { UploadPage } from './features/upload';
import { Jobs, PreflightPage } from './features/workflow';
import { Editor } from './features/editor';
import { Glossaries, Memories, Search, Settings } from './features/knowledge';
import { HistoryPage } from './features/history';
import type { Capability, Preferences } from './types';
import './styles.css';
import './navigation.css';
import './ui-refinements.css';
const navigation = [{ page: 'library', label: '文档库', icon: 'book' }, { page: 'upload', label: '上传 PDF', icon: 'upload' }, { page: 'jobs', label: '任务中心', icon: 'tasks' }, { page: 'search', label: '搜索文档', icon: 'search' }, { page: 'glossary', label: '术语表', icon: 'terms' }, { page: 'memory', label: '个人翻译记忆', icon: 'memory' }, { page: 'settings', label: '设置', icon: 'settings' }];
function App() {
  const uiLocale = useUiLocale();
  useEffect(() => {
    document.documentElement.lang = uiLocale;
    document.title = t('对照文库 · 个人 PDF 知识库');
  }, [uiLocale]);
  const route = useRoute(); const capabilities = useResource<Capability>('/capabilities'); const preferences = useResource<Preferences>('/settings/preferences'); const [menu, setMenu] = useState(false);
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width:760px)').matches);
  const menuDialog = useRef<HTMLDialogElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const focusContentOnClose = useRef(false);
  const previousRoute = useRef(`${route.page}/${route.id ?? ''}/${route.extra ?? ''}`);
  useEffect(() => {
    const media = window.matchMedia('(max-width:760px)');
    const update = () => { setMobile(media.matches); if (!media.matches) setMenu(false); };
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useLayoutEffect(() => {
    const next = `${route.page}/${route.id ?? ''}/${route.extra ?? ''}`;
    if (previousRoute.current !== next && menu) {
      focusContentOnClose.current = true;
      setMenu(false);
    }
    previousRoute.current = next;
  }, [route.page, route.id, route.extra, menu]);
  useLayoutEffect(() => {
    const dialog = menuDialog.current;
    if (!mobile || !menu || !dialog) return;
    const overflow = document.body.style.overflow;
    dialog.showModal();
    dialog.querySelector<HTMLButtonElement>('.mobile-close')?.focus();
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = overflow;
      dialog.close();
      const content = focusContentOnClose.current;
      focusContentOnClose.current = false;
      if (content || !window.matchMedia('(max-width:760px)').matches) {
        document.getElementById('main')?.focus({ preventScroll: true });
      } else {
        menuButton.current?.focus({ preventScroll: true });
      }
    };
  }, [mobile, menu]);
  useEffect(() => { document.documentElement.dataset.theme = preferences.data?.theme ?? 'system'; }, [preferences.data?.theme]);
  const label = t(navigation.find(n => n.page === route.page)?.label ?? ({ documents: '文档详情', preflight: '解析结果', drafts: '译文编辑', history: '版本历史' }[route.page] ?? '文档库'));
  let content;
  switch (route.page) {
    case 'upload': content = <UploadPage capability={capabilities.data}/>; break;
    case 'documents': content = route.id ? <DocumentDetail id={route.id} capability={capabilities.data}/> : <Library/>; break;
    case 'jobs': content = <Jobs id={route.id}/>; break;
    case 'preflight': content = route.id ? <PreflightPage id={route.id}/> : <Library/>; break;
    case 'drafts': content = route.id ? <Editor key={route.id} id={route.id}/> : <Library/>; break;
    case 'history': content = route.id ? <HistoryPage id={route.id}/> : <Library/>; break;
    case 'glossary': content = <Glossaries/>; break;
    case 'memory': content = <Memories/>; break;
    case 'search': content = <Search/>; break;
    case 'settings': content = <Settings onTheme={theme => { document.documentElement.dataset.theme = theme; preferences.reload(); }}/>; break;
    default: content = <Library/>;
  }
  const navigationContent = <><a className="brand" href="#/library"><span className="brand-icon"><Icon name="book"/></span><span>{t("对照文库")}<small>BILINGUAL LIBRARY</small></span></a>{mobile && <button className="icon-btn mobile-close" aria-label={t("关闭菜单")} onClick={() => setMenu(false)}><Icon name="close"/></button>}<nav aria-label={t("页面")}>{navigation.map(n => <a className="nav-item" key={n.page} href={`#/${n.page}`} aria-current={route.page === n.page || n.page === 'library' && ['documents', 'history', 'drafts', 'preflight'].includes(route.page) ? 'page' : undefined}><Icon name={n.icon}/>{t(n.label)}</a>)}</nav><div className="side-bottom"><div className="ui-language"><label htmlFor="ui-language">{t("界面语言")}</label><select id="ui-language" value={uiLocale} title={t("仅在此浏览器保存，切换后立即生效。")} onChange={event => setUiLocale(event.target.value as typeof uiLocale)}>{uiLocales.map(locale => <option key={locale.value} value={locale.value} lang={locale.value}>{locale.label}</option>)}</select></div><a href="#/settings">{t("查看运行与配置状态")}</a></div></>;
  return <>
    <a className="skip-link" href="#main" onClick={event => { event.preventDefault(); const main = document.getElementById('main'); main?.focus({ preventScroll: true }); main?.scrollIntoView({ block: 'start' }); }}>{t("跳到主要内容")}</a>
    {mobile ? <dialog ref={menuDialog} id="mobile-navigation" className="sidebar mobile-navigation" aria-label={t("主要导航")} onKeyDown={event => {
      if (event.key !== 'Tab') return;
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), select:not([disabled])')].filter(element => element.getClientRects().length > 0);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }} onCancel={event => { event.preventDefault(); setMenu(false); }} onClose={event => { if (!event.currentTarget.open) setMenu(false); }} onClick={event => {
      const dialog = event.currentTarget;
      if (event.target === dialog) {
        const bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) setMenu(false);
      } else {
        const link = (event.target as Element).closest<HTMLAnchorElement>('a[href]');
        if (link?.hash === location.hash) { focusContentOnClose.current = true; setMenu(false); }
      }
    }}>{navigationContent}</dialog> : <aside className="sidebar" aria-label={t("主要导航")}>{navigationContent}</aside>}
    <div className="shell"><header className="topbar"><div className="stack"><button ref={menuButton} className="icon-btn mobile-menu" aria-label={t("打开菜单")} aria-haspopup="dialog" aria-controls="mobile-navigation" aria-expanded={menu} onClick={() => setMenu(true)}><Icon name="menu"/></button><div className="breadcrumb">{t("个人知识库 ")}<span> / {label}</span></div><span className="mobile-title">{t("对照文库")}</span></div><a className="topbar-action" href="#/upload"><Icon name="upload"/> {t(" 上传 PDF")}</a></header><main className="main" id="main" tabIndex={-1}><ErrorNotice error={capabilities.error} retry={capabilities.reload}/>{content}</main></div>
  </>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
